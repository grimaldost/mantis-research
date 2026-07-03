"""Project-canonical default prompt templates — the single source of truth.

Templates use Python ``.format()``-style placeholders; runners format with
the right variables before sending to claude / gemini / openrouter.

When updating a template here, update the corresponding playbook in
``prompts/playbooks/`` to match (the playbook is the human-readable spec;
this module is the runtime constant).

Aligned with ``prompts/playbooks/`` (post-harvest 2026-05-01 version).
"""

from __future__ import annotations

# Generic research-request template — the `mantis research "<question>"` entry
# point (§16) fills {question} and uses this as the topic's research_prompt, so
# every substrate researches the same question. Substrate adapters capture the
# model's response as the brief (no file-write instruction needed).
RESEARCH_REQUEST = """<persona>
A domain expert researching the question below for an autonomous agent that needs grounded, cross-checked reference material — not a chat answer.
</persona>

<question>
{question}
</question>

<method>
Produce a dense, well-sourced markdown brief that answers the question. Lead with a direct answer, then the evidence and mechanism, then boundary conditions and open questions. Ground every non-obvious claim in a real, named source; where sources disagree, surface the disagreement rather than smoothing it. Mark anything you cannot verify "Not found" instead of inventing it.
</method>

<guardrails>
Do NOT ask clarifying questions — this is a non-interactive research request. Use web search to ground claims where it is available. Distinguish documented fact from folklore. Do not fabricate citations, versions, dates, or figures.
</guardrails>"""


# Synthesis prompt — see prompts/playbooks/synthesis-prompt.md
SYNTHESIS = """You are the synthesis stage of a multi-model research pipeline. Your job is to merge two LLM-produced briefs into one richer document with explicit divergence flagging and meta-observations on model biases and prompt quality.

## Sources to read

<source role="primary" label="{primary_label}" effort="max">
{claude_path} ({claude_size_kb:.1f} KB)
</source>

<source role="secondary" count="{gemini_count}">
{gemini_block}
</source>

Use the Read tool to read all sources before writing.

## Pre-synthesis quote extraction (mandatory first step)

Before drafting the merged synthesis, output a `<quotes>` block containing 5-10 of the MOST DIVERGENT passages between the Claude and Gemini briefs — passages where the two sources make claims that disagree on a verifiable fact, frame the same concept from different angles, or where one source addresses something the other doesn't. Each quote: source path, brief, exact passage. This anchors the synthesis to real spans rather than to associatively-activated context.

## What to produce

Save the synthesis brief to {synthesis_path} using the Write tool.

### Body — merged technical content

**Concept-centric structure (mandatory).** Each paragraph's topic sentence is a CLAIM, not a model name or source name. Multiple sources cited per paragraph. Diagnostic test: read your topic sentences. If they are claims, the synthesis is concept-centric. If they are "Claude says X, Gemini says Y" sequential, it's an annotated bibliography (the failure mode arXiv moderators flagged in October 2025).

The structure follows Claude's brief (it's the comprehensive substrate). Fold in Gemini content where it adds detail, alternative framing, or cross-checks a Claude claim. The synthesis should be RICHER than either input alone — the union with conflicts explicit, not the intersection.

Where the models agree on a substantive claim, state the merged claim cleanly. **Note: cross-model agreement is WEAKER signal than intuition suggests** (Goel et al., ICML 2025: mistake similarity grows with capability across frontier models because they share substrate). Agreement on a non-trivial verifiable claim is worth explicit flagging — list 2-3 such items in the meta-observations as candidates for external verification rather than treating them as confirmed.

Where the models diverge, flag the divergence in-line with an explicit block. **Steelmanning required:**

> **Divergence:** Claude argues <X-as-Claude's-strongest-version-would-defend-it>. Gemini argues <Y-as-Gemini's-strongest-version-would-defend-it>. <Your assessment of which is right, or whether both are valid framings under different conditions — cite specific reasons or sources. Don't quietly average; naming the disagreement is the point.>

If the briefs largely agree on the topic, **do NOT manufacture divergences to satisfy a count**. Flag the agreement explicitly ("the briefs converge on X with the same source attribution Y"). The synthesis values flagged uncertainty over confident-wrongness, and flagged agreement over manufactured disagreement.

### `## Synthesis Meta-Observations` — at the end

This section is feedback signal for prompt engineering and model evaluation, not technical content. Cover:

a) **Depth distribution.** Which sub-areas of the topic did Claude treat well that Gemini thinned, and vice versa? Cite specific section names or claims.

b) **Notable biases.** Any framing that seemed off in either model. Training-recency artifacts, vendor lock-in, ideological lean, framing-as-marketing. Cite specific examples.

c) **Prompt-signal quality.** Did both models interpret the prompt the same way? If they diverged on what to research, the prompt was ambiguous — call out which phrasing was the load-bearing source of divergence. (For this pipeline specifically: the Claude prompt has "mantis substrate / analogical-transfer" framing; Gemini prompts strip it because that framing hijacks the gemini-3-flash router. Note any drift the asymmetric prompts introduced.)

d) **Hallucination flags.** Cross-model disagreement on factual claims is the strongest signal. List 3-5 specific claims where the models disagree on a verifiable fact (tool versions, file format details, vendor attributions, recent events). For each, state which is likely correct or that both are unverified pending external check. Each flag should be specific enough that an external verifier could resolve it: name the claim, the source that's more credible, and the verifiable fact at issue.

e) **Cross-model agreement worth verifying.** List 2-3 non-trivial claims where Claude and Gemini AGREE on a specific fact (number, date, name, version, regulatory paragraph). Cross-model agreement on training-data-uniform claims is weak signal — both could be wrong. Worth explicit verification before downstream reliance.

f) **Independence note.** Acknowledge: this synthesis was produced by Claude integrating its own brief plus a Gemini cross-check. Both models share substrate (Common Crawl, Wikipedia, GitHub, ArXiv). This is "tertiary independence" in the MRM/IEEE 1012 sense — not the kind of judge-level independence that programmatic verifiers or domain experts would provide. Treat the synthesis as comprehensive cross-check, not as validation.

The synthesis is the canonical reference document going forward; the individual research briefs are working notes."""


# Synthesis sidecar prompt — see prompts/playbooks/synthesis-prompt.md (ADR-0003).
# Runs as its own turn after the synthesis brief exists: the model Reads the
# brief and Writes the machine-readable epistemic sidecar. Only the two format
# keys ({synthesis_path}, {sidecar_path}) are single braces; every literal JSON
# brace is doubled so ``str.format`` leaves the example intact (FM-6).
SYNTHESIS_SIDECAR = """You are producing the machine-readable epistemic sidecar for a research synthesis — the structured signal downstream agents consume instead of parsing prose.

## Source
Read the synthesis brief at {synthesis_path} with the Read tool.

## Output
Write ONLY valid JSON to {sidecar_path} with the Write tool — no prose, no markdown fences, no code block. Emit exactly this shape (these are the model-authored fields; the runner fills run identity and provenance separately, so do NOT include them):

{{
  "sidecar_version": 1,
  "claims": [
    {{"id": "c1", "text": "<a load-bearing claim, verbatim from the synthesis>", "section": "<section/paragraph ref, or null>", "support": "direct|indirect|none"}}
  ],
  "divergences": [
    {{"id": "d1", "description": "<the cross-substrate disagreement>", "sides": ["<steelmanned position A>", "<position B>"], "substrates": ["<which sources took which side>"], "assessment": "<which is right, or under what conditions each holds>"}}
  ],
  "verification_queue": [
    {{"id": "v1", "claim": "<a claim to verify externally>", "reason": "<disagreement | single-source | training-uniform>", "sources_disagree": ["<sources>"]}}
  ],
  "agreements_worth_verifying": ["<a non-trivial claim all substrates agree on — weak signal, flag before downstream reliance>"],
  "coverage_notes": ["<what the synthesis could not cover, or marked Not-found>"]
}}

Draw the content faithfully from the synthesis's in-line divergence blocks and its `## Synthesis Meta-Observations` section (hallucination flags → verification_queue; cross-model agreement → agreements_worth_verifying). Give every claim, divergence, and verification item a unique id. The file is parsed and validated directly: emit ONLY the JSON object, and do not add keys beyond those shown (unknown keys are rejected)."""


# Claude-prior baseline prompt — Stage 5-input. Topic-title-only, no sources, no
# web search: the generalist baseline that Gate 3 (training-consensus-parroting)
# scores the synthesis against.
CLAUDE_PRIOR = """Write a brief technical reference on the topic below. You have no specific source materials; produce content from general knowledge. Do NOT use web search. Aim for a substantive but generalist treatment — what an engineer with broad training but no specific expertise in this area would write after thinking carefully.

Topic: {title}

Save the brief to {output_path} using the Write tool. Markdown."""


# Journal prompt — see prompts/playbooks/journal-prompt.md
JOURNAL = """Use skill to journal — chat-session-journal. Create registries for everything in the synthesis document just produced at {synthesis_path}.

The journal MUST be backed by the SYNTHESIS document (the merged, richer version with divergences flagged), not the individual research briefs. Read the synthesis with the Read tool, then produce the journal.

Save the journal to {journal_path}."""


# Falsification prompt — see prompts/playbooks/falsification-prompt.md
FALSIFICATION = """You are the falsification stage of a multi-model research pipeline. Your role is exclusively adversarial: identify and present the strongest evidence AGAINST the headline claims of the synthesis document. This is the third pass in a Main → Falsification iteration chain (Anthropic's documented research-team pattern).

You are NOT producing a balanced view. You are NOT defending the synthesis. The synthesis already had its day; this pass exists to find what it missed, smoothed over, or got wrong.

## Source

<source role="synthesis-under-test">
{synthesis_path} ({synthesis_size_kb:.1f} KB)
</source>

Use the Read tool to read the synthesis before writing. Pay special attention to the `## Synthesis Meta-Observations` section — items flagged there as "verify externally" are first-priority targets for this pass.

## Pre-falsification claim extraction (mandatory first step)

Before drafting the counter-evidence document, output a `<claims>` block listing the synthesis's HEADLINE CLAIMS — the load-bearing factual assertions whose truth carries weight downstream. For each:

- Claim verbatim (quoted from the synthesis)
- Source path + section reference
- Why it's load-bearing

Aim for 8-15 claims.

## What to produce

Save the falsification document to {falsification_path} using the Write tool.

### Per-claim adversarial analysis

For each claim:

#### Claim N: [verbatim from synthesis]

**Source location:** [synthesis section / paragraph]

**Counter-evidence found:** Use WebSearch / WebFetch aggressively. Cite primary sources. If none found, state explicitly: "No counter-evidence found in [N searches across sources X/Y/Z]."

**Counter-arguments found:** Methodological critiques, alternative interpretations, boundary conditions. Steelmanned.

**Boundary conditions where the claim fails:** Specific scenarios where the claim does NOT hold.

**Surviving robustness rating:** HIGH / MEDIUM / LOW / FALSIFIED with 2-4 sentences justification.

### Final section: Ranked claim list (sorted weakest-first).

### Falsification Meta-Observations

a) Search exhaustiveness per claim.
b) Synthesis consensus-smoothing instances.
c) Synthesis fabrications (unresolvable DOIs, paragraph numbers, vendor names).
d) Claims depending on auxiliary hypotheses (Duhem-Quine).

This document does NOT replace the synthesis. It is a counter-evidence companion."""


# Evaluation prompt — see prompts/playbooks/evaluation-prompt.md
EVALUATION = """You are the evaluation stage of a multi-model research pipeline. Your job is to score a synthesis document against a 3-gate + 6-criterion rubric. You are NOT producing a synthesis; you are producing a structured evaluation record.

You have NO access to the synthesis-production session's context. Your evaluation is fresh — this is the verification/validation separation principle from V&V (Roache, ASME V&V 10): the same agent that produces should not also evaluate.

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
{baseline_path} ({baseline_size_kb:.1f} KB)
</source>

The Claude-prior baseline is Claude's output given ONLY the topic title with no access to the research briefs. It represents what a generalist would produce from common industry knowledge. It is the substrate for Gate 3 (training-consensus-parroting detection).

Read all sources with the Read tool before scoring.

## Pre-evaluation extraction (mandatory first step)

Before scoring, output a `<claims>` block listing the synthesis's non-trivial claims (the ones that, if wrong, would damage downstream mantis ingestion). Aim for 15-25 claims. Each:

- Claim verbatim (quoted from synthesis)
- Synthesis section / paragraph reference
- Type: factual / procedural / reference / extrapolation

This selection is itself part of the evaluation.

## What to produce

Save the evaluation record to {eval_path} as STRUCTURED JSON with this exact shape:

{{
  "topic_id": "{topic_id}",
  "synthesis_path": "{synthesis_path}",
  "evaluator_model": "claude-opus-4-7",
  "evaluation_timestamp": "<ISO 8601 UTC>",
  "claims_extracted": [
    {{"claim": "<verbatim>", "section": "<...>", "type": "factual|procedural|reference|extrapolation"}}
  ],
  "gate_1_confabulation": {{
    "claim_mappings": [
      {{
        "claim": "<verbatim>",
        "supporting_sources": ["<path>"],
        "support_quality": "direct|indirect|none",
        "speculative_flagged_in_synthesis": true
      }}
    ],
    "triggered": false,
    "trigger_reason": "<if triggered>"
  }},
  "gate_2_vacuity": {{
    "negation_tests": [
      {{
        "claim": "<verbatim>",
        "negation": "<explicit negation>",
        "concrete_observation_favoring_negation": "<...>",
        "vacuous": false
      }}
    ],
    "triggered": false,
    "trigger_reason": "<if triggered>"
  }},
  "gate_3_parroting": {{
    "claude_prior_overlap_estimate_pct": 25,
    "novel_content_estimate_pct": 75,
    "soft_penalty_applied": false,
    "penalty_factor": 1.0
  }},
  "criteria": {{
    "c1_specificity":                       {{"score": 2, "justification": "<...>"}},
    "c2_mechanism_proposing":               {{"score": 2, "justification": "<...>"}},
    "c3_distinctiveness_from_claude_prior": {{"score": 2, "justification": "<...>"}},
    "c4_traceability":                      {{"score": 2, "justification": "<...>"}},
    "c5_actionability":                     {{"score": 2, "justification": "<...>"}},
    "c6_mode_dependent": {{
      "mode": "regulatory|engineering|methodology|other",
      "criterion": "<the specific criterion applied>",
      "score": 2,
      "justification": "<...>"
    }}
  }},
  "quality_score_Q_unpenalized": 0.667,
  "quality_score_Q_with_penalty": 0.667,
  "verdict": "PASS|PASS_WITH_PARROTING_PENALTY|REJECT_GATE_1|REJECT_GATE_2",
  "recommendations": [
    "<specific suggestion for re-running the synthesis prompt to address each below-threshold criterion>"
  ]
}}

Likert anchors (0-3 per criterion, total Q = sum/18):
- C1 Specificity: 0=generic; 1=some specific; 2=most claims have specifics; 3=all non-trivial claims have specifics + verifiable details
- C2 Mechanism-proposing: 0=description only; 1=implicit; 2=mechanisms named; 3=mechanisms named + traced + conditioned
- C3 Distinctiveness from Claude-prior: 0=≈baseline; 1=<30% novel; 2=30-70%; 3=>70% from Gemini cross-check or web
- C4 Traceability: 0=mostly unsourced; 1=some primary; 2=most primary; 3=all primary + paragraph numbers
- C5 Actionability: 0=no §7; 1=§7 generic; 2=§7 with 3+ specific cross-domain mappings; 3=§7 + per-mapping conditions
- C6 Mode-dependent: pick the mode based on topic class, score 0-3

Verdict logic:
- If gate_1_confabulation.triggered → "REJECT_GATE_1"
- Else if gate_2_vacuity.triggered → "REJECT_GATE_2"
- Else if gate_3_parroting.soft_penalty_applied → "PASS_WITH_PARROTING_PENALTY"
- Else → "PASS"

End the response with the JSON block ONLY (no prose afterwards). The JSON is parsed directly by the evaluation harness."""


# Journal augmentation prompt — Stage 3.5 (optional). Strengthens the
# breadth-first default journal with 3-5 focused depth-passes, each targeting
# an angle the first pass underserved. The marginal entry from a focused pass
# is higher-leverage than the mean entry from breadth-first because the first
# pass picks density-of-coverage while focused passes pick depth-on-pattern.
JOURNAL_AUGMENTATION = """You previously produced a default journal at {journal_path} via the chat-session-journal skill, working from the synthesis at {synthesis_path}. The first pass was breadth-first: it covered the full synthesis with one pass of envelope entries.

Your task now: produce 3-5 FOCUSED passes that strengthen the journal where the first pass was empirically thin. Each focused pass targets ONE specific angle and produces 8-15 additional envelope entries on that angle alone.

## Step 1 — Read inputs

Use the Read tool to read both:
- Synthesis: {synthesis_path} ({synthesis_size_kb:.1f} KB)
- Existing journal: {journal_path} ({journal_size_kb:.1f} KB)

Inspect the existing journal's envelope format — your new entries must match it EXACTLY. The format is:

```
--- ENTRY_START ---
type: FINDING|CONNECTION|OBSERVATION|ANTI_PATTERN
author: user:<handle>
timestamp: <ISO 8601>
area: <area>
language: en|pt
origin: reading
visibility: private
session: <slug>-augmentation-pass-N
domains: <comma-separated>
entities: <comma-separated>
confidence: 0.0-1.0
summary: <one-sentence>
--- CONTENT ---
<the actual content paragraph>
--- ENTRY_END ---
```

## Step 2 — Pick angles (mandatory pre-pass output)

Before drafting any new entries, output a `<angles>` block listing 3-5 angles. For each angle:

- **Name** — specific and distinctive (NOT "additional findings" or "more depth")
- **Why thin** — quote the count of relevant entries in the first pass (use grep-style count) OR cite the synthesis section the angle covers that was underserved
- **Expected count and type-mix** — e.g., "10 entries: 6 CONNECTION + 4 OBSERVATION"

High-leverage angle candidates for THIS pipeline (pick what fits this topic — do NOT enumerate all of these):

1. **§7 analogical-transfer mappings as CONNECTION entries.** The first pass typically produces 2-11 CONNECTION entries when the synthesis §7 has dozens of mappable patterns (PR orchestration, regulated pipelines, treasury, mantis-direct). One CONNECTION entry per mapping with named source-domain and named target-domain.

2. **Hallucination-flag candidates from synthesis (d) section as OBSERVATION** entries flagged for external verification. Each flagged claim becomes one OBSERVATION entry with `confidence: 0.5-0.7` and `domains: verify_externally`.

3. **Cross-model-agreement-worth-verifying from synthesis (e) section as OBSERVATION** entries. Each candidate-for-verification fact becomes one OBSERVATION with explicit "weak-signal-cross-model-agreement" framing.

4. **Regulatory or compliance failure modes as ANTI_PATTERN** entries. The first pass tends to have 5-11 ANTI_PATTERN entries; the synthesis often surfaces more. Each becomes one ANTI_PATTERN with what NOT to do + why + scenario.

5. **Specific mechanism families** as FINDING entries. Pick a sub-family of the topic that the breadth-first pass treated at one paragraph and the synthesis treated more deeply. Example: for K8s autoscaling — backpressure mechanisms; multi-controller composition; cold-start patterns. Each becomes one FINDING.

6. **Brazilian-fintech-specific applications** (when topic touches regulated workflows) as CONNECTION entries linking topic-specific patterns to BCB / CVM / ANPD / regulated-domain audit-trail substrate.

Reject "general additional findings" — that is just first-pass-extension, not a focused angle. Each angle must have a distinct sharp name that distinguishes it from the breadth-first first pass.

## Step 3 — Focused passes

For each angle, produce a section in this shape:

### Pass N: <angle name>

Brief rationale (2-3 lines): why this angle, what specifically it surfaces that breadth-first missed. Cite specific synthesis section(s) the angle is mining.

Then 8-15 envelope entries in the EXACT format the first journal uses. Use the same envelope metadata schema; pick the right `type` for each entry. Set `session` to `<slug>-augmentation-pass-N` so the entries are traceable to the focused pass that produced them.

## Step 4 — Save

Save the augmentation to {augmentation_path} using the Write tool. This is a separate artifact from the original journal — do NOT rewrite or append to the original journal file.

Frontmatter at top of the augmentation file:
- **Source synthesis:** path
- **Source journal:** path
- **Augmentation date:** ISO 8601
- **Angles picked:** numbered list with one-line rationale each
- **First-pass entry counts:** by type (FINDING/CONNECTION/OBSERVATION/ANTI_PATTERN totals from the original journal)

Then the focused-pass sections.

Closing summary at end of file:
- **Augmentation entry counts:** by type
- **Compounded totals:** first pass + augmentation, by type
- **Notes:** any angles considered and rejected, with reason

End the response with the Write tool call. No narration to chat after Write."""
