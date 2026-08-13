import tempfile
from pathlib import Path

from app.workspace.scaffolder import scaffold_web_app


def test_scaffold_creates_files():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        files = scaffold_web_app(repo, "Test App", "A test application")
        assert "app/main.py" in files
        assert "Dockerfile" in files
        assert "tests/test_app.py" in files
        assert (repo / "app" / "main.py").exists()


def test_scaffold_health_in_code():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        scaffold_web_app(repo, "Health App", "Health check app")
        main_py = (repo / "app" / "main.py").read_text()
        assert "/health" in main_py
        assert "Health App" in main_py
