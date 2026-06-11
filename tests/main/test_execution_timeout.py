import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import docker_executor as docker_executor_module
from app.services.docker_executor import docker_executor

client = TestClient(app)


@pytest.fixture
def short_timeout(monkeypatch):
    """Reduce the sandbox execution timeout so the test fails fast."""
    monkeypatch.setattr(docker_executor_module.settings, "SANDBOX_MAX_EXECUTION_TIME", 2)


def test_execution_timeout_bash(short_timeout):
    """A long-running bash command is killed once the timeout is exceeded."""
    response = client.post("/v1/execute", json={"code": "sleep 30", "lang": "bash"})

    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "error"
    assert "timed out after 2 seconds" in result["run"]["stderr"]


def test_execution_timeout_python(short_timeout):
    """A long-running Python script is killed once the timeout is exceeded."""
    response = client.post(
        "/v1/execute", json={"code": "import time\ntime.sleep(30)", "lang": "py"}
    )

    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "error"
    assert "timed out after 2 seconds" in result["run"]["stderr"]


def test_container_cleaned_up_after_timeout(short_timeout):
    """The container is force-deleted after a timeout, freeing the semaphore slot."""
    response = client.post("/v1/execute", json={"code": "sleep 30", "lang": "bash"})

    assert response.status_code == 200
    assert response.json()["run"]["status"] == "error"
    assert docker_executor._active_containers == {}


def test_fast_execution_unaffected_by_timeout(short_timeout):
    """Commands that finish within the timeout still succeed."""
    response = client.post("/v1/execute", json={"code": "echo 'quick'", "lang": "bash"})

    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "ok"
    assert "quick" in result["run"]["stdout"]
