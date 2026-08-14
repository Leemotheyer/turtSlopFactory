from uuid import UUID

from app.db_models import ProjectRow
from app.services.git_branching import (
    apply_isolated_branch_fields,
    generate_work_branch,
    resolve_branch_plan,
)


def _row(**kwargs) -> ProjectRow:
    defaults = {
        "name": "Invoice App",
        "description": "",
        "repo_url": "https://github.com/acme/widget",
        "branch": "main",
        "base_branch": "main",
        "work_branch": None,
        "isolate_branch": True,
        "merge_status": None,
    }
    defaults.update(kwargs)
    row = ProjectRow(
        id=UUID("12345678-1234-5678-1234-567812345678"),
        name=defaults["name"],
        description=defaults["description"],
        repo_url=defaults["repo_url"],
        branch=defaults["branch"],
        base_branch=defaults["base_branch"],
        work_branch=defaults["work_branch"],
        isolate_branch=defaults["isolate_branch"],
        merge_status=defaults["merge_status"],
    )
    return row


def test_generate_work_branch():
    pid = UUID("12345678-1234-5678-1234-567812345678")
    assert generate_work_branch("Invoice App", pid) == "factory/invoice-app-12345678"


def test_resolve_branch_plan_isolated():
    row = _row()
    plan = resolve_branch_plan(row)
    assert plan.isolated is True
    assert plan.base_branch == "main"
    assert plan.work_branch == "factory/invoice-app-12345678"
    assert plan.active_branch == plan.work_branch


def test_resolve_branch_plan_not_isolated():
    row = _row(isolate_branch=False, branch="develop")
    plan = resolve_branch_plan(row)
    assert plan.isolated is False
    assert plan.work_branch is None
    assert plan.active_branch == "develop"


def test_resolve_branch_plan_no_repo():
    row = _row(repo_url=None, isolate_branch=True)
    plan = resolve_branch_plan(row)
    assert plan.isolated is False


def test_apply_isolated_branch_fields_generates_work_branch():
    row = _row(work_branch=None)
    apply_isolated_branch_fields(row)
    assert row.work_branch == "factory/invoice-app-12345678"
    assert row.branch == row.work_branch
    assert row.merge_status == "pending"


def test_apply_isolated_branch_fields_clears_on_unlink():
    row = _row()
    apply_isolated_branch_fields(row, repo_url=None)
    assert row.isolate_branch is False
    assert row.work_branch is None
    assert row.merge_status is None
