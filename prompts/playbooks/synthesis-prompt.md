# Synthesis prompt — playbook

How to author the `topics[].stages.synthesis.prompt` field — or use the
project default in `default_prompts.synthesis`. Most topics use the
default; per-topic override is for unusual cases.

The synthesis stage is **Claude two-turn** running the synthesis model
(`claude-opus-4-7` max-effort by default). Turn 1 reads all sources
(Claude brief + 1+ Gemini sub-briefs), produces a merged document with
explicit divergence flagging and meta-observations, saves to
`research-outputs-synthesis/NN-slug.md`. Turn 2 invokes the
chat-session-journal skill on the synthesis (see
`journal-prompt.md`).

This playbook governs Turn 1. Validated empirically on the topic-1
(semiconductor) test: 65 KB Claude + 5.6 KB Gemini → 91.8 KB synthesis
with 1 inline divergence block and 7 hallucination flags in the
meta-observations section.

---

## Default synthesis prompt (project-wide)

The default lives in `default_prompts.synthesis` of the batch config
and is injected by the runner with the actual source paths. Two design
notes shape its structure:

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

Template structure (the runner formats `{claude_path}`, `{gemini_block}`,
etc. before sending):

```
You are the synthesis stage of a multi-model research pipeline. Your
job is to merge two LLM-produced briefs into one richer document with
explicit divergence flagging and meta-observations on model biases and
prompt quality.

## Sources to read

<source role="primary" model="claude-opus-4-7" effort="max">
{claude_path} ({claude_size_kb:.1f} KB)
</source>

<source role="secondary" model="gemini-3-flash-preview-via-oauth" count="{gemini_count}">
{gemini_block}
</source>

Use the Read tool to read all sources before writing.

## Pre-synthesis quote extraction (mandatory first step)

Before drafting the merged synthesis, output a `<quotes>` block
containing 5-10 of the MOST DIVERGENT passages between the Claude and
Gemini briefs — passages where the two sources make claims that
disagree on a verifiable fact, frame the same concept from different
angles, or where one source addresses something the other doesn't.
Each quote: source path, brief, exact passage. This anchors the
synthesis to real spans rather than to associatively-activated
context.

## What to produce

Save the synthesis brief to {synthesis_path} using the Write tool.

### Body — merged technical content

**Concept-centric structure (mandatory).** Each paragraph's topic
sentence is a CLAIM, not a model name or source name. Multiple sources
cited per paragraph. Diagnostic test: read your topic sentences. If
they are claims, the synthesis is concept-centric. If they are
"Claude says X, Gemini says Y" sequential, it's an annotated
bibliography (the failure mode arXiv moderators flagged in October
2025).

The structure follows Claude's brief (it's the comprehensive
substrate). Fold in Gemini content where it adds detail, alternative
framing, or cross-checks a Claude claim. The synthesis should be
RICHER than either input alone — the union with conflicts explicit,
not the intersection.

Where the models agree on a substantive claim, state the merged claim
cleanly. **Note: cross-model agreement is WEAKER signal than intuition
suggests** (Goel et al., ICML 2025: mistake similarity grows with
capability across frontier models because they share substrate).
Agreement on a non-trivial verifiable claim is worth explicit
flagging — list 2-3 such items in the meta-observations as candidates
for external verification rather than treating them as confirmed.

Where the models diverge, flag the divergence in-line with an explicit
block. **Steelmanning required:**

> **Divergence:** Claude argues <X-as-Claude's-strongest-version-would-defend-it>.
> Gemini argues <Y-as-Gemini's-strongest-version-would-defend-it>.
> <Your assessment of which is right, or whether both are valid
> framings under different conditions — cite specific reasons or
> sources. Don't quietly average; naming the disagreement is the
> point.>

If the briefs largely agree on the topic, **do NOT manufacture
divergences to satisfy a count**. Flag the agreement explicitly
("the briefs converge on X with the same source attribution Y"). The
synthesis values flagged uncertainty over confident-wrongness, and
flagged agreement over manufactured disagreement.

### `## Synthesis Meta-Observations` — at the end

This section is feedback signal for prompt engineering and model
evaluation, not technical content. Cover:

a) **Depth distribution.** Which sub-areas of the topic did Claude
   treat well that Gemini thinned, and vice versa? Cite specific
   section names or claims.

b) **Notable biases.** Any framing that seemed off in either model.
   Training-recency artifacts, vendor lock-in, ideological lean,
   framing-as-marketing. Cite specific examples.

c) **Prompt-signal quality.** Did both models interpret the prompt
   the same way? If they diverged on what to research, the prompt was
   ambiguous — call out which phrasing was the load-bearing source of
   divergence. (For this pipeline specifically: the Claude prompt has
   "mantis substrate / analogical-transfer" framing; Gemini prompts
   strip it because that framing hijacks the gemini-3-flash router.
   Note any drift the asymmetric prompts introduced.)

d) **Hallucination flags.** Cross-model disagreement on factual
   claims is the strongest signal. List 3-5 specific claims where
   the models disagree on a verifiable fact (tool versions, file
   format details, vendor attributions, recent events). For each,
   state which is likely correct or that both are unverified pending
   external check. Each flag should be specific enough that an
   external verifier could resolve it: name the claim, the source
   that's more credible, and the verifiable fact at issue.

e) **Cross-model agreement worth verifying.** List 2-3 non-trivial
   claims where Claude and Gemini AGREE on a specific fact (number,
   date, name, version, regulatory paragraph). Cross-model agreement
   on training-data-uniform claims is weak signal — both could be
   wrong. Worth explicit verification before downstream reliance.

f) **Independence note.** Acknowledge: this synthesis was produced by
   Claude integrating its own brief plus a Gemini cross-check. Both
   models share substrate (Common Crawl, Wikipedia, GitHub, ArXiv).
   This is "tertiary independence" in the MRM/IEEE 1012 sense — not
   the kind of judge-level independence that programmatic verifiers
   or domain experts would provide. Treat the synthesis as
   comprehensive cross-check, not as validation.

The synthesis is the canonical reference document going forward; the
individual research briefs are working notes.
```

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
| Size | ≥ Claude brief size | Synthesis is doing intersection, not union — rewrite prompt to require integration of Gemini-unique content |
| Concept-centric paragraphs | Topic sentences are claims, not model names | Author-centric / annotated-bibliography failure |
| Steelmanned divergence blocks | Each `> **Divergence:**` presents each model's *strongest* form | Weak-form straw arguments — re-emphasize steelmanning |
| Inline divergence blocks | ≥ 1 IF disagreement is real; 0 acceptable if convergence is genuine + flagged | Zero divergence blocks AND no convergence note = consensus-smoothing |
| `## Synthesis Meta-Observations` present | Yes, at the end | Missing — prompt didn't anchor strongly enough |
| All 6 meta-observation subsections (a–f) | Yes, all populated | Missing subsection — re-emphasize in prompt |
| Hallucination flags concrete | Each flag names a specific claim, the more credible source, the verifiable fact | Handwavy ("Gemini was off somewhere") — demand named claims |
| Cross-model agreement section | 2-3 verifiable claims listed for external verification | Missing — risk of inflated trust in shared-substrate agreement |
| Independence note | Explicit acknowledgment of tertiary-only independence | Missing — risk of overclaiming validation |

Validated topic-1 numbers (under the v1 prompt without quote-first or
steelmanning): 91.8 KB output, 1 inline divergence block, 7 hallucination
flags, 5 meta-observation subsections populated. Re-running under the v2
prompt (with quote-first + steelmanning + cross-model agreement section)
should produce: more divergence blocks (or explicit convergence flagging),
substantively similar size, and a populated cross-model-agreement section.

---

## Anti-patterns

| Symptom | Fix |
|---|---|
| Synthesis ≤ Claude brief size | Rewrite prompt to require explicit integration of Gemini-unique content; smaller output = intersection-thinking, not union |
| No `<quotes>` block emitted | Quote-first directive ignored — strengthen "MANDATORY first step" framing |
| Topic sentences are model names | Author-centric — re-emphasize concept-centric structure with diagnostic test |
| Manufactured divergences | "Flag at least N divergences" prompts can produce hallucinated disagreement — pair with explicit "do NOT manufacture" guard |
| Weak-form straw divergences | Steelmanning ignored — demand "strongest version each model would defend" |
| Meta-observations vague | Demand specific section/claim citations, not general remarks |
| Hallucination flags handwavy | Require named claims with concrete verdicts — items 1-2 in the validated topic-1 run did this well; items 3-7 marked as "verify externally" |
| Body re-emits Gemini's framing verbatim | Synthesis should integrate, not paste. Re-emphasize "merged" wording |
| Independence note missing or denied | Tertiary-only independence is a fact — demand explicit acknowledgment per Goel et al. ICML 2025 |
| Cross-model agreement treated as validation | Add explicit "agreement is weak signal" framing; demand verification candidate list |

---

## When the synthesis is the wrong tool

If the topic genuinely had matched-quality output from both models
(rare on the OAuth path — typically only happens on very short
prompts that stayed on pro tier), the synthesis is doing meaningful
merge work. If Gemini produced 5 KB of generic content that adds
nothing the Claude brief doesn't have, the synthesis stage just
adds latency and cost without value — in that case, the failure
is upstream (Gemini prompt was too generic). Fix the Gemini
prompt; don't try to make the synthesis stage compensate.

---

## Epistemic sidecar (ADR-0003, spec §14)

After the synthesis brief is written, the stage runs a **dedicated sidecar
turn**: the model reads the brief and writes `<stem>.sidecar.json` — the
machine-readable epistemic contract agent consumers load instead of parsing
prose. The schema is `core/sidecar.py` (`ResearchSidecar`, `sidecar_version: 1`),
with two authorship zones:

- **model-authored** — `claims`, `divergences`, `verification_queue`,
  `agreements_worth_verifying`, `coverage_notes` (drawn from the synthesis's
  divergence blocks and `## Synthesis Meta-Observations`).
- **runner-authored** — run identity (`topic_id` / `slug` / `batch_name` /
  `synthesis_path` / `generated_at`), `sources`, and `provenance`, merged in by
  the stage after the model's JSON validates.

Mechanics that matter:

- The prompt template (`SYNTHESIS_SIDECAR` in `core/prompts.py`) brace-escapes
  its JSON example so `str.format` binds only `{synthesis_path}` / `{sidecar_path}`.
- A malformed sidecar does **not** re-run the expensive synthesis: the stage
  validates and re-asks on the same session up to `_SIDECAR_MAX_ATTEMPTS` times,
  and an orchestrator retry skips Turn 1 when the brief already exists (the
  sidecar is a cheap, model-fallible step, isolated from the brief).
- The sidecar joins the synthesis done-condition — an unrecoverable sidecar
  fails the attempt (brief left intact for the retry).
