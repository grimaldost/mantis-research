# Synthesis prompt — playbook

How to author the `topics[].stages.synthesis.prompt` field — or use the
project default in `default_prompts.synthesis`. Most topics use the
default; per-topic override is for unusual cases.

The synthesis stage is **Claude multi-turn** running the synthesis model
(`models.synthesis`, falling back to `models.claude`; unpinned configs
resolve to the newest Opus — max effort by default). Turn 1 reads all
sources (the primary brief plus every secondary, per `models.primary`),
produces a merged document with explicit divergence flagging and
meta-observations, saved to `research-outputs-synthesis/NN-slug.md`
(legacy layout). A dedicated follow-up turn emits the epistemic sidecar
(`NN-slug.sidecar.json`), and the optional journal turn (see
`journal-prompt.md`) runs when `stages.journal.enabled` allows it.

This playbook governs Turn 1.

**The template is substrate-neutral, and that is load-bearing.** A default
run is Path B: N OpenRouter research substrates and no Claude research
brief at all. The template therefore names no vendor. It takes the brief
count, the primary label and the substrate list from the run itself, so
the model is told the truth about its own inputs. Before this, the
template opened "merge two LLM-produced briefs", asked for divergences
"between the Claude and Gemini briefs", asserted "the structure follows
Claude's brief", carried a Gemini router note, and closed with an
independence paragraph describing one model integrating its own brief plus
a cross-check — none of it true on a three-substrate run. Every synthesis
in one six-topic batch independently detected and corrected the label
mismatch, and one noted the template had no slot for a third brief at all.
`tests/unit/test_synthesis_prompt.py` now holds the neutrality.

---

## Default synthesis prompt (project-wide)

The default template is packaged as `SYNTHESIS` in
`src/mantis_research/core/prompts.py`; the runner injects the actual
source paths, labels and counts. A batch can override it via
`default_prompts.synthesis` and a topic via `stages.synthesis.prompt` —
the resolution chain is documented in
[batch-config.md](../../docs/batch-config.md#default_prompts).

Three design notes shape its structure:

1. **U-shape attention bias** (Liu 2023, Hsieh 2024): tokens at the
   beginning and end of input receive disproportionate attention.
   Sources are wrapped in XML tags at the top; the "what to produce"
   instructions land at the bottom. This is the empirically-validated
   shape per Anthropic's own long-context guidance ("up to 30%
   response-quality improvement" putting queries at the bottom).

2. **Quote-first prompting** (Shi 2023, Modarressi 2025 NoLiMa):
   forcing the model to extract relevant passages into a `<quotes>`
   block before answering anchors reasoning to real spans rather than
   to associatively-activated context.

3. **Agreement is not corroboration.** Frontier models share substrate,
   so mistake similarity grows with capability (Goel et al., ICML 2025).
   The template says so twice: once as a general caution, and once as a
   hard rule — agreement on a *named artifact* no brief traces to a
   verifiable primary source is a co-hallucination flag. This exists
   because two substrates co-hallucinated the same fake source and the
   synthesis promoted it to a recommendation on the strength of their
   agreement; the same class recurred as an entire invented repository
   with detailed properties.

### Variables the runner supplies

| Variable | Meaning |
|---|---|
| `{primary_label}` | The primary brief's label, e.g. `openrouter:openai` |
| `{primary_path}` / `{primary_size_kb}` | The primary brief on disk |
| `{secondary_count}` / `{secondary_block}` | The secondaries, one line each with label, path and size |
| `{source_count}` | Total briefs being merged (primary + secondaries) |
| `{substrate_list}` | Every label in the run, comma-joined — what the independence note names |
| `{synthesis_path}` | Where to write the merged brief |

The legacy `{claude_path}` / `{claude_size_kb}` / `{gemini_count}` /
`{gemini_block}` aliases are still bound to the resolved primary and the
secondary block, so a config carrying an old custom prompt keeps working.
Do not use them in new prompts: they name substrates a Path-B run does not
have, which is exactly how the default template came to describe a
pipeline that no longer existed.

### Template structure

Read the current text in `core/prompts.py` — it is the single source of
truth and is short enough to read directly. Its shape:

- **Sources to read** — the primary in a `<source role="primary">` tag,
  the secondaries in a `<source role="secondary" count=…>` tag.
- **Pre-synthesis quote extraction** — a mandatory `<quotes>` block of
  5-10 of the most divergent passages *across the briefs*.
- **Body** — concept-centric structure (topic sentences are claims, not
  source names), organised by the topic's own structure rather than any
  one brief's; agreement stated cleanly but flagged, with the
  co-hallucination rule above it; divergences in steelmanned
  `> **Divergence:**` blocks; an explicit guard against manufacturing
  divergences to satisfy a count.
- **`## Synthesis Meta-Observations`** — six subsections (a) depth
  distribution, (b) notable biases, (c) prompt-signal quality, (d)
  hallucination flags, (e) cross-brief agreement worth verifying plus the
  unverifiable named artifacts, (f) an independence note naming
  `{substrate_list}`.

---

## When to override the default

Per-topic override of the synthesis prompt is rarely needed. Override
when:

### Known multi-source disagreement requires aggressive flagging

For regulatory topics where authoritative interpretations diverge
across regulators (e.g., the same accounting concept under IFRS vs US
GAAP vs Brazilian CPC, where each has paragraph-level wording
differences). In this case, demand more inline divergence blocks:

> *"Where the IFRS, US GAAP, and Brazilian CPC treatments diverge on
> the same concept, flag with a `> **Divergence:**` block citing the
> specific paragraph from each. Aim for at least 5 inline divergence
> blocks across the body."*

### Domain-specific verification protocols

For topics where verification matters more than usual (e.g.,
load-bearing financial figures, regulatory thresholds), augment the
Hallucination flags directive:

> *"For each numerical claim flagged as a divergence, state the
> primary source that should be consulted to resolve, and the URL
> path to the specific document section."*

### Non-standard output structure

Rare. If the topic should produce a decision memo rather than a
merged brief (e.g., "should we adopt library X" topics), override
the body-structure section to require a decision-memo shape with
recommendation / rationale / risks / next steps.

---

## Quality signals to verify post-run

After Turn 1 completes, the synthesis at
`research-outputs-synthesis/NN-slug.md` should satisfy:

| Signal | Expected | Failure mode if violated |
|---|---|---|
| `<quotes>` block in stdout | Present at top of response, 5-10 entries | Missing — quote-first directive ignored; synthesis didn't anchor to real spans |
| Size | ≥ the largest input brief | Synthesis is doing intersection, not union — require integration of content unique to each brief |
| Concept-centric paragraphs | Topic sentences are claims, not source labels | Author-centric / annotated-bibliography failure |
| Steelmanned divergence blocks | Each `> **Divergence:**` presents each brief's *strongest* form | Weak-form straw arguments — re-emphasize steelmanning |
| Inline divergence blocks | ≥ 1 IF disagreement is real; 0 acceptable if convergence is genuine + flagged | Zero divergence blocks AND no convergence note = consensus-smoothing |
| `## Synthesis Meta-Observations` present | Yes, at the end | Missing — prompt didn't anchor strongly enough |
| All 6 meta-observation subsections (a–f) | Yes, all populated | Missing subsection — re-emphasize in prompt |
| Hallucination flags concrete | Each flag names a specific claim, the more credible source, the verifiable fact | Handwavy ("one brief was off somewhere") — demand named claims |
| Co-hallucination candidates listed | Every agreed-on named artifact the briefs do not establish appears in (e) | Missing — an invented repository can reach a recommendation on agreement alone |
| Independence note | Names the substrate set actually used; acknowledges tertiary-only independence | Missing, or naming substrates the run did not use — risk of overclaiming validation |

No worked example is carried here. The one that used to be — a two-brief
Claude+Gemini run with per-brief byte counts — described an input shape
the pipeline no longer produces, and a stale example in a spec is worse
than none: it teaches the shape it froze. Validate against a current
three-substrate run instead.

---

## Anti-patterns

| Symptom | Fix |
|---|---|
| Synthesis smaller than its largest input | Require explicit integration of content unique to each brief; smaller output = intersection-thinking, not union |
| No `<quotes>` block emitted | Quote-first directive ignored — strengthen "MANDATORY first step" framing |
| Topic sentences are source labels | Author-centric — re-emphasize concept-centric structure with the diagnostic test |
| Manufactured divergences | "Flag at least N divergences" prompts can produce hallucinated disagreement — pair with the explicit "do NOT manufacture" guard |
| Weak-form straw divergences | Steelmanning ignored — demand "strongest version each brief would defend" |
| Meta-observations vague | Demand specific section/claim citations, not general remarks |
| Hallucination flags handwavy | Require named claims with concrete verdicts |
| A named artifact several briefs agree on reaches a recommendation | The co-hallucination rule was not applied — agreement without a traceable primary source is a flag, not corroboration |
| Body re-emits one brief's framing verbatim | Synthesis should integrate, not paste. Re-emphasize "merged" wording |
| Independence note missing, denied, or naming the wrong substrates | Tertiary-only independence is a fact, and the substrate list is supplied — demand both |
| Cross-brief agreement treated as validation | The "agreement is weak signal" framing is in the template; demand the verification-candidate list |
| The prompt names a vendor | A substrate-specific clause in a substrate-neutral template will be false on most runs — parameterise it or delete it |

---

## When the synthesis is the wrong tool

The synthesis earns its cost when the briefs actually differ — in
coverage, in framing, or in what they cite. If every substrate returned
near-identical content, the stage adds latency without adding signal, and
the fix is upstream: a research prompt too generic to produce distinct
briefs, or a substrate set with too little substrate diversity (see
`model-recommendations.md`). Do not try to make the synthesis stage
compensate for briefs that had nothing to disagree about.

---

## Epistemic sidecar (ADR-0003, spec §14)

After the synthesis brief is written, the stage runs a **dedicated sidecar
turn**: the model reads the brief and writes `<stem>.sidecar.json` — the
machine-readable epistemic contract agent consumers load instead of parsing
prose. The schema is `core/sidecar.py` (`ResearchSidecar`, `sidecar_version: 2`),
with two authorship zones:

- **model-authored** — `claims`, `divergences`, `verification_queue`,
  `agreements_worth_verifying`, `coverage_notes` (drawn from the synthesis's
  divergence blocks and `## Synthesis Meta-Observations`), plus
  `source_citations`: one citation inventory per research brief.
- **runner-authored** — run identity (`question` / `topic_id` / `slug` /
  `batch_name` / `synthesis_path` / `generated_at`), `sources`, and
  `provenance`, merged in by the stage after the model's JSON validates.

Mechanics that matter:

- The prompt template (`SYNTHESIS_SIDECAR` in `core/prompts.py`) brace-escapes
  its JSON example so `str.format` binds only `{synthesis_path}` / `{sidecar_path}`.
- A malformed sidecar does **not** re-run the expensive synthesis: the stage
  validates and re-asks on the same session up to `_SIDECAR_MAX_ATTEMPTS` times,
  and an orchestrator retry skips Turn 1 when the brief already exists (the
  sidecar is a cheap, model-fallible step, isolated from the brief).
- The sidecar joins the synthesis done-condition — an unrecoverable sidecar
  fails the attempt (brief left intact for the retry).
- The **runner-authored zone is gated separately** from the model's. After the
  merge, `require_complete()` demands `question`, `generated_at` and a non-empty
  `sources`, and raises if any is absent. That failure does not consume a
  re-ask: the gap is the runner's, so another model turn would reproduce it.
- **`source_overlaps` is recomputed, not accepted.** The model writes the
  citation inventory and, per overlapping source, whether the briefs read
  incompatible figures out of it. `derive_source_overlaps` then recomputes which
  substrates cited each source and which never did, and folds the model's
  conflict judgement onto that. Membership is data; only the conflict is
  judgement. This is what makes "two substrates cited the same URL and disagreed
  about it" a computed fact rather than free text improvised into
  `Divergence.substrates` — a field documented for something else.
