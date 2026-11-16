"""Test bootstrap — run inside the dev core container (``PYTHONPATH=/app``).

* ``core.services`` must be imported before ``core.api`` (circular import in
  lyndrix-core — the runtime loads services first via main.py).
* ``entrypoint.py`` uses package-relative imports, so the plugin root is also
  registered under the alias ``ext_plugin`` (``import ext_plugin.entrypoint``).
"""
# TODO(agent): fix the core.api ↔ ui.layout cycle in lyndrix-core and drop the first import.
import sys
import types
from pathlib import Path

import core.services  # noqa: F401

_ROOT = Path(__file__).resolve().parents[1]
if "ext_plugin" not in sys.modules:
    _pkg = types.ModuleType("ext_plugin")
    _pkg.__path__ = [str(_ROOT)]
    sys.modules["ext_plugin"] = _pkg
