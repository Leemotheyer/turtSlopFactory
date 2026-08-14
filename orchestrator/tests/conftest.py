import os
from pathlib import Path

import pytest

_test_root = Path("/tmp/factory-test-workspaces")
_test_root.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("WORKSPACE_ROOT", str(_test_root))

from app.workspace.manager import WorkspaceManager


@pytest.fixture
def workspace(tmp_path):
    return WorkspaceManager(str(tmp_path))
