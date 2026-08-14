from app.workspace.provisioner import normalize_repo_url, repo_display_name


def test_normalize_repo_url():
    assert normalize_repo_url("https://github.com/acme/widget") == "https://github.com/acme/widget"
    assert normalize_repo_url("https://github.com/acme/widget.git") == "https://github.com/acme/widget"
    assert normalize_repo_url("https://github.com/acme/widget/") == "https://github.com/acme/widget"
    assert normalize_repo_url(None) is None
    assert normalize_repo_url("") is None


def test_normalize_repo_url_rejects_non_github():
    try:
        normalize_repo_url("https://gitlab.com/acme/widget")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "GitHub" in str(exc)


def test_repo_display_name():
    assert repo_display_name("https://github.com/acme/widget") == "acme/widget"
