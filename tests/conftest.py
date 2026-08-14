"""Re-export orchestrator API test fixtures for repo-root pytest runs."""

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_test_root = tempfile.mkdtemp(prefix="turtslopfactory-test-")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("WORKER_ENABLED", "false")
os.environ["WORKSPACE_ROOT"] = _test_root
os.environ["FACTORY_CONFIG_DIR"] = _test_root
sys.path.insert(0, str(ROOT / "orchestrator"))

_spec = importlib.util.spec_from_file_location(
    "orchestrator_conftest",
    ROOT / "orchestrator" / "tests" / "conftest.py",
)
_module = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_module)

api_client = _module.api_client
