"""Tests for the TTL-based file cleanup service."""

from datetime import datetime, timedelta, UTC

import aiosqlite

from app.services.cleanup import cleanup_service
from app.services.database import db_manager
from app.shared.const import UPLOAD_PATH
from app.utils.generate_id import generate_id


async def _make_old_file(session_id: str, filename: str, age_hours: int) -> str:
    """Create a file on disk and a matching DB row backdated by age_hours."""
    file_id = generate_id()
    session_dir = UPLOAD_PATH / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / filename).write_text("stale content")

    await db_manager.add_file(
        {
            "id": file_id,
            "session_id": session_id,
            "filename": filename,
            "filepath": f"{session_id}/{filename}",
            "size": 13,
            "content_type": "text/plain",
            "original_filename": filename,
            "etag": "etag",
        }
    )

    backdated = (datetime.now(UTC) - timedelta(hours=age_hours)).isoformat()
    async with aiosqlite.connect(db_manager.db_path) as db:
        await db.execute("UPDATE files SET last_modified = ? WHERE id = ?", (backdated, file_id))
        await db.commit()

    return file_id


async def test_cleanup_removes_old_files_from_disk_and_db():
    """Old files are deleted from disk and DB, and empty session dirs are removed."""
    session_id = generate_id()
    file_id = await _make_old_file(session_id, "old.txt", age_hours=48)

    await cleanup_service.cleanup_files()

    assert not (UPLOAD_PATH / session_id / "old.txt").exists()
    assert not (UPLOAD_PATH / session_id).exists()

    files = await db_manager.list_files(session_id)
    assert all(f["id"] != file_id for f in files)


async def test_cleanup_keeps_recent_files():
    """Files newer than the max age are untouched."""
    session_id = generate_id()
    file_id = await _make_old_file(session_id, "fresh.txt", age_hours=1)

    await cleanup_service.cleanup_files()

    assert (UPLOAD_PATH / session_id / "fresh.txt").exists()
    files = await db_manager.list_files(session_id)
    assert any(f["id"] == file_id for f in files)

    # Cleanup the test artifacts
    (UPLOAD_PATH / session_id / "fresh.txt").unlink()
    (UPLOAD_PATH / session_id).rmdir()
    await db_manager.delete_file(session_id, file_id)


async def test_cleanup_removes_db_row_when_disk_file_already_gone():
    """Rows whose disk file is already missing are still cleaned up."""
    session_id = generate_id()
    file_id = await _make_old_file(session_id, "ghost.txt", age_hours=48)
    (UPLOAD_PATH / session_id / "ghost.txt").unlink()

    await cleanup_service.cleanup_files()

    files = await db_manager.list_files(session_id)
    assert all(f["id"] != file_id for f in files)
