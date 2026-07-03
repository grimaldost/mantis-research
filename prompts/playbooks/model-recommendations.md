# Model recommendations: per-topic-class substrate selection

**Status:** evidence-based, derived from batch-10 (engineering disciplines, 2-model + 4-model + 5-model variants) + batch-11 (mantis-direct, 3-model) + batch-12 (research-path comparison, Path A 5-substrate vs Path B 4-substrate).

**Default DeepSeek model — May 2026 update:** Switched from `deepseek/deepseek-r1` to `deepseek/deepseek-v4-pro` for batches authored 2026-05-15+. V4 Pro released April 24, 2026 (MIT license, 1.6T total / 49B activated MoE, 1M context, 384k max output, `reasoning_effort: high` and `xhigh` supported). Benchmarks: 80.6% SWE-bench Verified (within 0.2pt of Claude Opus 4.6), competitive on standard reasoning with GPT-5 + Gemini 3.1 Pro. Same DeepSeek lineage-diversity dividend (non-Western RLHF), sharper reasoning, bigger context. Existing batches (10-38) keep their original `deepseek/deepseek-r1` references — no retroactive change.

**Backlog-refresh substrate audit — 2026-05-15:** First post-batch-38 backlog refresh used 4-substrate discovery (GPT-5 deep + Gemini 3 Pro deep + Sonar Reasoning Pro + DeepSeek V4 Pro web) → Claude consolidation with cost-vs-quality audit (Section 6). **Audit-driven recommendations for FUTURE backlog-refresh runs only** (NOT per-topic research — different job, different substrate calculus):

- **GPT-5 deep research**: KEEP as anchor — earned premium on BR-regulatory precision (correctly named Res. BCB 494/495/496, CP 124/2025, Res. 522/2025, SUSEP Portaria 8.442/2025), protocol-frontier specificity (A2A, MCP 2025-11-25), agent-eval sharpness (τ-bench state-diff, Inspect AI, pass^k).
- **DeepSeek V4 Pro web**: KEEP as workhorse — best signal/$. Matched GPT-5 on BR regulatory specifics (Operação Carbono Oculto trigger, COAF R$96.9M figure, OPIN Bloco 6 cert dates), alone caught AutoGen→MAF transition (Sep 2025), alone surfaced the agentic-memory competitive landscape (Mem0/Letta/Zep/Cognee).
- **Gemini 3 Pro deep research**: CONDITIONAL KEEP — only for systems-level Python/Rust frontier runs (PEP 703, PyO3, GLiNER, Docling, msgspec, XGrammar). BR regulatory coverage cited 2022 resolutions (BCB 277/278) as current 2026 framework — currency failure at premium cost.
- **Sonar Reasoning Pro**: DROP for refresh — hallucinated BCB resolution numbers (4753/4754/4759 don't exist), invented "CVM Res 20/2024", generic singletons absorbed by consensus, 18% count inflation. Replace with **Grok 4 + web / xAI deep search** if a third middle slot wanted.

**Important scope note:** This audit measured topic-discovery quality (proposing 50-80 candidate topics), NOT per-topic research quality. Sonar's real-time index value for catching recent BCB/SUSEP updates inside an authored topic research run is a separate question that the substrate cheat sheet below still endorses. Refresh-run substrate ≠ per-topic substrate.

**Frontier-substrate audit — 2026-05-15 (batches 39-44):** Test batches 39-44 ran 30 topics with GPT-5+Exa + DeepSeek-V4-Pro+Exa as anchors plus 2 rotating frontier substrates per topic (10 candidates, 120 calls total, all completed). Verdicts extracted from Claude's per-topic synthesis blocks in `research-outputs-synthesis/<id>-*.md`. Headline outcomes:

- **Promote to default rotation:** `qwen/qwen3.6-max-preview`, `minimax/minimax-m2.7`, `moonshotai/kimi-k2.6` — each consistently matched or beat the legacy Sonar/Gemini-OR slot on volume, citation discipline, and unique-contribution density.
- **Conditional / specialist:** `z-ai/glm-5.1` (topic-174 star on agentic-memory taxonomy, but one substrate-level corruption failure on topic 179 — 871 bytes of CJK/Cyrillic/numeric fragments); `x-ai/grok-4.20` (strong on tech-comparative, "fluency over epistemic disclosure" on BR-regulatory).
- **Drop from rotation:** `mistralai/mistral-large-2512`, `nvidia/nemotron-3-super-120b-a12b`, `cohere/command-a`, `meta-llama/llama-4-maverick`, `ai21/jamba-large-1.7`, `bytedance-seed/seed-2.0-lite` — collectively consumed ~50% of test budget for sub-anchor quality.
- **Disqualify:** `baidu/ernie-4.5-300b-a47b` — topic 183 fabricated "Mantis (Anthropic)" as a reference MCP implementation with invented URL `anthropic.com/blog/mantis-security`; pattern-matches confidently into nonexistent product names. Hard-fail for a research harness that feeds downstream memory ingestion.
- **ZDR / data-policy update:** the OpenRouter privacy block on Qwen / xAI / MoonshotAI / MiniMax / ByteDance Seed / ERNIE was **relaxed** before 2026-05-15; all 12 candidates ran successfully on this account. The Tier 2 "blocked" table below has been retired.

Full per-model verdicts and topic-class fit in the [Frontier-substrate audit section](#frontier-substrate-audit--2026-05-15-batches-39-44) below.

**Use this guide when authoring `openrouter[]` entries for a new topic.**

---

## TL;DR — the substrate cheat sheet

**Updated 2026-05-15 post-batch-44.** Anchors (GPT-5+Exa and DeepSeek-V4-Pro+Exa) are now fixed across every class; the third and fourth slots vary by topic class:

| Topic class | Recommended substrate set (2026-05-15+) | Rationale |
|---|---|---|
| **Brazilian regulatory + recent** (PIX, DREX, ICP-Brasil, BCB normativos, ANPD/LGPD) | GPT-5+Exa + DeepSeek-V4-Pro+Exa + **Qwen 3.6 Max+Exa** + Sonar-Reasoning-Pro | Qwen brings explicit BR-regulatory framing + dev-implication callouts (topic 183 was the only substrate to surface BACEN + LGPD framing); Sonar still earns its slot for real-time BCB/ANPD index. Avoid Grok-4 and Mistral for this class — both confabulate regulatory specifics |
| **Cutting-edge spec / moving target** (MCP/A2A, GenAI semconv, recent arxiv papers) | GPT-5+Exa + DeepSeek-V4-Pro+Exa + **Kimi K2.6+Exa** + Sonar-Reasoning-Pro | Kimi's citation precision (exact arxiv submission/revision dates, repo metadata) catches issues GPT-5 misses; Sonar for currency on rapidly-evolving specs |
| **Comparative tooling** (workflow orchestrators, policy engines, vector DBs, observability platforms) | GPT-5+Exa + DeepSeek-V4-Pro+Exa + **MiniMax M2.7+Exa** + **Qwen 3.6 Max+Exa** | MiniMax for engineering-depth on internals (Cedar Rust-crate organization, PyO3 FFI, OpenSearch WORM caveats); Qwen for operational framing. Drop Sonar here — substrate diversity > currency for vendor-pitch triangulation |
| **Math / theory** (USL, queueing, Bayes opt, eval statistics, pass^k) | GPT-5+Exa + DeepSeek-V4-Pro+Exa (reasoning=xhigh) + **MiniMax M2.7+Exa** | MiniMax's structured engineering framing complements reasoning-mode DeepSeek; 3 substrates sufficient |
| **Established methodology** (postmortems, ADRs, fitness functions, audit patterns) | GPT-5+Exa + DeepSeek-V4-Pro+Exa + **Kimi K2.6+Exa** | Kimi's "Not found" discipline beats Sonar on slow-evolving topics; 3 substrates sufficient. ~30% cost reduction vs the 4-substrate default |
| **LLM internals / agent architectures** (incl. mantis home turf) | GPT-5+Exa + DeepSeek-V4-Pro+Exa + **MiniMax M2.7+Exa** + **Qwen 3.6 Max+Exa** | mantis home turf — substrate diversity is the value. MiniMax + Qwen replace Sonar + Gemini-OR for this class |
| **Agentic-memory / mantis competitive intel** (new class, batches 43+) | GPT-5+Exa + DeepSeek-V4-Pro+Exa + **GLM 5.1+Exa** + **MiniMax M2.7+Exa** | GLM was the topic-174 star (cognitive-science roots, ontology proposal, EPHEMERAL/OPERATIONAL/REGULATORY persistence tier). Accept reliability risk — add corruption-detection retry in the adapter |
| **Tech-comparative without regulatory edge** (e.g. policy engines, identity stacks, eval frameworks) | GPT-5+Exa + DeepSeek-V4-Pro+Exa + **MiniMax M2.7+Exa** + **Grok 4.20+Exa** | Grok earned its keep on topic 180 (Rego decidability framing was the most technically defensible). Do NOT use Grok if the topic touches BR regulatory specifics |

**Default 4-substrate set (May 2026, post-batch-44):** for a generic topic where no class strongly applies, use `GPT-5+Exa + DeepSeek-V4-Pro+Exa + Qwen 3.6 Max+Exa + MiniMax M2.7+Exa`. Comprehensive, ~$2-6/topic, all four substrates earn their cost. (Legacy: pre-batch-39 default was `Gemini-OR + DeepSeek-V4-Pro+Exa + Sonar-Reasoning-Pro + GPT-5+Exa` — keep this template for legacy reruns; existing batches 10-38 use `deepseek-r1` — no retroactive change.)

---

## Substrate inventory and what each contributes

### Tier 1 — verified working on this account

| Substrate | OR slug | Search engine | Strengths | Weaknesses | Cost/call |
|---|---|---|---|---|---|
| **Gemini Pro** | `google/gemini-3.1-pro-preview` | Native Google index | Comprehensive coverage, long context (1M+), good citation discipline | Sometimes "marketing-shape" framing; can drift to wrong topic if prompt is ambiguous (saw this on OTel topic in batch-10-5model) | ~$0.30-1 |
| **DeepSeek V4 Pro** (default for new batches 2026-05-15+) | `deepseek/deepseek-v4-pro` (with Exa) | Exa semantic curated | Open-weight (different RLHF), reasoning-strong (`xhigh` mode for long-horizon), MoE 1.6T/49B activated, 1M context, 384k max output, MIT license; 80.6% SWE-bench Verified | Hallucinates regulatory codes + version numbers (inherit R1 pattern; verify regulatory claims against Sonar/Gemini cross-check) | ~$0.10-0.40 ($0.435/M in, $0.87/M out) |
| **DeepSeek-R1** (legacy — used in batches 10-38) | `deepseek/deepseek-r1` (with Exa) | Exa semantic curated | Open-weight (different RLHF), reasoning-strong, code+math heavy | Hallucinates regulatory codes and version numbers (caught fabricating SPI namespaces, IN BCB numbers, A3 mandate dates); superseded by V4 Pro April 2026 | ~$0.05-0.15 |
| **Perplexity Sonar-Reasoning-Pro** | `perplexity/sonar-reasoning-pro` | Native real-time Google-Bing | Citation-heavy by default, real-time index, fastest of the 4 (~30-60s/call) | Smaller briefs (5-25KB) than GPT-5; can mistranslate domain-specific terms (saw "Conta PI" → "Participant Investment" instead of "Pagamentos Instantâneos") | ~$0.10-0.30 |
| **GPT-5** | `openai/gpt-5` (with Exa) | Exa semantic curated | Largest, densest briefs (35-40KB typical); different RLHF tradition than Anthropic; strong on structured tooling claims | Slightly slower than Sonar (~3 min/call); not the strongest at flagging cross-substrate disagreement when used as primary | ~$0.10-0.40 |
| **Qwen 3.6 Max** (preview, added 2026-05-15) | `qwen/qwen3.6-max-preview` (with Exa) | Exa semantic curated | Large briefs (~35 KB avg, GPT-5-class volume); "Not found" discipline matches Claude; explicit dev-implication callouts after each section; uniquely surfaces BR-fintech regulatory framing (BACEN + LGPD + PIX audit on topic 183 where other 3 substrates missed it) | Preview tier — slug may shift; verify via OR `/models` endpoint. Medium-slow (~280-400s) | ~$0.30-0.80 |
| **MiniMax M2.7** (added 2026-05-15) | `minimax/minimax-m2.7` (with Exa) | Exa semantic curated | Largest briefs (~40 KB avg, can hit 52 KB); best engineering-depth on technical comparisons (Cedar Rust crates, Permify/CockroachDB, PyO3 FFI maturity on topic 180); sharpest caveat discipline on OpenSearch WORM claims (topic 166); surfaces open questions others miss | Latency variable (89-410s); can be verbose without being denser | ~$0.20-0.60 |
| **Kimi K2.6** (added 2026-05-15) | `moonshotai/kimi-k2.6` (with Exa) | Exa semantic curated | "Not found" discipline matches Claude; precise arxiv-metadata pinning (exact submission/revision dates on topic 168); cross-substrate convergent honesty; topic 155 verdict was "strongest secondary substrate" | Output volume variance is the risk (range 5.6-31.4 KB across 5 topics — was thin on topic 159); slower (145-665s) | ~$0.15-0.50 |

### Tier 2 — conditional / specialist (added 2026-05-15)

| Substrate | OR slug | Verdict | When to use |
|---|---|---|---|
| **GLM 5.1** | `z-ai/glm-5.1` (with Exa) | Topic 174 was a star performance — most comprehensive on agentic-memory taxonomy with cognitive-science roots (Tulving 1972, Squire 1992), EPHEMERAL/OPERATIONAL/REGULATORY persistence tier model. **But topic 179 was a total system-level corruption: 871 bytes of CJK/Cyrillic/numeric fragments.** Reliability concern. | Use ONLY for the agentic-memory / mantis-direct competitive-intel class where its upside is highest. Add corruption-detection (byte-count threshold or character-class check) in the adapter and retry-on-empty before letting GLM gate synthesis. |
| **Grok 4.20** | `x-ai/grok-4.20` (with Exa) | Topic 180 (Cedar/OPA/OpenFGA) — most defensible technical characterization of Rego decidability. Topic 162 (BR payment arrangements) — verdict was "weakest substrate… produced concrete content for a source it likely did not retrieve… xAI's RLHF appears to optimize for fluency over epistemic disclosure." | Use for **tech-comparative without regulatory edge** (policy engines, identity stacks, eval frameworks). **Never** for BR-regulatory topics. |

**ZDR / data-policy note:** the OpenRouter privacy block on Qwen / xAI / MoonshotAI / MiniMax / ByteDance Seed / ERNIE was relaxed before 2026-05-15. All providers above ran successfully on this account. If the block is re-enabled, this Tier 2 reverts to "blocked" and the substrate cheat sheet falls back to the legacy default (Gemini-OR + Sonar + DeepSeek + GPT-5).

### Tier 3 — tested-and-not-recommended (batches 39-44 evidence)

These ran successfully in batches 39-44 but underperformed the Tier 1 additions on quality, latency, or volume. Drop from default rotation; keep on the candidate list for niche re-tests.

| Substrate | OR slug | Why it fell off |
|---|---|---|
| **Mistral Large 3** | `mistralai/mistral-large-2512` | "Fluency-as-accuracy substitution" — false precision on regulatory; topic 159 invented "at-risk fintech" attributions to named companies (defamation risk for downstream use); topic 174 — "should not be cited for any numeric claim" |
| **Nvidia Nemotron 3 Super 120B** | `nvidia/nemotron-3-super-120b-a12b` | Catastrophic latency (10-22 min/call vs 3-5 min anchors); confident hallucinations (fabricated GitHub issue numbers on topic 154, internally-inconsistent "2-3× overhead" claim, fabricated governance-publication titles on topic 168) |
| **Cohere Command A** | `cohere/command-a` | Smallest briefs (~9 KB avg); fabricated PT-BR Presidio FNR benchmark numbers (topic 165), hallucinated τ³-bench leaderboard (topic 170), invented "10-year retention" attribution to RC 16/2025 (topic 160) |
| **Meta Llama 4 Maverick** | `meta-llama/llama-4-maverick` | Shallowest output (~7 KB avg); off-by-one-concept errors on multi-layer systems (rotation cadences on topic 179); technically-misleading WORM framing (topic 166) that "would lead to noncompliant designs if taken at face value" |
| **AI21 Jamba Large 1.7** | `ai21/jamba-large-1.7` | Hallucinated a LongMemEval leaderboard (topic 173); fabricated Cloudflare-internal-use claim with no citation (topic 182); prototype confident-fabrication pattern for smaller models under web-search grounding |
| **ByteDance Seed 2.0 Lite** | `bytedance-seed/seed-2.0-lite` | Name says it — small-model failure mode under web-search grounding; topic 164 invented "9 total sanctions" and forward-dated precedents; topic 177 internal contradiction in its primary recommendation |

### Tier 4 — disqualified

| Substrate | OR slug | Why disqualified |
|---|---|---|
| **Baidu ERNIE 4.5 300B** | `baidu/ernie-4.5-300b-a47b` | Topic 183 fabricated **"Mantis (Anthropic)"** as a reference MCP implementation with invented URL `anthropic.com/blog/mantis-security` — pattern-matched "MCP" to "Anthropic" and produced confident product names *for the user's own project*. Topic 158 produced "the highest-density hallucination cluster" of the four briefs (fabricated release months). Topic 167 cited fabricated PR #12345. Topic 183 invented MCP versions 1.0/2.0 that predate MCP's actual 2024 launch. **Hard-fail in a research harness that feeds downstream memory ingestion** — exclude from all batches. |

### Tier 5 — legacy / structurally redundant

| Substrate | Reason |
|---|---|
| `anthropic/claude-opus-4-7` via OR | Most expensive on OR ($15/$75 per million); Path B test confirmed Claude-CLI synthesis works fine without Claude in research; no point paying premium |
| `anthropic/claude-sonnet-*` | Same substrate as Claude-CLI (just a different size); adds redundancy not diversity |
| `openai/gpt-4-turbo`, `openai/gpt-4` | Older substrate; GPT-5 supersedes |
| `qwen/qwen-2.5-*` | Older substrate; prefer `qwen/qwen3.6-max-preview` (now in Tier 1) |
| `qwen/qwen3-max-thinking` | Superseded by `qwen3.6-max-preview`; the 3.6 variant has the discipline tradeoff resolved |
| `x-ai/grok-4` (base, non-4.20) | Superseded by `grok-4.20` for tech-comparative slot; do not use the base variant |

---

## Decision tree for substrate selection (updated 2026-05-15 post-batch-44)

Anchors are fixed: every batch runs **GPT-5+Exa + DeepSeek-V4-Pro+Exa**. The tree picks the 2 rotating slots.

```
Is the topic Brazilian-fintech / regulatory / recent-events?
│
├── YES → Rotators: Qwen 3.6 Max+Exa + Sonar-Reasoning-Pro
│         (Qwen for BR-fintech operational framing; Sonar for BCB/ANPD real-time index)
│         AVOID: Grok-4.20, Mistral-Large-3, Cohere Command A — all confabulate
│         regulatory specifics; ERNIE-4.5 disqualified
│
└── NO → Is the topic a cutting-edge spec or recent arxiv paper?
         │
         ├── YES → Rotators: Kimi K2.6+Exa + Sonar-Reasoning-Pro
         │         (Kimi for citation precision; Sonar for currency on
         │          rapidly-evolving specs)
         │
         └── NO → Is the topic agentic-memory / mantis-direct competitive intel?
                  │
                  ├── YES → Rotators: GLM 5.1+Exa + MiniMax M2.7+Exa
                  │         (GLM was topic-174 star; add corruption-detection
                  │          retry in adapter)
                  │
                  └── NO → Is the topic comparative-vendor-tooling (no regulatory edge)?
                           │
                           ├── YES → Rotators: MiniMax M2.7+Exa + Qwen 3.6 Max+Exa
                           │         (MiniMax engineering-depth; Qwen operational
                           │          framing — substrate diversity is the value)
                           │
                           └── NO → Is the topic math / theory / eval statistics?
                                    │
                                    ├── YES → Drop to 3 substrates: anchors + MiniMax M2.7+Exa
                                    │         (set DeepSeek reasoning_effort=xhigh;
                                    │          Sonar's edge is wasted on stable theory)
                                    │
                                    └── NO (established methodology) →
                                         Drop to 3 substrates: anchors + Kimi K2.6+Exa
                                         (Kimi's "Not found" discipline beats Sonar
                                          on slow-evolving topics)
```

---

## Per-topic-class evidence

### Brazilian regulatory + recent (PIX, DREX, ISO 20022)

**Test data:** batch-11 topic 20 (DREX 3-model), batch-10 topic 5 (ISO 20022 4-model), batch-12 topic 21 (PIX 5-substrate Path A vs 4-substrate Path B).

**Catches:**
- DeepSeek fabricated `IN BCB 561/2024` (doesn't exist)
- DeepSeek fabricated `pacs.002.spi v3.0` minor version (Catálogo doesn't track that way)
- DeepSeek fabricated `AB08` as MED reason code
- DeepSeek fabricated 2023 ICP-Brasil A3 mandate citing "ITI Normative #3.7"
- DeepSeek hallucinated DICT IBAN validation (Brazil uses ISPB+Agência+Conta)
- Sonar mistranslated "Conta PI" as "Participant Investment" (correct: "Pagamentos Instantâneos") — caught only by Path B because Path A's Claude-CLI primary masked the disagreement

**Conclusion:** DeepSeek is the **most prolific hallucinator on regulatory codes** but provides valuable cross-check signal. Always include it AND Sonar AND Gemini-OR for multi-source triangulation. GPT-5 adds density.

### Cutting-edge spec / moving target (WASI, GenAI semconv)

**Test data:** batch-10 topic 2 (OTel semconv 4-model + 5-model), batch-12 topic 22 (WASM/WASI 5-substrate Path A vs 4-substrate Path B).

**Findings:**
- Gemini went off-topic entirely on OTel semconv in batch-10-5model (recovered by DeepSeek + Sonar + GPT-5)
- DeepSeek hallucinated "Header case normalization → Raw header names" (Prometheus-rule conflation)
- Sonar's stability-level count was wrong (4 vs Claude's 6 per OTEP 0232)
- Path B's WASM synthesis was 36% smaller than Path A's but produced 3× more journal entries — divergence-flagging on a moving spec is more valuable than primary-brief depth

**Conclusion:** Sonar's real-time index is critical for spec-tracking. GPT-5 brings structure. Don't trust any single substrate; the 4-substrate divergence flagging IS the value.

### Comparative tooling (vector DBs, embedding models, workflow orchestrators)

**Test data:** batch-11 topics 12, 14, 17 (3-model); batch-12 topic 23 (workflow orchestration 5-substrate vs 4-substrate).

**Findings:**
- Gemini name-dropped fabricated products ("Med-PaLM 2 Embeddings", "Bloomberg-adapted vectors") in batch-11 topic 14 — caught only by 3-substrate triangulation
- DeepSeek's broken arXiv id (`arXiv:2404.XXXXX` for BMRetriever) caught
- Workflow-orchestration 4-substrate paths produced equally rich syntheses with substantial substrate-attribution density (DeepSeek 246 mentions, Gemini 333 in Path B)

**Conclusion:** Substrate diversity matters most here — vendors push narratives in their docs, and no single substrate is immune. Use all 4.

### Math / theory (USL, Bayesian opt, queueing)

**Test data:** batch-11 topic 19 (USL 3-model), batch-10 topic 9 (Bayes Opt MLOps 4-model + 5-model).

**Findings:**
- Sonar adds less on stable theory (USL is unchanged since Gunther 1991-2007)
- DeepSeek with reasoning=high produces strong derivations
- GPT-5 adds structured comparisons and pseudo-code

**Conclusion:** Drop Sonar for pure theory/math; save the call. 3-substrate (DeepSeek + GPT-5 + Gemini-OR) is sufficient.

### Established methodology (postmortems, ADRs, fitness functions)

**Test data:** batch-10 topic 1 (C4/ADRs 5-substrate), batch-10 topic 8 (postmortems 5-substrate).

**Findings:**
- Slow-evolving topics: substrates converge on the same canonical sources (Nygard 2011 ADR memo, Westrum 2004 typology)
- Sonar's real-time edge is wasted
- Substrate diversity still helps on minor framings

**Conclusion:** Drop Sonar; 3-substrate (Gemini-OR + DeepSeek-V4-Pro + GPT-5) is enough. ~30% cost reduction with negligible quality drop.

### LLM internals / agent architectures

**Test data:** batch-11 (10 topics, 3-model — all in this class).

**Findings:**
- DeepSeek's open-weight + Exa semantic search adds the most signal on substrate-different framings (e.g., on AriGraph vs MemGPT comparative)
- GPT-5 brings OpenAI-lineage view (sometimes contrasts with Anthropic-lineage Claude)
- Sonar surfaces recent papers Gemini's training data missed
- Gemini-OR is comprehensive but tends toward smoothed framing

**Conclusion:** All 4 substrates earn their cost. This is mantis's home turf.

---

## Frontier-substrate audit — 2026-05-15 (batches 39-44)

**Test design:** 6 batches × 5 topics × 4 substrates = 120 substrate calls. Every topic ran GPT-5+Exa and DeepSeek-V4-Pro+Exa as fixed anchors plus 2 of 10 rotating frontier candidates: Mistral Large 3, Cohere Command A, Llama 4 Maverick, Grok 4.20, Nemotron 3 Super 120B, Kimi K2.6, Qwen 3.6 Max, GLM-5.1, MiniMax M2.7, ERNIE 4.5 300B, ByteDance Seed 2.0 Lite, AI21 Jamba Large 1.7. All 120 calls completed (no API failures). Verdicts below are extracted from Claude's per-topic synthesis blocks at `research-outputs-synthesis/<id>-*.md` and the per-substrate state at `state-openrouter/<id>.json`.

### Quantitative summary

| Substrate | Topics run | Avg brief size | Byte range | Avg dur (s) | Notable |
|---|---|---|---|---|---|
| **Anchors** | | | | | |
| gpt-5-exa | 30/30 | 41.2 KB | 34.4–50.0 KB | 184 | Reference primary |
| deepseek-v4-pro-online | 30/30 | 25.7 KB | 16.5–33.1 KB | 314 | Reference cross-check |
| **Tier A — promoted to default rotation** | | | | | |
| qwen3-6-max-exa | 5/5 | **35.1 KB** | 27.7–44.3 KB | 346 | Largest after GPT-5 |
| minimax-m2-7-exa | 5/5 | **40.3 KB** | 22.1–52.5 KB | 176 | Largest overall (incl. anchors) |
| kimi-k2-6-exa | 5/5 | 22.8 KB | 5.6–31.4 KB | 401 | Output variance is the risk |
| **Tier B — conditional** | | | | | |
| glm-5-1-exa | 5/5 | 27.0 KB | **0.87**–49.9 KB | 211 | **One total-failure (topic 179)** |
| grok-4-20-exa | 5/5 | 19.2 KB | 17.0–22.1 KB | 70 | Fastest at real-content tier |
| **Tier C — dropped from rotation** | | | | | |
| nemotron-3-super-exa | 5/5 | 26.5 KB | 16.9–31.4 KB | **794** | 10–22 min/call |
| mistral-large-3-exa | 5/5 | 22.7 KB | 15.4–27.7 KB | 120 | Fast but false-precision |
| seed-2-0-lite-exa | 5/5 | 16.4 KB | 13.1–18.1 KB | 357 | Slow for size |
| ernie-4-5-300b-exa | 5/5 | 12.1 KB | 9.7–13.9 KB | 141 | Thin |
| command-a-exa | 5/5 | 9.6 KB | 7.9–10.9 KB | 65 | Smallest of any tier |
| jamba-large-1-7-exa | 5/5 | 11.1 KB | 9.3–13.3 KB | 48 | Fast but thin |
| llama-4-maverick-exa | 5/5 | **7.2 KB** | 5.9–8.1 KB | 44 | Shallowest of all |

### Per-model verdict + topic-class fit

#### Qwen 3.6 Max — `qwen/qwen3.6-max-preview` (Exa) — Tier A

**Recommended for:**
- ✅ **Brazilian regulatory + recent** (ANPD/LGPD, BCB normativos, PIX/DREX/eFX) — topic 183 was the only substrate to surface BACEN cybersecurity resolutions + LGPD data-localization + PIX audit framing; topic 178 contributed Levenshtein span thresholds and LINDB tacit-repeal modelling that were folded into synthesis as material improvements
- ✅ **Comparative tooling with operational framing** — topic 163 (eFX/CP 124) added per-section "developer implication" callouts (rail_type tagging, segregated wallets, compliance gates) that no other substrate produced
- ✅ **Established methodology** — Qwen's "Not found in provided sources" discipline matches Claude's

**Avoid for:** no observed failure mode in 5 topics, but watch for slug shifts (it's a preview tier — verify via OR `/models`)

**Best-of:** topic 183 — "Brazilian fintech regulatory context (Qwen-unique addition)... directly load-bearing for mantis"

#### MiniMax M2.7 — `minimax/minimax-m2.7` (Exa) — Tier A

**Recommended for:**
- ✅ **Comparative tooling** (policy engines, observability, data stacks, identity stacks) — topic 180 went deepest on Cedar's Rust crate organization, Permify's CockroachDB consistency implications, and explicit mantis Python integration concerns (PyO3 bindings, FFI maturity) that no other substrate raised
- ✅ **LLM internals / agent architectures** (mantis home turf) — surfaces engineering-depth open questions
- ✅ **Math / theory + eval statistics** — structured framing complements reasoning-mode DeepSeek
- ✅ **Spec-level engineering** — sharpest caveat on OpenSearch immutable-index claims (topic 166): "`index.blocks.write: true` is not sufficient for WORM compliance" — corrected a technically-misleading framing from Llama-4-Maverick

**Avoid for:** no observed failure mode in 5 topics

**Best-of:** topic 180 — uniquely surfaced the LGPD-specific Cedar schema patterns no other substrate raised

#### Kimi K2.6 — `moonshotai/kimi-k2.6` (Exa) — Tier A

**Recommended for:**
- ✅ **Cutting-edge spec / moving target** — topic 168 alone pinned exact arxiv submission/revision/venue dates ("arXiv:2302.12173, submitted 23 February 2023, revised 5 May 2023, published at AISec '23") consistent with public arxiv metadata
- ✅ **Established methodology / audit patterns** — topic 155 verdict was "the strongest secondary substrate... methodological discipline matches Claude's — flags 'Not found' honestly"
- ✅ **Cross-substrate convergence checking** — useful as a 3rd substrate when you want Claude-style honesty without paying Claude-via-OR

**Avoid for:** topics where you need guaranteed minimum brief size — Kimi's output range was 5.6–31.4 KB (topic 159 came in at only 5.6 KB)

**Best-of:** topic 155 — strongest secondary on MCP authorization + registry, named registry backers (Anthropic, GitHub, PulseMCP, Microsoft) no other substrate did

#### GLM 5.1 — `z-ai/glm-5.1` (Exa) — Tier B (conditional)

**Recommended for:**
- ✅ **Agentic-memory / mantis-direct competitive intel** — topic 174 verdict was "most comprehensive across dimensions — longest brief, deepest taxonomy section, explicit acknowledgement of cognitive-science roots (Tulving 1972, Squire 1992), explicit ontology proposal for mantis, EPHEMERAL/OPERATIONAL/REGULATORY persistence tiers... largest verifiable-citation surface — most likely to be cited in derivative work"
- ✅ **Tech-comparative where mantis-positioning matters** — topic 157 hallucination-flagging on A2A `sideEffects` field was "the single highest-value hallucination flag in this batch"

**Avoid for:** anything where reliability matters more than upside — **topic 179 produced 871 bytes of corrupted output (CJK + Cyrillic + numeric fragments — substrate-level failure)**. Without corruption-detection wrapping, GLM can silently gate synthesis on garbage.

**Required mitigation if used:** add an output-validation step in `interface/adapters/openrouter_http.py` that checks (a) minimum byte threshold (≥3 KB), (b) ratio of ASCII-letter chars to total chars (>0.5) before accepting GLM responses. Retry-once on validation failure.

#### Grok 4.20 — `x-ai/grok-4.20` (Exa) — Tier B (specialist)

**Recommended for:**
- ✅ **Tech-comparative without regulatory edge** (policy engines, identity protocols, eval frameworks) — topic 180 framing of Rego decidability ("Turing-complete only when combined with OPA's host language integration") was "the most technically defensible characterization across the four"

**Avoid for:**
- ❌ **Brazilian regulatory** — topic 162 verdict was "weakest substrate for this topic"; "produced concrete content for a source it likely did not retrieve... xAI's RLHF appears to optimize for fluency over epistemic disclosure"
- ❌ Any topic where missing-source-honesty is load-bearing

#### Tier C drops — when (and only when) to consider re-testing

| Substrate | Re-test trigger |
|---|---|
| Mistral Large 3 | Only if Mistral ships a successor with documented hallucination-reduction work |
| Nemotron 3 Super | Only if NVIDIA ships a v4 with substantially lower latency (current 10-22 min/call is uncompetitive) |
| Cohere Command A | Only if Cohere ships a "Pro" tier with larger context budget |
| Llama 4 Maverick | Only if Meta ships a non-Maverick variant tuned for long-form research |
| Jamba Large 1.7 | Only if AI21 ships a v2 with web-search-grounding-aware fine-tuning |
| Seed 2.0 Lite | The "Lite" name flags the issue; revisit only if ByteDance ships a non-Lite variant |

#### Tier D — ERNIE 4.5 300B disqualification standard

The ERNIE failure mode (fabricating "Mantis (Anthropic)" as a reference implementation with invented URL `anthropic.com/blog/mantis-security`) is the **disqualification standard for this harness**: any substrate that pattern-matches the user's own project into a confidently-cited nonexistent product is excluded outright, regardless of its performance on other topics. Future batches should not include `baidu/ernie-4.5-300b-a47b` even as a test rotator.

### Source files for re-verification

- Per-topic state: `state-openrouter/154.json` through `state-openrouter/183.json`
- Per-substrate briefs: `research-outputs-openrouter/<id>-<slug>/<subslug>.md`
- Claude's verdict synthesis: `research-outputs-synthesis/<id>-<slug>.md`
- The corruption case: `research-outputs-openrouter/179-spiffe-spire-workload-identity-2025-2026/glm-5-1-exa.md`

---

## Cost optimization patterns

| Strategy | Savings | When to use |
|---|---|---|
| Drop Sonar for stable methodology / math | ~$0.10-0.30/topic | Topics with no recent-events component |
| Drop the 4th substrate to go 3-substrate | ~$0.40-1.00/topic | Established methodology + math/theory (anchors + 1 frontier substrate suffices) |
| Use Kimi K2.6 instead of Sonar on slow-evolving topics | ~$0 (similar cost) | ADRs, fitness functions, audit patterns — Kimi's "Not found" discipline beats Sonar |
| Use MiniMax M2.7 instead of Gemini-OR on code-heavy topics | ~$0.20/topic | Engineering-depth comparisons where Gemini's "smoothed framing" loses to MiniMax's structural depth |
| Promote a cheaper substrate as primary in Path B | ~$0 (free swap) | GPT-5 as primary as default; DeepSeek as primary for math; legacy: Sonar as primary for regulatory |
| Skip Grok-4.20 if no tech-comparative topic class | ~$0.20-0.40/topic | Grok-4.20 is specialist-only after the topic-162 BR-regulatory failure; do not include in regulatory batches |

---

## Substrate quirks to remember (tribal knowledge)

1. **DeepSeek V4 Pro with reasoning="high"** — generates hidden thinking tokens billed at output rate. Use `reasoning_effort: "high"` as default; `"xhigh"` available for math-heavy or long-horizon agent topics (more expensive). MoE architecture means thinking tokens still meaningful. V4 Pro inherits R1's reasoning-mode billing pattern. (Legacy: same applies to existing batches' `deepseek/deepseek-r1` entries.)
2. **Sonar does NOT accept the `web` plugin** — its search is baked in. Setting `web_search: true` with engine=exa fails. Always set `web_search: false` for Sonar entries.
3. **Gemini Pro Preview slug shifts often** — was `google/gemini-3-pro-preview`, now `google/gemini-3.1-pro-preview` (April 2026). Verify before each new batch via OR's /models endpoint.
4. **GPT-5 with Exa** — produces large dense briefs (35-40 KB typical). Excellent primary substitute when Path B is used.
5. **OR data-policy / ZDR — relaxed before 2026-05-15.** The account's privacy block on Qwen / xAI / MoonshotAI / MiniMax / ByteDance Seed / ERNIE has been lifted; all 12 frontier candidates ran successfully in batches 39-44. Manage at https://openrouter.ai/settings/privacy. If the block is re-enabled, the new Tier 1 entries (Qwen, MiniMax, Kimi) and Tier 2 (GLM, Grok) revert to "blocked" and the substrate cheat sheet falls back to the legacy default (Gemini-OR + Sonar + DeepSeek + GPT-5). Verify availability at the start of any new batch via OR's `/models` endpoint before committing a `series.toml`.
6. **Claude-via-OR is overpriced** — `anthropic/claude-opus-4-7` costs $15/$75 per million. Use Claude only via Claude CLI subscription, never via OR.
7. **Claude CLI subscription** — best used for synthesis + journal-passes (where the agent loop matters), not for research (where it doesn't outperform 4 OR substrates per the batch-12 test).
8. **Qwen 3.6 Max is preview-tier** — slug is `qwen/qwen3.6-max-preview`. Preview slugs shift on Qwen releases; verify via OR `/models` before committing a `series.toml`. Once the GA variant ships, prefer that.
9. **GLM 5.1 output corruption is a real failure mode.** Topic 179 produced 871 bytes of CJK + Cyrillic + numeric fragments. If GLM is in the rotation, the adapter must validate output before accepting (byte threshold + ASCII-letter ratio) and retry-once on failure. Without that wrapping, GLM can silently gate synthesis on garbage.
10. **MiniMax M2.7 latency variance** — observed 89-410s across 5 topics. Not problematic for batch runs but factor into per-batch wall-clock estimates.
11. **Kimi K2.6 output volume variance** — observed 5.6-31.4 KB across 5 topics. If a downstream stage requires minimum brief size, add a length check in the adapter.
12. **Grok 4.20 is the only substrate with explicit "use only for tech-comparative" guidance.** Topic 162 verdict was unambiguous: Grok's xAI-RLHF "fluency over epistemic disclosure" pattern makes it dangerous for BR-regulatory work. Configure topic templates to exclude Grok from regulatory batches.
13. **ERNIE 4.5 300B is permanently disqualified.** The Mantis-as-Anthropic-product fabrication is the disqualification standard — any substrate that confidently invents the user's own project as a vendor product is excluded. Document this when reviewing any future ERNIE successor before re-inclusion.

---

## Default starting point for new batches (updated 2026-05-15 post-batch-44)

### Default A — generic technical topic (no strong class signal)

Use this when the topic doesn't clearly fit one of the cheat-sheet classes.

```json
[
  {
    "subslug": "gpt-5-exa",
    "model": "openai/gpt-5",
    "web_search": true,
    "web_search_engine": "exa",
    "web_search_max_results": 8,
    "reasoning_effort": "high",
    "max_tokens": 16000,
    "prompt": "<the OR-shared persona prompt>"
  },
  {
    "subslug": "deepseek-v4-pro-online",
    "model": "deepseek/deepseek-v4-pro",
    "web_search": true,
    "web_search_engine": "exa",
    "web_search_max_results": 8,
    "reasoning_effort": "high",
    "max_tokens": 16000,
    "prompt": "<same prompt cloned>"
  },
  {
    "subslug": "qwen3-6-max-exa",
    "model": "qwen/qwen3.6-max-preview",
    "web_search": true,
    "web_search_engine": "exa",
    "web_search_max_results": 8,
    "max_tokens": 16000,
    "prompt": "<same prompt cloned>"
  },
  {
    "subslug": "minimax-m2-7-exa",
    "model": "minimax/minimax-m2.7",
    "web_search": true,
    "web_search_engine": "exa",
    "web_search_max_results": 8,
    "max_tokens": 16000,
    "prompt": "<same prompt cloned>"
  }
]
```

### Default B — Brazilian regulatory / recent-events topic

Swap MiniMax for Sonar (real-time index) and keep Qwen for BR-fintech operational framing:

```json
[
  { "subslug": "gpt-5-exa", "model": "openai/gpt-5", "web_search": true, "web_search_engine": "exa", "web_search_max_results": 8, "reasoning_effort": "high", "max_tokens": 16000, "prompt": "<...>" },
  { "subslug": "deepseek-v4-pro-online", "model": "deepseek/deepseek-v4-pro", "web_search": true, "web_search_engine": "exa", "web_search_max_results": 8, "reasoning_effort": "high", "max_tokens": 16000, "prompt": "<...>" },
  { "subslug": "qwen3-6-max-exa", "model": "qwen/qwen3.6-max-preview", "web_search": true, "web_search_engine": "exa", "web_search_max_results": 8, "max_tokens": 16000, "prompt": "<...>" },
  { "subslug": "sonar-reasoning-pro", "model": "perplexity/sonar-reasoning-pro", "web_search": false, "max_tokens": 16000, "prompt": "<...>" }
]
```

### Default C — agentic-memory / mantis-direct competitive intel

Includes GLM 5.1 (topic-174 star) and requires corruption-detection in the adapter:

```json
[
  { "subslug": "gpt-5-exa", "model": "openai/gpt-5", "web_search": true, "web_search_engine": "exa", "web_search_max_results": 8, "reasoning_effort": "high", "max_tokens": 16000, "prompt": "<...>" },
  { "subslug": "deepseek-v4-pro-online", "model": "deepseek/deepseek-v4-pro", "web_search": true, "web_search_engine": "exa", "web_search_max_results": 8, "reasoning_effort": "high", "max_tokens": 16000, "prompt": "<...>" },
  { "subslug": "glm-5-1-exa", "model": "z-ai/glm-5.1", "web_search": true, "web_search_engine": "exa", "web_search_max_results": 8, "max_tokens": 16000, "prompt": "<...>" },
  { "subslug": "minimax-m2-7-exa", "model": "minimax/minimax-m2.7", "web_search": true, "web_search_engine": "exa", "web_search_max_results": 8, "max_tokens": 16000, "prompt": "<...>" }
]
```

### Legacy default — pre-batch-39

Kept for legacy reruns or in case the ZDR / data-policy block is re-enabled. **Do not use for new batches** unless the new defaults are unavailable.

```json
[
  { "subslug": "gemini-3-pro-or", "model": "google/gemini-3.1-pro-preview", "web_search": false, "max_tokens": 16000, "prompt": "<...>" },
  { "subslug": "deepseek-v4-pro-online", "model": "deepseek/deepseek-v4-pro", "web_search": true, "web_search_engine": "exa", "web_search_max_results": 8, "reasoning_effort": "high", "max_tokens": 16000, "prompt": "<...>" },
  { "subslug": "sonar-reasoning-pro", "model": "perplexity/sonar-reasoning-pro", "web_search": false, "max_tokens": 16000, "prompt": "<...>" },
  { "subslug": "gpt-5-exa", "model": "openai/gpt-5", "web_search": true, "web_search_engine": "exa", "web_search_max_results": 8, "reasoning_effort": "high", "max_tokens": 16000, "prompt": "<...>" }
]
```

Drop the 4th entry (or replace with the 3rd Tier 1 substrate appropriate to the class) to go to 3-substrate mode — saves ~30% per topic with minimal quality cost on established-methodology topics.

---

## Provenance / accumulated test data

| Batch | Topics | Substrate count | Date | What it taught |
|---|---|---|---|---|
| batch-10 | 1-10 | 2 (Claude-CLI + Gemini-CLI) | 2026-05-01 | Baseline; topic 12 produced thin synth (4 KB) — 2-model can fail |
| batch-11 | 11-20 | 3 (Claude-CLI + Gemini-CLI + DeepSeek+Exa) | 2026-05-02 | DeepSeek catches Gemini fabrications; +127% divergence blocks |
| batch-10-4model | 5 of 10 (2,3,5,7,9) | 4 (Claude-CLI + Gemini-CLI + DeepSeek + Sonar) | 2026-05-03 | Sonar adds catches on regulatory; ISO 20022 had 11 divergence blocks |
| batch-10-5model | 5 of 10 (1,4,6,8,10) | 5 (Claude-CLI + Gemini-CLI + DeepSeek + Sonar + GPT-5) | 2026-05-03 | GPT-5 adds density (38 KB briefs); Qwen+Grok blocked by ZDR |
| batch-12 | 3 (21,22,23) | 5 (Path A) vs 4 (Path B) | 2026-05-04 | Path B (no Claude in research) is competitive; +62% journal entries |
| batch-13–38 | 24-153 | 4 (Path B canonical: Gemini-OR + Sonar + DeepSeek + GPT-5) | 2026-05-04 → 2026-05-14 | Production batches; Path B canonical default validated |
| **batch-39** | **154-158 (agent runtime)** | **4 (Path B test: anchors + 2 rotators)** | **2026-05-15** | **First frontier-substrate test batch; introduced GPT-5 + DeepSeek anchors with rotating frontier candidates** |
| **batch-40** | **159-163 (BR payment/FX reform)** | **4 (Path B test)** | **2026-05-15** | **Qwen 3.6 Max emerged as strongest BR-regulatory secondary; Mistral confabulated named-fintech "at-risk" attributions** |
| **batch-41** | **164-168 (LGPD audit evidence)** | **4 (Path B test)** | **2026-05-15** | **Seed-2.0-Lite confirmed small-model failure pattern; Mistral "false precision" risk on quantitative tables** |
| **batch-42** | **169-173 (agent eval)** | **4 (Path B test)** | **2026-05-15** | **Kimi K2.6 strong on citation precision; Qwen on pairwise-judge framing; Jamba hallucinated a LongMemEval leaderboard** |
| **batch-43** | **174-178 (memory architecture deep-dive)** | **4 (Path B test)** | **2026-05-15** | **GLM 5.1 was the topic-174 star on agentic-memory taxonomy; MiniMax M2.7 deepest on GraphRAG economics** |
| **batch-44** | **179-183 (identity / JIT access)** | **4 (Path B test)** | **2026-05-15** | **GLM 5.1 produced 871 bytes of corrupted output on topic 179 (substrate-level failure); ERNIE fabricated "Mantis (Anthropic)" with invented URL — disqualified outright. ZDR/data-policy block confirmed relaxed.** |

**Total evidence base as of 2026-05-15:** ~183 topics across 44 batches; the post-batch-44 audit promotes Qwen 3.6 Max / MiniMax M2.7 / Kimi K2.6 to default rotation and disqualifies ERNIE 4.5 300B.

This guide is updated when new evidence is collected. Next planned re-tests:
- Re-validate GLM 5.1 with corruption-detection wrapping in `interface/adapters/openrouter_http.py` to confirm whether topic 179 was a stable failure mode or a transient OR-side glitch
- Compare a 5-substrate rotation (anchors + Qwen + MiniMax + Kimi) against the 4-substrate default to measure whether the marginal substrate earns its cost on mantis-internals topics
- Test successor versions when announced: Mistral Large 4, Llama 5, ERNIE 5 (if/when released — ERNIE 5 must independently re-qualify by not pattern-matching user projects into fabricated Anthropic products)
