"""Provider adapters — drivers for Claude CLI, Gemini CLI, OpenRouter HTTP.

Each adapter wraps the actual model call (subprocess for CLI tools, HTTP
for OpenRouter). Stages compose a Stage protocol implementation with the
right adapter; the orchestrator runs the stage generically.

Adapters:

- ``ClaudeCliAdapter`` — wraps ``claude -p`` (Anthropic Claude Code CLI).
- ``GeminiCliAdapter`` — wraps ``gemini -p`` (Google Gemini CLI, OAuth path).
- ``OpenRouterHttpAdapter`` — wraps ``POST openrouter.ai/api/v1/chat/completions``
  (lands in Phase 5).
"""

from __future__ import annotations
