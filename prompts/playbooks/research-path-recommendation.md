# Research-path recommendation: Claude-CLI primary vs all-OR research

**Status:** evidence-based, derived from batch-12 controlled experiment (2026-05-04)
**Verdict:** **Path B is competitive, sometimes superior.** Adopt Path B as the default for new batches; reserve Path A for narrow cases where Claude-CLI's agent-loop is load-bearing.

---

## TL;DR

| Question | Answer |
|---|---|
| Can Claude CLI synthesize as well from 4 OR research briefs (Path B) as from Claude-CLI primary + 4 OR (Path A)? | **Yes — comparable quality, sometimes better.** |
| Does Path B produce more or fewer flagged hallucinations on regulatory topics? | **About the same; Path B caught one Path A missed.** |
| Does Path B produce richer or thinner journals? | **Richer.** Base-journal entries: 136 (A) → 220 (B), +62%. |
| Does Path B reduce subscription stress? | **Yes — Claude CLI used only for synthesis + journal-passes.** |
| Cost in OR API per topic? | **~$2-6 — essentially equal between paths**. |
| Should I drop Gemini Advanced subscription? | **Yes — Gemini-via-OR is the better choice in both paths.** |

---

## The two paths (vocabulary)

**Path A — Claude-CLI primary + 4 OR substrates** (current default before this experiment)
- Stage 1: Claude CLI research (subscription, agent-loop, multi-turn, WebSearch + WebFetch)
- Stage 2: Gemini-via-OR (`google/gemini-3.1-pro-preview`)
- Stage 3: OR DeepSeek-R1 + Sonar-Reasoning-Pro + GPT-5 (Exa for non-Sonar)
- Stage 4: Claude CLI synthesis (subscription, 2-turn)
- Stage 5: Claude CLI journal-passes (subscription)
- **Substrates feeding synthesis: 5** (Claude-CLI primary + 4 OR secondaries)

**Path B — 4 OR research, no Claude in research** (proposed new default)
- Stage 1: 4 OR research substrates: Gemini-OR + DeepSeek-R1 + Sonar + GPT-5
- Stage 2: GPT-5 brief selected as primary via `models.primary: 'openrouter:<subslug>'` (ADR-0005)
- Stage 3: Claude CLI synthesis (subscription, 2-turn) — sees GPT-5 as primary, 3 OR as secondaries
- Stage 4: Claude CLI journal-passes (subscription)
- **Substrates feeding synthesis: 4 OR** (GPT-5 promoted as primary + 3 secondaries)

**Both paths drop Gemini Advanced subscription** — Gemini-via-OR replaces it.

---

## Evidence (batch-12, 3 topics × both paths)

### Topic selection rationale

Picked for diverse substrate-strength axes:

| ID | Topic | Class | Why it tests the hypothesis |
|---|---|---|---|
| 21 | PIX evolution (ⓑ★) | Brazilian regulatory + recent | Highest stakes — BCB primary sources are deep, agent-loop multi-fetch should win if anywhere |
| 22 | WASM/WASI Preview 2 | Cutting-edge moving spec | Tests whether OR-only research handles spec-tracking with Sonar's real-time index |
| 23 | Workflow orchestration | Comparative tooling | Established multi-vendor — both paths should produce strong output |

### File-size deltas

| Topic | Synth A | Synth B | Δ% | Journal A | Journal B | Δ% | Augmentation A | Augmentation B | Δ% |
|---|---|---|---|---|---|---|---|---|---|
| 21 PIX | 49 KB | 63 KB | **+29%** | 91 KB | 145 KB | **+59%** | 85 KB | 85 KB | 0% |
| 22 WASM | 72 KB | 46 KB | -36% | 29 KB | 107 KB | **+269%** | 92 KB | 94 KB | +2% |
| 23 workflow | 58 KB | 61 KB | +5% | 146 KB | 141 KB | -3% | 101 KB | 107 KB | +6% |
| **TOTAL** | 179 KB | 170 KB | -5% | 266 KB | 393 KB | **+48%** | 278 KB | 286 KB | +3% |

**Interpretation:** Path B synthesis is ~5% smaller on average but the **first-pass journals are 48% richer**. Augmentations saturate at similar size in both.

### Cross-substrate signals in synthesis

| Signal | Path A | Path B | Δ |
|---|---|---|---|
| Divergence blocks | 14 | **25** | **+79%** |
| Hallucination/verify-externally flags | 28 | 29 | ~equal |
| Cross-substrate agreement blocks | 4 | 3 | ~equal |
| Claude-CLI attributions in body | 117 | 22 | -81% (Claude is no longer a research source in B) |
| GPT-5 explicit attributions | 196 | 0 | -100% (GPT-5 is now the unnamed "primary" in B) |
| Sonar attributions | 147 | 186 | +27% |
| DeepSeek attributions | 193 | 246 | +27% |
| Gemini attributions | 241 | 333 | +38% |

**Key finding:** Path B has **+79% more flagged divergence blocks** despite having one fewer substrate. This is counter-intuitive but explainable: Path A's Claude-CLI primary tends to dominate the synthesis structure, smoothing over disagreements. Path B's 4 OR substrates are peers and the synthesis stage flags more cross-pair conflicts.

### Journal entry counts (mantis-ingestion-ready)

| Topic | Base journal entries A→B | Augmented A→B |
|---|---|---|
| 21 PIX | 51 → **91** (+78%) | 41 → 42 |
| 22 WASM | 13 → **56** (+330%) | 36 → 36 |
| 23 workflow | 72 → 73 | 49 → 48 |
| **TOTAL** | **136 → 220 (+62%)** | 126 → 126 (saturated) |

Path B's first-pass journals are dramatically richer, especially on topic 22 where Path A's Claude-CLI primary produced a tight synthesis but only 13 envelope entries. Path B's synthesis (with no Claude-CLI primary) flagged 7 divergence blocks (vs 0 in Path A) and the journal extracted 56 entries.

### PIX hallucination-catch comparison (regulatory topic)

Both paths caught the same DeepSeek fabrications:
- `IN BCB 561/2024` — fabricated normativo number
- `pacs.002.spi v3.0` with `StsRglm=RJCT` (2024) — fabricated minor version
- `AB08` as MED fraud reason code — fabricated
- 2023 ICP-Brasil A3 mandate citing "ITI Normative #3.7" — fabricated
- DICT IBAN validation — fabricated (Brazil uses ISPB+Agência+Conta, not IBAN)

**Path B caught one Path A missed:** Sonar's mistranslation of "Conta PI" as "Participant Investment" (canonical BCB usage is "Pagamentos Instantâneos"). Path A's synthesis didn't surface this disagreement because Claude-CLI's primary brief used the correct term and the synthesis structure followed Claude.

---

## Recommendations

### Default for new batches: **Path B**

Use Path B as the standard pipeline for batches where:
- Topics are not extremely Brazilian-fintech-deep (Path A has no measurable advantage on PIX)
- You want to preserve Claude CLI subscription quota for synthesis + journal-passes
- You want to drop Gemini Advanced subscription
- You want richer first-pass journals (62% more entries on average)

### When to use Path A instead

**Narrow cases where Claude-CLI's agent-loop multi-fetch is genuinely load-bearing:**

1. **Topics where the primary source is unindexed by Exa/Sonar/native search.** If WebFetch on a specific BCB-only-PDF or paywalled paper is the only way to ground a claim, Claude-CLI's agent loop matters. (None of our 3 batch-12 topics fit this.)
2. **Topics with deep multi-step research dependencies** — where one source must be read to know what the next source is. The OR HTTP path is single-shot; agent loops handle this naturally. (Most mantis topics don't fit this either.)
3. **When you want a Claude-CLI brief on disk for archival/audit reasons** — the agent-loop transcript is a richer working-notes artifact than OR's single response.

### Cost guidance

Per-topic OR API spend for both paths is essentially equal: **~$2-6**.

Subscription savings if you adopt Path B for all batches:
- Drop Gemini Advanced ($20/mo savings)
- Free Claude CLI quota for synthesis + journal-passes only (less rate-limit pressure)
- If you currently pay for Claude Max ($100-200/mo), Path B may let you downgrade to Pro ($20/mo) since you're not stressing limits with research-stage agent loops

### Implementation

Path B requires:
1. The standard openrouter stage with 4 substrates (Gemini-OR + DeepSeek + Sonar + GPT-5)
2. `models.primary: 'openrouter:<subslug>'` in the batch config to select the primary
   brief (ADR-0005 — no promote/restore step; the synthesis reads primary from config)
3. Standard synthesis + journal-passes stages (no code changes)

Config template: `config/example-batch.json` (Path B).

### Mixed-strategy for sensitive batches

For batches with a mix of topic classes, you can run **Path A on the regulatory subset and Path B on the rest**, then synthesize each subset separately. The cost saving is partial (subscription stress is intermediate) but the catch-rate matches the topic-class need.

---

## Open questions for future iteration

- **Does Path B benefit from a different "primary" choice than GPT-5?** We picked GPT-5 because it produced the largest briefs in our smoke tests. A future test could compare GPT-5 vs Sonar vs Gemini-OR as primary. Hypothesis: Sonar may be a better primary for regulatory/recent-events topics because of its native real-time citations.
- **Does Path B need the OR-Claude (anthropic/claude-opus-4-7) substrate added?** We deliberately excluded it because it's expensive ($15/$75 per million tokens). Adding it would test whether closed-weight Claude lineage provides distinct signal from GPT-5/Gemini, at a cost of ~$2-3 per topic.
- **How do Qwen-3 and Grok-4 perform when added?** Currently blocked by OpenRouter data-policy / ZDR settings on the user's account. If those policies relax, the experiment is straightforward to extend (just add entries to the openrouter array).

---

## Provenance

- Batch-12 ran 3 topics × both paths (Path A: Claude-CLI research; Path B: OpenRouter research)
- Total wall-clock: ~7h (Path A research bottlenecked by Claude CLI sequential per topic; Path B research fast in OR)
- Total OR API cost: ~$8 for all 3 topics × 4 OR substrates × both syntheses (research is shared)
- Subscription stress: 3 Claude-CLI research sessions (Path A) + 6 Claude-CLI synthesis sessions (3×2 paths) + 6 journal-passes sessions
