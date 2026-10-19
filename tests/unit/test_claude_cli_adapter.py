"""Unit tests for ClaudeCliAdapter — cmd assembly + dry-run flow."""

from __future__ import annotations

from pathlib import Path

import pytest

from mantis_research.core.cli_stream import ClaudeOutputFormat
from mantis_research.interface.adapters.claude_cli import (
    ClaudeCliAdapter,
    ClaudeCliOptions,
)


class TestCmdAssembly:
    def test_basic_session_cmd(self) -> None:
        adapter = ClaudeCliAdapter(binary='/fake/claude')
        opts = ClaudeCliOptions(model='claude-opus-4-7', session_id='sess-1')
        cmd = adapter._build_cmd('hello prompt', opts, 'sess-1')

        # Required components present in order.
        assert cmd[0] == '/fake/claude'
        assert cmd[1] == '-p'
        assert '--session-id' in cmd
        assert 'sess-1' in cmd
        assert '--model' in cmd
        assert 'claude-opus-4-7' in cmd
        assert '--effort' in cmd
        assert 'max' in cmd  # default effort
        # Adjacent pair, not membership: `'text' in cmd` also passes when any
        # unrelated argv element happens to equal 'text'.
        fmt = cmd.index('--output-format')
        assert cmd[fmt + 1] == 'stream-json'
        assert '--verbose' in cmd  # the CLI refuses stream-json without it
        # Prompt is the last arg, after the `--` terminator.
        assert cmd[-2] == '--'
        assert cmd[-1] == 'hello prompt'

    def test_resume_uses_resume_flag_not_session_id(self) -> None:
        adapter = ClaudeCliAdapter(binary='/fake/claude')
        opts = ClaudeCliOptions(model='c', resume_session_id='resume-abc')
        cmd = adapter._build_cmd('p', opts, 'unused-new-id')

        assert '--resume' in cmd
        assert 'resume-abc' in cmd
        assert '--session-id' not in cmd

    def test_allowed_tools_packed_as_csv(self) -> None:
        adapter = ClaudeCliAdapter(binary='/fake/claude')
        opts = ClaudeCliOptions(
            model='c',
            allowed_tools=('WebSearch', 'WebFetch', 'Write', 'Read'),
            session_id='s',
        )
        cmd = adapter._build_cmd('p', opts, 's')

        idx = cmd.index('--allowedTools')
        assert cmd[idx + 1] == 'WebSearch,WebFetch,Write,Read'

    def test_add_dirs_emitted_per_directory(self, tmp_path: Path) -> None:
        adapter = ClaudeCliAdapter(binary='/fake/claude')
        d1, d2 = tmp_path / 'a', tmp_path / 'b'
        opts = ClaudeCliOptions(
            model='c',
            add_dirs=(d1, d2),
            session_id='s',
        )
        cmd = adapter._build_cmd('p', opts, 's')

        # Two --add-dir occurrences, each followed by the dir.
        adds = [(i, cmd[i + 1]) for i, x in enumerate(cmd) if x == '--add-dir']
        assert len(adds) == 2
        assert adds[0][1] == str(d1)
        assert adds[1][1] == str(d2)

    def test_append_system_prompt_added_when_set(self) -> None:
        adapter = ClaudeCliAdapter(binary='/fake/claude')
        opts = ClaudeCliOptions(
            model='c',
            append_system_prompt='save to X',
            session_id='s',
        )
        cmd = adapter._build_cmd('p', opts, 's')

        idx = cmd.index('--append-system-prompt')
        assert cmd[idx + 1] == 'save to X'

    def test_name_emitted_when_set(self) -> None:
        adapter = ClaudeCliAdapter(binary='/fake/claude')
        opts = ClaudeCliOptions(model='c', name='research-topic-1', session_id='s')
        cmd = adapter._build_cmd('p', opts, 's')

        idx = cmd.index('--name')
        assert cmd[idx + 1] == 'research-topic-1'

    def test_extra_args_appended_before_prompt(self) -> None:
        adapter = ClaudeCliAdapter(binary='/fake/claude')
        opts = ClaudeCliOptions(
            model='c',
            extra_args=('--custom-flag', 'value'),
            session_id='s',
        )
        cmd = adapter._build_cmd('p', opts, 's')

        # Custom args are before the `--` separator and the prompt.
        idx = cmd.index('--custom-flag')
        assert cmd[idx + 1] == 'value'
        assert cmd.index('--') > idx

    def test_session_id_auto_generated_when_options_id_missing(self) -> None:
        adapter = ClaudeCliAdapter(binary='/fake/claude')
        opts = ClaudeCliOptions(model='c', session_id=None)
        # _build_cmd takes the session_id explicitly — caller (run()) generates uuid
        cmd = adapter._build_cmd('p', opts, 'auto-generated')
        assert 'auto-generated' in cmd


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_writes_marker_and_succeeds(self, tmp_path: Path) -> None:
        adapter = ClaudeCliAdapter(binary='/fake/claude')
        transcript_path = tmp_path / 'tx.log'
        opts = ClaudeCliOptions(model='c', session_id='s')

        result = await adapter.run('hello', opts, transcript_path, dry_run=True)

        assert result.success is True
        assert result.exit_code == 0
        assert result.duration_s == 0.0
        # Transcript was created with a DRY RUN marker.
        assert transcript_path.exists()
        assert 'DRY RUN' in transcript_path.read_text(encoding='utf-8')


class TestTheFormatAndTheWatchdogAgree:
    """MANT-B58 — the pair that drifted apart is now checked where it is built.

    The adapter asked for `text` (which emits nothing until the turn ends) and
    the stage set a 600 s watchdog on silence. Neither setting knew about the
    other, so the watchdog became a cap on total runtime and killed 66 of the
    237 local-seat stages this tool has historically completed.
    """

    def test_the_default_format_streams(self) -> None:
        assert ClaudeCliOptions(model='c').output_format is ClaudeOutputFormat.STREAM_JSON

    def test_a_mute_format_beside_a_watchdog_is_refused(self) -> None:
        with pytest.raises(ValueError, match='silence'):
            ClaudeCliOptions(
                model='c',
                output_format=ClaudeOutputFormat.TEXT,
                idle_timeout_s=600.0,
            )

    def test_a_mute_format_with_no_watchdog_is_allowed(self) -> None:
        opts = ClaudeCliOptions(
            model='c', output_format=ClaudeOutputFormat.TEXT, idle_timeout_s=None
        )
        assert opts.output_format is ClaudeOutputFormat.TEXT

    def test_a_text_run_does_not_ask_for_verbose(self) -> None:
        adapter = ClaudeCliAdapter(binary='/fake/claude')
        opts = ClaudeCliOptions(
            model='c',
            session_id='s',
            output_format=ClaudeOutputFormat.TEXT,
            idle_timeout_s=None,
        )
        assert '--verbose' not in adapter._build_cmd('p', opts, 's')


class TestWhatTheStageIsGivenToClassify:
    """The envelope must not reach the rate-limit classifier (MANT-B58).

    `RATE_LIMIT_PATTERNS` matches the substring `rate_limit`, and a healthy
    stream-json turn emits `{"type": "rate_limit_event"}` to report remaining
    quota. Passing `raw_output` on would classify every failure as a rate limit
    and wait 30 minutes for it.
    """

    @staticmethod
    def _stream() -> str:
        import json

        return '\n'.join(
            [
                json.dumps({'type': 'rate_limit_event', 'rate_limit_info': {'ok': True}}),
                json.dumps(
                    {
                        'type': 'result',
                        'subtype': 'success',
                        'result': 'the file was not written',
                        'is_error': True,
                        'total_cost_usd': 0.031,
                        'session_id': 's-1',
                    }
                ),
            ]
        )

    async def test_the_prose_excludes_the_envelopes_own_vocabulary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = await self._run_with(self._stream(), tmp_path, monkeypatch)
        assert 'rate_limit' not in result.prose_output
        assert 'the file was not written' in result.prose_output

    async def test_the_prose_is_not_a_rate_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mantis_research.core.retry import FailureKind, classify_failure

        result = await self._run_with(self._stream(), tmp_path, monkeypatch)
        assert classify_failure(result.prose_output) is FailureKind.GENERIC
        # And the raw envelope is what would have gone wrong.
        assert classify_failure(result.raw_output) is FailureKind.RATE_LIMIT

    async def test_the_turns_cost_is_recovered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = await self._run_with(self._stream(), tmp_path, monkeypatch)
        assert result.cost_usd == 0.031

    @staticmethod
    async def _run_with(stream: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from mantis_research.interface.adapters._subprocess import StreamResult

        async def canned(_cmd, transcript, **_kw):
            for line in stream.splitlines():
                transcript.append_line(line + '\n')
            return StreamResult(exit_code=0, output=stream, timed_out=False)

        monkeypatch.setattr('mantis_research.interface.adapters.claude_cli.run_streaming', canned)
        adapter = ClaudeCliAdapter(binary='/fake/claude')
        opts = ClaudeCliOptions(model='m', session_id='s-1')
        return await adapter.run('p', opts, tmp_path / 'tx.log')


class TestTheChildDoesNotInheritTheCallersProject:
    """A local-seat child starts in a neutral directory (MANT-02).

    The spawn named no working directory, so the child started wherever the MCP
    server did: the calling project. In a real run the synthesis child received
    that project's SessionStart control anchor, its AGENTS.md and its memory
    index, none of which the question asked for. Claude Code reads CLAUDE.md
    and AGENTS.md from the working directory and every directory above it, and
    keys a session's memory and hooks on it, so where the child starts decides
    what it is told before the prompt.
    """

    @staticmethod
    def _project(tmp_path: Path) -> Path:
        project = tmp_path / 'calling-project'
        (project / '.claude' / 'anchors').mkdir(parents=True)
        (project / 'CLAUDE.md').write_text('project instructions', encoding='utf-8')
        (project / 'AGENTS.md').write_text('agent rules', encoding='utf-8')
        (project / '.claude' / 'anchors' / 'control.md').write_text('anchor', encoding='utf-8')
        return project

    @staticmethod
    async def _spawn_cwds(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: int = 1
    ) -> list[Path | None]:
        from mantis_research.interface.adapters._subprocess import StreamResult

        seen: list[Path | None] = []

        async def record(_cmd, transcript, **kw):
            cwd = kw.get('cwd')
            seen.append(None if cwd is None else Path(cwd))
            return StreamResult(exit_code=0, output='', timed_out=False)

        monkeypatch.setattr('mantis_research.interface.adapters.claude_cli.run_streaming', record)
        adapter = ClaudeCliAdapter(binary='/fake/claude')
        for i in range(calls):
            opts = ClaudeCliOptions(model='m', session_id=f's-{i}')
            await adapter.run('p', opts, tmp_path / f'tx-{i}.log')
        return seen

    async def test_the_spawn_names_a_directory_outside_the_calling_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = self._project(tmp_path)
        monkeypatch.chdir(project)
        (cwd,) = await self._spawn_cwds(tmp_path, monkeypatch)
        assert cwd is not None, 'the child inherits the caller working directory'
        resolved = cwd.resolve()
        assert resolved != project.resolve()
        assert project.resolve() not in resolved.parents

    async def test_no_project_instructions_are_visible_from_where_the_child_starts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(self._project(tmp_path))
        (cwd,) = await self._spawn_cwds(tmp_path, monkeypatch)
        assert cwd is not None
        for directory in (cwd.resolve(), *cwd.resolve().parents):
            for name in ('CLAUDE.md', 'AGENTS.md', 'CLAUDE.local.md'):
                assert not (directory / name).exists(), f'{directory / name} reaches the child'

    async def test_every_turn_starts_in_the_same_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Claude Code finds a session to `--resume` by the working directory,
        # so the journal and sidecar re-ask turns, which resume the synthesis
        # session, must start where it started.
        cwds = await self._spawn_cwds(tmp_path, monkeypatch, calls=2)
        assert cwds[0] is not None
        assert cwds[0] == cwds[1]
