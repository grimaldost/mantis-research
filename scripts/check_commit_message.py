"""Reject AI-attribution lines in a commit message (commit-msg hook).

The contribution guidelines forbid attributing authorship to an AI tool,
whether as a Co-Authored-By trailer or as a standalone "Generated with ..."
line. The check lives in a script rather than inline in the hook config so a
test can load it by path and prove it can fail, same as the other gates.

Reads the message file pre-commit passes at the commit-msg stage and exits 1
naming each offending line. Repo-local tooling, deliberately not part of the
`mantis_research` package.
"""

import re
import sys
from pathlib import Path

FORBIDDEN = (
    re.compile(r'^co-authored-by:.*\b(claude|gpt|anthropic)\b', re.IGNORECASE),
    re.compile(r'\bgenerated with\b.*\b(claude|gpt|anthropic)\b', re.IGNORECASE),
)


def attribution_lines(message: str) -> list[str]:
    """The lines in ``message`` that attribute authorship to an AI tool ([] when clean)."""
    return [
        line for line in message.splitlines() if any(rx.search(line) for rx in FORBIDDEN)
    ]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    offending = attribution_lines(Path(args[0]).read_text(encoding='utf-8'))
    if not offending:
        return 0
    print('Commit message carries an AI-attribution line; the contribution guidelines forbid these:')
    for line in offending:
        print(f'  {line}')
    print('Remove the line and re-commit.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
