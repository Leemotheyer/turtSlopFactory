from app.services.diagnosis import diagnose_failure


def test_docker_daemon_failure_is_infra():
    result = diagnose_failure("Cannot connect to the Docker daemon at unix:///var/run/docker.sock")
    assert result["error_class"] == "infra"


def test_cursor_capacity_is_infra():
    result = diagnose_failure("No Cursor Cloud agent slots available for implementation.")
    assert result["error_class"] == "infra"


def test_disk_full_is_infra():
    result = diagnose_failure("OSError: [Errno 28] No space left on device")
    assert result["error_class"] == "infra"


def test_assertion_error_is_app():
    result = diagnose_failure("FAILED tests/test_app.py::test_health - AssertionError: assert 500 == 200")
    assert result["error_class"] == "app"


def test_collection_error_is_test():
    result = diagnose_failure("ERROR tests/test_app.py - ImportError while importing test module")
    assert result["error_class"] == "test"


def test_unknown_defaults_to_app():
    result = diagnose_failure("something inexplicable happened")
    assert result["error_class"] == "app"
    assert result["matched"] is None


def test_logs_tail_contributes_to_classification():
    result = diagnose_failure("stage failed", logs_tail="... port is already allocated ...")
    assert result["error_class"] == "infra"
