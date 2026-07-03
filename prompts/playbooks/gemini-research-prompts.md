# Gemini research prompts — playbook

How to author the `topics[].stages.gemini[]` array for a topic. Each
entry in the array becomes one Gemini headless session producing one
output file.

Gemini is an **independent pass with different training data and
different web-crawl coverage** in this pipeline. The synthesis stage uses
it for cross-check, alternative framings, and disagreement-signal — not
for equal-weight depth. Quantitatively the output is ~10× lighter than
Claude's brief; the *value* is independence of distributional base.

What Gemini contributes:

- Alternative framings the synthesis can fold in
- Cross-model disagreement signal (the strongest hallucination-flag
  signal we have without external verification)
- Breadth of phrasing for terms / cheat sheets / analogies

**Important caveat (Goel et al., ICML 2025):** mistake similarity GROWS
with capability across frontier models because they share substrate
(Common Crawl, Wikipedia, GitHub, ArXiv) and converged post-training
methods. Cross-model AGREEMENT on factual claims is therefore weaker
signal than intuition suggests — both could be wrong on training-data-
uniform topics (vendor-marketing AI claims, mainstream textbook
errors, etc.). Cross-model DISAGREEMENT is the strong signal we
exploit. The synthesis stage should weight disagreement-as-evidence
above agreement-as-evidence.

Don't expect equal-depth coverage. The OAuth path constraints (below)
mean Gemini's output is fundamentally bounded — and the substrate-
sharing constraint above means even matched-depth output would not give
true judge-level independence.

Distilled from *The Gemini Deep Research Playbook (2025–2026)* with
this pipeline's empirically-validated calibrations.

---

## OAuth code-assist path constraints (read first)

Our pipeline runs `gemini-cli` against the OAuth subscription auth, not
a paid API key. Several non-obvious constraints follow — these are
empirically validated, not theoretical:

### Server downroutes substantive prompts to flash

`--model gemini-3-pro-preview` is honored for SHORT prompts (single-
question chats). For SUBSTANTIVE research prompts the server silently
routes to `gemini-3-flash-preview` regardless of `--model`. The JSONL
session file under `~/.gemini/tmp/` records the actual model.

**Mitigation:** chunking. Shorter sub-prompts have a higher chance of
staying on pro-tier. Multi-session decomposition is partly an end-run
around this routing.

### Workspace exposure triggers router/agent mode

Running `gemini-cli` with `cwd` inside the project root, OR with
`--include-directories` pointing at a directory full of project files,
puts the model into a router mode where it explores the workspace,
reads other research outputs, and produces off-topic content (e.g.,
inventing journal entries about Topic 44 instead of researching the
requested Topic 1).

**Mitigation:** the runner sets `cwd=Path.home()` and does NOT pass
`--include-directories`. **Don't reference project paths inside the
prompt either** — references like "see research-outputs/" re-trigger
exploration. Keep prompts free of any project-internal pathing.

### Framing keywords hijack the flash router

The Claude prompt's framing — "mantis-ready substrate for a Python
developer at a fintech" — caused Gemini to produce fintech journal
entries instead of the intended substrate brief on the actual topic.
The flash router latches onto vocabulary like "mantis", "fintech",
"substrate", "journal" and constructs a different topic entirely.

**Mitigation:** strip mantis and fintech framing from Gemini prompts.
Topic-first. The synthesis stage merges asymmetric framings later;
that's its job. Don't try to make the Gemini side look like the Claude
side.

### Restricted tool set — no `write_file`

The OAuth path's gemini-cli has `read_file`, `update_topic`,
`grep_search`, `invoke_agent` — but NOT `write_file` or
`run_shell_command`. Gemini cannot save the brief to disk itself.

**Mitigation:** the runner captures stdout from gemini-cli and writes
the file from Python. Don't ask Gemini to save anything. Tell it
explicitly:

> *"Output the complete brief as your final markdown response. Do not
> call any file-saving tools — the calling script captures stdout and
> writes the result to disk."*

### Trust check requires explicit env var

`--skip-trust` is necessary but insufficient for tool-using prompts on
the OAuth path. The runner sets `GEMINI_CLI_TRUST_WORKSPACE=true`
explicitly. Don't add tool-invocation language to prompts — it triggers
the trust-check path even when the prompt doesn't ostensibly need
tools.

---

## When to decompose into multiple sub-sessions

Default: **single session per topic** (gemini[] array length 1). Switch
to multi-session when ANY of:

- Topic has 5+ independent comparison axes (5 jurisdictions, 5
  libraries, 5 instruments) where each merits its own focused run
- Combined prompt length would exceed ~3K characters (longer prompts
  increase the probability of flash-routing)
- Sub-topics have non-overlapping primary sources (one needs Bacen,
  another needs IFRS Foundation, another needs GitHub repos)
- One sub-topic warrants substantially more depth than others; better
  to spend it focused than diluted
- The topic has a natural taxonomy that surfaces in the synthesis
  anyway (e.g., "the four major XVA components" → 4 sub-sessions)

### Decomposition examples

- Topic "Brazilian fixed-income mechanics" → subslugs: `ltn`, `ntn-b`,
  `ntn-f`, `lft`, `secondary-market-conventions`. Each instrument has
  separate Tesouro / Bacen primary docs.
- Topic "Anthropic prompt caching" → subslugs: `wire-format`,
  `pricing-model`, `cache-invalidation-rules`,
  `production-failure-modes`. Each axis is a separate engineering
  question.
- Topic "MCP protocol mechanics" → subslugs: `wire-format-jsonrpc`,
  `lifecycle-handshake`, `server-discovery`, `tool-call-flow`. Each is
  a self-contained protocol layer.
- Topic "XVA framework" → subslugs: `cva`, `dva`, `fva`, `kva`, `mva`.

### Subslug naming conventions

- Kebab-case
- 2–4 words ideally
- The subslug becomes the basename of the per-session output file
  (`research-outputs-gemini/NN-slug/<subslug>.md`)
- If reading order matters for downstream review, prefix with `01-`,
  `02-`, etc. — the synthesis script reads them in alphabetical order

---

## The 8-block scaffold

Adapted from the Gemini Deep Research Playbook. Each block must change
agent behavior.

### `<persona>`

Concrete domain role, NOT mantis-framed. Examples:

- "Senior IFRS technical accountant with 15 years of Brazilian banking
  experience, fluent in CPC pronouncements and Bacen prudential
  regulation."
- "Principal Python engineer reviewing OSS architecture for production
  adoption. Cares about: type-system surface, extension points,
  dependency footprint, error model, test strategy, release engineering."
- "Hardware-engineering technical writer covering modern semiconductor
  flows for software audiences."

### `<context>`

3–6 lines of background and audience. **Avoid Brazilian-fintech context
unless the topic actually requires it** (Bacen-jurisdictional topics:
yes; general engineering topics: no). The context is what the audience
already knows; it should orient the agent, not project the user's
working environment onto unrelated topics.

### `<objective>`

One sharp deliverable. **For multi-session topics, the objective for
THIS session is the sub-question, not the whole topic.**

- Bad (single-session topic dressed up): "Cover the entire semiconductor
  pipeline."
- Good (sub-session): "Document the verification story across the
  semiconductor digital flow: simulation, formal equivalence, static
  timing analysis, DRC/LVS — what's checked at each gate, what fails,
  recovery patterns."

### `<scope>`

- **Time horizon:** "As of [explicit date]" beats "current". Pin to a
  specific YYYY-MM-DD.
- **Jurisdictions:** by name.
- **Versions:** library/spec versions explicitly.
- **What to EXCLUDE:** matters MORE for Gemini than Claude — flash is
  more easily distracted. List adjacent topics by name and exclude
  them.

### `<sources>`

Priority-ordered URL/source classes. Examples:

- Brazilian regulatory: "Prefer in this order: bcb.gov.br, cvm.gov.br,
  cpc.org.br, anbima.com.br, b3.com.br. Big-4 (kpmg.com, pwc.com,
  ey.com, deloitte.com) as secondary. Avoid generic accounting blogs."
- Engineering: "Official GitHub repo, PyPI, official documentation,
  PEPs, accepted PyCon/EuroPython talks, maintainer blog posts on
  official project domains. Avoid Medium tutorials except from named
  maintainers."
- Standards / regulatory: "ifrs.org, iasplus.com (KPMG), bis.org for
  Basel; bcb.gov.br for Brazilian implementations. Read full text of
  any cited Resolução."

### `<method>`

How to compare/synthesize. Be explicit about structure:

- "Provide a four-column matrix: [A] / [B] / [C] / [D]; rows: scope,
  recognition, measurement, disclosure, transition."
- "Section-by-section walkthrough with code excerpts (5-15 lines) for
  each architectural claim."
- "Side-by-side comparison: IFRS 9 (paragraph references) vs CPC 48
  (paragraph references), then a Bacen overlay section, then a worked
  numerical example."

### `<format>`

- Markdown.
- Section headers and target length (typically 3–8 KB per Gemini
  session — don't expect Claude-tier 50 KB+).
- Citation density: "every claim sourced; inline numbered citations or
  inline parenthetical citations".
- Comparison tables required where relevant.
- "End with an 'Open questions' section listing items needing external
  verification."

### `<guardrails>`

Critical for flash-tier; these prevent the failure modes we documented:

- *"Do not ask clarifying questions. This is a non-interactive
  request."*
- *"Do not call any tools. Do not read project files. Do not invoke
  agents. Output the brief in your final response only."*
- *"Do not invent statistics. Mark unknown values as 'Not found'."*
- *"If sources disagree, present both and identify the primary."*
- *"Where the topic involves recent events (versions, dates, market
  data), state the date you're treating as 'now' and avoid speculating
  beyond that."*
- *"Do not produce journal entries. Do not produce envelope-formatted
  output. Just write the markdown brief."* (This is the
  flash-router-hijack mitigation specific to our pipeline — without it,
  Gemini sometimes produces mantis-style envelopes after seeing
  similar entries in adjacent contexts.)

---

## Multi-session coordination

When a topic uses multiple Gemini sub-sessions, each is independent —
no shared state, each is a fresh `gemini -p` invocation. The synthesis
stage discovers all parts via the file-layout convention (single
`NN-slug.md` OR a directory at `NN-slug/`) and merges them along with
the Claude brief.

**Tips:**

- Each sub-prompt should produce content that can stand alone as a
  partial brief on its sub-topic. The synthesis integrates; the
  sub-sessions don't need to.
- **Avoid cross-references between sub-sessions** — "see part 2
  for…" is meaningless to a fresh Gemini session. The synthesis will
  integrate them anyway.
- Naming consistency matters less than scope-consistency: each
  subslug's content should map to its name.
- Don't over-decompose. If you'd write the same `<persona>` and
  `<context>` for all sub-sessions, that's a sign the topic is one
  session, not five.

---

## Anti-patterns

| Symptom | Fix |
|---|---|
| Mantis / fintech framing in `<persona>` or `<context>` | Strip; topic-first |
| Asks Gemini to save the file | Remove file-save directives; runner does it via captured stdout |
| References project paths in prompt body | Strip workspace-leaking text |
| Vague topic | Tighten with falsifiable sub-question |
| 5KB+ prompt | Decompose into multiple sub-sessions |
| Same prompt as Claude side | Different model, different shape — rewrite for the 8-block scaffold |
| Says "research X comprehensively" | Replace with bounded, scoped sub-question |
| Mentions "tools", "agents", "skills" | Strip — these vocabulary tokens trigger router/agent mode |
| Asks for JSON output / envelope format | Just markdown; don't trigger format-hallucination |
| Long list of `<sources>` URLs (>10) | Cut to 5-7 highest-priority; let agent discover Tier 2/3 |

---

## Quality signals to verify post-run

- Output size 3–15 KB markdown per session is normal on the OAuth path.
- Output is on-topic for the requested sub-question (verify by reading
  the first paragraph + section headings).
- The session JSONL at
  `~/.gemini/tmp/<cwd-name>/chats/session-*.jsonl` records the model
  used. If it's `gemini-3-flash-preview`, server downrouted; the brief
  may be thinner than ideal but should still be on-topic.
- No envelope-formatted entries in the output (those would indicate the
  framing-hijack failure mode).
- No file-write tool errors in the captured stdout (those indicate the
  prompt asked Gemini to save and Gemini tried).

If quality is poor, the most common fixes (in order of frequency):

1. Strip mantis/fintech framing from prompt
2. Decompose into smaller sub-sessions
3. Tighten `<scope>` exclusions (flash distracts easily)
4. Remove tool-invocation language from prompt
5. Set `cwd=Path.home()` in the runner if not already (default already
   does this; verify)

---

## Density check

Same as the Claude playbook: every line in the prompt should change
agent behavior. Cut decorative lines. Target 1–2 KB per Gemini sub-prompt
(longer prompts increase flash-routing probability).
