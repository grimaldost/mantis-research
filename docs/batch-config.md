# Batch config reference

The v2 batch config is the JSON file every `mantis run <stage>` command takes.
The source of truth is the pydantic schema in
[`core/config.py`](../src/mantis_research/core/config.py) — configs are
validated on load, and a bad one fails at startup with the offending field
named. Two standing properties:

- **Unknown keys are tolerated at every level** (`extra='allow'`); this is how
  adapter-specific knobs travel without schema churn.
- **The schema evolves additively** (invariant I4): new fields are optional
  with backward-compatible defaults, and existing configs must keep loading
  across releases.

A worked two-topic example lives at
[`config/example-batch.json`](../config/example-batch.json). Prompt *content*
is specified in [`prompts/playbooks/`](../prompts/playbooks/README.md);
substrate/model choice per topic class in
[`model-recommendations.md`](../prompts/playbooks/model-recommendations.md).

## Top level

| Field | Type / default | Meaning |
|---|---|---|
| `schema_version` | literal `2`, required | Schema generation marker. |
| `batch_name` | string, required | Names the run; with `layout: 'batch'` it also names the run's directory subtree. |
| `description` | string, `''` | Free-form; what this batch is. |
| `models` | block, required | Stage-level model choices — below. |
| `runner` | block, defaulted | Orchestrator settings — below. |
| `default_prompts` | block, defaulted | Batch-wide prompt overrides — below. |
| `topics` | array, required | The topics — below. Duplicate `id`s fail validation. |

## `models`

| Field | Type / default | Meaning |
|---|---|---|
| `claude` | ModelSpec, required | Model for the Claude research stage, and the fallback for synthesis-family stages. |
| `synthesis` | ModelSpec, optional | Model for the synthesis stage; falls back to `claude` when absent. |
| `gemini` | ModelSpec, optional | Model for the legacy Gemini CLI stage. |
| `openrouter` | ModelSpec, optional | Accepted but currently unused — the OpenRouter stage reads each subsession's own `model`. |
| `primary` | `null` \| `'claude'` \| `'openrouter:<subslug>'` | Which research brief anchors the synthesis ([ADR-0005](adr/0005-primary-brief-selection-in-config.md)). `null`/`'claude'` keeps the Claude brief primary; `'openrouter:<subslug>'` promotes that subsession's brief and demotes every other (Claude included) to secondary. An unresolvable primary blocks synthesis with a clear reason. |

A **ModelSpec** is `{ "model": …, "effort": … }`, both optional. An unset
model (or `'auto'` / `'latest'`) opts into the newest-frontier policy — for
Claude stages that resolves to the CLI alias `opus` (always the newest Opus);
an explicit id (e.g. `claude-opus-4-8`) is used verbatim. `effort` defaults to
`'max'` where the stage reads it. See
[architecture.md § Model selection](architecture.md#model-selection).

## `runner`

| Field | Default | Meaning |
|---|---|---|
| `max_parallel_topics` | `4` | Concurrent topics per stage run (override per run with `--parallel`). |
| `max_retries_per_stage` | `2` | Attempts per topic within one run. |
| `rate_limit_backoff_minutes` | `30` | Sleep after a rate-limited attempt (interruptible). |
| `generic_failure_backoff_minutes` | `5` | Sleep after other failures (interruptible). |
| `caller_idle_budget_seconds` | `1500.0` | How long the caller waits without hearing anything before abandoning the call. Every backoff is capped at half of it, so a rate-limited substrate cannot outlast the MCP client's 1800 s idle default. `null` disables the cap. |
| `child_idle_timeout_minutes` | `10.0` | Watchdog on a spawned local-seat child: kill it if it produces no output for this long, and fail the attempt. A clock on silence, not on runtime — it resets on every line. `null` disables it. |
| `layout` | `'legacy'` | `'legacy'` = the flat directories at the root; `'batch'` scopes state/outputs/transcripts under `<batch_name>/` ([ADR-0006](adr/0006-batch-scoped-run-layout.md)). Where files land: [running-batches.md](running-batches.md#where-files-land). |

## `default_prompts`

Batch-wide prompt templates: `synthesis`, `journal`, `journal_augmentation`,
`falsification`, `evaluation` — all optional strings. The resolution chain for
those stages is:

1. the topic's own `stages.<name>.prompt`, when set;
2. else `default_prompts.<name>`, when set;
3. else the packaged template in
   [`core/prompts.py`](../src/mantis_research/core/prompts.py) (whose
   behavior is specified by the matching playbook).

## `topics[]`

| Field | Type / default | Meaning |
|---|---|---|
| `id` | string, required | Unique per batch (JSON ints are coerced). Numeric ids are zero-padded to two digits in filenames (`'7'` → `07-slug.md`); non-numeric ids pass through verbatim. |
| `slug` | string, required | Kebab-case; with the id it forms the file stem `NN-slug` used by every stage. |
| `title` | string, required | Human title; also what the claude-prior baseline sees (title only, no sources). |
| `tier` | string, optional | Free-form classification label; informational only. |
| `high_stakes` | bool, `false` | Marks the topic for deeper checking: falsification and evaluation default **on** for this topic. |
| `research_prompt` | string, optional | One research prompt inherited by any research subsession that omits its own ([ADR-0008](adr/0008-research-prompt-templating.md)) — see resolution rules below. |
| `stages` | block, required | Per-stage entries — below. |

### `stages.claude` (required block)

`{ "prompt": … }`. The block itself is required even for Path B topics that
never run the Claude research stage — give it `"prompt": ""` (an explicit
empty string is a valid, kept prompt) or omit `prompt` and provide
`research_prompt`.

### `stages.openrouter[]` — one entry per research subsession

| Field | Default | Meaning |
|---|---|---|
| `subslug` | `'single'` | Kebab-case name; becomes the brief's filename under `…openrouter/<NN-slug>/<subslug>.md`, and the key `models.primary` / sidecar sources refer to. |
| `model` | `null` | A pinned OpenRouter id (`openai/gpt-5`) used verbatim, or the auto-latest policy: `'auto:<vendor>'` / `'latest:<vendor>'`, or `null`/`'auto'` with a separate `vendor` field. Auto resolution queries the live catalog and degrades to a pinned fallback offline. |
| `vendor` | `null` | Vendor for the auto policy when `model` doesn't encode it. Ignored for pinned ids. |
| `prompt` | `null` | This subsession's research prompt; `null` inherits `research_prompt`. |
| `web_search` | `false` | Attach OpenRouter's web plugin. (Sonar models: leave `false` — their search is built in; see the playbook's substrate quirks.) |
| `web_search_engine` | `null` (sent as `'native'`) | Which index the web plugin reads: `'native'`, `'exa'`, `'parallel'`, `'perplexity'` or `'firecrawl'`. Any other value fails validation. `mantis research` always sets it, giving each substrate its own index where it can; see [Search engines](#search-engines). |
| `web_search_max_results` | `5` | Search-result budget per call. |
| `reasoning_effort` | `null` | `'low'` \| `'medium'` \| `'high'` \| `'xhigh'` where the model supports it. |
| `max_tokens` | `null` | Response cap. |

#### Search engines

`web_search_engine` picks the index a substrate's web search reads. Two briefs
that cite the same pages are one source read twice, so a batch that wants
cross-model checking should give each substrate its own index
([ADR-0012](adr/0012-one-search-index-per-substrate.md)).

| Value | Reads | Price per search request (as of 2026-10-08) |
|---|---|---|
| `native` | The model provider's own search, where the model has it. Needs a model with native search: the OpenAI, Anthropic, xAI and Perplexity models, and Gemini 3.x (`auto:google` resolves to one). DeepSeek has none on any OpenRouter endpoint, and Gemini 2.5 and `:batch` variants have none. With the plugin, `native` on a model without native search may error. | Passed through from the provider. For Gemini 3.x that is Google Search grounding, $14 per 1,000 search queries after a 5,000/month free allowance; whether OpenRouter passes the allowance through is not documented, and one request may issue several queries. |
| `exa` | Exa. | $0.007 in the default `auto` mode, up to 10 results included. |
| `parallel` | Parallel. | $0.005 in the default `basic` mode, up to 10 results included. |
| `perplexity` | Perplexity. | $0.005. |
| `firecrawl` | Firecrawl. | Not billed by OpenRouter: bring-your-own-key, on Firecrawl credits (27 credits for 5 results). |

Prices and the engine list are from OpenRouter's
[web search documentation](https://openrouter.ai/docs/guides/features/plugins/web-search).
Google's native search does not support domain filters. Results come back in the
same `url_citation` annotation shape for every engine. On the regional endpoint
`us.openrouter.ai` only `exa` runs.

**What `mantis research` assigns.** It builds its substrate entries itself, with
[`core/search_engines.py`](../src/mantis_research/core/search_engines.py):

- A substrate whose vendor has native search (`openai`, `perplexity`,
  `anthropic`, `x-ai`, `google`) gets `native`.
- Every other vendor gets the next engine from the pool `parallel`, `exa`,
  `perplexity` that is not already assigned in the run. The `perplexity` engine
  is skipped when the `perplexity` vendor is also a substrate, since that
  vendor already reads Perplexity's index.
- When there are more such vendors than engines the pool wraps around, two
  substrates then share an index, and the run logs a warning naming them.

The default substrates `openai`, `deepseek` and `google` therefore get `native`,
`parallel` and `native`; `deepseek`, `qwen`, `openai` get `parallel`, `exa` and
`native`. The assignment is recorded as `search_engines` in the manifest,
`run.json` and the MCP result (a substrate with web search off is `null`, and so is one whose engine is unknown: a resumed run that began before the field existed, for a substrate that had already finished), and
`retrieval_overlap` reports how far the finished briefs' cited pages overlap.

A hand-written batch config is not touched: it keeps whatever it names, and an
entry with `web_search: true` and no engine is sent as `native`.

Avoid `auto:perplexity`:
[`interface/research_service.py`](../src/mantis_research/interface/research_service.py)
records that its pick (`sonar-pro-search`) 404s on the completions endpoint,
which is why `mantis research` leaves `perplexity` out of its default substrate
set. Pin a Sonar model explicitly instead — `perplexity/sonar-reasoning-pro` is
the one `core/model_policy.py` pins and the playbook's templates use, with
`web_search: false`. Provider slugs shift, so check OpenRouter's `/models` list
before committing a config.

### `stages.gemini[]` (legacy)

One entry per Gemini CLI subsession: `{ "subslug": …, "prompt": … }` with the
same prompt-inheritance rule. Kept for historical batches; new batches use
Gemini via OpenRouter (`auto:google`) instead.

### Optional stages: `synthesis`, `journal`, `journal_passes`, `falsification`, `evaluation`

Each accepts `{ "prompt": …, "enabled": … }`, both optional; which stages
honour `enabled` is noted per stage below.

- `synthesis` — always runs; `prompt: null` uses the default chain above. Its
  sidecar turn is not configurable per topic.
- `journal` — the synthesis's optional journal turn. `null`/`true` = on (the
  batch default, [ADR-0002](adr/0002-reposition-as-agent-researcher-tool.md));
  `false` = skipped, and the topic succeeds on the brief alone. One-shot
  `mantis research` runs default it off.
- `journal_passes` — augmentation over an existing journal. Like `synthesis`,
  its `enabled` flag is accepted by the schema but ignored: the stage runs for
  every topic in the config and blocks on topics whose first-pass journal is
  missing. Use `--only` to restrict it.
- `falsification` / `evaluation` — opt-in checking stages: an explicit
  `enabled` wins; unset follows `high_stakes`. Evaluation additionally needs
  the claude-prior baseline on disk (its Gate 3 input).

### Research-prompt resolution (ADR-0008)

Resolution keys on **presence**, never truthiness: an explicitly-set prompt —
including the empty string — is kept as-is; only an omitted (`null`) prompt
falls back to the topic's `research_prompt`. A subsession with no prompt and
no `research_prompt` fails at load time, naming the topic and subsession.

## Minimal Path B example

```json
{
  "schema_version": 2,
  "batch_name": "my-batch",
  "runner": { "layout": "batch" },
  "models": { "claude": {}, "primary": "openrouter:openai" },
  "topics": [
    {
      "id": "1",
      "slug": "my-topic",
      "title": "My topic, stated as a question",
      "research_prompt": "Research …; cite primary sources.",
      "stages": {
        "claude": { "prompt": "" },
        "openrouter": [
          { "subslug": "openai", "model": "auto:openai", "web_search": true },
          { "subslug": "deepseek", "model": "auto:deepseek", "web_search": true, "web_search_engine": "parallel" },
          { "subslug": "google", "model": "auto:google", "web_search": true, "web_search_engine": "native" }
        ],
        "journal": { "enabled": false }
      }
    }
  ]
}
```

Validate it without spending anything:

```bash
uv run mantis run openrouter config/my-batch.json --dry-run
```
