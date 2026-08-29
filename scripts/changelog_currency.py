"""Fail a change that ships source without recording it (CONTRIBUTING, changelog rule).

The version-site test proves the version copies AGREE; nothing proved a shipped change was
RECORDED. "Every user-visible change appends to `CHANGELOG.md` under Unreleased" was prose held by
habit, so a source-touching PR could merge CI-green with no entry. Ported from keel's working
`changelog-currency` gate, with one addition: a commit in the range may declare
`Changelog: none (<reason>)` for source changes with nothing user-visible in them.

Reads a changed-file list (arguments, else stdin, one path per line) and exits 1 when it touches a
source path while `CHANGELOG.md` is untouched and no declaration is present. Repo-local tooling,
deliberately not part of the `mantis_research` package: it enforces this repo's release loop, not
a consumer's.

    git diff --name-only "origin/$BASE...HEAD" | uv run python scripts/changelog_currency.py \
        --messages <file with the range's commit messages>
"""

import re
import sys
from collections.abc import Iterable
from pathlib import Path

# What ships to a consumer of this repo: the package and the repo-local gate scripts.
SOURCE_PREFIXES = ('src/', 'scripts/')
RECORD = 'CHANGELOG.md'
DECLARATION = re.compile(r'^Changelog: none \(.+\)\s*$', re.MULTILINE)


def unrecorded_source_paths(changed: Iterable[str], messages: str = '') -> list[str]:
    """The source paths in `changed` that no CHANGELOG edit or declaration covers ([] when fine)."""
    paths = [path.strip().replace('\\', '/') for path in changed if path.strip()]
    if RECORD in paths:
        return []
    if DECLARATION.search(messages):
        return []
    return [path for path in paths if path.startswith(SOURCE_PREFIXES)]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    messages = ''
    if '--messages' in args:
        at = args.index('--messages')
        messages = Path(args[at + 1]).read_text(encoding='utf-8')
        del args[at : at + 2]
    changed = args or sys.stdin.read().splitlines()
    unrecorded = unrecorded_source_paths(changed, messages)
    if not unrecorded:
        print('OK: no source change, or the CHANGELOG records it, or a commit declares none.')
        return 0
    print('Source paths changed with no CHANGELOG.md entry:')
    for path in unrecorded:
        print(f'  {path}')
    print(
        'Record the change in CHANGELOG.md under Unreleased (CONTRIBUTING, changelog rule), '
        'or declare `Changelog: none (<reason>)` in a commit message.'
    )
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
