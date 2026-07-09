# Feedback reports

Per-session dogfooding reports for this tool: what worked, friction, misses
(with the phase that should have caught them), and proposed changes with
severity tags. Reports are the raw input to periodic triage, which clusters
findings by underlying cause and promotes recurring ones into durable changes.
The reports themselves are append-only history.

Conventions:

- One file per session or wave: `YYYY-MM-DD-<source-slug>.md`, with a distinct
  slug per wave so later reports never clobber earlier ones.
- `INDEX.md` is generated (`build_feedback_index.py <dir>`, from the feedback
  tooling) — do not hand-edit it. Grep it for an existing finding before
  restating one; extend by reference instead.
- Run a triage pass once ~8–10 un-triaged reports accumulate, or after any
  multi-report wave.
