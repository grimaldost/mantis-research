# Evaluation prompt — playbook (synthesis quality harness)

How to author the evaluation prompt for measuring synthesis quality
(post-Stage-3) — and how to interpret the structured output.

The evaluation stage is **separate from the synthesis stage** by design.
This is the verification-validation separation principle from VV&UQ
(Roache, ASME V&V 10) and the three-lines-of-defense from MRM (Federal
Reserve SR 11-7): the same Claude session that produced the synthesis
should NOT also evaluate it. Conflation of producer and validator is
the most common failure mode in computational science evaluation
(Oberkampf & Roy 2010).

The evaluation produces a structured JSON record at
`evaluations/NN-slug-eval.json` that drives:

- Quality gating (which synthesis outputs pass / fail / need rerun)
- Calibration tracking (over time, do confidence values predict
  verification outcomes?)
- Pipeline iteration (which prompts produce systematically better
  output?)

---

## The 3-gate + 6-criterion rubric

Adapted from `mantis-meditation-rubric-philosophy-of-science.md` and
`workstream-c-evaluator-spec-proposal.md`. Mantis-first, not
philosophy-first: mantis failure modes (confabulation from sparse
clusters, LLM surface-pattern-matching, training-consensus bias,
vacuous-tautology synthesis) drive the rubric, with philosophy-of-
science criteria borrowed only where they transfer cleanly.

### Hard gates (auto-reject if triggered)

**Gate 1 — Confabulation.** Per-claim source-mapping. The evaluator
emits, for each non-trivial claim in the synthesis,
`{"claim": "...", "supporting_sources": [paths], "support_quality":
"direct" | "indirect" | "none"}`. If more than one substantive claim
has `support_quality: "none"` AND is not explicitly flagged as
speculative in the synthesis text, Gate 1 triggers.

**Gate 2 — Vacuous-tautology.** The evaluator explicitly states the
negation of each major synthesis claim, then describes a concrete
observation that would be more consistent with the negation than with
the original. Inability to produce such an observation triggers the
gate. Secondary test: "If the user acted opposite to what this claim
implies, would their work obviously and trivially be worse?" — yes-
trivially answers are vacuity signals.

### Soft gate (penalty, not reject)

**Gate 3 — Training-consensus-parroting.** The evaluator receives a
**Claude-prior baseline** (Claude given only the topic title with no
cluster content — a reproducible, version-pinned baseline) and is
asked: "Could a competent generalist with no access to the original
research briefs produce this synthesis content from common industry
knowledge alone?" If yes for >30% of synthesis content, multiply Q
by 0.5. Soft because occasionally mainstream advice IS the right
answer for the topic — but the system should KNOW it.

### Six graded criteria (0-3 Likert each, total Q = sum/18 ∈ [0,1])

Likert scales bounded at 4 levels — past 4 levels, judge reliability
drops on subjective rubric criteria (Zheng 2023, MT-Bench).

| Criterion | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| **C1 — Specificity** | Generic claims, no specific tools / numbers / dates | Some specific entities but mostly generic | Most claims have specific tools / numbers / dates | All non-trivial claims have specific entities + verifiable details |
| **C2 — Mechanism-proposing** | Pure description, no causal claims | Implicit mechanisms, no naming | Some mechanisms named but not justified | Mechanisms named, traced to evidence, conditions stated |
| **C3 — Distinctiveness from Claude-prior** | Synthesis ≈ what Claude alone would produce | <30% novel content | 30-70% novel content | >70% content traceable to Gemini cross-check or to web-search-discovered novelty |
| **C4 — Traceability** | Most claims have no source attribution | Some claims sourced, secondary commentary | Most claims sourced to primary or Tier 2 | All non-trivial claims sourced to primary text + paragraph number |
| **C5 — Actionability** | No actionable substrate for downstream mantis ingestion | Some § 7 cross-domain links present but generic | § 7 with 3+ specific cross-domain mappings + conditions | § 7 + per-mapping action: "this pattern applies when X" |
| **C6 — Mode-dependent (varies by topic class)** | (Adapt: for regulatory = paragraph-level citation; for engineering = working code; for methodology = falsifiability + symmetric-treatment) | | | |

Total quality score: **Q = (C1 + C2 + C3 + C4 + C5 + C6) / 18 ∈ [0,1]**.

Combined with gate flags reported separately. A synthesis can score
Q=0.8 but trigger Gate 1 → still rejected.

---

## Default evaluation prompt

The evaluation runs as a **separate Claude session from the synthesis**
(critical — see VV&UQ playbook). Same model class (Claude Opus 4.7) but
fresh context. Template structure (runner formats source paths):

```
You are the evaluation stage of a multi-model research pipeline. Your
job is to score a synthesis document against a 3-gate + 6-criterion
rubric. You are NOT producing a synthesis; you are producing a
structured evaluation record.

You have NO access to the synthesis-production session's context.
Your evaluation is fresh — this is the verification/validation
separation principle from V&V (Roache, ASME V&V 10): the same agent
that produces should not also evaluate.

## Sources

<source role="synthesis-under-test">
{synthesis_path} ({synthesis_size_kb:.1f} KB)
</source>

<source role="claude-original">
{claude_path} ({claude_size_kb:.1f} KB)
</source>

<source role="gemini-originals">
{gemini_block}
</source>

<source role="claude-prior-baseline">
{claude_prior_baseline_path}
</source>

The Claude-prior baseline is Claude's output given ONLY the topic
title, with no access to the research briefs. It represents what a
generalist would produce from common industry knowledge. It is the
substrate for Gate 3 (training-consensus-parroting detection).

Read all sources with the Read tool before scoring.

## Pre-evaluation extraction (mandatory first step)

Before scoring, output a `<claims>` block listing the synthesis's
non-trivial claims (the ones that, if wrong, would damage downstream
mantis ingestion). Aim for 15-25 claims. Each:

- Claim verbatim (quoted from synthesis)
- Synthesis section / paragraph
- Type: factual / procedural / reference / extrapolation (the four-
  category taxonomy from confident-wrongness research)

This selection is itself part of the evaluation — identifying what's
load-bearing distinguishes substantive evaluation from prose review.

## What to produce

Save the evaluation record to {eval_path} as STRUCTURED JSON with this
exact shape:

{
  "topic_id": "{topic_id}",
  "synthesis_path": "{synthesis_path}",
  "evaluator_model": "claude-opus-4-7",
  "evaluation_timestamp": "<ISO 8601>",
  "claims_extracted": [<list of 15-25 claim objects>],
  "gate_1_confabulation": {
    "claim_mappings": [
      {
        "claim": "<verbatim>",
        "supporting_sources": ["<path>", ...],
        "support_quality": "direct" | "indirect" | "none",
        "speculative_flagged_in_synthesis": true | false
      },
      ...
    ],
    "triggered": true | false,
    "trigger_reason": "<if triggered, which claims with support=none and not flagged>"
  },
  "gate_2_vacuity": {
    "negation_tests": [
      {
        "claim": "<verbatim>",
        "negation": "<the explicit negation>",
        "concrete_observation_favoring_negation": "<...>" | null,
        "vacuous": true | false
      },
      ...
    ],
    "triggered": true | false,
    "trigger_reason": "<if triggered, which claims have no concrete-observation-favoring-negation>"
  },
  "gate_3_parroting": {
    "claude_prior_overlap_estimate_pct": <0-100>,
    "novel_content_estimate_pct": <0-100>,
    "soft_penalty_applied": true | false,
    "penalty_factor": 1.0 | 0.5
  },
  "criteria": {
    "c1_specificity": {"score": 0|1|2|3, "justification": "<...>"},
    "c2_mechanism_proposing": {"score": 0|1|2|3, "justification": "<...>"},
    "c3_distinctiveness_from_claude_prior": {"score": 0|1|2|3, "justification": "<...>"},
    "c4_traceability": {"score": 0|1|2|3, "justification": "<...>"},
    "c5_actionability": {"score": 0|1|2|3, "justification": "<...>"},
    "c6_mode_dependent": {
      "mode": "regulatory|engineering|methodology|other",
      "criterion": "<the specific criterion applied>",
      "score": 0|1|2|3,
      "justification": "<...>"
    }
  },
  "quality_score_Q_unpenalized": <sum of c1-c6 scores / 18>,
  "quality_score_Q_with_penalty": <Q * gate_3_penalty_factor>,
  "verdict": "PASS" | "PASS_WITH_PARROTING_PENALTY" | "REJECT_GATE_1" | "REJECT_GATE_2",
  "recommendations": [
    "<specific suggestion for re-running the synthesis prompt to address each below-threshold criterion>",
    ...
  ]
}

End the response with the JSON block ONLY (no prose afterwards). The
JSON is parsed directly by the evaluation harness.
```

The runner formats `{synthesis_path}`, `{claude_path}`, etc. and runs
`jq` validation on the output to check the JSON structure is correct.

---

## Building the Claude-prior baseline

Gate 3 needs a Claude-prior baseline per topic. Generate it ONCE per
topic, not per evaluation:

```
uv run python -m mantis_research run claude-prior config/<batch>.json --only N
```

This runs `claude -p` with ONLY the topic title and no other context,
no source files, no specific framing — just "Write a brief on {topic
title}." The output saves to `claude-prior-baselines/NN-slug.md`.
The evaluation harness reads this file to compute Gate 3's overlap.

Re-generate the baseline:
- When the model version changes (Opus 4.7 → 4.8 → ...)
- Once a quarter as a freshness check
- Never per-evaluation (defeats the purpose of having a fixed baseline)

---

## When to override the default

The default rubric works for ~all topic classes. Override C6 (mode-
dependent criterion) for specific domain classes:

- **Regulatory topics**: C6 = paragraph-level citation density (% of
  claims that cite paragraph numbers from primary regulatory texts)
- **Engineering topics**: C6 = working-code-snippet density (% of
  claims that include runnable code snippets, type signatures, or
  specific commit hashes)
- **Methodology topics**: C6 = falsifiability + symmetric-treatment
  (% of claims that have explicit falsification conditions stated)
- **Treasury / quant topics**: C6 = numerical-form compliance
  (`[value] [units] [methodology source] [sample] [date] [reasoning]`
  form; % compliance)

---

## Quality signals for the evaluation itself

The evaluation can fail in its own ways. Verify post-run:

| Signal | Expected |
|---|---|
| JSON parses | `jq` validation passes |
| Claims extracted | 15-25 entries |
| All rubric criteria scored | C1-C6 all populated with score + justification |
| Gate booleans set | All three gate `triggered` fields populated |
| Q score computed | `quality_score_Q_unpenalized` = sum/18; `_with_penalty` = Q * factor |
| Verdict matches gate states | If Gate 1 triggered → verdict = REJECT_GATE_1 |
| Recommendations present | Specific suggestions for each below-threshold criterion |

If JSON doesn't parse or any gate field is missing, the evaluation
itself failed — re-run.

---

## Calibration tracking

Over time, the evaluation harness produces a series of `eval.json`
records. These can be aggregated:

- **Q distribution by topic class**: do regulatory topics produce
  higher / lower Q than engineering topics on average?
- **Gate trigger frequency**: which gates trigger most often? If Gate
  3 (parroting) triggers most often, the synthesis stage is over-
  relying on Claude-prior content; the prompt needs to push for more
  Gemini-derived novelty.
- **Confidence calibration**: within journal entries, do high-
  confidence claims (`confidence: 0.8+`) actually have higher Gate-1
  pass rates than low-confidence claims (`confidence: 0.6-`)? If not,
  confidence values are uncalibrated.
- **Per-criterion patterns**: which criterion scores lowest most
  consistently? That's the prompt-engineering target.

Build a simple aggregation script in `scripts/eval_summary.py` that
reads all `evaluations/*.json` and produces a summary report. Run
quarterly as part of the re-evaluation discipline.

---

## Anti-patterns

| Symptom | Fix |
|---|---|
| Evaluation always passes | Rubric is too soft — check that gates have actual triggers; raise score thresholds |
| Evaluation always fails Gate 1 | Synthesis genuinely confabulates, OR evaluator is over-strict on "indirect" support — check sample of failed claims manually |
| Q scores cluster around 0.7 | Likert anchors are vague — provide more concrete examples per level |
| Gate 3 never triggers | Claude-prior baseline is too generic OR the synthesis is genuinely 100% novel (unlikely on most topics) — sanity-check baseline content |
| Recommendations are vague | "Improve specificity" doesn't help — demand "Add specific entities (vendor names, version numbers, regulator paragraphs) for X% of claims in section Y" |
| Same evaluator scoring same synthesis differently across runs | LLM-judge inter-trial variance — accept noise floor, run 3 evaluations and take median, OR fine-tune Likert anchors |

---

## Integration

Evaluation is **post-pipeline**, not in-pipeline. After Stage 3 (or
Stage 4 if used), run:

```
uv run python -m mantis_research run evaluation config/<batch>.json --only N
```

Which:
1. Reads the synthesis at `research-outputs-synthesis/NN-slug.md`
2. Reads the Claude original, Gemini originals, Claude-prior baseline
3. Runs `claude -p` with the evaluation prompt
4. Parses the JSON output
5. Saves to `evaluations/NN-slug-eval.json`

The harness can run on all topics in a batch:

```
uv run python -m mantis_research run evaluation config/batch-XX.json
```

Re-run the harness any time the rubric or prompts change.
