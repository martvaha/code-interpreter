from fastapi import APIRouter, UploadFile, File, HTTPException, Path, Form, Request
from fastapi.responses import JSONResponse, StreamingResponse
from typing import List, Optional, Union
from loguru import logger
from io import BytesIO

from app.api.exceptions import BadLanguageException

from ..models.base import (
    PathParams,
    SuccessResponse,
    CodeExecutionRequest,
)
from ..models.librechat import (
    LibreChatExecuteResponse,
    LibreChatUploadResponse,
    LibreChatBatchUploadFileResult,
    LibreChatBatchUploadResponse,
    LibreChatSessionObjectInfo,
    LibreChatFileObject,
    LibreChatError,
)
from ..services.database import db_manager
from ..services.file_manager import file_manager
from ..shared.config import get_settings
from app.utils.generate_id import generate_id
from app.utils.read_upload import read_upload_within_limit
from .base import (
    execute_code as base_execute_code,
    upload_files as base_upload_files,
    download_file as base_download_file,
    list_files as base_list_files,
    delete_file as base_delete_file,
)

settings = get_settings()
router = APIRouter(prefix=f"{settings.API_PREFIX}/librechat", tags=["librechat"])


def create_error_response(status_code: int, message: str) -> JSONResponse:
    """Create a standardized error response for the LibreChat API.

    Args:
        status_code (int): HTTP status code to return
        message (str): Error message to include in the response

    Returns:
        JSONResponse: A FastAPI JSON response containing the error details in LibreChat format
    """
    return JSONResponse(status_code=status_code, content=LibreChatError(message=message).model_dump())


@router.post(
    "/exec",
    responses={400: {"model": LibreChatError}, 500: {"model": LibreChatError}},
    response_model=LibreChatExecuteResponse,
    response_model_exclude_none=True,
    description="Execute code in a sandboxed environment",
    summary="Execute code",
    response_description="Returns the execution results",
)
async def execute_code(request: CodeExecutionRequest) -> Union[LibreChatExecuteResponse, JSONResponse]:
    """Execute code in a sandboxed environment.

    This endpoint handles code execution requests from LibreChat. It processes the provided
    code in an isolated environment and returns the execution results.

    Args:
        request (CodeExecutionRequest): Request object containing:
            - code: Code to execute
            - files: Optional list of files needed for execution
            - language: Programming language ('py' for Python or 'r' for R)
            - stdin: Optional standard input for the code

    Returns:
        LibreChatExecuteResponse: Object containing:
            - output: Execution output (stdout/stderr)
            - error: Error message if execution failed
            - exitCode: Process exit code

    Raises:
        HTTPException:
            - 400: Invalid request parameters
            - 401: Unauthorized access
            - 500: Internal server error during execution
            - 503: Service temporarily unavailable
    """
    try:
        logger.info(f"Executing code request: {request.model_dump_json()}")

        result = await base_execute_code(request)
        logger.debug(f"Execution result: {result}")
        return LibreChatExecuteResponse.from_base(result)
    except BadLanguageException as e:
        # Surface the message via stdout in a 200 response so LibreChat
        # relays it to the model instead of treating it as a request failure
        return LibreChatExecuteResponse(
            session_id=request.session_id or generate_id(),
            stdout=f"{e.detail}",
            stderr="",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in execute_code: {str(e)}", exc_info=True)
        return create_error_response(500, str(e))


@router.post(
    "/upload",
    responses={413: {"model": LibreChatError}, 400: {"model": LibreChatError}, 500: {"model": LibreChatError}},
    description="Upload files for code execution",
    summary="Upload files",
    response_description="Returns information about the uploaded files",
)
async def upload_files(
    request: Request,
    file: UploadFile = File(...),
    kind: Optional[str] = Form(None),
    id: Optional[str] = Form(None),
    version: Optional[str] = Form(None),
) -> JSONResponse:
    """Upload a file for use in code execution.

    Files are stored in a new storage session and can be referenced in
    subsequent execution requests via (storage_session_id, fileId).

    Args:
        request (Request): The FastAPI request object containing metadata
        file (UploadFile): The file to be uploaded
        kind (Optional[str]): Resource kind owning the file ('skill' | 'agent' | 'user')
        id (Optional[str]): Resource identifier (skillId / agentId / userId)
        version (Optional[str]): Resource version, sent for kind == 'skill'

    Returns:
        JSONResponse: Response containing:
            - message: 'success' on success
            - storage_session_id: Storage session the file was uploaded to
            - files: List of uploaded file objects ({fileId, filename})

    Raises:
        HTTPException:
            - 400: Invalid file or request parameters
            - 413: File size exceeds maximum allowed size
            - 500: Internal server error during upload
    """
    try:
        logger.info(f"File: {file.filename}, content_type: {file.content_type}, kind: {kind}, id: {id}")

        try:
            content = await read_upload_within_limit(file, settings.FILE_MAX_UPLOAD_SIZE)
        except ValueError:
            return create_error_response(413, f"File exceeds size limit of {settings.FILE_MAX_UPLOAD_SIZE} bytes")
        logger.debug(f"File size: {len(content)} bytes")

        # Reset file pointer and prepare for upload
        file.file = BytesIO(content)
        response = await base_upload_files(files=[file])

        if not response.files:
            return create_error_response(500, "File upload failed")

        result = LibreChatUploadResponse.from_base(response)
        logger.info(f"Upload successful: {result.model_dump()}")

        return JSONResponse(content=result.model_dump())

    except Exception as e:
        logger.error(f"Error processing upload: {str(e)}", exc_info=True)
        return create_error_response(400, str(e))


@router.post(
    "/upload/batch",
    responses={413: {"model": LibreChatError}, 400: {"model": LibreChatError}, 500: {"model": LibreChatError}},
    description="Upload multiple files sharing one storage session",
    summary="Batch upload files",
    response_description="Returns per-file upload results and the shared storage session",
)
async def upload_files_batch(
    request: Request,
    file: List[UploadFile] = File(...),
    kind: Optional[str] = Form(None),
    id: Optional[str] = Form(None),
    version: Optional[str] = Form(None),
    read_only: Optional[str] = Form(None),
) -> JSONResponse:
    """Upload multiple files in a single request, sharing one storage session.

    Each file is processed independently: failures are reported per file
    instead of failing the whole batch.
    """
    try:
        if len(file) > settings.FILE_MAX_BATCH_COUNT:
            return create_error_response(
                413,
                f"Too many files in batch: {len(file)} exceeds limit of {settings.FILE_MAX_BATCH_COUNT}",
            )

        session_id = generate_id()
        logger.info(f"Batch upload of {len(file)} files to session {session_id}, kind: {kind}, id: {id}")

        results: List[LibreChatBatchUploadFileResult] = []
        for upload_file in file:
            try:
                content = await read_upload_within_limit(upload_file, settings.FILE_MAX_UPLOAD_SIZE)

                file_info = await file_manager.save_file(
                    session_id=session_id, file_content=content, filename=upload_file.filename
                )
                results.append(
                    LibreChatBatchUploadFileResult(
                        status="success", fileId=file_info["id"], filename=upload_file.filename
                    )
                )
            except Exception as e:
                logger.error(f"Batch upload failed for {upload_file.filename}: {str(e)}")
                results.append(
                    LibreChatBatchUploadFileResult(status="error", filename=upload_file.filename, error=str(e))
                )

        succeeded = sum(1 for r in results if r.status == "success")
        failed = len(results) - succeeded
        response = LibreChatBatchUploadResponse(
            message="error" if succeeded == 0 else "success",
            storage_session_id=session_id,
            files=results,
            succeeded=succeeded,
            failed=failed,
        )
        return JSONResponse(content=response.model_dump())

    except Exception as e:
        logger.error(f"Error processing batch upload: {str(e)}", exc_info=True)
        return create_error_response(400, str(e))


@router.get(
    "/sessions/{session_id}/objects/{file_id}",
    response_model=LibreChatSessionObjectInfo,
    responses={404: {"model": LibreChatError}},
    description="Get metadata for a stored file object (used as a liveness check)",
    summary="Get session object info",
    response_description="Returns the object's last modified timestamp",
)
async def get_session_object(
    session_id: str = Path(..., description=PathParams.model_fields["session_id"].description),
    file_id: str = Path(..., description=PathParams.model_fields["file_id"].description),
) -> Union[LibreChatSessionObjectInfo, JSONResponse]:
    """Return lastModified for a stored file.

    LibreChat probes this endpoint before each execution to decide whether a
    previously uploaded file is still available or must be re-uploaded.
    """
    try:
        file_info = await db_manager.get_file(session_id, file_id)
        return LibreChatSessionObjectInfo(lastModified=file_info["last_modified"])
    except FileNotFoundError:
        return create_error_response(404, f"File {file_id} not found")
    except Exception as e:
        logger.error(f"Error getting session object: {str(e)}", exc_info=True)
        return create_error_response(404, str(e))


@router.delete(
    "/sessions/{session_id}/objects/{file_id}",
    response_model=SuccessResponse,
    responses={404: {"model": LibreChatError}},
    description="Delete a stored file object",
    summary="Delete session object",
    response_description="Returns a success message if the object was deleted",
)
async def delete_session_object(
    session_id: str = Path(..., description=PathParams.model_fields["session_id"].description),
    file_id: str = Path(..., description=PathParams.model_fields["file_id"].description),
) -> Union[SuccessResponse, JSONResponse]:
    """Delete a stored file object by storage session and file id."""
    try:
        return await base_delete_file(session_id=session_id, file_id=file_id)
    except Exception as e:
        logger.error(f"Error deleting session object: {str(e)}", exc_info=True)
        return create_error_response(404, str(e))


@router.get(
    "/download/{session_id}/{file_id}",
    responses={404: {"model": LibreChatError}, 400: {"model": LibreChatError}},
    description="Download a file by session ID and file ID",
    summary="Download a file",
    response_description="Returns the file as a streaming response",
)
async def download_file(
    session_id: str = Path(..., description=PathParams.model_fields["session_id"].description),
    file_id: str = Path(..., description=PathParams.model_fields["file_id"].description),
) -> StreamingResponse:
    """Download a previously uploaded file.

    Retrieves a file that was previously uploaded and streams it back to the client.
    Files are identified by both session ID and file ID for security.

    Args:
        session_id (str): Unique identifier for the session that owns the file
        file_id (str): Unique identifier for the specific file to download

    Returns:
        StreamingResponse: Streams the file content with appropriate content type

    Raises:
        HTTPException:
            - 400: Invalid request parameters
            - 404: File not found
    """
    try:
        logger.info(f"Downloading file {file_id} from session {session_id}")
        return await base_download_file(session_id=session_id, file_id=file_id)
    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}", exc_info=True)
        return create_error_response(404, str(e))


@router.get(
    "/files/{session_id}",
    response_model=List[LibreChatFileObject],
    responses={400: {"model": LibreChatError}, 404: {"model": LibreChatError}},
    description="List all files associated with a session",
    summary="List session files",
    response_description="Returns a list of file objects for the session",
)
async def list_files(
    session_id: str = Path(..., description=PathParams.model_fields["session_id"].description),
    detail: Optional[str] = None,
) -> JSONResponse:
    """List all files associated with a session.

    Retrieves metadata for all files uploaded in a specific session.

    Args:
        session_id (str): Unique identifier for the session
        detail (Optional[str], optional): Level of detail to include in the response.
            If provided, may include additional file metadata.

    Returns:
        JSONResponse: List of LibreChatFileObject containing file metadata:
            - id: Unique file identifier
            - name: Original filename
            - type: File MIME type
            - size: File size in bytes
            - path: Internal storage path
            - session_id: Associated session identifier

    Raises:
        HTTPException:
            - 400: Invalid session ID or parameters
            - 404: Session not found
    """
    try:
        logger.info(f"Listing files for session {session_id}, detail={detail}")
        files = await base_list_files(session_id=session_id)
        logger.debug(f"Found {len(files)} files")

        result: List[LibreChatFileObject] = []
        for file in files:
            logger.debug(f"Processing file: {file.model_dump_json()}")
            file_data = LibreChatFileObject.from_base(file)
            result.append(file_data)

        return result

    except Exception as e:
        logger.error(f"Error listing files: {str(e)}", exc_info=True)
        return create_error_response(400, str(e))


@router.delete(
    "/files/{session_id}/{file_id}",
    response_model=SuccessResponse,
    responses={404: {"model": LibreChatError}, 400: {"model": LibreChatError}},
    description="Delete a specific file by session ID and file ID",
    summary="Delete a file",
    response_description="Returns a success message if file was deleted",
)
async def delete_file(
    session_id: str = Path(..., description=PathParams.model_fields["session_id"].description),
    file_id: str = Path(..., description=PathParams.model_fields["file_id"].description),
) -> SuccessResponse:
    """Delete a specific file from storage.

    Permanently removes a file from the system. The file must belong to the specified session.

    Args:
        session_id (str): Unique identifier for the session that owns the file
        file_id (str): Unique identifier for the specific file to delete

    Returns:
        SuccessResponse: Object confirming successful deletion with message

    Raises:
        HTTPException:
            - 400: Invalid request parameters
            - 404: File or session not found
    """
    try:
        logger.info(f"Deleting file {file_id} from session {session_id}")
        return await base_delete_file(session_id=session_id, file_id=file_id)
    except Exception as e:
        logger.error(f"Error deleting file: {str(e)}", exc_info=True)
        return create_error_response(404, str(e))
