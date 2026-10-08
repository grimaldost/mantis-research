# ADR-0012 — Each research substrate reads its own web-search index

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

The tool's value is cross-model checking: several models answer one question,
and the synthesis weighs their agreement and disagreement (ADR-0002). That only
counts when the models read different evidence. Models that retrieve the same
pages agree because they were shown the same pages, and the synthesis reads
that agreement as independent confirmation.

Field evidence, 2026-10-07: across 16 research-tier runs, DeepSeek and Google
both searched through OpenRouter's `exa` engine, and in 10 of the 16 they cited
exactly the same pages. Three "independent checks" were two. The cause was a
default in `_substrate_entry`: every vendor outside a short native-search set
(`openai`, `perplexity`, `anthropic`, `x-ai`) was sent to `exa`, and `google`
was not in the set, although `auto:google` resolves to a Gemini 3.x model that
has native Google Search on OpenRouter.

Nothing in the tool's output showed this. The Jaccard overlap of the briefs'
cited URLs was computed only inside the synthesis prompt
(`core/retrieval_overlap.py`), never for the `research` tier, which has no
synthesis, and was never recorded.

OpenRouter's web plugin accepts the engines `native`, `exa`, `firecrawl`,
`parallel` and `perplexity` (checked 2026-10-08 against OpenRouter's web-search
documentation and the live `native_tools` field of the endpoints API):

| Engine | Price per search request | Note |
|---|---|---|
| `exa` | $0.007 (default `auto` mode) | up to 10 results included |
| `parallel` | $0.005 (default `basic` mode) | up to 10 results included |
| `perplexity` | $0.005 | |
| `firecrawl` | not billed by OpenRouter | bring-your-own-key, 27 Firecrawl credits for 5 results |
| `native` | passed through from the provider | for Gemini 3.x, Google Search grounding at $14 per 1,000 queries after a 5,000/month free allowance; whether OpenRouter passes the allowance through is undocumented, and one request may issue several queries |

DeepSeek has no native search on any OpenRouter endpoint. Gemini 2.5 models and
`:batch` variants have none either.

## Decision

**Each substrate of a `mantis research` run reads a different web-search index
wherever the engines allow it, and the run records which.**

- The assignment is a pure function in `core/search_engines.py`. A vendor with
  native search (`openai`, `perplexity`, `anthropic`, `x-ai`, and now `google`)
  gets `native`. Every other vendor gets the next engine from the pool
  `parallel`, `exa`, `perplexity` not already assigned in the run, skipping an
  engine whose index a native vendor in the set already reads (the `perplexity`
  engine, when the `perplexity` vendor is a substrate). When the pool runs out
  it wraps, two substrates then share an index, and the run logs a warning
  naming them. The default set `openai`, `deepseek`, `google` becomes `native`,
  `parallel`, `native`.
- `web_search_engine` becomes a declared, validated field of
  `OpenRouterSubsessionConfig` (`native`, `exa`, `parallel`, `perplexity`,
  `firecrawl`). Until now it rode through as an unvalidated extra, so a typo
  silently reached the API. An entry that omits it is still sent as `native`.
- The engine each brief used is recorded as `search_engines`
  (`{subslug: engine}`, `null` where web search is off, or where the engine is unknown: a resumed run that began before the field existed, for a substrate that had already finished), in every `run.json`
  write, the manifest, and the MCP result.
- The overlap is measured from the tool's own output. The manifest, `run.json`
  and the MCP result carry `retrieval_overlap`: `null` when fewer than two
  briefs are on disk (every dry run), otherwise the Jaccard overlap of each
  pair's cited URLs and the maximum. It uses the same pure functions as the
  synthesis prompt; reading the brief files happens in the interface layer.

Hand-written batch configs are not rewritten: they keep the engine they name.

## Alternatives considered

- **Leave the engines and only measure the overlap.** The measurement is part of
  this decision, but alone it reports the problem after the research is paid
  for. The cheaper fix is to not create it.
- **Put Google on an OpenRouter engine different from DeepSeek's.** Also yields
  distinct indexes, and works for Gemini models without native search. Rejected
  as the default because it adds a third party's index where the model's own
  provider index is available, and because the point of the native set is that
  the provider's retrieval is what that model was built around. The pool still
  serves any vendor outside the set.
- **Use `firecrawl` as a default engine.** It is bring-your-own-key, which would
  make a fresh install fail on a credential it has no reason to hold. It stays
  selectable in a hand-written config.
- **Add substrates until the indexes differ.** Costs a whole model call per
  substrate to fix a retrieval choice.

## Consequences

- **Cost changes, and not uniformly.** DeepSeek's search drops from $0.007 to
  $0.005 per request. Google's moves from $0.007 per request to Google Search
  grounding at $14 per 1,000 queries ($0.014 each), with a free allowance that
  OpenRouter may or may not pass through, and a request can issue several
  queries. For the default set the search line can therefore rise, by an amount
  that depends on how many queries Gemini issues. It is small next to the model
  tokens of a research brief, but it is not zero, and it is unmeasured.
- **New invariant.** The default substrate set reads one index per substrate; a
  shared index is a logged warning, never silent. A change to the default set or
  to the native set updates `core/search_engines.py` and its tests together.
- Google's native search does not support domain filters. Nothing here uses
  them.
- Native search needs a model that has it. If `auto:google` ever resolves to a
  model without native search (a Gemini 2.5 model, a `:batch` variant), the
  `native` request may error. The model policy currently resolves, online and in
  its offline table, to `google/gemini-3.1-pro-preview`.
- On the regional endpoint `us.openrouter.ai` only `exa` runs, so a deployment
  pinned there cannot follow this assignment.
- Different engines are not proof of different evidence: two engines can still
  surface the same pages. `retrieval_overlap` is how that is seen, and the
  assignment should be re-judged against it once enough runs carry the field.
- The new keys are additive on every persisted surface (I4): `search_engines`
  and `retrieval_overlap` are new keys in `run.json`, the manifest and the MCP
  result. Records written before them read `search_engines` as `null`, meaning
  unknown. Old state trees are untouched (I6). `web_search_engine` is not
  additive: it was accepted as an extra and is now validated against the five
  engines, so a config naming anything else must correct it.
