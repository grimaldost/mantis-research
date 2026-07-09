# Falsification prompt — playbook (Stage 4, optional)

How to author the `topics[].stages.falsification.prompt` field — or use
the project default in `default_prompts.falsification`. Stage 4 is
**optional** and recommended only for high-stakes topics where being
wrong is expensive (regulatory, financial, model-validation, decision-
relevant work).

The falsification stage is **Claude single-turn** running the synthesis
model (`models.synthesis`/`models.claude`; unpinned configs resolve to
the newest Opus — max effort by default). It takes the synthesis
document as input and produces a counter-evidence document at
`research-outputs-falsification/NN-slug.md` challenging the synthesis's
headline claims.

This is the **Main → Falsification iteration pattern** documented in
*Prompting Claude's Advanced Research Mode* — third launch in a chain,
unusual but powerful. Anthropic's own research-team multi-agent system
uses this pattern internally (the "advisor strategy" / Main → Falsification
chain).

---

## When to use Stage 4

Run falsification when ANY of:

- The topic is regulatory or financial — being wrong has audit / capital /
  fiduciary cost
- The synthesis's headline claims drive a downstream decision (adopt
  library X, switch convention Y, change architecture Z)
- The hallucination-hotspot framing applies (Brazilian regulatory
  specifics, specialized law/finance — citation hallucination ceiling
  17–33% even with retrieval-grounded products)
- The synthesis Meta-Observations flagged 5+ items requiring external
  verification — that's enough material to justify a dedicated pass

Skip when:

- Topic is engineering / methodology / mantis-substrate without a load-
  bearing decision attached
- Synthesis converges with high-quality citations to primary sources
  already, no flagged claims
- Cost / time budget exhausted (this is +30-60 min and another Opus
  4.7 max-effort run)

---

## Default falsification prompt

The default lives in `default_prompts.falsification` of the batch config.
Template structure (runner formats `{synthesis_path}`,
`{falsification_path}`):

```
You are the falsification stage of a multi-model research pipeline.
Your role is exclusively adversarial: identify and present the
strongest evidence AGAINST the headline claims of the synthesis
document. This is the third pass in a Main → Falsification iteration
chain (Anthropic's documented research-team pattern).

You are NOT producing a balanced view. You are NOT defending the
synthesis. The synthesis already had its day; this pass exists to
find what it missed, smoothed over, or got wrong.

## Source

<source role="synthesis-under-test">
{synthesis_path} ({synthesis_size_kb:.1f} KB)
</source>

Use the Read tool to read the synthesis before writing. Pay special
attention to the `## Synthesis Meta-Observations` section — items
flagged there as "verify externally" are first-priority targets for
this pass.

## Pre-falsification claim extraction (mandatory first step)

Before drafting the counter-evidence document, output a `<claims>`
block listing the synthesis's HEADLINE CLAIMS — the load-bearing
factual assertions whose truth carries weight downstream. For each:

- Claim verbatim (quoted from the synthesis)
- Source path + section reference
- Why it's load-bearing (what downstream decision or framing depends
  on it)

Aim for 8-15 claims. The selection itself is part of the value:
identifying what's load-bearing distinguishes substantive falsification
from prose critique.

## What to produce

Save the falsification document to {falsification_path} using the
Write tool. Structure it as follows:

### Per-claim adversarial analysis

For each claim from the `<claims>` block, produce a subsection:

#### Claim N: [verbatim from synthesis]

**Source location:** [synthesis section / paragraph]

**Counter-evidence found:** Use WebSearch / WebFetch aggressively to
find the strongest counter-evidence against this specific claim. Cite
primary sources (regulator texts, peer-reviewed papers, contradicting
benchmarks). If none found, state explicitly: "No counter-evidence
found in [N searches across sources X/Y/Z]."

**Counter-arguments found:** Methodological critiques, alternative
interpretations, boundary conditions where the claim fails.
Steelmanned: present each counter-argument in the form its strongest
proponent would defend, not the weakest paraphrase.

**Boundary conditions where the claim fails:** Specific scenarios
(time periods, jurisdictions, parameter regimes, populations) where
the claim does NOT hold. If the synthesis stated the claim as a
universal but it's actually conditional, surface the conditions.

**Surviving robustness rating:** Rate the claim's surviving robustness
after counter-evidence is incorporated:
- **HIGH** — counter-evidence is weak / non-existent / outweighed by primary-source weight
- **MEDIUM** — claim holds under most conditions but has documented exceptions
- **LOW** — claim has substantive counter-evidence and is contested in the literature
- **FALSIFIED** — direct primary-source evidence contradicts the claim

Provide a short justification (2-4 sentences) for the rating.

### Final section: Ranked claim list

Reproduce the claim list, sorted by surviving robustness ascending
(weakest first). This is the primary deliverable for downstream
review — the claims most likely to be wrong are at the top, the
claims most likely to be right are at the bottom.

### Falsification Meta-Observations

a) **Search exhaustiveness.** For each claim rated HIGH (no
   counter-evidence found), state how exhaustive the search was — N
   queries, N sources consulted, gaps where you could not access
   paywalled / non-English / archived material.

b) **Synthesis consensus-smoothing.** Did the synthesis treat any
   contested claim as settled? List specific instances. (This is
   the "false synthesis" failure mode that cluster-then-synthesize
   pipelines are structurally biased toward.)

c) **Synthesis fabrications.** Did the synthesis cite any source
   that you couldn't resolve? Any DOI / arXiv id / paragraph
   number / vendor product name that doesn't exist? List them
   explicitly.

d) **Claims that depend on auxiliary hypotheses (Duhem-Quine).**
   Where the synthesis treats a claim as direct, but it actually
   depends on auxiliary hypotheses (measurement-theory assumptions,
   benchmark validity, training-data validity), surface the
   auxiliaries. A counter-instance to the auxiliary would invalidate
   the headline.

This document does NOT replace the synthesis. It is a counter-evidence
companion. The synthesis remains the canonical reference; this stage
flags which parts of it should be downgraded in confidence.
```

The runner formats `{synthesis_path}`, `{falsification_path}` before
sending.

---

## Quality signals to verify post-run

After Stage 4 completes, the falsification document at
`research-outputs-falsification/NN-slug.md` should satisfy:

| Signal | Expected |
|---|---|
| `<claims>` block emitted with 8-15 claims | Yes |
| Per-claim subsections with all 4 fields | Yes (counter-evidence, counter-arguments, boundary conditions, robustness rating) |
| Robustness ratings populated | Each claim rated HIGH/MEDIUM/LOW/FALSIFIED with justification |
| Ranked list at end | Yes, sorted weakest-first |
| Meta-observations section | All 4 subsections (search exhaustiveness, consensus-smoothing, fabrications, auxiliary hypotheses) |
| At least one claim downgraded | If ALL claims rate HIGH after falsification, the search wasn't exhaustive — flag for re-run |

---

## When to override the default

Per-topic override of the falsification prompt is rarely needed.
Override when:

### Specific authorities to consult

For regulatory topics, list specific primary sources the falsification
must check:

> *"For each numeric claim, fetch the primary regulatory document and
> cross-reference. Sources to consult: bcb.gov.br, cvm.gov.br, basel.org,
> ifrs.org. If the synthesis cites a paragraph number, verify the
> paragraph number resolves to the cited content."*

### Verification protocols

For software-engineering topics:

> *"For each library / API / version claim, verify against the official
> docs and PyPI / GitHub release pages. If the synthesis claims a feature
> is present in version X, check the changelog. If it claims a function
> signature, paste the actual signature from the docs."*

### Domain expert framing

For domains where the falsification model has weaker prior knowledge:

> *"Treat yourself as a [specific role: senior banking regulator / IFRS
> technical accountant / chip-design EDA engineer]. The synthesis was
> produced by a generalist; this pass exists to apply domain expertise
> the synthesis lacked. Where the synthesis makes claims that a
> [specific role] would immediately question, surface those questions."*

---

## Integration with the rest of the pipeline

- **Stages 1, 2, 3** (Claude research, Gemini research, synthesis +
  journal) run as usual.
- **Stage 4** runs OPTIONALLY after Stage 3 completes. Gates: synthesis
  file must exist; no other stages need to follow.
- **Journal stage interaction**: the journal (Stage 3 turn 2) is
  produced BEFORE Stage 4 in default sequencing. If Stage 4 finds the
  synthesis has FALSIFIED claims, the journal is also affected.
  Workflow: re-run Stage 4 with falsification, then re-run the journal
  stage (via `run_journal_only.py --source falsification`) to journal
  the falsified-version document.

Alternative: defer the journal stage until after falsification, so the
canonical journal is always backed by the falsification-tested document.
This is cleaner but adds 30-60 min to the wall-clock per topic.

---

## Anti-patterns

| Symptom | Fix |
|---|---|
| Falsification produces "this claim looks fine" for all claims | Search wasn't exhaustive — re-run with explicit "search at least 5 sources per claim" directive |
| Counter-arguments are weak-form straw arguments | Steelmanning ignored — demand "strongest version proponent would defend" |
| All ratings are MEDIUM | Calibration failure — demand explicit decision rule for HIGH vs MEDIUM vs LOW |
| Meta-observations missing search-exhaustiveness | Specific failure mode — accept-as-is is not the same as nothing-found-after-thorough-search |
| Falsification rewrites the synthesis | Stage 4 is adversarial commentary, not replacement. The synthesis remains canonical |

---

## Caveat

Stage 4 is itself subject to the same shared-substrate independence
limitation as Stage 3 (Goel et al. ICML 2025: cross-model mistake
correlation grows with capability). A Claude-Opus-4.7 falsifying a
Claude-Opus-4.7 synthesis has the same training distribution. The
"adversarial" framing helps via the third-person / role-locked
mechanism (SYCON Bench: third-person reduces sycophancy by up to
63.8%), but does not give true judge-level independence.

For genuinely high-stakes topics, programmatic verification (URL/DOI/
identifier resolution, package PyPI check) and human-expert review
are more reliable independence axes than another Claude session.
Stage 4 is "additional adversarial pass," not "external validation."
