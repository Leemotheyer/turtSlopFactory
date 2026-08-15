import tempfile
from pathlib import Path

from app.workspace.scaffolder import ensure_dockerfile, scaffold_web_app


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


def test_scaffold_frontend_uses_relative_api_urls():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        scaffold_web_app(repo, "Rel App", "relative urls")
        html = (repo / "app" / "static" / "index.html").read_text()
        assert "fetch('api/items')" in html
        assert "fetch('/api/items')" not in html


def test_ensure_dockerfile_does_not_overwrite(tmp_path):
    repo = tmp_path
    dockerfile = repo / "Dockerfile"
    dockerfile.write_text("FROM custom\n")
    assert ensure_dockerfile(repo) is False
    assert dockerfile.read_text() == "FROM custom\n"


def test_ensure_dockerfile_writes_when_missing(tmp_path):
    assert ensure_dockerfile(tmp_path) is True
    text = (tmp_path / "Dockerfile").read_text()
    assert "uvicorn" in text
    assert "EXPOSE 8080" in text


def test_scaffold_env_files():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        scaffold_web_app(repo, "Env App", "App with env")
        assert (repo / ".env.example").exists()
        gitignore = (repo / ".gitignore").read_text()
        assert ".env" in gitignore
