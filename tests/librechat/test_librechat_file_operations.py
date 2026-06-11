from fastapi.testclient import TestClient
from app.main import app
import os

client = TestClient(app)


def test_create_and_read_file():
    """Test creating and reading a file."""
    # First, create a file
    create_file_code = """
import os
# Write to file
with open('/mnt/data/test.txt', 'w') as f:
    f.write('Hello from file!')
print('File created')
# List files in directory
print('Files in /mnt/data:', os.listdir('/mnt/data'))
"""
    response = client.post("/v1/librechat/exec", json={"code": create_file_code, "lang": "py"})

    assert response.status_code == 200
    result = response.json()
    assert "stdout" in result
    assert "stderr" in result
    assert "File created" in result["stdout"]
    assert "test.txt" in result["stdout"]
    session_id = result["session_id"]

    # Now read the file back using the same session_id
    read_file_code = """
with open('/mnt/data/test.txt', 'r') as f:
    content = f.read()
print(f'File content: {content}')
"""
    response = client.post(
        "/v1/librechat/exec",
        json={
            "code": read_file_code,
            "lang": "py",
            "files": [
                {
                    "id": result["files"][0]["id"],
                    "storage_session_id": result["files"][0]["storage_session_id"],
                    "name": "test.txt",
                }
            ],
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert "stdout" in result
    assert "stderr" in result
    assert "File content" in result["stdout"]


def test_file_persistence():
    """Test that files persist between executions in the same session."""
    # Create multiple files
    create_files_code = """
for i in range(3):
    with open(f'/mnt/data/test_{i}.txt', 'w') as f:
        f.write(f'Content {i}')
print('Files created')
"""
    response = client.post("/v1/librechat/exec", json={"code": create_files_code, "lang": "py"})

    assert response.status_code == 200
    result = response.json()
    assert "stdout" in result
    assert "Files created" in result["stdout"]
    session_id = result["session_id"]

    # Read back all files
    read_files_code = """
import os
files = sorted(os.listdir('/mnt/data'))
print('Files:', files)
for file in files:
    with open(f'/mnt/data/{file}', 'r') as f:
        print(f'{file}: {f.read()}')
"""
    response = client.post(
        "/v1/librechat/exec",
        json={
            "code": read_files_code,
            "lang": "py",
            "files": [
                {"id": f["id"], "storage_session_id": f["storage_session_id"], "name": f["name"]}
                for f in result["files"]
            ],
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert "stdout" in result
    assert "test_0.txt" in result["stdout"]
    assert "test_1.txt" in result["stdout"]
    assert "test_2.txt" in result["stdout"]
    assert "Content 0" in result["stdout"]
    assert "Content 1" in result["stdout"]
    assert "Content 2" in result["stdout"]


def test_file_isolation():
    """Test that files are isolated between different sessions."""
    # Create a file in first execution
    response = client.post(
        "/v1/librechat/exec",
        json={"code": "with open('/mnt/data/secret.txt', 'w') as f: f.write('secret data')", "lang": "py"},
    )

    assert response.status_code == 200

    # Try to access file in a new session
    response = client.post(
        "/v1/librechat/exec", json={"code": "\nimport os\nprint('Files:', os.listdir('/mnt/data'))\n", "lang": "py"}
    )

    assert response.status_code == 200
    result = response.json()
    assert "stdout" in result
    assert "Files: []" in result["stdout"]  # New session should see no files


def test_file_creation_and_metadata():
    """Test that exec creates a file and stores metadata in SQLite."""
    # Create a file using exec
    create_file_code = """
with open('/mnt/data/test.txt', 'w') as f:
    f.write('Test content')
print('File created')
"""
    response = client.post("/v1/librechat/exec", json={"code": create_file_code, "lang": "py"})

    assert response.status_code == 200
    result = response.json()
    assert "stdout" in result
    assert "File created" in result["stdout"]
    assert "files" in result
    assert len(result["files"]) == 1
    session_id = result["session_id"]
    file_id = result["files"][0]["id"]

    # List files to check metadata
    response = client.get(f"/v1/librechat/files/{session_id}")
    assert response.status_code == 200
    files = response.json()
    assert len(files) == 1
    assert files[0]["name"] == f"{session_id}/{file_id}"
    assert files[0]["lastModified"] is not None


def test_upload_returns_storage_session_id():
    """Test that upload responds with the storage_session_id LibreChat reads."""
    response = client.post(
        "/v1/librechat/upload",
        files={"file": ("data.csv", b"a,b\n1,2\n", "text/csv")},
        data={"kind": "user", "id": "user123"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["message"] == "success"
    assert "storage_session_id" in result
    assert len(result["files"]) == 1
    assert result["files"][0]["filename"] == "data.csv"
    assert result["files"][0]["fileId"]


def test_batch_upload():
    """Test batch upload sharing one storage session with per-file results."""
    response = client.post(
        "/v1/librechat/upload/batch",
        files=[
            ("file", ("one.txt", b"first", "text/plain")),
            ("file", ("two.txt", b"second", "text/plain")),
        ],
        data={"kind": "user", "id": "user123"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["message"] == "success"
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert len(result["files"]) == 2
    assert all(f["status"] == "success" and f["fileId"] for f in result["files"])

    # Both files must be downloadable from the shared storage session
    session_id = result["storage_session_id"]
    for f, expected in zip(result["files"], [b"first", b"second"]):
        download = client.get(f"/v1/librechat/download/{session_id}/{f['fileId']}")
        assert download.status_code == 200
        assert download.content == expected


def test_batch_upload_oversized_file_reported_per_file():
    """Test that an oversized file in a batch yields a per-file error, not a 413."""
    from app.shared.config import get_settings

    settings = get_settings()
    oversized = b"x" * (settings.FILE_MAX_UPLOAD_SIZE + 1)

    response = client.post(
        "/v1/librechat/upload/batch",
        files=[
            ("file", ("ok.txt", b"fits", "text/plain")),
            ("file", ("huge.txt", oversized, "text/plain")),
        ],
    )

    assert response.status_code == 200
    result = response.json()
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    by_name = {f["filename"]: f for f in result["files"]}
    assert by_name["ok.txt"]["status"] == "success"
    assert by_name["huge.txt"]["status"] == "error"
    assert "size limit" in by_name["huge.txt"]["error"]


def test_batch_upload_too_many_files_rejected():
    """Test that batches over FILE_MAX_BATCH_COUNT are rejected before any processing."""
    from app.shared.config import get_settings

    settings = get_settings()
    files = [
        ("file", (f"file_{i}.txt", b"x", "text/plain")) for i in range(settings.FILE_MAX_BATCH_COUNT + 1)
    ]

    response = client.post("/v1/librechat/upload/batch", files=files)

    assert response.status_code == 413
    assert "Too many files" in response.json()["message"]


def test_batch_upload_oversized_file_rejected_per_file():
    """Test that an oversized file fails per-file without sinking the rest of the batch."""
    from app.shared.config import get_settings

    settings = get_settings()
    oversized = b"x" * (settings.FILE_MAX_UPLOAD_SIZE + 1)

    response = client.post(
        "/v1/librechat/upload/batch",
        files=[
            ("file", ("big.txt", oversized, "text/plain")),
            ("file", ("small.txt", b"ok", "text/plain")),
        ],
    )

    assert response.status_code == 200
    result = response.json()
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    by_name = {f["filename"]: f for f in result["files"]}
    assert by_name["big.txt"]["status"] == "error"
    assert "exceeds size limit" in by_name["big.txt"]["error"]
    assert by_name["small.txt"]["status"] == "success"


def test_session_object_liveness_check():
    """Test the GET /sessions/{sid}/objects/{fid} endpoint used by primeCodeFiles."""
    upload = client.post(
        "/v1/librechat/upload",
        files={"file": ("alive.txt", b"still here", "text/plain")},
        data={"kind": "user", "id": "user123"},
    )
    assert upload.status_code == 200
    result = upload.json()
    session_id = result["storage_session_id"]
    file_id = result["files"][0]["fileId"]

    response = client.get(
        f"/v1/librechat/sessions/{session_id}/objects/{file_id}",
        params={"kind": "user", "id": "user123"},
    )
    assert response.status_code == 200
    assert response.json()["lastModified"]

    # Missing objects must 404 so LibreChat falls back to re-upload
    response = client.get(f"/v1/librechat/sessions/{session_id}/objects/nonexistent")
    assert response.status_code == 404


def test_delete_session_object():
    """Test the DELETE /sessions/{sid}/objects/{fid} endpoint."""
    upload = client.post(
        "/v1/librechat/upload",
        files={"file": ("doomed.txt", b"delete me", "text/plain")},
    )
    assert upload.status_code == 200
    result = upload.json()
    session_id = result["storage_session_id"]
    file_id = result["files"][0]["fileId"]

    response = client.delete(f"/v1/librechat/sessions/{session_id}/objects/{file_id}")
    assert response.status_code == 200

    response = client.get(f"/v1/librechat/sessions/{session_id}/objects/{file_id}")
    assert response.status_code == 404


def test_exec_with_uploaded_file():
    """Test the full LibreChat flow: upload, then exec referencing the storage session."""
    upload = client.post(
        "/v1/librechat/upload",
        files={"file": ("driver_data.csv", b"driver,points\nalice,25\nbob,18\n", "text/csv")},
        data={"kind": "user", "id": "user123"},
    )
    assert upload.status_code == 200
    uploaded = upload.json()
    storage_session_id = uploaded["storage_session_id"]
    file_id = uploaded["files"][0]["fileId"]

    # Exec the way LibreChat v0.8.6 does: no top-level session_id, per-file
    # refs carrying storage_session_id/kind/resource_id
    response = client.post(
        "/v1/librechat/exec",
        json={
            "code": "cat /mnt/data/driver_data.csv",
            "lang": "bash",
            "user_id": "user123",
            "files": [
                {
                    "id": file_id,
                    "name": "driver_data.csv",
                    "storage_session_id": storage_session_id,
                    "resource_id": "user123",
                    "kind": "user",
                }
            ],
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert "driver,points" in result["stdout"]
    assert "alice,25" in result["stdout"]
    # A fresh exec session is created; the input file is staged into it
    assert result["session_id"] != storage_session_id


def test_exec_with_files_from_multiple_storage_sessions():
    """Test that files from different storage sessions are staged together."""
    refs = []
    for filename, content in [("first.txt", b"alpha"), ("second.txt", b"beta")]:
        upload = client.post("/v1/librechat/upload", files={"file": (filename, content, "text/plain")})
        assert upload.status_code == 200
        uploaded = upload.json()
        refs.append(
            {
                "id": uploaded["files"][0]["fileId"],
                "name": filename,
                "storage_session_id": uploaded["storage_session_id"],
                "kind": "user",
            }
        )

    # Each upload created its own storage session
    assert refs[0]["storage_session_id"] != refs[1]["storage_session_id"]

    response = client.post(
        "/v1/librechat/exec",
        json={"code": "cat /mnt/data/first.txt /mnt/data/second.txt", "lang": "bash", "files": refs},
    )

    assert response.status_code == 200
    result = response.json()
    assert "alpha" in result["stdout"]
    assert "beta" in result["stdout"]


def test_exec_generated_file_carries_storage_session_id():
    """Test that generated files return refs LibreChat can download and re-inject."""
    response = client.post(
        "/v1/librechat/exec",
        json={"code": "echo 'artifact' > /mnt/data/out.txt && echo done", "lang": "bash"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["files"], "Generated file should be returned"
    file_ref = result["files"][0]
    assert file_ref["name"] == "out.txt"
    assert file_ref["storage_session_id"] == result["session_id"]

    # The ref must be downloadable (processCodeOutput path)
    download = client.get(f"/v1/librechat/download/{file_ref['storage_session_id']}/{file_ref['id']}")
    assert download.status_code == 200
    assert download.content.decode().strip() == "artifact"

    # And re-injectable into a later exec (subsequent tool call path)
    response2 = client.post(
        "/v1/librechat/exec",
        json={
            "code": "cat /mnt/data/out.txt",
            "lang": "bash",
            "files": [
                {
                    "id": file_ref["id"],
                    "name": file_ref["name"],
                    "storage_session_id": file_ref["storage_session_id"],
                    "kind": "user",
                }
            ],
        },
    )
    assert response2.status_code == 200
    assert "artifact" in response2.json()["stdout"]


def test_exec_unsupported_language_returns_valid_response():
    """Unsupported languages must return a schema-valid 200 with the message in stdout."""
    # 'java' passes request validation but is not in SUPPORTED_LANGUAGES
    response = client.post("/v1/librechat/exec", json={"code": "System.out.println(1);", "lang": "java"})

    assert response.status_code == 200
    result = response.json()
    assert "not supported" in result["stdout"]
    assert result["session_id"]
    assert result["stderr"] == ""


def test_file_download():
    """Test downloading a file using the session file download endpoint."""
    # Create a file with specific content
    test_content = "Hello, this is test content for download!"
    create_file_code = (
        """import os
# Create session directory
os.makedirs('/mnt/data', exist_ok=True)
# Write to file
with open('/mnt/data/download_test.txt', 'w') as f:
    f.write('"""
        + test_content
        + """')
print('File created')
# List files in directory
print('Files in /mnt/data:', os.listdir('/mnt/data'))"""
    )

    response = client.post("/v1/librechat/exec", json={"code": create_file_code, "lang": "py"})

    assert response.status_code == 200
    result = response.json()
    assert "stdout" in result
    assert "File created" in result["stdout"]
    session_id = result["session_id"]
    file_id = result["files"][0]["id"]

    # Download the file
    response = client.get(f"/v1/librechat/download/{session_id}/{file_id}")
    assert response.status_code == 200
    assert response.content.decode() == test_content

    # Test non-existent file
    response = client.get(f"/v1/librechat/download/{session_id}/nonexistent")
    assert response.status_code == 404

    # Test non-existent session
    response = client.get("/v1/librechat/download/nonexistent-session/nonexistent")
    assert response.status_code == 404
