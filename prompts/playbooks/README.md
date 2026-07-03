# Mantis Research Pipeline — Prompt Playbooks

Reference material for authoring per-topic prompts in
`config/<batch-config>.json`. This README defines the pipeline, the JSON
schema, the sub-playbooks per role, and the project-level disciplines
that operate across all stages.

These files are intended to be read by an LLM (or an experienced
operator) authoring a new batch config. The output of that authoring is
a JSON config the runner consumes.

---

## Pipeline (3 mandatory stages + 2 optional)

```
   Stage 1 — Claude research              Stage 2 — Gemini research
   run_batch.py                           run_batch_gemini.py
   Opus 4.7 max + WebSearch               OAuth gemini-cli, 1+ sessions
   → research-outputs/NN-slug.md          → research-outputs-gemini/...
                  └────────┬───────────────────┘
                           │
                Stage 3 — Synthesis + Journal
                run_synthesis_batch.py (Claude two-turn)
                T1 → research-outputs-synthesis/NN-slug.md
                T2 → journals/NN-slug-journal.md
                           │
              ┌────────────┴────────────┐
              ▼ optional                ▼ optional
   Stage 4 — Falsification    Stage 5 — Evaluation
   run_falsification.py       evaluate_synthesis.py
   Claude single-turn,        Separate Claude session,
   adversarial against        3-gate + 6-criterion rubric,
   synthesis                  structured JSON output
   → research-outputs-        → evaluations/NN-slug-eval.json
     falsification/...
```

**Stage gating:**

- Stage 3 gates on Stages 1 AND 2 both complete for the topic.
- Stage 4 (optional) gates on Stage 3 complete; recommended for high-
  stakes topics (regulatory, financial, decision-relevant). See
  [falsification-prompt.md](falsification-prompt.md).
- Stage 5 (optional) gates on Stage 3 (or 4) complete; produces
  structured eval JSON for quality gating + calibration tracking. See
  [evaluation-prompt.md](evaluation-prompt.md).

**Critical principle: separation of producer and validator.** The
synthesis stage produces; evaluation runs as a *separate Claude
session* with no synthesis-production context. Conflating producer and
validator is the most common failure mode in computational science
evaluation (Oberkampf & Roy 2010; SR 11-7 effective-challenge triad).

**Critical caveat: cross-family LLM judging gives only TERTIARY
independence.** Frontier LLMs share substrate (Common Crawl, Wikipedia,
GitHub, ArXiv) and converged post-training methods. Goel et al. ICML
2025: mistake similarity GROWS with capability across ~130 frontier
models. True independence requires programmatic verifiers (URL/DOI/
package resolution) or human-expert review — neither implemented yet.

---

## JSON config schema (v2)

```json
{
  "schema_version": 2,
  "batch_name": "mantis-research-batch-<descriptor>",
  "models": {
    "claude":    { "model": "claude-opus-4-7", "effort": "max" },
    "gemini":    { "model": "gemini-3-pro-preview" },
    "synthesis": { "model": "claude-opus-4-7", "effort": "max" }
  },
  "runner": {
    "max_parallel_topics": 4,
    "max_retries_per_stage": 2,
    "rate_limit_backoff_minutes": 30,
    "generic_failure_backoff_minutes": 5
  },
  "default_prompts": {
    "synthesis":     "<inline default — used when topics[].stages.synthesis.prompt is null>",
    "journal":       "<inline default — used when topics[].stages.journal.prompt is null>",
    "falsification": "<inline default — used when topics[].stages.falsification.prompt is null and Stage 4 enabled>",
    "evaluation":    "<inline default — used by Stage 5 evaluation harness>"
  },
  "topics": [
    {
      "id": "1",
      "slug": "semiconductor-design-flow",
      "tier": "D",
      "title": "Semiconductor design flow end-to-end",
      "high_stakes": false,
      "stages": {
        "claude": {
          "prompt": "<full 7-block brief — see claude-research-prompt.md>"
        },
        "gemini": [
          {
            "subslug": "pipeline-stages",
            "prompt": "<8-block brief scoped to stages — see gemini-research-prompts.md>"
          },
          {
            "subslug": "tool-ecosystem",
            "prompt": "<8-block brief scoped to tools and lock-in>"
          }
        ],
        "synthesis":     { "prompt": null },
        "journal":       { "prompt": null },
        "falsification": { "prompt": null, "enabled": false },
        "evaluation":    { "prompt": null, "enabled": true }
      }
    }
  ]
}
```

`high_stakes: true` flips on Stage 4 by default for that topic
(regulatory / financial / decision-relevant work). `evaluation.enabled`
defaults to true; set false to skip the evaluation harness for a topic.

### Key properties

- **`gemini` is always an array.** Length 1 = single-session (output
  `research-outputs-gemini/NN-slug.md`). Length N = multi-session (output
  `research-outputs-gemini/NN-slug/<subslug>.md`).
- **`synthesis.prompt` and `journal.prompt` default to null** → runner
  uses `default_prompts.*`. Override per-topic only when justified.
- **`subslug` is kebab-case** and becomes the basename of the per-session
  output file. Subslugs sort alphabetically; prefix with `01-`, `02-`
  etc. if reading order matters.
- **No `turn_1` / `turn_2` / `turn_3` fields.** The "turn" abstraction
  was Claude-specific (single chat session, sequential turns). The 3
  stages run as separate sessions with separate authentication and
  separate models.

---

## Which playbook governs which field

| Authoring this field | Reference this playbook |
|---|---|
| `topics[].stages.claude.prompt` | [claude-research-prompt.md](claude-research-prompt.md) |
| `topics[].stages.gemini[].prompt` | [gemini-research-prompts.md](gemini-research-prompts.md) |
| `topics[].stages.synthesis.prompt` (or `default_prompts.synthesis`) | [synthesis-prompt.md](synthesis-prompt.md) |
| `topics[].stages.journal.prompt` (or `default_prompts.journal`) | [journal-prompt.md](journal-prompt.md) |
| `topics[].stages.falsification.prompt` (or `default_prompts.falsification`) | [falsification-prompt.md](falsification-prompt.md) — Stage 4, optional |
| Evaluation harness (post-pipeline, separate session) | [evaluation-prompt.md](evaluation-prompt.md) — Stage 5, optional |

---

## When to decompose Gemini into multiple sub-sessions

Default is single-session (`gemini[]` array length 1). Switch to
multi-session when ANY of:

- Topic has 5+ independent comparison axes (5 jurisdictions, 5
  libraries, etc.) where each merits its own focused run
- Combined prompt length would exceed ~3K characters (longer prompts
  increase the probability of flash-routing on the OAuth path)
- Sub-topics have non-overlapping primary sources (e.g., one needs
  Bacen, another needs IFRS Foundation, another needs GitHub repos)
- One sub-topic warrants substantially more depth than others

See `gemini-research-prompts.md` § "Decomposition" for the full guide
and concrete examples.

---

## External references this playbook distills from

- *The Gemini Deep Research Playbook (2025–2026)* — 8-block scaffold,
  source preference syntax, plan-editing patterns (we don't get plan
  editing on the headless OAuth path, but the prompt-design discipline
  carries over).
- *Research Brief Authoring Playbook (Claude)* — 7-block scaffold,
  falsifiability hooks, source tiers, anti-pattern detection,
  pre/post-launch skeptical passes.

---

## Project-specific calibrations on top of the references

These are the deviations from the external references, all empirically
validated on the topic-1 (semiconductor) test run:

- **Claude prompt:** the mantis-substrate framing + § 7
  analogical-transfer requirement is what makes a brief
  mantis-grade rather than encyclopedia-grade. Without it Claude
  produces a textbook chapter. With it, the brief carries cross-domain
  pattern-mapping that the journal stage turns into CONNECTION
  entries.
- **Gemini prompts:** the mantis/fintech framing **must be stripped**
  for Gemini. On the OAuth subscription path it hijacks the flash
  router into producing off-topic fintech journal entries.
  Topic-first, no project context.
- **Synthesis prompt:** explicit `> **Divergence:**` blocks and a
  closing `## Synthesis Meta-Observations` section with five
  subsections (depth distribution, biases, prompt-signal quality,
  hallucination flags, asymmetry note). The meta-observations are
  themselves journalable content (they become `OBSERVATION` entries).
- **Journal prompt:** the journal must be backed by the synthesis
  document, not the individual research briefs. Re-emphasize this in
  the prompt — Claude will sometimes default to the original Claude
  brief if not redirected.

---

## Authoring workflow

1. Pick or write a topic; identify it by `id` and `slug`.
2. Author the Claude prompt per `claude-research-prompt.md`. This is
   the substrate; spend the most time here.
3. Decide single- vs multi-session Gemini per the criteria above.
   Author each sub-prompt per `gemini-research-prompts.md`.
4. Use `null` for `synthesis.prompt` and `journal.prompt` unless the
   topic has unusual characteristics that warrant overriding the
   project default.
5. Insert the topic into `topics[]` array of the batch config.
6. Validate the JSON parses and no required fields are missing.

---

## Anti-patterns at the config level

| Symptom | Fix |
|---|---|
| Same prompt copy-pasted to claude and gemini | Don't. Different models, different prompt shapes — see `gemini-research-prompts.md` |
| `gemini` set to a single string instead of array | Always array, even for length 1 |
| `subslug` set when array length is 1 | Subslug is meaningful only for multi-session; runner ignores it for single |
| Mantis framing in Gemini prompts | Strip — hijacks flash router |
| `synthesis.prompt` overridden but no clear reason | Use the default; override only when justified |

---

## Project-level disciplines (apply across all stages and topics)

Each of these is a workflow / mental-model commitment that the
playbooks individually assume. Documented here so they don't drift
across the per-role playbooks.

### D1 — First-pass output is suspect by default

The pass-1-misses-30-50% phenomenon recurs at every scale of
cognitive work product. Audit findings, prompt templates, fix-PR
series, journals, research outputs, synthesis outputs — every
first-pass artifact has a "missed substantive content" failure mode.
Mitigated by **forced second-pass with a different lens**.

For our pipeline:
- Stage 3 IS the second-pass relative to Stages 1+2
- Stage 4 (falsification) is a third pass with adversarial lens
- Stage 5 (evaluation) is independent verification with a different
  agent context

When iterating prompts: don't accept "first version passes coverage
checks" as final. Request explicit second-pass review.

### D2 — Pre-launch and post-launch skeptical pass

Before running the pipeline on a high-stakes topic: paste the prompts
(claude + gemini + synthesis defaults) into a fresh Claude session
and run the 7-question diagnostic from *Prompting Claude's Advanced
Research Mode for Technical and Quantitative Work*:

1. Ambiguous terms an agent would have to guess at?
2. Embedded assumptions in the brief itself that may be wrong?
3. Scope gaps — adjacent questions whose absence will leave the
   report incomplete?
4. Source-tier instructions too tight (forecloses discovery) or too
   loose (admits low-quality content)?
5. Places where consensus-smoothing is likely?
6. Falsifiability hooks I should add but didn't?
7. Riskiest claim the agent might make that isn't pinned to a
   primary-source verification requirement?

After the pipeline runs: post-launch skeptical pass on the synthesis,
without re-searching, working only from the synthesis.

### D3 — Fold organic discoveries back into templates

When the synthesis stage (or any agent) surfaces a useful meta-
question or pattern that wasn't in the template, **fold it back into
all matching templates** rather than relying on per-session
rediscovery. /q's organic discovery is variable; explicit instructions
are reliable.

For our pipeline: after each pipeline run, review synthesis
Meta-Observations for patterns that should become explicit
instructions in `default_prompts.synthesis`. Update the template;
don't rely on the next run to rediscover.

### D4 — Prompt-author primary-source verification

Don't lock specific domain terminology in research prompts (regulator
names, paragraph numbers, vendor names, version numbers) without
verifying against primary sources. Phantom-finding risk is real; the
2-5 minute verification cost prevents the much higher cost of
researching against phantom terms. See
[claude-research-prompt.md](claude-research-prompt.md) §
"Prompt-author primary-source verification" for full discipline.

### D5 — Eval-driven development for prompt iteration

Anthropic's 5-step loop applies to our prompts:

1. Identify gaps — run pipeline without the candidate prompt change;
   document specific failures
2. Create evaluations — 3 scenarios with explicit expected behavior
3. Establish baseline — measure performance without
4. Write minimal instructions — just enough to address the gaps
5. Iterate — execute evaluations, compare to baseline, refine

Don't speculate-then-add; observe failures, then counter. The Stage 5
evaluation harness produces the metric needed for steps 3-5.

### D6 — Quarterly re-evaluation discipline

Skills/prompts depend on underlying model competence; competence
shifts with each model release. **Re-run pipeline against latest
models quarterly.** Retire prompts whose deltas have collapsed
(model handles natively now); harden prompts whose deltas remain.

Schedule a recurring task. As models improve, less mechanical
instruction is needed; more calibration and discipline content
becomes valuable.

### D7 — Condition-qualified principles

When stating a principle in a playbook or prompt, name the
conditions under which it holds: "Principle X holds when (C₁) (C₂)
(C₃); otherwise it fails as Y." Flat unconditioned principles are
the failure mode of "Strategy 1 — In-place evolution with parser
tolerance" (Schema Evolution & Contract Versioning playbook): they
become a graveyard of optional-by-spec / required-by-observation
fields. Pre-empt by stating conditions.

### D8 — Cross-model agreement is weak signal

(Goel et al. ICML 2025) Mistake similarity grows with capability
across frontier models because they share substrate. The synthesis
stage's strongest signal is cross-model DISAGREEMENT, not agreement.
Treat agreement on training-data-uniform claims (vendor-marketing
AI claims, mainstream textbook errors) as candidates for external
verification, not as confirmation. The synthesis Meta-Observations
has explicit subsections for this (e: Cross-model agreement worth
verifying; f: Independence note).

### D9 — Producer ≠ validator

The synthesis stage produces; evaluation runs as a separate Claude
session with no synthesis-production context. Conflating producer
and validator is the most common failure mode in computational
science evaluation (Oberkampf & Roy 2010). The Stage 5 evaluation
harness enforces this separation; don't undermine it by sharing
context across sessions.

### D10 — Density over volume

Every line in a prompt should change agent behavior. The "model is
already smart" principle: only add context the model doesn't
already have. Three challenge questions per paragraph:

1. Does the model really need this explanation?
2. Can I assume the model knows this?
3. Does this paragraph justify its token cost?

Cut anything that fails. Target one page per prompt for ~15-30 min
of agent work. Verbose prompts get garbled in subagent paraphrasing
and crowd attention budget.

---

## Methodology references

The principles above distill from these external references (most
already integrated; cross-reference for deeper rationale):

- *The Gemini Deep Research Playbook (2025–2026)* — 8-block scaffold
- *Research Brief Authoring Playbook (Claude)* — 7-block scaffold
- *Prompting Claude's Advanced Research Mode for Technical and
  Quantitative Work* — orchestrator-worker mechanics, 10 failure
  modes, iteration patterns, pre/post-launch skeptical passes
- *Signal Engineering for LLM Attachments* — three quality
  properties (trigger accuracy, payload efficiency, behavioral
  compliance), match degrees of freedom to task fragility, anti-
  rationalization tables, eval-driven dev
- *Multiple Testing, P-Hacking, and the Generalizability Crisis* —
  selection conditional on data inflates statistics; FDR > Bonferroni
  for LLM-judge eval
- *Model risk management as a design lens for mantis evaluator
  independence* — cross-family LLM judging is tertiary independence
  only; programmatic verifiers / human raters are the true
  independence axes
- *Mantis_Evaluation_Consolidated* — retrieval accuracy ≠ agentic
  utility; measure synthesis quality by downstream task improvement,
  not by intermediate metrics (Goodhart's Law)
- *VV&UQ as a Unified Engineering Discipline* — verification ≠
  validation; same person doing both is the canonical failure mode
- *mantis-meditation-rubric-philosophy-of-science* — 3 hard gates +
  6 graded criteria; mantis-first not philosophy-first
