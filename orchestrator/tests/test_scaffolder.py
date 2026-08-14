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


def test_scaffold_env_files():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        scaffold_web_app(repo, "Env App", "App with env")
        assert (repo / ".env.example").exists()
        gitignore = (repo / ".gitignore").read_text()
        assert ".env" in gitignore


def test_scaffold_multiline_description():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        description = '# My App\n\nA "quoted" multiline\ndescription'
        scaffold_web_app(repo, "My App", description)
        main_py = (repo / "app" / "main.py").read_text()
        compile(main_py, "main.py", "exec")
        assert description in main_py
