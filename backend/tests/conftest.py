from __future__ import annotations

import sys
import types
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = BACKEND_ROOT / "src"

if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))


# Avoid executing videoagent/__init__.py side effects during test collection.
if "videoagent" not in sys.modules:
    package = types.ModuleType("videoagent")
    package.__path__ = [str(BACKEND_SRC / "videoagent")]
    package.__package__ = "videoagent"
    sys.modules["videoagent"] = package

