import json
import shutil
from pathlib import Path
from uuid import UUID

from app.config import settings


class WorkspaceManager:
    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.workspace_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: UUID) -> Path:
        path = self.root / "projects" / str(project_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def repo_dir(self, project_id: UUID) -> Path:
        path = self.project_dir(project_id) / "repo"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def artifacts_dir(self, project_id: UUID) -> Path:
        path = self.project_dir(project_id) / "artifacts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def logs_dir(self, project_id: UUID) -> Path:
        path = self.project_dir(project_id) / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_artifact(self, project_id: UUID, name: str, content: str) -> Path:
        path = self.artifacts_dir(project_id) / name
        path.write_text(content)
        return path

    def read_artifact(self, project_id: UUID, name: str) -> str | None:
        path = self.artifacts_dir(project_id) / name
        return path.read_text() if path.exists() else None

    def list_artifacts(self, project_id: UUID) -> list[str]:
        return sorted(p.name for p in self.artifacts_dir(project_id).iterdir() if p.is_file())

    def write_log(self, project_id: UUID, name: str, content: str) -> None:
        path = self.logs_dir(project_id) / name
        path.write_text(content)

    def append_log(self, project_id: UUID, name: str, line: str) -> None:
        path = self.logs_dir(project_id) / name
        with path.open("a") as f:
            f.write(line)
            if not line.endswith("\n"):
                f.write("\n")

    def save_metadata(self, project_id: UUID, data: dict) -> None:
        path = self.project_dir(project_id) / "metadata.json"
        path.write_text(json.dumps(data, indent=2))

    def load_metadata(self, project_id: UUID) -> dict:
        path = self.project_dir(project_id) / "metadata.json"
        if path.exists():
            return json.loads(path.read_text())
        return {}

    def reset_repo(self, project_id: UUID) -> Path:
        repo = self.repo_dir(project_id)
        if repo.exists():
            shutil.rmtree(repo)
        repo.mkdir(parents=True)
        return repo

    def delete_project(self, project_id: UUID) -> None:
        """Remove all local workspace files for a project. Does not touch GitHub."""
        path = self.root / "projects" / str(project_id)
        if path.exists():
            shutil.rmtree(path)
