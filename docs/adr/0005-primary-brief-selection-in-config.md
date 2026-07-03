# ADR-0005 — Primary-brief selection in config (Path B native)

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

The synthesis stage hard-assumes the primary brief is Claude's: its upstream
gate requires a file in the Claude output directory and its prompt variables
are named `{claude_path}` / `{claude_size_kb}`. The evidence-based default
pipeline is Path B (`prompts/playbooks/research-path-recommendation.md`): 4
OpenRouter substrates, no Claude research, one OR brief promoted to primary.
Today Path B works only by running `scripts/_promote_or_to_primary.py` to copy
an OR brief into the Claude directory and restore it afterwards — a
file-shuffling workaround that mutates the output tree and that no agent
caller (ADR-0004) can be expected to run.

## Decision

Primary selection becomes config: a `models.primary` field (optional string).
`'claude'` — the default, preserving today's behavior — selects the Claude
brief; `'openrouter:<subslug>'` selects that OR subsession's brief as primary,
with all remaining briefs (including Claude's, when present) as secondaries.
The synthesis stage resolves paths accordingly and its upstream gate requires
"primary brief exists + ≥1 secondary brief exists". Prompt formatting gains
`{primary_path}` / `{primary_size_kb}` / `{primary_label}`; the legacy
`{claude_path}` / `{claude_size_kb}` keys are kept as aliases bound to the
primary, so every existing template keeps working. The promote/restore script
is deprecated in place (docstring pointer), not deleted.

## Alternatives considered

- **Keep the promote/restore scripts** — rejected: mutates data trees to fake
  a config condition (Axiom-4 violation — untracked, reversible-by-hand
  change), unusable from a one-shot entry point.
- **Symlink the OR brief into the Claude dir** — rejected: same masquerade
  with extra Windows-permissions fragility.
- **Per-topic primary override in `stages.synthesis`** — deferred: batch-level
  primary covers every observed use; per-topic adds schema surface with no
  current consumer. Revisit if a mixed-path batch materializes.

## Consequences

Path B becomes a config line; the output tree is never mutated to satisfy a
gate. Config schema change is additive (I4): absent field = today's behavior.
Synthesis templates gain clearer variable names without breaking old ones.
`mantis research` defaults to an OR primary per the Path B recommendation.
