# Claude research prompt — playbook

How to author the `topics[].stages.claude.prompt` field for a topic.

The Claude research turn is the **primary substrate** for the topic. It
runs on `claude-opus-4-7` with `--effort max` and web search enabled,
single-turn, ~15–30 min wall clock, typical output 50–100 KB markdown
saved to `research-outputs/NN-slug.md`. Downstream synthesis treats this
as the comprehensive base; Gemini's output is an independent pass from
different training data and different web crawl coverage, useful as
cross-check / alternative framing rather than equal-weight depth — so
this prompt has to do most of the substantive lifting.

Distilled from the *Research Brief Authoring Playbook (Claude)* and
*Prompting Claude's Advanced Research Mode for Technical and Quantitative
Work* with mantis-pipeline-specific calibrations.

---

## Persona-first opening (mandatory)

Open the prompt with a one-line persona statement. Anthropic's own Explore
agent: *"You are a file search specialist for Claude Code."* Plan agent:
*"You are a software architect and planning specialist for Claude Code."*
Persona compresses signal — primes the model to draw from the right region
of training distribution without enumerating every behavior.

For our pipeline, the canonical opening is:

> *"You are a research-substrate analyst producing a reference brief on
> {topic}. The brief is consumed downstream by a multi-model synthesis
> stage and a chat-session-journal skill, not read end-to-end by a human.
> Density beats narrative."*

Customize for sub-domain (regulatory, engineering, etc.) but keep
persona-first.

---

## The 7-block scaffold

Every prompt has all 7 blocks. Each block must change agent behavior.
Decorative lines go.

### Block 1 — Role and standard

One paragraph specifying audience and rigor bar.

- **Audience:** typically a Brazilian fintech Python developer; the
  primary lens is analogical transfer to multi-stage engineering
  pipelines (PR orchestration, treasury systems, regulated workflows,
  hardware-software co-design, regulated-domain compliance pipelines).
  State this explicitly in the prompt.
- **Reference class:** "hardware-engineering / regulatory / technical
  textbooks that treat the topic as a pipeline with measurable handoffs."
  NOT marketing copy or vendor explainers. NOT undergraduate primers.
- **Mantis framing:** "the deliverable is reference material for
  downstream agentic-memory ingestion, not a chat response. Dense
  and structured, not narrative."

This framing is the load-bearing reason Claude's brief comes out
mantis-grade rather than encyclopedia-grade. Don't water it down.

### Block 2 — Falsifiable research question

Replace any "research X" / "tell me about X" framing with a question
that has an answer.

Acceptable forms:
- "How is X operationalized when {scenario}…"
- "What are the load-bearing handoffs in pipeline X, and where does each
  fail in practice…"
- "Where do practitioners and regulators disagree on…"
- "What changed in X between {date} and {date}, and what is the new
  shape of the field…"

Reject any prompt that doesn't admit a falsifiable answer. The prompt
should be re-readable five years later and still be a coherent
question.

### Block 3 — Scope fences

Explicit `In: / Out: / Edge:` lines.

- **In:** specific stages, regulators, standards, libraries — by name
  and document number. List them.
- **Out:** explicit exclusions and brief rationale where useful.
  Excluding *adjacent but distinct* topics is the lever that prevents
  scope creep.
- **Edge cases:** how to handle ambiguous boundaries (e.g., "treat
  hybrid ASIC-FPGA flows as out-of-scope but cite once in passing").

### Block 4 — Source tiers (the highest-leverage block)

```
Tier 1 (must consult if relevant):
  [primary sources by document number, regulator URL, standards body,
   GitHub repo at specific commit/release, peer-reviewed paper]
Tier 2 (high quality):
  [Big-4 technical bulletins, central-bank papers, published academic
   surveys, accepted conference talks (PyCon, USENIX, etc.)]
Tier 3 (acceptable for triangulation):
  [practitioner posts from named authors with verifiable affiliation,
   maintainer blog posts on official project domains]
Avoid:
  [SEO listicles, vendor marketing, AI-generated practitioner content
   (no named author, undated, missing primary citations),
   Medium/Substack except by named regulators or academics,
   "what is X" explainer pages]
If only low-tier sources are available for a claim, mark it
"weakly sourced".
```

For Brazilian topics, Tier 1 must explicitly include
`bcb.gov.br`, `cvm.gov.br`, `cpc.org.br`, `anbima.com.br`,
`receita.fazenda.gov.br` as appropriate, and the Diário Oficial da
União for normative texts. Without explicit pinning, Claude will
default to English-language Big-4 commentary even on
Brazilian-jurisdictional questions.

For engineering topics, pin specific GitHub orgs/repos by URL and
demand "linked GitHub commits or release tags, not paraphrase."

**Hallucination-hotspot domains — abstention is the right answer.**
Specialized law/finance and Brazilian-specific regulatory topics carry
documented citation hallucination ceilings of **17–33% even with
retrieval-grounded products** (Stanford legal RAG study). On these:

> *"Treat regulatory paragraph numbers, specific resolution numbers,
> and named-institution claims as abstain-by-default unless you can
> quote primary text. 'Not found in primary sources I could access' is
> a higher-quality answer than a confidently-stated number that
> turns out to be hallucinated. The synthesis stage values flagged
> uncertainty over confident-wrongness."*

### Block 5 — Output schema

The required structure for mantis-pipeline briefs:

- **§0 Reading guide and what's deliberately left out** — sets the
  reader's expectations and bounds the scope explicitly.
- **§1 Pipeline-as-a-map** — one-page overview, dense.
- **§2 Stage-by-stage walkthrough** — each stage as a numbered subsection
  (§2.1, §2.2, …) with: what it consumes, what it produces, how it
  fails, the recovery pattern.
- **§3 Tool ecosystem and lock-in** — vendors, market shares, structural
  reasons for lock-in.
- **§4 Inter-stage file formats / "the API"** — the file formats and
  protocols traded between stages (this is what makes the pipeline
  swappable / verifiable).
- **§5 Verification story per stage** — what is checked, by whom, at
  which gate, and what fails.
- **§6 What's changed in 2020-2026** — recency anchor; the agent has
  web search, use it.
- **§7 Analogical-transfer notes** — **REQUIRED**. This is the section
  that turns a brief from "encyclopedia chapter" into "mantis-grade
  substrate." Map the structural patterns of the topic to:
  - PR orchestration (the user's primary working context)
  - One regulated multi-stage pipeline (pharma, aerospace, naval,
    chemical commissioning) for transfer
  - Optionally: treasury / banking / risk pipelines if the topic
    structurally connects there
  - Identify the recurring patterns and where the topic-specific
    constraints stretch them.
- **§8 Brief glossary** — for terminology unique to the domain.
- **§9 Cheat sheet / software-engineer translation table** — when the
  topic is technical and the analogies map cleanly.

Tell Claude to use the Write tool to save to
`research-outputs/NN-slug.md`. Do not just print to chat.

**Concept-centric structure (mandatory).** Within each section, paragraphs
must be organized around ideas, not around sources or sub-topics by name.

> *"Do not write paragraphs whose topic sentence is a model name, a
> source name, or a sub-topic label. Each paragraph's topic sentence is
> a CLAIM; the paragraph cites multiple sources to support, qualify, or
> contradict the claim. Diagnostic test: read only your topic sentences.
> If they are claims, the brief is concept-centric. If they are
> 'Section 3 covers X', 'NumPy supports Y', etc., it is author-centric
> and degrades to an annotated bibliography."*

(Webster & Watson 2002, MIS Quarterly. The arXiv "DDoS attack" failure
mode that moderators flagged in October 2025 is exactly this.)

### Block 6 — Falsifiability hooks

Insert verbatim where relevant. Pick the ones that fit the topic.

- *"Where positions diverge, present in own terms with attribution. Do
  not synthesize a balanced view."*
- *"Numerical claims as [value] [units] [methodology source] [sample]
  [date] [stated reasoning]. Qualitative paraphrase of quantitative claims is
  not acceptable."*
- *"Cite the primary source for every factual claim. Secondary
  commentary only as supplementary."*
- *"Define every term of art on first use; do not switch definitions
  mid-report."*
- *"Prefer canonical primary over recent secondary commentary. Recency
  is a signal only when the literature has moved."*
- *"Conclude with explicit 'What I could not find' section listing items
  that needed external verification but the agent could not access."*

**Citation-metadata requirement (mandatory; mitigates the documented
17–33% legal-RAG hallucination ceiling and the patent/case-law
fabrication failure mode).**

> *"Every citation must include enough metadata for verification:
> author(s), title, venue/publisher, year, AND a stable identifier — DOI,
> arXiv id, BCBS document number, regulator-document-number, GitHub
> commit hash, or RFC number. URL is supplementary, NOT a substitute for
> identifier metadata. If a URL cannot be confirmed live during the
> research, mark it `[archive-only]` or remove the claim entirely. Do not
> invent DOIs, arXiv ids, or document numbers — the 2025 NeurIPS
> contamination episode found 100+ fabricated citations submitted to a
> single conference."*

For decision-relevant topics (regulatory, financial, model-validation):
- *"For each conclusion, state the assumptions under which it holds and
  ≥2 scenarios under which it fails."*
- *"Identify embedded assumptions in this brief and search for evidence
  against them. If the brief's assumption is empirically wrong, say so
  directly."*

### Block 7 — Verbatim preservation

Required when exact quotation matters (regulation, standards, formulas,
type signatures):

> *"Surface paragraph-numbered exact quotations from primary sources
> where the analytical claim depends on the wording. For each
> quoted passage, cite article/paragraph/section number, not just
> the document title."*

For code-heavy engineering topics:

> *"Quote type signatures, function definitions, and configuration
> directives verbatim from the source — file path and line range —
> not paraphrased."*

---

## Project-specific calibrations

### Length and density

Validated brief sizes on this pipeline:
- 50–80 KB markdown is the typical good-quality range.
- 30 KB or less suggests the prompt was thin. Revisit Block 3 (scope) and
  Block 5 (output schema) — likely missing § 7.
- 100 KB+ is fine if the topic legitimately has the depth (e.g., the
  semiconductor brief at 65 KB before synthesis).

### The §7 requirement

Without §7 the brief is missing the analogical-transfer signal that the
journal stage turns into `CONNECTION` entries. The validated topic-1
journal had 10 `CONNECTION` entries directly traceable to the §7
content. Skipping §7 means the journal will be heavier on `FINDING` and
lighter on cross-domain patterns.

### Web-search direction

Claude with `--effort max` will use web search aggressively. Direct
it explicitly:

> *"Use WebSearch to anchor recency claims (versions, regulatory dates,
> market shares, recent papers). Use WebFetch to fetch primary sources
> when the snippet is insufficient — particularly Bacen Resoluções, IFRS
> Foundation pages, GitHub README/CHANGELOG/issue pages."*

### File save directive

The runner appends a `--append-system-prompt` directive that tells
Claude to use the Write tool to save the document. You can additionally
mention it in the prompt body to reinforce; just don't *only* rely on
the prompt body — the system-prompt directive is the reliable hook.

---

## Prompt-author primary-source verification (discipline)

Before locking specific domain terminology in a research prompt, **verify
the terminology against primary sources**. Phantom-finding risk is real:
the user's audit-fix work surfaced a phantom "ISMA maturity-month
exception" that didn't exist in any spec but appeared authoritative
because the prompt-author had drawn the term from training-data memory.
The codebase correctly implemented ISDA §4.16(g) Eurobond Basis but the
audit prompt's terminology made it look like a violation.

**Rule:** any time a research prompt names a regulator, paragraph
number, vendor product name, or specific version number, the prompt
author cross-checks the term against a primary source (regulator
website, vendor docs, GitHub release page) **before** committing the
prompt to the JSON config. The 2-5 minute verification cost prevents
the much higher cost of:

- Researching against a phantom term
- Producing synthesis content built on the phantom term
- Discovering during journal coverage check that the canonical findings
  don't track to anything real

This applies particularly for prompts that anchor on:

- ISDA section numbers (the 2006 → 2021 renumbering is a known
  cross-generation drift; pin the generation explicitly: "ISDA 2006
  §4.16(f)" not just "§4.16(f)")
- BACEN Resoluções / CMN Resoluções / CVM Resoluções (different
  numbering schemes; easy to misattribute one as another)
- Library version numbers (post-cutoff APIs, deprecated functions —
  what you remember about pandas 1.x doesn't apply to 2.x)
- Product/vendor names with confusable variants (DSO.ai vs Cerebrus,
  Innovus vs Encounter, etc.)

---

## Anti-patterns

| Anti-pattern | Symptom | Fix |
|---|---|---|
| Vague topic | "Research X" with no question | Reformulate as falsifiable question (Block 2) |
| Embedded conclusion | "Confirm that X is optimal" | Pose as open question; require symmetric treatment |
| Exhaustive URL whitelist | List of 30 specific URLs only | Whitelist by type/quality unless canonical doc is genuinely the only one |
| Mantis framing missing | No § 7 mapping | Add § 7 with at least 2 cross-domain mappings |
| § 7 hand-waved | "Lessons apply broadly" | Demand at least 2 named adjacent domains with structural-pattern statements |
| Cross-launch implicit context | "Now do CECL" expecting prior run's context | Make brief self-contained or attach prior report as a source |
| Recency-as-authority | Brief implies "newest = best" | Add: "Prefer canonical primary over recent secondary commentary" |
| Source tiers too tight | Specific URLs only, no Tier 2/3 | Use type-and-quality criteria; allow discovery |
| Source tiers too loose | "Use any reputable source" | Define what reputable means for the topic; use Tier 4 reference table in the README playbook |

---

## Pre-launch skeptical pass (mental, before saving the config)

Before committing the prompt to the JSON config, mentally simulate:

1. What are the 3 sub-questions a competent agent would dispatch first?
   If the prompt makes those obvious, density is good.
2. What's the riskiest factual claim the agent might make? Is there a
   falsifiability hook (Block 6) that pins it to a primary source?
3. What's the embedded assumption in the brief itself? Does the
   prompt invite the agent to challenge it (recommended for
   decision-relevant topics)?
4. If the topic has known disputes, are the falsifiability hooks
   adequate to surface them rather than smooth them?

Revise if any answer is "no."

---

## Density check (final)

Read the prompt line-by-line. For each line, ask: "does this change
what the agent does?"

If no, cut. Target one page (~60-80 lines) of prompt for ~15-30 min of
agent work. The framing density of the prompt is correlated with the
framing density of the output; thinness here propagates downstream.
