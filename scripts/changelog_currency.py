"""Fail a change that ships source without recording it (CONTRIBUTING, changelog rule).

The version-site test proves the version copies AGREE; nothing proved a shipped change was
RECORDED. "Every user-visible change appends to `CHANGELOG.md` under Unreleased" was prose held by
habit, so a source-touching PR could merge CI-green with no entry. Ported from keel's working
`changelog-currency` gate, with one addition: a commit in the range may declare
`Changelog: none (<reason>)` for source changes with nothing user-visible in them.

Two arms, both run by CI's `changelog-currency` job:

- **Record arm** (default; exits 1): a changed-file list (arguments, else stdin, one path per
  line) touching a source path while `CHANGELOG.md` is untouched and no declaration is present.

      git diff --name-only "origin/$BASE...HEAD" | uv run python scripts/changelog_currency.py \
          --messages <file with the range's commit messages>

- **Version arm** (`--headings BASE_FILE HEAD_FILE`; exits 1): when the PR cuts a new newest
  `## [x.y.z]` heading, it must be a strict SemVer increase over the base's — the version-site
  equality tests (tests/unit/test_plugin_manifest.py) then hold every site to that heading in
  the same CI run.

Repo-local tooling, deliberately not part of the `mantis_research` package: it enforces this
repo's release loop, not a consumer's.
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


HEADING = re.compile(r'^## \[([0-9]+)\.([0-9]+)\.([0-9]+)\]', re.MULTILINE)


def _newest_version(changelog_text: str) -> tuple[int, int, int] | None:
    match = HEADING.search(changelog_text)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch))


def heading_regression(base_text: str, head_text: str) -> str | None:
    """Why the newest-heading move is wrong (None when there is no cut, or the cut is forward)."""
    head = _newest_version(head_text)
    if head is None:
        return 'parse rot: no `## [x.y.z]` heading left in CHANGELOG.md'
    base = _newest_version(base_text)
    if base is None or head == base or head > base:
        return None
    dotted_head, dotted_base = ('.'.join(map(str, v)) for v in (head, base))
    return (
        f'the newest CHANGELOG heading moved from {dotted_base} to {dotted_head} — a release '
        'cut inserts a strictly greater version above the previous heading, never at or below it'
    )


def _headings_mode(base_file: str, head_file: str) -> int:
    problem = heading_regression(
        Path(base_file).read_text(encoding='utf-8'),
        Path(head_file).read_text(encoding='utf-8'),
    )
    if problem is None:
        print('OK: no release cut, or the newest heading moved strictly forward.')
        return 0
    print(problem)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ['--headings']:
        return _headings_mode(args[1], args[2])
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
