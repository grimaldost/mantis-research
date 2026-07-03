"""Enable ``python -m mantis_research`` as an alternative to the
``mantis`` console script. Useful when the script wrapper is blocked by
OS security policies (Windows Application Control, etc.).
"""

from __future__ import annotations

from mantis_research.interface.cli import app

if __name__ == '__main__':
    app()
