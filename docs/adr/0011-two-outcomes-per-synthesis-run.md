# ADR-0011 — A synthesis run reports two outcomes, not one

- **Status:** Accepted
- **Date:** 2026-09-13

## Context

Five dogfooding reports between 2026-08-30 and 2026-09-12 describe one shape:
**paid, complete work reported as a failed run.** The synthesis document is on
disk, 45–63 KB, ending in a proper conclusion; the run says `ok: false` and
`synthesis.exit_code: 1`, the pipeline stops before falsification, and the
retry regenerates the document it already had. The triage
(`2026-09-13-triage-mantis-research-delta-2`) grounded four distinct mechanisms
behind that one shape, and they compound:

1. `interface/adapters/_subprocess.py:119` reads the local-seat child with
   `process.stdout.readline()` and no `limit=` override, so
   `asyncio.StreamReader`'s 64 KiB default line cap raises
   `ValueError('Separator is found, but chunk is longer than limit')` on one
   long line — reproduced 2/2, then 7/7 at scale, always *after* three research
   briefs and a full synthesis are paid for.
2. That `ValueError` is deterministic, and nothing classifies it: it reaches
   `Orchestrator._retry_loop`'s `except Exception` as a `GENERIC` failure and
   buys three attempts into an unchanged environment.
3. It also escapes `SynthesisStage.run_attempt` *between* the adapter call and
   `state.synthesis_bytes = …`, so the idempotence guard
   `need_brief = not (synthesis_path.exists() and state.synthesis_bytes)` never
   learns that Turn 1 produced its document. The next attempt regenerates the
   synthesis — which is the byte-level evidence the field filed
   (60,542 B → 57,271 B, 11 sections → 14).
4. Independently of all three, the sidecar turn's failure is the *whole*
   attempt's failure: `run_attempt` returns one `AttemptResult` for Turn 1 and
   the sidecar loop together, so a synthesis that finished cleanly is recorded
   as a failed stage.

ADR-0003 makes the sidecar the product, and ADR-0009's serving path refuses a
run that owed a sidecar and has none. Neither says the *synthesis document*
stops existing when its derived artifact fails to.

## Decision

**A synthesis attempt has two outcomes, and the code says so.** The attempt's
success is whether the synthesis document (and the journal, when enabled) was
produced. The epistemic sidecar carries its own outcome — `ok` or `failed` with
a reason — recorded on the stage's state, surfaced on the run manifest as a
`sidecar` block, and passed through the MCP result. A failed sidecar is a named
degraded outcome on a successful run; it no longer fails the stage, stops the
pipeline, or marks the topic `FAILED`.

Three supporting rules follow from the same reading:

- **"Did this run deliver an answer" has one producer.** `ok` no longer answers
  it, so every surface that used to read `ok` for it must read the same new
  judgement instead: `research_service.missing_product` returns the reason a run
  owes a sidecar it does not have, or `None`. The MCP tool builds its
  `IncompleteRunError` blame line from it and `mantis research` derives its exit
  code from it. A per-surface copy of the test is what drifts — and did, within
  this very change: the first cut reconciled the MCP path and left the CLI
  exiting 0 over a manifest that path refuses.

- **What an attempt produced is observed, not assigned.** Turn 1's product is
  recorded from disk in a `finally`, against a fingerprint taken before the
  call, so a turn that ends by raising cannot skip the bookkeeping that makes
  the retry idempotent.
- **The published sidecar path is written once, by the runner, atomically.**
  The model writes a `.sidecar.draft.json`; the runner validates it, merges the
  runner-authored zone, and renames the merged document into place. No reader
  ever observes the model's draft — with `sources: []` and `provenance: {}` —
  at the path that means "finished".

## Alternatives considered

- **Keep one outcome and widen the sidecar's re-ask budget.** Treats the
  symptom: a sidecar can fail for reasons no re-ask fixes (schema drift, a
  malformed response, a runner-side gap), and every one of them would still
  convert a complete synthesis into a failed run.
- **Drop `IncompleteRunError` so the MCP path returns a briefs-only run.**
  Rejected: that refusal is ADR-0003 + ADR-0009's shipped decision, grounded in
  its own field incident, and is about a sidecar that is *absent*. This ADR
  changes which outcome `ok` reports, not whether a missing product is refused.
- **Make the guard `synthesis_path.exists()` alone.** Simpler, and it breaks
  invariant I5: `--force` clears state but not outputs, so Turn 1 would be
  skipped exactly when a regeneration was asked for.
- **Temp-name + rename only the runner's own write.** Does not fix the reported
  hazard: the partial document at the published path is the *model's* draft,
  written there before the runner ever reads it.

## Consequences

- **New invariant.** A derived artifact's failure is reported on its own axis;
  it never retracts an artifact that was produced. Later stages that add
  derived outputs follow the same shape.
- **A second invariant, learned the hard way in this change.** Every surface
  that reports whether a run delivered an answer reads `missing_product`, and a
  test asserts they agree. Changing what a widely-read field means obliges you
  to find every reader of it — and the cheapest way to keep that true later is a
  cross-surface test rather than care.
- `mantis research` gains exit code **3**: the stages passed and the sidecar
  they owed is missing. 1 keeps meaning "a stage failed", because scripts key on
  it and because `ok` is genuinely true in the new case.
- `SynthesisState` gains `sidecar_status` / `sidecar_error` (additive optional,
  I4). Historical state files read as "unknown", which is what they are.
- The MCP result gains a `sidecar` block (additive, ADR-0009). A caller that
  ignores it sees exactly what it saw before.
- A run whose sidecar failed now continues into falsification and is resumable
  *at the sidecar*, not at the synthesis — the expensive turn is no longer
  re-bought to retry a cheap one.
- Raising the stream limit is a ceiling, not a proof: a line above the new
  16 MiB limit still raises, so the classification in rule 2 stays load-bearing.

## Implementation shape

One PR; per `docs/specs/README.md` a single-PR change takes an ADR rather than
a spec, and the spec machinery's Definition-of-Ready expects a non-author
pre-mortem certification this wave does not have. Rows are the triage's.

| Row | Shape | Home |
|---|---|---|
| T14a | Pass an explicit 16 MiB `limit=` to `create_subprocess_exec`; contract test feeds a 200 KB single line through the real consumer | `interface/adapters/_subprocess.py` |
| T15a | `classify_failure` recognises asyncio's own stream-limit texts as `PRECONDITION`; the orchestrator's unexpected-exception path carries the exception text into `error_output` so the classifier can see it | `core/retry.py`, `interface/orchestrator.py` |
| T15b | Fingerprint the synthesis path before Turn 1; record what is on disk in a `finally`, only when it changed | `interface/stages/synthesis.py` |
| T16a | Sidecar outcome recorded on state, surfaced on the manifest and the MCP result; the attempt no longer fails on it. `missing_product` is the one producer of the completeness judgement both surfaces read, and `mantis research` exits 3 when the stages passed without it | `interface/stages/synthesis.py`, `core/state.py`, `core/sidecar.py`, `interface/research_service.py`, `interface/mcp/server.py`, `interface/cli/research.py` |
| T16b | Model writes `<stem>.sidecar.draft.json`; the runner renames the merged document onto `<stem>.sidecar.json` | `interface/stages/synthesis.py` |

Out of this wave, and unchanged: T25a (prompt provenance), T26a (`SKILL.md`
turn count), and every row the triage holds at `watch`.
