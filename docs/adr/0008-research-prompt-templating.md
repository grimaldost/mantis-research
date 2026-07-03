# ADR-0008 — Research-prompt templating in the config schema

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

Every research subsession carries its full prompt verbatim in the config. In
multi-substrate batches the same ~6 KB prompt is repeated once per substrate
(7× in a seven-substrate batch), and the per-batch
builder scripts under `scripts/_build_batch_*.py` exist largely to generate
that duplication. A request-level entry point (ADR-0004) needs to expand one
question into N substrate prompts programmatically anyway. Asymmetric
prompting (mantis/router-hijack framing stripped from secondary substrates) is
established practice and must remain expressible.

## Decision

Add an optional per-topic `research_prompt` field. A research subsession
(openrouter entry, and the claude stage prompt) may omit its `prompt`; it then
falls back to the topic's `research_prompt`. An explicit per-subsession
`prompt` always wins — that is how asymmetric prompting is expressed, exactly
as today. Config validation fails at load when a subsession has neither its
own prompt nor a topic `research_prompt` (fail-fast, I4-additive: all existing
configs carry explicit prompts and validate unchanged). `mantis research`
authors configs through this field.

## Alternatives considered

- **Keep builder scripts as the templating layer** — rejected: authoring a
  batch should not require writing a Python script; the duplication lands in
  committed configs where it drifts.
- **Substrate-strip rules as code** (runner rewrites one rich prompt per
  substrate) — rejected for now: the asymmetry policy is editorial judgment
  that differs per batch; encoding it as transforms would hide prompt content
  from the config. Explicit override remains the mechanism; revisit if a
  stable strip-rule set emerges.
- **Jinja-style templating inside prompts** — rejected: `.format()`
  placeholders already cover path/size substitution; a template language adds
  an escaping regime to every prompt author's load.

## Consequences

Multi-substrate configs shrink to one prompt + N thin entries; builder scripts
become optional conveniences. Precedence (subsession > topic default) is one
rule, tested at config load. The evaluation/falsification/synthesis default
prompts are unaffected (they already have the `default_prompts` fallback
chain).
