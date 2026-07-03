# Journal prompt — playbook

How to author the `topics[].stages.journal.prompt` field — or use the
project default. Override is **rarely** needed; the default works for
~all topics.

The journal stage is **Turn 2 of the synthesis Claude session** —
resumes the same session via `claude --resume <session_id>` and
invokes the chat-session-journal skill on the synthesis document just
produced. Output goes to `journals/NN-slug-journal.md` and is the
canonical journal for mantis ingestion.

Validated empirically on the topic-1 (semiconductor) test:
122.8 KB / 2145 lines / 55 envelope-formatted entries (10 CONNECTION,
29 FINDING, 7 ANTI_PATTERN, 9 OBSERVATION).

---

## Default journal prompt

```
Use skill to journal — chat-session-journal. Create registries for
everything in the synthesis document just produced at
{synthesis_path}.

The journal MUST be backed by the SYNTHESIS document (the merged,
richer version with divergences flagged), not the individual research
briefs. Read the synthesis with the Read tool, then produce the
journal.

Save the journal to {journal_path}.
```

The runner injects the actual paths. Keep the prompt this tight —
the chat-session-journal skill itself carries the production rules
for envelope format, schema fields, and entry types. Adding more
prompt content here mostly creates conflict with the skill's own
guidance.

---

## What the chat-session-journal skill produces

Envelope-format entries with 14 schema fields per entry. Validated
entry types and typical counts on a substantive topic:

| Type | Typical count per topic | Role |
|---|---|---|
| CONNECTION | 8–12 | Cross-domain pattern recognition. For our pipeline, expect this many because the Claude prompt's § 7 produces named cross-domain mappings that the journal stage faithfully turns into CONNECTION entries. |
| FINDING | 20–30 | Concrete factual claims, distinctions, named results, specific values. Most numerous category. |
| ANTI_PATTERN | 3–7 | Risk-aware lessons, common mistakes. Synthesis-backed journals carry the bias observations from the synthesis Meta-Observations as ANTI_PATTERN entries. |
| OBSERVATION | 5–10 | Methodology / meta-level reflections, including reflections on the multi-model synthesis pipeline itself. The synthesis Meta-Observations directly produce these. |

### Schema fields per entry

Each `--- ENTRY_START ---` envelope contains:

- `type`: CONNECTION / FINDING / ANTI_PATTERN / OBSERVATION
- `author`: typically `user:<handle>` or similar
- `timestamp`: ISO 8601 UTC
- `area`: domain area string
- `language`: en / pt-br
- `origin`: reading / conversation / etc.
- `visibility`: private / shared
- `session`: session identifier (helps the synthesis-backed journal
  cluster as its own thing)
- `domains`: comma-separated domain tags
- `entities`: specific named entities (tools, regulators, standards)
- `confidence`: 0.0–1.0 (calibrated; not over-confident)
- `summary`: dense one-line summary
- Body content
- `--- ENTRY_END ---`

---

## Quality signals to verify post-run

After Turn 2 completes, the journal at `journals/NN-slug-journal.md`
should satisfy:

| Signal | Expected | Failure mode if violated |
|---|---|---|
| Size | 80–150 KB typical | <50 KB suggests the synthesis was thin or the skill ran with too small a budget |
| Total entries | 30+ | Synthesis was too thin; revisit synthesis prompt and/or rerun with stronger Claude prompt upstream |
| `--- ENTRY_START ---` envelopes | All entries use proper format | Skill didn't activate; verify `~/.claude/skills/chat-session-journal/SKILL.md` is present and the Read tool was used |
| CONNECTION entries | ≥ one per cross-domain mapping in synthesis § 7 (so 5+) | Synthesis § 7 was missing or weak; revisit Claude prompt — § 7 is the load-bearing source of CONNECTION entries |
| ANTI_PATTERN entries | At least 3–5 | Synthesis Meta-Observations §b (biases) was thin; biases are the primary source of ANTI_PATTERN entries |
| OBSERVATION entries | At least 5 | Synthesis Meta-Observations §c, §e were thin |
| Coverage check footer | Present at end of journal | Skill normally produces; if missing, journal turn was killed before the skill emitted the wrap-up |

### Calibration check

Sample a few entries and verify:

- `confidence` values are NOT all 1.0 — that's a failure mode (over-
  confident journaling). Validated topic-1 confidence values typically
  in the 0.7–0.85 range.
- `domains` and `entities` populated with specific terms, not
  generic placeholders.
- The `summary` field is dense and informative — not a paraphrase of
  the title.
- Entries don't repeat the same claim across types (e.g., a FINDING
  shouldn't be the same content as an OBSERVATION just relabeled).

---

## When to override the default

Rare. Per-topic override only when:

### The synthesis has unusual structure

If the synthesis is a decision memo (recommendation / rationale / risks
shape) rather than a merged brief, the standard journal prompt may
under-utilize it. Override to:

> *"The synthesis is a decision-memo-shaped document. Produce journal
> entries as: 1 OBSERVATION for the recommendation rationale; 1+
> FINDING per analytical factor; 1 ANTI_PATTERN per risk identified;
> CONNECTION entries to map the decision pattern to similar decisions
> in adjacent domains."*

### Specific domain tags need pinning

If the topic's downstream mantis ingestion needs domain tags not
inferrable from the synthesis content (e.g., a treasuryutils-specific
cluster), pin them:

> *"All entries should include `domains` field containing
> `treasury, fixed_income, br_regulatory` regardless of which
> sub-area of the synthesis they reference."*

### Cross-project lens explicitly named

The Claude § 7 typically lists adjacent domains; if the journal stage
is missing that signal, demand it:

> *"At least 1 CONNECTION entry per adjacent domain named in the
> synthesis § 7 (typically: PR orchestration, pharmaceutical
> development, aerospace V&V, naval architecture, chemical plant
> commissioning). Each CONNECTION entry should state the specific
> structural pattern shared and the structural difference, not just
> note that the domains are 'related'."*

In practice: keep the default for ~all topics. Re-running with a
stronger upstream Claude prompt and synthesis is usually a better
fix than overriding the journal prompt.

---

## Anti-patterns

| Symptom | Fix |
|---|---|
| Journal uses individual briefs instead of synthesis | Re-emphasize "MUST be backed by synthesis" in prompt; check that the synthesis path is correctly injected |
| <30 entries on a substantive topic | Synthesis is too thin; revisit synthesis quality first — don't try to fix at the journal stage |
| No CONNECTION entries | Synthesis § 7 was missing or weak; revisit Claude prompt — see claude-research-prompt.md anti-patterns |
| All entries are OBSERVATION | Skill didn't read the synthesis body; check that Read tool was used and the synthesis path is correct |
| Confidence values all 1.0 | Over-confident journaling — likely the prompt didn't ask the skill to calibrate; the chat-session-journal skill normally calibrates by default, so this signals the skill didn't fully activate |
| Entries with empty `domains` | Skill produced thin entries; usually means the synthesis didn't have enough structured content for the skill to extract domain context |

---

## Operational note: this turn is slow

Empirically, the journal Turn 2 takes 25-40+ minutes on max-effort
Opus 4.7 against a 90+ KB synthesis. The skill writes incrementally
(many small Write calls accumulating), so partial output may be
visible at intermediate intervals. **Don't kill prematurely** — even if
output appears stalled at 20-30 KB for several minutes, the skill is
likely buffering for the next batch of envelopes. The validated
topic-1 journal jumped from 23 KB to 122 KB in a single late flush.

If you must kill early, the partial journal at the kill moment is
salvageable but won't have the closing coverage-check footer. You can
rerun the journal-only stage via `run_journal_only.py` once the
synthesis is intact.

---

## Density check

The default prompt is intentionally tight (3 paragraphs). Don't bloat
it. The skill itself carries the production rules; adding prompt
content here either duplicates the skill or conflicts with it.
