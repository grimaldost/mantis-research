# series.toml (convoy)

The series config for [convoy](https://github.com/grimaldost/convoy), the multi-PR
execution engine, run as `convoy run series.toml`. Convoy owns the authoritative
schema and is a v1 engine under active development — check its repo for the
current field set; this note only sketches the shape, it does not restate it.

A `series.toml` describes a **DAG of PR-sized tasks**. Convoy loads and validates
the spec, orders the PRs by their `depends_on` edges, spawns a coding agent per
`[[pr]]` (each carrying its `model`) under the `[governance]` literals, runs each
result through the gate (ruff · type-check · pytest), integrates the branch, and
records per-spawn economy to `spawns.jsonl`.

```toml
[series]
# series-level identity + config (convoy owns the exact fields)

# One [[pr]] per PR-sized task; convoy orders them by the dependency DAG.
[[pr]]
model = "<coding-agent model for this task>"
depends_on = []        # PR entries this one waits on ([] = no upstream)
independent = true     # may land without integrating siblings first

# v1 spawn governance — convoy reads these as fixed literals per spawn.
[governance]
permission = "<spawn permission mode>"
effort     = "<reasoning effort>"
budget     = "<per-spawn cost cap>"
tools      = ["<allowed tools>"]
timeout    = "<per-spawn timeout>"
```

Convoy's exit taxonomy: `0` integrated · `N1` blocking failure · `N2`
infrastructure halt · `N3` usage error.

**Budget note:** in convoy the cost cap is a per-spawn `[governance]` field, so the
wave-level budget the method once tracked in a separate `[budget]` table is now the
orchestrator's own concern. Without an orchestrator, the series table still serves
as a manual checklist.
