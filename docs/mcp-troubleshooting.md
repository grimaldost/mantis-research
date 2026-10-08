# MCP troubleshooting

What goes wrong when an agent calls the `research` tool, how much of it came
from this code and how much from the machine it runs on, and the checks that
tell the two apart. The tool itself is described in the
[README](../README.md) (§ Serve to agents) and in
[skills/research/SKILL.md](../skills/research/SKILL.md).

## Field error classes

Between 2026-07-26 and 2026-09-26 agents made 37 `research` calls and 15 of
them ended in a tool error. Each error was reconciled three ways: the field
records, the session transcripts, and Claude Code's own client-side MCP logs.

| Class | Errors | Version in use | Cause | Kind | Fixed in |
|---|---|---|---|---|---|
| Client abort: no progress for 1800 s | 5 | 0.1.2 | The handler sent no notification of any kind while the run worked. | Code | 0.2.0: run events bridged to progress notifications. |
| Client abort: no progress for 1800 s | 9 | 0.3.0 | Progress stopped once research finished; the local-seat phase sent nothing. | Code | 0.4.0: `detach`, and seat-wait and `thinking` events. 0.6.0: seat tiers detach by default. 0.7.0: every event sent as progress, and a keepalive on blocking calls. |
| `run X is still owned by a live process (pid N)` on a resume | 1 | 0.4.0 | The resume named a run that the same server process was still running. | Code | 0.7.0: the resume answers with the run's handle. |

All 15 errors were code faults. None was an environment fault, but the
environment can produce the same symptoms, so the checks in
[Environment checks](#environment-checks) are worth running first when a call
fails on a machine that has not run the tool before:

| Environment cause | What it looks like |
|---|---|
| The local Claude seat is not signed in | A seat tier is refused before anything is dispatched, naming the seat. |
| The plugin's virtualenv is damaged | The server does not start; the client reports that the MCP server failed to connect. |

## The client's idle limit

Claude Code (checked in client 2.1.291) aborts a tool call when it has received
no progress notification for 1800 s. It checks every 30 s. Only a progress
notification resets the clock (an elicitation does too, but this server sends
none). A log notification does not: a server that reports only through
`ctx.info` looks idle to the client however much it writes.

Since 0.7.0 the server keeps a blocking call's clock reset in two ways:

- Every run event goes out as a progress notification, not only the events that
  advance a stage. A step that advances is sent as itself, so `progress / total`
  still reads as stages done out of stages planned; any other event (a
  `thinking` line, a seat `waiting` tick, a backoff heartbeat, a substrate
  starting or finishing) is sent as a value between the last step and the next.
  No value passes `total`, which only the end of the run reaches. The log line
  is still sent as well.
- While a blocking call waits for its run, a keepalive progress notification
  goes out every 60 s, reading `still running: <last event> (<elapsed> s)`. This
  covers the phases that emit nothing at all, such as the sidecar turn or a
  child process that has stopped printing.

A call blocks when its tier is `research`, when it is a dry run or a collect,
or when it passes `detach=false`; `detach=true` detaches any call but a collect.
A detached call returns at once and is not exposed to the limit.

## Calls in one message run one after another

Claude Code runs MCP tool calls that do not declare `readOnlyHint` one after
another when they are issued in the same assistant message. Neither `research`
nor `research_status` declares it. Three `research` calls in one message
therefore run in sequence, and the latency measured from the message for the
third includes the time spent waiting for the first two. Read latency figures
from a single call's own start and end.

## A tool error rate measures the transport

A tool-call error says the call failed, not that the research did. Since
0.6.0, a seat-tier call detaches by default and returns a handle within seconds,
and counts as a success whatever the run does afterwards. A run that fails later shows up in
`research_status` and in the run's `run.json` (`ok`, the per-stage `exit_code`s,
`sidecar.status`), not as a tool error. To measure outcomes, read the run
records, not the tool-call results.

## Collecting a run

Collect when `research_status` reports `state: "finished"`, then call `research`
with `resume=<outputs_dir>`. Do not collect because files have appeared in the
run directory: a sidecar file written by a failed attempt can be on disk before
the stage it belongs to has settled, and reading it then can hand back the
output of an attempt that failed.

A resume of a run that this same server is still running returns
`state: "running"` with the run's `outputs_dir`, `batch_name`, `current_stage`
and `stages`, and a `note` saying to poll `research_status` until the run is
finished. It is not an error. A resume of a run owned by another live process,
such as a CLI run or a different server, is still refused: two owners over one
state tree would corrupt it.

## Environment checks

Each check below is read-only unless it says otherwise.

**The local Claude seat.** The synthesis-family stages drive the local `claude`
CLI. Check that it is signed in:

```bash
claude auth status
```

**The plugin's virtualenv.** The plugin launches the server with
`uv run --project <plugin dir>`, where `<plugin dir>` is
`~/.claude/plugins/cache/mantis-research/mantis-research/<version>`. Check that
its virtualenv can import what the server needs. On Windows:

```bash
"<plugin dir>/.venv/Scripts/python.exe" -c "import typing_extensions, yaml, certifi, mcp; print('ok')"
```

On Linux and macOS the interpreter is `<plugin dir>/.venv/bin/python`. If the
import fails, delete `<plugin dir>/.venv`; the next launch of the plugin
recreates it through `uv run --project`. Deleting it removes nothing but the
installed packages.

**The client's MCP logs.** Claude Code writes a log per MCP server. On Windows
the logs for this plugin are under:

```text
%LOCALAPPDATA%\claude-cli-nodejs\Cache\*\mcp-logs-plugin-mantis-research-mantis-research\
```

To find the calls the client gave up on for want of progress, from Git Bash:

```bash
grep -r "aborting: no response or progress notification" \
  "$LOCALAPPDATA"/claude-cli-nodejs/Cache/*/mcp-logs-plugin-mantis-research-mantis-research/
```

or from PowerShell:

```powershell
Select-String -Pattern 'aborting: no response or progress notification' `
  -Path "$env:LOCALAPPDATA\claude-cli-nodejs\Cache\*\mcp-logs-plugin-mantis-research-mantis-research\*"
```

From 0.7.0 a blocking call sends progress at least every 60 s, so a match on a
call made with 0.7.0 or later means the notifications did not reach the client
(for example, a server process that died or stopped responding), not that the
run was quiet.
