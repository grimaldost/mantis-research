"""Unit tests for ClaudeCliAdapter — cmd assembly + dry-run flow."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mantis_research.interface.adapters.claude_cli import (
    ClaudeCliAdapter,
    ClaudeCliOptions,
)

if TYPE_CHECKING:
    from pathlib import Path


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
        assert '--output-format' in cmd
        assert 'text' in cmd
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
