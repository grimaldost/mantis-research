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
| `web_search_engine` | `'native'` | `'native'` where the provider supports it (OpenAI / Anthropic / xAI / Perplexity), otherwise OpenRouter routes to `'exa'`. |
| `web_search_max_results` | `5` | Search-result budget per call. |
| `reasoning_effort` | `null` | `'low'` \| `'medium'` \| `'high'` \| `'xhigh'` where the model supports it. |
| `max_tokens` | `null` | Response cap. |

### `stages.gemini[]` (legacy)

One entry per Gemini CLI subsession: `{ "subslug": …, "prompt": … }` with the
same prompt-inheritance rule. Kept for historical batches; new batches use
Gemini via OpenRouter (`auto:google`) instead.

### Optional stages: `synthesis`, `journal`, `journal_passes`, `falsification`, `evaluation`

Each is `{ "prompt": …, "enabled": … }`, both optional.

- `synthesis` — always runs; `prompt: null` uses the default chain above. Its
  sidecar turn is not configurable per topic.
- `journal` — the synthesis's optional journal turn. `null`/`true` = on (the
  batch default, [ADR-0002](adr/0002-reposition-as-agent-researcher-tool.md));
  `false` = skipped, and the topic succeeds on the brief alone. One-shot
  `mantis research` runs default it off.
- `journal_passes` — augmentation over an existing journal; blocks until the
  journal artifact exists.
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
          { "subslug": "deepseek", "model": "auto:deepseek", "web_search": true, "web_search_engine": "exa" },
          { "subslug": "google", "model": "auto:google", "web_search": true, "web_search_engine": "exa" }
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
