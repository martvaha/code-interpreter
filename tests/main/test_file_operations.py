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
    response = client.post(
        "/v1/execute",
        json={
            "code": create_file_code,
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "ok"
    assert "File created" in result["run"]["stdout"]
    assert "test.txt" in result["run"]["stdout"]
    session_id = result["session_id"]
    
    # Now read the file back using the same session_id
    read_file_code = """
with open('/mnt/data/test.txt', 'r') as f:
    content = f.read()
print(f'File content: {content}')
"""
    response = client.post(
        "/v1/execute",
        json={
            "code": read_file_code,
            "lang": "py",
            "files": [
                {
                    "id": result["files"][0]["id"],
                    "storage_session_id": result["files"][0]["storage_session_id"],
                    "name": "test.txt",
                }
            ]
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "ok"
    assert "File content" in result["run"]["stdout"]

def test_file_persistence():
    """Test that files persist between executions in the same session."""
    # Create multiple files
    create_files_code = """
for i in range(3):
    with open(f'/mnt/data/test_{i}.txt', 'w') as f:
        f.write(f'Content {i}')
print('Files created')
"""
    response = client.post(
        "/v1/execute",
        json={
            "code": create_files_code,
            "lang": "py"
        }
    )

    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "ok"
    assert "Files created" in result["run"]["stdout"]
    session_id = result["session_id"]
    created_files = result["files"]

    # List and verify files using the same session_id
    list_files_code = """
import os
files = sorted(os.listdir('/mnt/data'))
print('Files:', files)
for file in files:
    with open(f'/mnt/data/{file}', 'r') as f:
        print(f'{file}: {f.read()}')
"""
    response = client.post(
        "/v1/execute",
        json={
            "code": list_files_code,
            "lang": "py",
            "files": [
                {"id": f["id"], "storage_session_id": f["storage_session_id"], "name": f["name"]}
                for f in created_files
            ]
        }
    )

    result = response.json()
    assert result["run"]["status"] == "ok"
    # Verify that all three files are present and have correct content
    assert "Files: ['test_0.txt', 'test_1.txt', 'test_2.txt']" in result["run"]["stdout"]
    assert "test_0.txt: Content 0" in result["run"]["stdout"]
    assert "test_1.txt: Content 1" in result["run"]["stdout"]
    assert "test_2.txt: Content 2" in result["run"]["stdout"]

def test_file_isolation():
    """Test that files are isolated between different sessions."""
    # Create a file in first execution
    response = client.post(
        "/v1/execute",
        json={
            "code": "with open('/mnt/data/secret.txt', 'w') as f: f.write('secret data')",
            "lang": "py"
        }
    )
    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "ok"
    
    # Try to read the file in a new execution (will get new session)
    response = client.post(
        "/v1/execute",
        json={
            "code": """
import os
print('Files:', os.listdir('/mnt/data'))
""",
            "lang": "py"
        }
    )
    
    result = response.json()
    assert result["run"]["status"] == "ok"
    assert "Files: []" in result["run"]["stdout"]

def test_file_creation_and_metadata():
    """Test that exec creates a file and stores metadata in SQLite."""
    # Create a file using exec
    create_file_code = """
with open('/mnt/data/test.txt', 'w') as f:
    f.write('Test content')
print('File created')
"""
    response = client.post(
        "/v1/execute",
        json={
            "code": create_file_code,
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "ok"
    assert "File created" in result["run"]["stdout"]
    session_id = result["session_id"]
    
    # Verify the file is listed in the response files
    assert "files" in result
    files = result["files"]
    assert len(files) > 0
    
    # Get the file metadata from the API
    response = client.get(f"/v1/files/{session_id}")
    assert response.status_code == 200
    files = response.json()
    
    # Verify file metadata
    assert len(files) > 0
    file = files[0]
    assert file["name"].endswith("test.txt")
    assert file["size"] > 0
    assert file["metadata"]["content-type"] == "text/plain"  # Content type for .txt files

def test_file_download():
    """Test downloading a file using the session file download endpoint."""
    # Create a file with specific content
    test_content = "Hello, this is test content for download!"
    create_file_code = """import os
# Create session directory
os.makedirs('/mnt/data', exist_ok=True)
# Write to file
with open('/mnt/data/download_test.txt', 'w') as f:
    f.write('""" + test_content + """')
print('File created')
# List files in directory
print('Files in /mnt/data:', os.listdir('/mnt/data'))"""

    response = client.post(
        "/v1/execute",
        json={
            "code": create_file_code,
            "lang": "py"
        }
    )

    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "ok"
    assert "File created" in result["run"]["stdout"]
    assert "download_test.txt" in result["run"]["stdout"]

    # Get the file ID from the response
    assert len(result["files"]) > 0
    file_ref = result["files"][0]
    session_id = result["session_id"]

    # Download the file
    response = client.get(f"/v1/download/{session_id}/{file_ref['id']}")
    assert response.status_code == 200
    assert response.content.decode() == test_content

    # Test downloading non-existent file
    response = client.get(f"/v1/download/{session_id}/nonexistent")
    assert response.status_code == 404

    # Test downloading from non-existent session
    response = client.get("/v1/download/nonexistent-session/nonexistent")
    assert response.status_code == 404


def test_upload_filename_path_traversal_rejected():
    """Test that a filename with path traversal is rejected and nothing is written outside uploads/."""
    from pathlib import Path

    response = client.post(
        "/v1/upload",
        files={"files": ("../../../tmp/evil.py", b"print('pwned')", "text/x-python")},
    )

    assert response.status_code == 400
    assert "Invalid filename" in response.json()["detail"]
    assert not Path("/tmp/evil.py").exists()


def test_upload_plain_filename_accepted():
    """Test that a normal filename still uploads fine after traversal hardening."""
    response = client.post(
        "/v1/upload",
        files={"files": ("safe.py", b"print('ok')", "text/x-python")},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["files"][0]["name"] == "safe.py"


def test_upload_too_many_files_rejected():
    """Test that uploads over FILE_MAX_BATCH_COUNT files are rejected with 413."""
    from app.shared.config import get_settings

    settings = get_settings()
    files = [
        ("files", (f"file_{i}.txt", b"x", "text/plain")) for i in range(settings.FILE_MAX_BATCH_COUNT + 1)
    ]

    response = client.post("/v1/upload", files=files)

    assert response.status_code == 413
    assert "Too many files" in response.json()["detail"]


def test_upload_oversized_file_rejected():
    """Test that an oversized file is rejected with 413 instead of a 500."""
    from app.shared.config import get_settings

    settings = get_settings()
    oversized = b"x" * (settings.FILE_MAX_UPLOAD_SIZE + 1)

    response = client.post("/v1/upload", files={"files": ("big.txt", oversized, "text/plain")})

    assert response.status_code == 413
    assert "exceeds size limit" in response.json()["detail"]
