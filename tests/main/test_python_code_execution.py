import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.docker_executor import docker_executor

client = TestClient(app)


def test_simple_code_execution():
    """Test executing a simple Python code snippet."""
    response = client.post(
        "/v1/execute", json={"code": "print('Hello from Python!')\nx = 1 + 1\nprint(f'Result: {x}')", "lang": "py"}
    )

    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "ok"
    assert "Hello from Python!" in result["run"]["stdout"]
    assert "Result: 2" in result["run"]["stdout"]
    assert result["run"]["stderr"] == ""
    assert isinstance(result["files"], list)  # Should have files list, even if empty


def test_code_execution_error():
    """Test executing code that raises an error."""
    response = client.post("/v1/execute", json={"code": "x = 1/0  # This will raise a ZeroDivisionError", "lang": "py"})

    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "error"
    assert "ZeroDivisionError" in result["run"]["stderr"]
    assert result["run"]["stdout"] == "Empty. Make sure to explicitly print the results in Python"
    assert isinstance(result["files"], list)


def test_stderr_only_success_keeps_stdout_empty():
    """A successful run writing only to stderr must not get the 'Empty...' placeholder."""
    response = client.post(
        "/v1/execute",
        json={"code": "import sys; sys.stderr.write('warning: deprecated\\n')", "lang": "py"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "ok"
    assert result["run"]["stdout"] == ""
    assert "warning: deprecated" in result["run"]["stderr"]


def test_syntax_error():
    """Test executing code with syntax errors."""
    response = client.post(
        "/v1/execute", json={"code": "print('Unclosed string  # Missing closing quote", "lang": "py"}
    )

    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "error"
    assert "SyntaxError" in result["run"]["stderr"]
    assert result["run"]["stdout"] == "Empty. Make sure to explicitly print the results in Python"
    assert isinstance(result["files"], list)


# Create a fixture for the Docker executor
@pytest.fixture(scope="function")
async def docker_exec():
    """Initialize and clean up the Docker executor."""
    # Initialize Docker executor
    await docker_executor.initialize()
    yield docker_executor
    # Clean up Docker executor
    await docker_executor.close()


def test_multiple_sequential_requests(docker_exec):
    """Test executing multiple code requests in sequence to verify event loop handling."""
    # First request
    response1 = client.post("/v1/execute", json={"code": "print('First request')", "lang": "py"})

    assert response1.status_code == 200
    result1 = response1.json()
    assert result1["run"]["status"] == "ok"
    assert "First request" in result1["run"]["stdout"]

    # Second request
    response2 = client.post("/v1/execute", json={"code": "print('Second request')", "lang": "py"})

    assert response2.status_code == 200
    result2 = response2.json()
    assert result2["run"]["status"] == "ok"
    assert "Second request" in result2["run"]["stdout"]

    # Third request
    response3 = client.post("/v1/execute", json={"code": "print('Third request')", "lang": "py"})

    assert response3.status_code == 200
    result3 = response3.json()
    assert result3["run"]["status"] == "ok"
    assert "Third request" in result3["run"]["stdout"]
