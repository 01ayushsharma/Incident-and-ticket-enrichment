"""Root conftest: put the service package roots on sys.path.

The repository deliberately mirrors the directory layout the submission
guidelines ask for (``services/``, ``mcp-servers/``, ``apps/``), which is not
a single importable package root. Rather than require an editable install
before tests can run, the roots are registered here.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent
for relative in (".", "services", "mcp-servers/alarm-management", "apps/backend", "apps/frontend"):
    path = str((ROOT / relative).resolve())
    if path not in sys.path:
        sys.path.insert(0, path)
