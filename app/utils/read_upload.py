from fastapi import UploadFile

CHUNK_SIZE = 64 * 1024


async def read_upload_within_limit(upload_file: UploadFile, max_size: int) -> bytes:
    """Read an UploadFile into memory while enforcing a size limit.

    Rejects oversized files before buffering them fully in memory: the
    multipart-reported size is checked first, and the chunked read aborts as
    soon as the limit is exceeded (guards against a missing/incorrect size).

    Raises:
        ValueError: If the file exceeds max_size bytes.
    """
    if upload_file.size is not None and upload_file.size > max_size:
        raise ValueError(f"File {upload_file.filename} exceeds size limit of {max_size} bytes")

    chunks = []
    total = 0
    while chunk := await upload_file.read(CHUNK_SIZE):
        total += len(chunk)
        if total > max_size:
            raise ValueError(f"File {upload_file.filename} exceeds size limit of {max_size} bytes")
        chunks.append(chunk)
    return b"".join(chunks)
