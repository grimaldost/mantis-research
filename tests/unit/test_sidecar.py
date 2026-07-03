"""Sidecar schema v1 tests (spec 0001 §13 / ADR-0003)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from mantis_research.core.sidecar import Provenance, ResearchSidecar, project_for_agent
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


class TestValidation:
    def test_wrong_version_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ResearchSidecar.from_model_json(json.dumps({'sidecar_version': 2}))

    def test_claim_without_id_rejected(self) -> None:
        doc = {'sidecar_version': 1, 'claims': [{'text': 'no id here'}]}
        with pytest.raises(ValidationError):
            ResearchSidecar.from_model_json(json.dumps(doc))

    def test_unknown_key_rejected(self) -> None:
        # extra='forbid' — a typo'd field must fail, not be silently dropped.
        doc = {'sidecar_version': 1, 'claimz': []}
        with pytest.raises(ValidationError):
            ResearchSidecar.from_model_json(json.dumps(doc))


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
