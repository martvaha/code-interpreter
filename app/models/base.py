from typing import Optional, List, Literal
from pydantic import BaseModel, Field


class Error(BaseModel):
    """Base error model as defined in OpenAPI spec."""

    error: str
    details: Optional[str] = None


class FileRef(BaseModel):
    """File reference returned from code execution."""

    id: str
    name: str  # Relative path of the file within the session directory
    storage_session_id: Optional[str] = None  # Session whose storage serves this file
    path: Optional[str] = None


class RequestFile(BaseModel):
    """Input file reference sent by LibreChat in execution requests.

    Each file points at the storage session it was uploaded to (or generated
    in), which may differ per file and from the execution session.
    """

    id: str = Field(..., description="File identifier", pattern="^[A-Za-z0-9_-]{21}$")
    storage_session_id: str = Field(
        ...,
        description="Storage session the file lives in",
        pattern="^[A-Za-z0-9_-]{21}$",
    )
    name: str
    resource_id: Optional[str] = None  # Entity owning the storage session (informational)
    kind: Optional[Literal["user", "agent", "skill"]] = None
    version: Optional[int] = None  # Only sent for kind == "skill"


class CodeExecutionRequest(BaseModel):
    """Code execution request model as defined in OpenAPI spec."""

    code: str = Field(..., description="The source code to be executed")
    lang: str = Field(
        ...,
        description="The programming language of the code",
        examples=["py", "r", "bash", "js", "ts"],
        pattern="^(c|cpp|d|f90|go|java|js|php|py|rs|ts|r|bash)$",
    )
    args: Optional[List[str]] = Field(None, description="Optional command line arguments to pass to the program")
    session_id: Optional[str] = Field(
        None,
        description="Optional session identifier to continue an existing sandbox session",
        pattern="^[A-Za-z0-9_-]{21}$",
    )
    user_id: Optional[str] = Field(None, description="Optional user identifier")
    entity_id: Optional[str] = Field(
        None,
        description="Optional assistant/agent identifier for file sharing and reference",
        max_length=40,
        pattern="^[A-Za-z0-9_-]+$",
        examples=["asst_axIyVEqAa3UVppsVP3WTl5So"],
    )
    files: Optional[List[RequestFile]] = Field(None, description="Array of file references to be used during execution")


class ExecutionResult(BaseModel):
    """Execution result model as defined in OpenAPI spec."""

    stdout: Optional[str] = None
    stderr: Optional[str] = None
    code: Optional[int] = None
    signal: Optional[str] = None
    output: Optional[str] = None
    memory: Optional[int] = None
    message: Optional[str] = None
    status: Optional[str] = None
    cpu_time: Optional[float] = None
    wall_time: Optional[float] = None


class ExecuteResponse(BaseModel):
    """Execute response model as defined in OpenAPI spec."""

    run: ExecutionResult
    language: str
    version: str
    session_id: str
    files: List[FileRef] = []


class FileMetadata(BaseModel):
    """File metadata model as defined in OpenAPI spec."""

    content_type: Optional[str] = Field(None, alias="content-type")
    original_filename: Optional[str] = Field(None, alias="original-filename")


class FileObject(BaseModel):
    """File object model as defined in OpenAPI spec."""

    name: str  # just request filename, not the path
    id: str
    session_id: str
    content: Optional[str] = None
    size: Optional[int]
    lastModified: Optional[str] = None
    etag: Optional[str] = None
    metadata: Optional[FileMetadata] = None
    contentType: Optional[str] = None


class UploadResponse(BaseModel):
    """Upload response model as defined in OpenAPI spec."""

    message: str
    session_id: str
    files: List[FileObject]


class PathParams(BaseModel):
    """Path parameters model."""

    session_id: str = Field(..., description="Session identifier")
    file_id: str = Field(..., description="File identifier")


class SuccessResponse(BaseModel):
    """Success response model."""

    message: str
