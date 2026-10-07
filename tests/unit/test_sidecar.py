"""Sidecar schema v1 tests (spec 0001 §13 / ADR-0003)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from mantis_research.core.prompts import SYNTHESIS_SIDECAR
from mantis_research.core.sidecar import (
    SIDECAR_VERSION,
    CitedSource,
    Provenance,
    ResearchSidecar,
    SidecarContractError,
    SourceCitations,
    SourceOverlap,
    SourceRef,
    VerificationItem,
    derive_source_overlaps,
    missing_required_fields,
    project_for_agent,
    run_root_of,
)
from mantis_research.core.state import SubsessionResult

_FULL_MODEL_DOC = {
    'sidecar_version': 1,
    'claims': [
        {'id': 'c1', 'text': 'X uses Rust core', 'section': '§2', 'support': 'direct'},
        {'id': 'c2', 'text': 'Y is 40% faster', 'support': 'indirect'},
    ],
    'divergences': [
        {
            'id': 'd1',
            'description': 'backend-free share',
            'sides': ['claude: ~60%', 'gpt: ~30%'],
            'substrates': ['claude', 'openrouter:gpt-5-exa'],
            'assessment': 'both plausible; depends on definition',
        }
    ],
    'verification_queue': [
        {'id': 'v1', 'claim': 'IN BCB 561/2024', 'reason': 'single-source', 'sources_disagree': []}
    ],
    'agreements_worth_verifying': ['both agree QuantLib uses SWIG'],
    'coverage_notes': ['GPU specifics out of scope'],
}


class TestRoundTrip:
    def test_full_model_document_round_trips(self) -> None:
        sc = ResearchSidecar.from_model_json(json.dumps(_FULL_MODEL_DOC))
        assert sc.sidecar_version == 1
        assert [c.id for c in sc.claims] == ['c1', 'c2']
        assert sc.claims[0].support == 'direct'
        assert sc.divergences[0].substrates == ['claude', 'openrouter:gpt-5-exa']
        # Round-trips through to_json without loss of the model-authored zone.
        again = ResearchSidecar.from_model_json(sc.to_json())
        assert again.claims == sc.claims
        assert again.verification_queue == sc.verification_queue

    def test_runner_zone_defaults_absent(self) -> None:
        # The model may omit identity/provenance; the runner fills them later.
        sc = ResearchSidecar.from_model_json(json.dumps(_FULL_MODEL_DOC))
        assert sc.topic_id is None
        assert sc.generated_at is None
        assert sc.provenance.total_cost_usd is None


class TestRequiredFieldsOnWrite:
    """MANT-B06 — a sidecar with no question is not a citation surface.

    Seven of seven sidecars across two runs were unusable because the schema had
    no ``question`` field at all, and nothing validated the runner-authored zone
    at write time, so a hollow artifact shipped silently.
    """

    def _merged(self, **overrides: object) -> ResearchSidecar:
        sc = ResearchSidecar.from_model_json(json.dumps(_FULL_MODEL_DOC))
        base: dict[str, object] = {
            'question': 'what changed in X?',
            'generated_at': '2026-08-11T00:00:00+00:00',
            'sources': [SourceRef(label='openrouter:openai', path='outputs/openai.md')],
        }
        return sc.model_copy(update={**base, **overrides})

    def test_question_is_carried_on_the_schema(self) -> None:
        assert self._merged().question == 'what changed in X?'

    def test_complete_document_passes(self) -> None:
        assert missing_required_fields(self._merged()) == []
        self._merged().require_complete()  # does not raise

    @pytest.mark.parametrize(
        ('field', 'empty'),
        [('question', None), ('question', '  '), ('generated_at', None), ('sources', [])],
    )
    def test_missing_required_field_is_reported(self, field: str, empty: object) -> None:
        sc = self._merged(**{field: empty})
        assert missing_required_fields(sc) == [field]

    def test_require_complete_raises_naming_every_missing_field(self) -> None:
        sc = self._merged(question=None, sources=[])
        with pytest.raises(SidecarContractError) as exc:
            sc.require_complete()
        assert 'question' in str(exc.value)
        assert 'sources' in str(exc.value)


class TestValidation:
    def test_current_version_is_three(self) -> None:
        # v2 was additive (I4): `question` plus the typed provenance fields. v3
        # changes what `sources[].path` and `synthesis_path` mean — relative to
        # the run root, no longer absolute (T4b) — so the version moves.
        assert SIDECAR_VERSION == 3
        assert ResearchSidecar().sidecar_version == 3

    def test_version_one_still_loads(self) -> None:
        # I6 — sidecars written before the bump stay readable.
        sc = ResearchSidecar.from_model_json(json.dumps(_FULL_MODEL_DOC))
        assert sc.sidecar_version == 1

    def test_version_two_with_absolute_paths_still_loads(self) -> None:
        doc = {
            'sidecar_version': 2,
            'synthesis_path': '/data/outputs/r/synthesis/01-t.md',
            'sources': [{'label': 'openrouter:openai', 'path': '/data/outputs/r/o/openai.md'}],
        }
        sc = ResearchSidecar.from_model_json(json.dumps(doc))
        assert sc.sidecar_version == 2
        assert sc.sources[0].path == '/data/outputs/r/o/openai.md'

    def test_wrong_version_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ResearchSidecar.from_model_json(json.dumps({'sidecar_version': 99}))

    def test_claim_without_id_rejected(self) -> None:
        doc = {'sidecar_version': 1, 'claims': [{'text': 'no id here'}]}
        with pytest.raises(ValidationError):
            ResearchSidecar.from_model_json(json.dumps(doc))

    def test_unknown_key_rejected(self) -> None:
        # extra='forbid' — a typo'd field must fail, not be silently dropped.
        doc = {'sidecar_version': 1, 'claimz': []}
        with pytest.raises(ValidationError):
            ResearchSidecar.from_model_json(json.dumps(doc))


class TestResolvedPaths:
    """T4b — a sidecar's file paths resolve wherever its run directory now sits.

    v1 and v2 recorded absolute machine paths, so a frozen sidecar copied to
    another machine had to be normalised by hand before its sources opened. v3
    records them relative to the run root; the resolver joins them back on.
    """

    def _v3(self) -> ResearchSidecar:
        return ResearchSidecar(
            synthesis_path='synthesis/01-t.md',
            sources=[
                SourceRef(label='openrouter:openai', path='openrouter/01-t/openai.md'),
                SourceRef(label='gemini', path='gemini/01-t.md'),
            ],
        )

    def test_run_root_is_two_levels_above_the_sidecar(self, tmp_path: Path) -> None:
        sidecar = tmp_path / 'outputs' / 'run' / 'synthesis' / '01-t.sidecar.json'
        assert run_root_of(sidecar) == tmp_path / 'outputs' / 'run'

    def test_relative_paths_join_the_given_run_root(self, tmp_path: Path) -> None:
        resolved = self._v3().resolved_paths(tmp_path)
        assert resolved.synthesis == tmp_path / 'synthesis' / '01-t.md'
        assert resolved.sources == (
            ('openrouter:openai', tmp_path / 'openrouter' / '01-t' / 'openai.md'),
            ('gemini', tmp_path / 'gemini' / '01-t.md'),
        )

    def test_an_absolute_v2_path_passes_through(self, tmp_path: Path) -> None:
        written = tmp_path / 'old' / 'synthesis' / '01-t.md'
        brief = tmp_path / 'old' / 'openrouter' / '01-t' / 'openai.md'
        sc = ResearchSidecar(
            sidecar_version=2,
            synthesis_path=written.as_posix(),
            sources=[SourceRef(label='openrouter:openai', path=brief.as_posix())],
        )
        resolved = sc.resolved_paths(tmp_path / 'elsewhere')
        assert resolved.synthesis == written
        assert resolved.sources == (('openrouter:openai', brief),)

    def test_a_v2_path_is_never_joined_even_when_relative(self, tmp_path: Path) -> None:
        # Before v3 a relative value was relative to the writer's working
        # directory, not the run root, so joining it would invent a location.
        sc = ResearchSidecar(
            sidecar_version=2, sources=[SourceRef(label='claude', path='outputs/01-t.md')]
        )
        assert sc.resolved_paths(tmp_path).sources == (('claude', Path('outputs/01-t.md')),)

    def test_an_absent_synthesis_path_stays_absent(self, tmp_path: Path) -> None:
        assert ResearchSidecar().resolved_paths(tmp_path).synthesis is None


class TestSourceProvenance:
    """MANT-B07 — the mechanism the tool actually wins on, made computable.

    The sharpest result the pipeline has produced was not averaging: two
    substrates cited the identical URL with incompatible figures while a third
    never cited it at all, so the source itself was suspect. With citations
    typed, "did two substrates cite the same source and disagree about it" is
    computed rather than improvised into a free-text field.
    """

    def _inventory(self) -> list[SourceCitations]:
        return [
            SourceCitations(
                substrate='openrouter:openai',
                cited=[
                    CitedSource(reference='https://bcb.gov.br/report-2025', kind='url'),
                    CitedSource(reference='quantlib/quantlib', kind='repository'),
                ],
            ),
            SourceCitations(
                substrate='openrouter:deepseek',
                cited=[CitedSource(reference='http://www.bcb.gov.br/report-2025/', kind='url')],
            ),
            SourceCitations(
                substrate='openrouter:google',
                cited=[CitedSource(reference='numpy', kind='package')],
            ),
        ]

    def test_overlap_is_derived_across_substrates(self) -> None:
        overlaps = derive_source_overlaps(self._inventory())
        assert [o.reference for o in overlaps] == ['https://bcb.gov.br/report-2025']
        assert overlaps[0].substrates == ['openrouter:openai', 'openrouter:deepseek']

    def test_overlap_records_who_never_cited_it(self) -> None:
        # The third substrate's silence is half the signal — it is what made the
        # source itself suspect rather than one model wrong.
        overlaps = derive_source_overlaps(self._inventory())
        assert overlaps[0].not_cited_by == ['openrouter:google']

    def test_url_forms_of_the_same_source_are_one_reference(self) -> None:
        # http/https, www, and a trailing slash are the same citation.
        overlaps = derive_source_overlaps(self._inventory())
        assert len(overlaps) == 1

    def test_a_source_cited_once_is_not_an_overlap(self) -> None:
        overlaps = derive_source_overlaps(self._inventory())
        assert 'numpy' not in [o.reference for o in overlaps]

    def test_model_conflict_judgement_is_folded_onto_the_derived_overlap(self) -> None:
        judgement = SourceOverlap(
            id='ignored',
            reference='https://BCB.gov.br/report-2025',
            figures_conflict=True,
            conflict='openai reads 4.2%, deepseek reads 6.1%, same table',
        )
        overlaps = derive_source_overlaps(self._inventory(), judgements=[judgement])
        assert overlaps[0].figures_conflict is True
        assert 'same table' in (overlaps[0].conflict or '')
        # Substrate membership stays derived, never taken from the model.
        assert overlaps[0].substrates == ['openrouter:openai', 'openrouter:deepseek']

    def test_ids_are_stable_and_unique(self) -> None:
        overlaps = derive_source_overlaps(self._inventory())
        assert [o.id for o in overlaps] == ['o1']

    def test_empty_inventory_yields_no_overlaps(self) -> None:
        assert derive_source_overlaps([]) == []

    def test_overlaps_reach_the_agent_projection(self) -> None:
        sc = ResearchSidecar.from_model_json(json.dumps(_FULL_MODEL_DOC)).model_copy(
            update={'source_overlaps': derive_source_overlaps(self._inventory())}
        )
        out = project_for_agent(sc)
        assert out['source_overlaps'][0]['reference'] == 'https://bcb.gov.br/report-2025'
        assert out['truncated']['source_overlaps'] == 0


_SHARED_UNSUPPORTED_DOC = {
    'sidecar_version': 2,
    'source_citations': [
        {
            'substrate': 'openrouter:deepseek',
            'cited': [{'reference': 'https://github.com/acme/waves', 'kind': 'repository'}],
        },
        {
            'substrate': 'openrouter:google',
            'cited': [{'reference': 'https://github.com/acme/waves', 'kind': 'repository'}],
        },
    ],
    'source_overlaps': [
        {
            'id': 'o1',
            'reference': 'https://github.com/acme/waves',
            'substrates': ['openrouter:deepseek', 'openrouter:google'],
            'figures_conflict': False,
            'source_check': 'shared_unsupported',
        }
    ],
}


class TestSourceCheck:
    """T32a — a brief-against-source judgement on each overlap.

    ``figures_conflict`` records briefs disagreeing with each other about a source
    they share. It cannot record two briefs agreeing on something the source does
    not say: in the field, two briefs cited one repository and agreed on five named
    items its README does not contain, and the overlap carried
    ``figures_conflict: false``, which reads as clean. ``source_check`` is where
    that verdict goes, defaulting to ``not_checked`` so every existing sidecar
    still validates and says nothing it did not check.
    """

    _VERDICTS = ('confirmed', 'contradicted', 'shared_unsupported', 'not_checked')

    def test_the_vocabulary_is_closed_to_the_four_verdicts(self) -> None:
        annotation = SourceOverlap.model_fields['source_check'].annotation
        assert get_args(annotation) == self._VERDICTS

    def test_a_v2_overlap_without_the_field_reads_as_not_checked(self) -> None:
        # I4/I6: every sidecar written before the field existed still validates.
        doc = {
            'sidecar_version': 2,
            'source_overlaps': [
                {'id': 'o1', 'reference': 'https://bcb.gov.br/x', 'figures_conflict': True}
            ],
        }
        sc = ResearchSidecar.model_validate_json(json.dumps(doc))
        assert sc.source_overlaps[0].source_check == 'not_checked'
        assert sc.source_overlaps[0].figures_conflict is True

    @pytest.mark.parametrize('verdict', _VERDICTS)
    def test_every_verdict_validates(self, verdict: str) -> None:
        overlap = SourceOverlap(id='o1', reference='https://bcb.gov.br/x', source_check=verdict)
        assert overlap.source_check == verdict

    def test_a_shared_unsupported_verdict_round_trips(self) -> None:
        sc = ResearchSidecar.model_validate_json(json.dumps(_SHARED_UNSUPPORTED_DOC))
        assert sc.source_overlaps[0].source_check == 'shared_unsupported'
        written = sc.to_json()
        assert json.loads(written)['source_overlaps'][0]['source_check'] == 'shared_unsupported'
        assert ResearchSidecar.model_validate_json(written) == sc

    def test_the_verdict_reaches_the_agent_projection(self) -> None:
        sc = ResearchSidecar.model_validate_json(json.dumps(_SHARED_UNSUPPORTED_DOC))
        out = project_for_agent(sc)
        assert out['source_overlaps'][0]['source_check'] == 'shared_unsupported'
        # The briefs agreeing is not a figures conflict; the two fields stay apart.
        assert out['source_overlaps'][0]['figures_conflict'] is False

    def test_the_merge_keeps_the_verdict_for_a_matched_reference(self) -> None:
        judgement = SourceOverlap(
            id='ignored', reference='https://github.com/acme/waves/', source_check='contradicted'
        )
        sc = ResearchSidecar.model_validate_json(json.dumps(_SHARED_UNSUPPORTED_DOC))
        overlaps = derive_source_overlaps(sc.source_citations, judgements=[judgement])
        assert overlaps[0].source_check == 'contradicted'
        assert overlaps[0].figures_conflict is False

    def test_the_merge_defaults_the_verdict_for_an_unmatched_reference(self) -> None:
        inventory = [
            SourceCitations(
                substrate='openrouter:openai',
                cited=[
                    CitedSource(reference='https://bcb.gov.br/x', kind='url'),
                    CitedSource(reference='https://github.com/acme/waves', kind='repository'),
                ],
            ),
            SourceCitations(
                substrate='openrouter:deepseek',
                cited=[
                    CitedSource(reference='https://bcb.gov.br/x', kind='url'),
                    CitedSource(reference='https://github.com/acme/waves', kind='repository'),
                ],
            ),
        ]
        judgement = SourceOverlap(
            id='o9', reference='https://bcb.gov.br/x', source_check='confirmed'
        )
        overlaps = derive_source_overlaps(inventory, judgements=[judgement])
        by_reference = {o.reference: o.source_check for o in overlaps}
        assert by_reference == {
            'https://bcb.gov.br/x': 'confirmed',
            'https://github.com/acme/waves': 'not_checked',
        }

    @pytest.mark.parametrize('verdict', ['verified', 'CONFIRMED', 'unsupported', ''])
    def test_an_unknown_verdict_is_rejected_by_the_vocabulary(self, verdict: str) -> None:
        doc = {
            'sidecar_version': 2,
            'source_overlaps': [{'id': 'o1', 'reference': 'x', 'source_check': verdict}],
        }
        with pytest.raises(ValidationError) as exc:
            ResearchSidecar.model_validate_json(json.dumps(doc))
        # Rejected as a value outside the closed vocabulary, not as an unknown key.
        (error,) = exc.value.errors()
        assert error['type'] == 'literal_error'
        assert error['loc'] == ('source_overlaps', 0, 'source_check')

    def test_a_misspelled_key_is_still_rejected(self) -> None:
        doc = {
            'sidecar_version': 2,
            'source_overlaps': [{'id': 'o1', 'reference': 'x', 'sourcecheck': 'confirmed'}],
        }
        with pytest.raises(ValidationError):
            ResearchSidecar.model_validate_json(json.dumps(doc))


class TestSidecarPromptCarriesTheVerdict:
    """The sidecar turn is told the field exists and when to fill it (T32a)."""

    def _prompt(self) -> str:
        return SYNTHESIS_SIDECAR.format(
            synthesis_path='/x/01-t.md',
            sidecar_path='/x/01-t.sidecar.draft.json',
            brief_block='- [openrouter:openai] /x/openrouter/01-t/openai.md',
        )

    def test_the_overlap_example_validates_and_shows_the_default(self) -> None:
        (line,) = [ln for ln in self._prompt().splitlines() if '"id": "o1"' in ln]
        SourceOverlap.model_validate_json(line.strip())  # the example obeys the schema
        # The key is written out, not left to the default, so the turn sees it.
        assert json.loads(line)['source_check'] == 'not_checked'

    def test_the_model_owned_fields_include_the_verdict(self) -> None:
        (sentence,) = [
            s for s in self._prompt().split('. ') if 'are yours' in s and 'reference' in s
        ]
        for field in ('reference', 'figures_conflict', 'conflict', 'source_check'):
            assert f'`{field}`' in sentence

    def test_the_turn_is_told_to_carry_over_spot_checks_and_otherwise_leave_the_default(
        self,
    ) -> None:
        (line,) = [ln for ln in self._prompt().splitlines() if ln.startswith('`source_check`')]
        for verdict in ('confirmed', 'contradicted', 'shared_unsupported', 'not_checked'):
            assert f'`{verdict}`' in line


_CHECK_KINDS = ('repo_exists', 'metric', 'license', 'url_resolves')

# A verification item as every sidecar before T4d wrote it.
_OLD_ITEM = {
    'id': 'v1',
    'claim': 'acme/waves ships a Rust core',
    'reason': 'single-source',
    'sources_disagree': ['openrouter:deepseek'],
}

_REPO_CHECK_DOC = {
    'sidecar_version': 2,
    'verification_queue': [
        {
            'id': 'v1',
            'claim': 'acme/waves ships a Rust core',
            'reason': 'single-source',
            'sources_disagree': [],
            'check_kind': 'repo_exists',
            'target': 'acme/waves',
        }
    ],
}


class TestVerificationCheckKind:
    """T4d — a verification item can say which check resolves it, and on what.

    The items were free text, so every consumer re-parsed ``claim`` to decide
    what to check. One scripted pass over a queue resolved 5 of 7 items and caught
    a repository that does not exist. ``check_kind`` (a closed vocabulary) and
    ``target`` carry that structure; both default to ``None`` so every sidecar
    already on disk still validates.
    """

    def test_the_vocabulary_is_closed_to_the_four_kinds(self) -> None:
        annotation = VerificationItem.model_fields['check_kind'].annotation
        literal, none = get_args(annotation)
        assert none is type(None)
        assert get_args(literal) == _CHECK_KINDS

    def test_an_item_written_before_the_fields_validates_with_both_none(self) -> None:
        # I4/I6: the four-key item every existing sidecar carries.
        doc = {'sidecar_version': 2, 'verification_queue': [_OLD_ITEM]}
        item = ResearchSidecar.model_validate_json(json.dumps(doc)).verification_queue[0]
        assert item.check_kind is None
        assert item.target is None
        assert item.sources_disagree == ['openrouter:deepseek']

    def test_an_old_item_rewritten_carries_both_keys_as_null_and_reloads(self) -> None:
        doc = {'sidecar_version': 2, 'verification_queue': [_OLD_ITEM]}
        sc = ResearchSidecar.model_validate_json(json.dumps(doc))
        written = json.loads(sc.to_json())['verification_queue'][0]
        assert written['check_kind'] is None
        assert written['target'] is None
        assert ResearchSidecar.model_validate_json(sc.to_json()) == sc

    @pytest.mark.parametrize('kind', _CHECK_KINDS)
    def test_every_kind_validates(self, kind: str) -> None:
        item = VerificationItem(id='v1', claim='c', reason='single-source', check_kind=kind)
        assert item.check_kind == kind

    def test_a_repo_exists_item_round_trips(self) -> None:
        sc = ResearchSidecar.model_validate_json(json.dumps(_REPO_CHECK_DOC))
        item = sc.verification_queue[0]
        assert (item.check_kind, item.target) == ('repo_exists', 'acme/waves')
        written = json.loads(sc.to_json())['verification_queue'][0]
        assert (written['check_kind'], written['target']) == ('repo_exists', 'acme/waves')
        assert ResearchSidecar.model_validate_json(sc.to_json()) == sc

    def test_the_fields_reach_the_agent_projection(self) -> None:
        sc = ResearchSidecar.model_validate_json(json.dumps(_REPO_CHECK_DOC))
        (projected,) = project_for_agent(sc)['verification_queue']
        assert projected['check_kind'] == 'repo_exists'
        assert projected['target'] == 'acme/waves'

    def test_an_old_item_projects_both_fields_as_none(self) -> None:
        doc = {'sidecar_version': 2, 'verification_queue': [_OLD_ITEM]}
        sc = ResearchSidecar.model_validate_json(json.dumps(doc))
        (projected,) = project_for_agent(sc)['verification_queue']
        assert projected['check_kind'] is None
        assert projected['target'] is None

    @pytest.mark.parametrize('kind', ['repo', 'REPO_EXISTS', 'doi_resolves', ''])
    def test_an_unknown_kind_is_rejected_by_the_vocabulary(self, kind: str) -> None:
        item = {**_OLD_ITEM, 'check_kind': kind, 'target': 'acme/waves'}
        doc = {'sidecar_version': 2, 'verification_queue': [item]}
        with pytest.raises(ValidationError) as exc:
            ResearchSidecar.model_validate_json(json.dumps(doc))
        # Rejected as a value outside the closed vocabulary, not as an unknown key.
        (error,) = exc.value.errors()
        assert error['type'] == 'literal_error'
        assert error['loc'] == ('verification_queue', 0, 'check_kind')


class TestSidecarPromptAsksForTheCheckKind:
    """The sidecar turn is shown both fields and told when to leave them out (T4d)."""

    def _prompt(self) -> str:
        return SYNTHESIS_SIDECAR.format(
            synthesis_path='/x/01-t.md',
            sidecar_path='/x/01-t.sidecar.draft.json',
            brief_block='- [openrouter:openai] /x/openrouter/01-t/openai.md',
        )

    def _example(self) -> dict[str, object]:
        (line,) = [ln for ln in self._prompt().splitlines() if '"id": "v1"' in ln]
        return json.loads(line)

    def test_the_example_shows_both_keys(self) -> None:
        example = self._example()
        assert 'check_kind' in example
        assert 'target' in example

    def test_the_example_names_exactly_the_schema_vocabulary(self) -> None:
        # The prompt's list and the Literal cannot drift apart unnoticed.
        placeholder = str(self._example()['check_kind'])
        named = placeholder.strip('<>').split(',')[0].split(' | ')
        assert tuple(named) == _CHECK_KINDS

    def test_the_example_keeps_the_existing_keys(self) -> None:
        example = self._example()
        old = {k: v for k, v in example.items() if k not in ('check_kind', 'target')}
        VerificationItem.model_validate(old)  # the pre-T4d part still obeys the schema

    def test_the_turn_is_told_to_omit_both_when_no_kind_fits(self) -> None:
        (line,) = [
            ln
            for ln in self._prompt().splitlines()
            if '`check_kind`' in ln and '`target`' in ln and 'omit' in ln
        ]
        assert 'rejected' in line


class TestProvenanceAggregation:
    """``Provenance.from_subsessions`` sums the research cost/usage (A1)."""

    def test_sums_cost_and_tokens_across_subsessions(self) -> None:
        subs = [
            SubsessionResult(
                subslug='gpt-5-exa', cost_usd=0.02, tokens_prompt=1000, tokens_completion=500
            ),
            SubsessionResult(
                subslug='gemini-3-pro', cost_usd=0.03, tokens_prompt=2000, tokens_completion=800
            ),
        ]
        prov = Provenance.from_subsessions(subs, synthesis_duration_s=12.5)
        assert prov.total_cost_usd == pytest.approx(0.05)
        assert prov.total_tokens_prompt == 3000
        assert prov.total_tokens_completion == 1300
        assert prov.per_source_cost_usd == {'gpt-5-exa': 0.02, 'gemini-3-pro': 0.03}
        assert prov.synthesis_duration_s == 12.5

    def test_missing_usage_stays_none_not_zero(self) -> None:
        # The Gemini CLI path reports no usage — totals must stay None (a missing
        # usage block must not masquerade as a genuine zero cost).
        prov = Provenance.from_subsessions([SubsessionResult(subslug='single', status='done')])
        assert prov.total_cost_usd is None
        assert prov.total_tokens_prompt is None
        assert prov.total_tokens_completion is None
        assert prov.per_source_cost_usd == {}

    def test_partial_usage_sums_only_reported(self) -> None:
        subs = [
            SubsessionResult(subslug='a', cost_usd=0.01, tokens_prompt=100, tokens_completion=50),
            SubsessionResult(subslug='b'),  # no usage block reported
        ]
        prov = Provenance.from_subsessions(subs)
        assert prov.total_cost_usd == pytest.approx(0.01)
        assert prov.total_tokens_prompt == 100
        assert prov.total_tokens_completion == 50
        assert prov.per_source_cost_usd == {'a': 0.01}

    def test_empty_subsessions_keeps_duration_only(self) -> None:
        prov = Provenance.from_subsessions([], synthesis_duration_s=3.0)
        assert prov.synthesis_duration_s == 3.0
        assert prov.total_cost_usd is None
        assert prov.per_source_cost_usd == {}


class TestProjectForAgent:
    """Bounded projection for the MCP result (spec 0002 §3/§4)."""

    def test_small_sidecar_projects_fully_untruncated(self) -> None:
        sc = ResearchSidecar.from_model_json(json.dumps(_FULL_MODEL_DOC))
        out = project_for_agent(sc)
        assert [c['id'] for c in out['claims']] == ['c1', 'c2']
        assert out['divergences'][0]['substrates'] == ['claude', 'openrouter:gpt-5-exa']
        assert out['truncated']['any'] is False

    def test_count_cap_truncates_and_reports_omitted(self) -> None:
        doc = {
            'sidecar_version': 1,
            'claims': [{'id': f'c{i}', 'text': 'short'} for i in range(50)],
        }
        sc = ResearchSidecar.from_model_json(json.dumps(doc))
        out = project_for_agent(sc, max_items=20)
        assert len(out['claims']) == 20
        assert out['truncated']['claims'] == 30
        assert out['truncated']['any'] is True

    def test_char_budget_clips_long_free_text(self) -> None:
        # Few-but-huge items still overflow a count-only cap; the char budget
        # keeps the serialized payload bounded (spec 0002 round-2 FM-7).
        doc = {'sidecar_version': 1, 'claims': [{'id': 'c1', 'text': 'x' * 100_000}]}
        sc = ResearchSidecar.from_model_json(json.dumps(doc))
        out = project_for_agent(sc, max_items=5, max_item_chars=200)
        assert len(out['claims'][0]['text']) < 250  # clipped to ~200 + marker
        assert out['claims'][0]['text'].endswith('[clipped]')
        assert len(json.dumps(out)) < 2000  # total payload stays small
