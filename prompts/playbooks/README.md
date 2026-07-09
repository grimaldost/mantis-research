# Prompt playbooks

Reference material for authoring the prompts in a batch config — written to be
read by an LLM (or an experienced operator) producing `config/<batch>.json`.
Each playbook below is the canonical spec for one pipeline role; the packaged
default templates in `src/mantis_research/core/prompts.py` follow these specs,
and the two change together (see [CONTRIBUTING.md](../../CONTRIBUTING.md)).

The config schema itself is documented in
[docs/batch-config.md](../../docs/batch-config.md) and batch operation in
[docs/running-batches.md](../../docs/running-batches.md). This README covers
what goes *into* the prompt fields, and the disciplines that apply across all
stages.

---

## The pipeline the prompts feed

Research fans out (one brief per substrate), synthesis fans in, and optional
stages check the result. Every stage is a `mantis run <stage>` subcommand:

```
   openrouter research (default: N substrates)   claude / gemini research (narrow / legacy)
   → …openrouter/NN-slug/<subslug>.md            → research-outputs*/NN-slug.md
                    └──────────────────┬──────────────┘
                                       ▼
                     synthesis (Claude CLI, multi-turn)
                     primary brief + secondaries → one cross-checked brief
                     → …synthesis/NN-slug.md  +  NN-slug.sidecar.json
                     (+ journal turn when enabled → journals/)
                                       │
             ┌─────────────────────────┼─────────────────────────┐
             ▼ optional                ▼ optional                 ▼ optional
      journal-passes             falsification              evaluation
      (journal augmentation)     (adversarial re-read)      (3-gate + 6-criterion rubric,
                                                             needs the claude-prior baseline)
```

- The default research path is **Path B**: OpenRouter substrates only, one of
  them promoted to primary via `models.primary`.
  [research-path-recommendation.md](research-path-recommendation.md) carries
  the evidence and the narrow cases where Claude-CLI research still wins.
- Synthesis gates on the **primary brief plus at least one secondary**; which
  brief is primary is config (`models.primary`), not pipeline order.
- Falsification and evaluation are per-topic opt-ins (`high_stakes: true` or
  `stages.<name>.enabled`). They exist because cross-model agreement is weak
  signal (D8) and the producer must not validate itself (D9).

## Which playbook governs which field

| Authoring this | Reference |
|---|---|
| `topics[].research_prompt` and `stages.openrouter[].prompt` | [claude-research-prompt.md](claude-research-prompt.md) — the 7-block scaffold is substrate-agnostic; strip the Claude-CLI tool instructions for single-shot HTTP substrates |
| Which substrates/models for a topic class | [model-recommendations.md](model-recommendations.md) |
| Where research runs (Path A vs Path B) | [research-path-recommendation.md](research-path-recommendation.md) |
| `stages.claude.prompt` (Path A research) | [claude-research-prompt.md](claude-research-prompt.md) |
| `stages.gemini[].prompt` (legacy CLI stage) | [gemini-research-prompts.md](gemini-research-prompts.md) |
| `stages.synthesis.prompt` / `default_prompts.synthesis` | [synthesis-prompt.md](synthesis-prompt.md) |
| `stages.journal.prompt` / `default_prompts.journal` | [journal-prompt.md](journal-prompt.md) |
| `stages.falsification.prompt` / `default_prompts.falsification` | [falsification-prompt.md](falsification-prompt.md) |
| Evaluation rubric / `default_prompts.evaluation` | [evaluation-prompt.md](evaluation-prompt.md) |

## When to decompose research into multiple subsessions

Default is one subsession per substrate, all inheriting the topic's
`research_prompt`. Give a substrate several focused subsessions (distinct
`subslug`s, each with its own `prompt`) when any of:

- The topic has 5+ independent comparison axes (jurisdictions, libraries,
  vendors) where each merits its own focused run.
- The combined prompt would be much longer than ~3K characters — long prompts
  dilute single-shot substrates.
- Sub-topics have non-overlapping primary sources (one needs Bacen, another
  IFRS, another GitHub repos).
- One sub-topic warrants substantially more depth than the others.

`gemini-research-prompts.md` § "Decomposition" has the fuller guide; its
criteria generalize to OpenRouter subsessions. Subslugs sort alphabetically —
prefix `01-`, `02-` if reading order matters.

## Project-specific calibrations on top of the references

Deviations from the external references, empirically validated on early runs:

- **Research prompts (Claude/primary):** the mantis-substrate framing + the
  §7 analogical-transfer requirement is what makes a brief mantis-grade
  rather than encyclopedia-grade. Without it the model produces a textbook
  chapter.
- **Research prompts for other substrates:** project framing **must be
  stripped** — topic-first, no mantis context. (Observed originally on the
  Gemini OAuth path, where it hijacked the flash router into off-topic
  fintech journal entries; the topic-first rule holds for all non-primary
  substrates.)
- **Synthesis prompt:** explicit `> **Divergence:**` blocks and a closing
  `## Synthesis Meta-Observations` section with five subsections (depth
  distribution, biases, prompt-signal quality, hallucination flags, asymmetry
  note). The meta-observations are themselves journalable content and feed
  the sidecar's claims/divergences.
- **Journal prompt:** the journal must be backed by the synthesis document,
  not the individual research briefs. Re-emphasize this in the prompt — the
  model will sometimes default to the primary brief if not redirected.

## Authoring workflow

1. Pick or write a topic; identify it by `id` and `slug`.
2. Write the topic's `research_prompt` per the 7-block scaffold. This is the
   substrate; spend the most time here.
3. Pick substrates for the topic class
   ([model-recommendations.md](model-recommendations.md)); add one
   `openrouter[]` entry per substrate. Give a subsession its own `prompt`
   only when it needs a scoped brief (see decomposition above).
4. Leave `synthesis` / `journal` prompts `null` unless the topic has unusual
   characteristics that justify overriding the defaults.
5. Set `high_stakes: true` for regulatory / financial / decision-relevant
   topics — it turns on falsification and evaluation for that topic.
6. Validate without spending:
   `uv run mantis run openrouter config/<batch>.json --dry-run`.

## Anti-patterns at the config level

| Symptom | Fix |
|---|---|
| The same long prompt pasted into every subsession | Put it in `research_prompt` once; subsessions inherit it (ADR-0008) |
| Project/mantis framing in non-primary research prompts | Strip it — topic-first (see calibrations) |
| `synthesis.prompt` overridden with no clear reason | Use the default; override only when justified |
| Dated model ids pinned in a new config | Use `auto:<vendor>` so the catalog resolves the newest flagship; pin only to reproduce a past run |
| `subslug` renamed between runs of the same batch | Subslugs are file stems and the `models.primary` key — keep them stable |

---

## Project-level disciplines (apply across all stages and topics)

Each of these is a workflow / mental-model commitment that the playbooks
individually assume. Documented here so they don't drift across the per-role
playbooks.

### D1 — First-pass output is suspect by default

The pass-1-misses-30-50% phenomenon recurs at every scale of cognitive work
product. Audit findings, prompt templates, fix-PR series, journals, research
outputs, synthesis outputs — every first-pass artifact has a "missed
substantive content" failure mode. Mitigated by **forced second-pass with a
different lens**.

For our pipeline:
- Synthesis IS the second pass relative to the research briefs
- Falsification is a third pass with an adversarial lens
- Evaluation is independent verification with a different agent context

When iterating prompts: don't accept "first version passes coverage checks"
as final. Request explicit second-pass review.

### D2 — Pre-launch and post-launch skeptical pass

Before running the pipeline on a high-stakes topic: paste the prompts
(research + synthesis defaults) into a fresh Claude session and run the
7-question diagnostic from *Prompting Claude's Advanced Research Mode for
Technical and Quantitative Work*:

1. Ambiguous terms an agent would have to guess at?
2. Embedded assumptions in the brief itself that may be wrong?
3. Scope gaps — adjacent questions whose absence will leave the report
   incomplete?
4. Source-tier instructions too tight (forecloses discovery) or too loose
   (admits low-quality content)?
5. Places where consensus-smoothing is likely?
6. Falsifiability hooks I should add but didn't?
7. Riskiest claim the agent might make that isn't pinned to a primary-source
   verification requirement?

After the pipeline runs: post-launch skeptical pass on the synthesis, without
re-searching, working only from the synthesis.

### D3 — Fold organic discoveries back into templates

When the synthesis stage (or any agent) surfaces a useful meta-question or
pattern that wasn't in the template, **fold it back into all matching
templates** rather than relying on per-session rediscovery. Organic discovery
is variable; explicit instructions are reliable.

For our pipeline: after each pipeline run, review synthesis Meta-Observations
for patterns that should become explicit instructions in
`default_prompts.synthesis`. Update the template; don't rely on the next run
to rediscover.

### D4 — Prompt-author primary-source verification

Don't lock specific domain terminology in research prompts (regulator names,
paragraph numbers, vendor names, version numbers) without verifying against
primary sources. Phantom-finding risk is real; the 2-5 minute verification
cost prevents the much higher cost of researching against phantom terms. See
[claude-research-prompt.md](claude-research-prompt.md) § "Prompt-author
primary-source verification" for the full discipline.

### D5 — Eval-driven development for prompt iteration

Anthropic's 5-step loop applies to our prompts:

1. Identify gaps — run the pipeline without the candidate prompt change;
   document specific failures
2. Create evaluations — 3 scenarios with explicit expected behavior
3. Establish baseline — measure performance without
4. Write minimal instructions — just enough to address the gaps
5. Iterate — execute evaluations, compare to baseline, refine

Don't speculate-then-add; observe failures, then counter. The evaluation
stage produces the metric needed for steps 3-5.

### D6 — Quarterly re-evaluation discipline

Skills/prompts depend on underlying model competence; competence shifts with
each model release. **Re-run the pipeline against the latest models
quarterly.** Retire prompts whose deltas have collapsed (the model handles it
natively now); harden prompts whose deltas remain.

Schedule a recurring task. As models improve, less mechanical instruction is
needed; more calibration and discipline content becomes valuable.

### D7 — Condition-qualified principles

When stating a principle in a playbook or prompt, name the conditions under
which it holds: "Principle X holds when (C₁) (C₂) (C₃); otherwise it fails as
Y." Flat unconditioned principles are the failure mode of "Strategy 1 —
In-place evolution with parser tolerance" (Schema Evolution & Contract
Versioning playbook): they become a graveyard of optional-by-spec /
required-by-observation fields. Pre-empt by stating conditions.

### D8 — Cross-model agreement is weak signal

(Goel et al. ICML 2025) Mistake similarity grows with capability across
frontier models because they share substrate (Common Crawl, Wikipedia,
GitHub, ArXiv) and converged post-training methods. The synthesis stage's
strongest signal is cross-model DISAGREEMENT, not agreement. Treat agreement
on training-data-uniform claims (vendor-marketing AI claims, mainstream
textbook errors) as candidates for external verification, not as
confirmation — that is what the sidecar's `agreements_worth_verifying` field
carries. True independence requires programmatic verifiers (URL/DOI/package
resolution) or human-expert review — neither implemented yet; cross-family
LLM judging is tertiary independence only.

### D9 — Producer ≠ validator

The synthesis stage produces; evaluation runs as a separate Claude session
with no synthesis-production context. Conflating producer and validator is
the most common failure mode in computational science evaluation (Oberkampf &
Roy 2010; SR 11-7 effective-challenge triad). The evaluation stage enforces
this separation; don't undermine it by sharing context across sessions.

### D10 — Density over volume

Every line in a prompt should change agent behavior. The "model is already
smart" principle: only add context the model doesn't already have. Three
challenge questions per paragraph:

1. Does the model really need this explanation?
2. Can I assume the model knows this?
3. Does this paragraph justify its token cost?

Cut anything that fails. Target one page per prompt for ~15-30 min of agent
work. Verbose prompts get garbled in subagent paraphrasing and crowd
attention budget.

---

## Methodology references

The principles above distill from these external references (most already
integrated; cross-reference for deeper rationale):

- *The Gemini Deep Research Playbook (2025–2026)* — 8-block scaffold, source
  preference syntax, plan-editing patterns (the prompt-design discipline
  carries over to headless paths)
- *Research Brief Authoring Playbook (Claude)* — 7-block scaffold,
  falsifiability hooks, source tiers, anti-pattern detection, pre/post-launch
  skeptical passes
- *Prompting Claude's Advanced Research Mode for Technical and Quantitative
  Work* — orchestrator-worker mechanics, 10 failure modes, iteration
  patterns, pre/post-launch skeptical passes
- *Signal Engineering for LLM Attachments* — three quality properties
  (trigger accuracy, payload efficiency, behavioral compliance), match
  degrees of freedom to task fragility, anti-rationalization tables,
  eval-driven dev
- *Multiple Testing, P-Hacking, and the Generalizability Crisis* — selection
  conditional on data inflates statistics; FDR > Bonferroni for LLM-judge
  eval
- *Model risk management as a design lens for mantis evaluator independence*
  — cross-family LLM judging is tertiary independence only; programmatic
  verifiers / human raters are the true independence axes
- *Mantis_Evaluation_Consolidated* — retrieval accuracy ≠ agentic utility;
  measure synthesis quality by downstream task improvement, not by
  intermediate metrics (Goodhart's Law)
- *VV&UQ as a Unified Engineering Discipline* — verification ≠ validation;
  same person doing both is the canonical failure mode
- *mantis-meditation-rubric-philosophy-of-science* — 3 hard gates + 6 graded
  criteria; mantis-first not philosophy-first
