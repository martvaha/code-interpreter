import pytest
from datetime import datetime
from pydantic import ValidationError

from app.models.base import (
    Error,
    FileRef,
    RequestFile,
    CodeExecutionRequest,
    ExecutionResult,
    ExecuteResponse,
    FileObject,
    UploadResponse,
)
from app.models.librechat import (
    LibreChatFileRef,
    LibreChatUploadResponse,
    LibreChatFileObject,
    LibreChatExecuteResponse,
    LibreChatError,
)


def test_base_error_model():
    """Test Error model validation."""
    error = Error(error="Test error")
    assert error.error == "Test error"
    assert error.details is None

    error_with_details = Error(error="Test error", details="More info")
    assert error_with_details.error == "Test error"
    assert error_with_details.details == "More info"


def test_file_ref_model():
    """Test FileRef model validation."""
    file_ref = FileRef(id="123", name="test.txt")
    assert file_ref.id == "123"
    assert file_ref.name == "test.txt"
    assert file_ref.path is None

    file_ref_with_path = FileRef(id="123", name="test.txt", path="/tmp")
    assert file_ref_with_path.path == "/tmp"


def test_code_execution_request():
    """Test CodeExecutionRequest model validation."""
    # Test valid Python request
    request = CodeExecutionRequest(code="print('hello')", lang="py")
    assert request.code == "print('hello')"
    assert request.lang == "py"

    # Test invalid language
    with pytest.raises(ValidationError):
        CodeExecutionRequest(code="print('hello')", lang="invalid")

    # Test with optional fields
    request = CodeExecutionRequest(
        code="print('hello')",
        lang="py",
        args=["--verbose"],
        user_id="user123",
        entity_id="asst_123",
        files=[
            RequestFile(
                id="f" * 21,
                storage_session_id="a" * 21,
                name="test.txt",
                resource_id="user123",
                kind="user",
            )
        ],
    )
    assert request.args == ["--verbose"]
    assert request.user_id == "user123"
    assert request.entity_id == "asst_123"
    assert len(request.files) == 1


def test_request_file_storage_session_id_validation():
    """Test that storage_session_id rejects path traversal and malformed values."""
    valid_id = "a" * 21

    file = RequestFile(id="f" * 21, storage_session_id=valid_id, name="test.txt")
    assert file.storage_session_id == valid_id
    assert file.kind is None

    for invalid in ["../../etc/passwd", "a/b/c", "abc", "a" * 22, ""]:
        with pytest.raises(ValidationError):
            RequestFile(id="f" * 21, storage_session_id=invalid, name="test.txt")


def test_request_file_id_validation():
    """Test that file id rejects path traversal and malformed values."""
    valid_id = "f" * 21

    file = RequestFile(id=valid_id, storage_session_id="a" * 21, name="test.txt")
    assert file.id == valid_id

    for invalid in ["../../etc/passwd", "a/b/c", "1", "f" * 22, ""]:
        with pytest.raises(ValidationError):
            RequestFile(id=invalid, storage_session_id="a" * 21, name="test.txt")


def test_code_execution_request_session_id_validation():
    """Test that session_id only accepts the generate_id() format (21 chars of [A-Za-z0-9_-])."""
    from app.utils.generate_id import generate_id

    # A generated ID is accepted
    session_id = generate_id()
    request = CodeExecutionRequest(code="echo hi", lang="bash", session_id=session_id)
    assert request.session_id == session_id

    # Omitting it is fine
    request = CodeExecutionRequest(code="echo hi", lang="bash")
    assert request.session_id is None

    # Path traversal and other malformed values are rejected
    invalid_session_ids = [
        "../../etc/passwd",
        "../" + "a" * 18,  # 21 chars but contains traversal
        "a/b/c",
        "abc",  # too short
        "a" * 22,  # too long
        "a" * 20 + ".",  # invalid character
        "",
    ]
    for invalid in invalid_session_ids:
        with pytest.raises(ValidationError):
            CodeExecutionRequest(code="echo hi", lang="bash", session_id=invalid)


def test_execute_response():
    """Test ExecuteResponse model."""
    result = ExecutionResult(stdout="output", stderr="error", code=0)
    response = ExecuteResponse(
        run=result, language="py", version="3.9.0", session_id="sess1", files=[FileRef(id="1", name="output.txt")]
    )
    assert response.run.stdout == "output"
    assert response.run.stderr == "error"
    assert response.language == "py"
    assert len(response.files) == 1


def test_librechat_file_ref():
    """Test LibreChat file reference model."""
    file_ref = LibreChatFileRef(id="123", name="test.txt")
    assert file_ref.id == "123"
    assert file_ref.name == "test.txt"


def test_librechat_upload_response():
    """Test LibreChat upload response model and conversion."""
    # Create base response
    base_response = UploadResponse(
        message="success",
        session_id="sess1",
        files=[FileObject(name="test.txt", id="123", session_id="sess1", size=100)],
    )

    # Convert to LibreChat format
    libre_response = LibreChatUploadResponse.from_base(base_response)
    assert libre_response.message == "success"
    assert libre_response.storage_session_id == "sess1"
    assert len(libre_response.files) == 1
    assert libre_response.files[0].fileId == "123"
    assert libre_response.files[0].filename == "test.txt"


def test_librechat_file_object():
    """Test LibreChat file object model and conversion."""
    last_modified = datetime.now().isoformat()
    # Create base file object
    base_file = FileObject(
        name="test.txt", id="123", session_id="sess1", size=100, contentType="text/plain", lastModified=last_modified
    )

    # Convert to LibreChat format
    libre_file = LibreChatFileObject.from_base(base_file)
    assert libre_file.name == "sess1/123"
    assert libre_file.id == "123"
    assert libre_file.storage_session_id == "sess1"
    assert libre_file.lastModified == last_modified
    assert libre_file.metadata["original-filename"] == "test.txt"


def test_librechat_execute_response():
    """Test LibreChat execute response model and conversion."""
    # Create base response
    result = ExecutionResult(stdout="output", stderr="error")
    base_response = ExecuteResponse(
        run=result,
        language="py",
        version="3.9.0",
        session_id="sess1",
        files=[FileRef(id="1", name="output.txt", storage_session_id="sess1")],
    )

    # Convert to LibreChat format
    libre_response = LibreChatExecuteResponse.from_base(base_response)
    assert libre_response.session_id == "sess1"
    assert libre_response.stdout == "output"
    assert libre_response.stderr == "error"
    assert libre_response.files is not None
    assert len(libre_response.files) == 1
    assert libre_response.files[0].storage_session_id == "sess1"


def test_librechat_error():
    """Test LibreChat error model and conversion."""
    # Create base error
    base_error = Error(error="Test error", details="More info")

    # Convert to LibreChat format
    libre_error = LibreChatError.from_base(base_error)
    assert libre_error.message == "Test error: More info"

    # Test without details
    base_error = Error(error="Test error")
    libre_error = LibreChatError.from_base(base_error)
    assert libre_error.message == "Test error"
