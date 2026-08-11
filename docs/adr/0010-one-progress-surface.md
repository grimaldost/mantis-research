# ADR-0010 — One progress surface: `mantis status` folds into `mantis monitor`

- **Status:** Accepted
- **Date:** 2026-08-11

## Context

Two commands reported run progress. `mantis monitor <stage>` followed one
stage's `progress.json`, emitting a line per transition. `mantis status
<config>` printed a cross-stage table for a batch and exited. They served the
same job — *what is this run doing* — split by shape rather than by question,
and a caller had to know both to get either answer.

Both are batch-mode surfaces, and batch mode has no live consumers: all 19 runs
on disk are single-question request-level runs. Two commands is twice the
surface to keep true for a path nothing currently walks, and the cross-project
consistency pass asks for one command shape across these tools rather than a
new one per capability.

## Decision

Fold the snapshot into the follower as its one-shot mode:

- `mantis monitor <stage>` follows, unchanged.
- `mantis monitor --snapshot <config>` prints the cross-stage table once and
  exits.
- `mantis status` is removed. Its module moves from `interface/cli/status.py` to
  `interface/cli/snapshot.py`, and `status_cmd` becomes `print_snapshot`, called
  by `monitor_cmd`.

`mantis monitor` with neither a stage nor `--snapshot` exits 2 with a message
naming both, so the missing command is discoverable from the place it used to
be typed.

## Alternatives considered

- **Keep both and cross-reference them in `--help`** — rejected: the cost is not
  discoverability, it is two surfaces to keep true. Prose pointing between them
  adds a third thing to keep true.
- **Delete the snapshot outright** — rejected: it is the only cross-stage view
  there is, and batch mode is documented as a secondary path rather than a dead
  one. Removing capability was not the point; removing a duplicate entry point
  was.
- **Make `--snapshot` a boolean and reuse the stage positional for the config
  path** — rejected: one positional meaning two different kinds of thing is how
  a CLI becomes unguessable.

## Consequences

There is one progress surface. Any script or habit invoking `mantis status
<config>` breaks loudly with an unknown-command error rather than silently, and
the replacement is one flag away. The `STAGES` table in `snapshot.py` remains
the one place that enumerates stages for reporting, so a stage retirement
touches it once.
