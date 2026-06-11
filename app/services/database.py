import aiosqlite
from loguru import logger
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import List, Dict, Any

from app.shared.const import CONFIG_PATH

from ..shared.config import get_settings

settings = get_settings()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL,
    size INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    etag TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    last_modified TIMESTAMP NOT NULL,
    UNIQUE(session_id, filename)
);

CREATE INDEX IF NOT EXISTS idx_files_last_modified ON files(last_modified);
CREATE INDEX IF NOT EXISTS idx_files_session_id ON files(session_id);
"""


class DatabaseManager:
    def __init__(self):
        self.db_path = CONFIG_PATH / "database.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = None

    async def initialize(self):
        """Initialize the database and create tables."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await db.commit()
        logger.info("Database initialized successfully")

    async def close(self):
        """Close any open database connections."""
        # Since we're using connection per operation, nothing to close
        logger.info("Database connections closed")

    async def add_file(self, file_data: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new file record to the database or update if exists."""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if file exists
            async with db.execute(
                "SELECT id FROM files WHERE session_id = ? AND filename = ?",
                (file_data["session_id"], file_data["filename"]),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing:
                # Update existing record
                await db.execute(
                    """
                    UPDATE files SET
                        id = ?, filepath = ?, size = ?,
                        content_type = ?, original_filename = ?, etag = ?,
                        last_modified = ?
                    WHERE session_id = ? AND filename = ?
                """,
                    (
                        file_data["id"],
                        file_data["filepath"],
                        file_data["size"],
                        file_data["content_type"],
                        file_data["original_filename"],
                        file_data["etag"],
                        datetime.now(UTC).isoformat(),
                        file_data["session_id"],
                        file_data["filename"],
                    ),
                )
            else:
                # Insert new record
                await db.execute(
                    """
                    INSERT INTO files (
                        id, session_id, filename, filepath, size,
                        content_type, original_filename, etag,
                        created_at, last_modified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        file_data["id"],
                        file_data["session_id"],
                        file_data["filename"],
                        file_data["filepath"],
                        file_data["size"],
                        file_data["content_type"],
                        file_data["original_filename"],
                        file_data["etag"],
                        datetime.now(UTC).isoformat(),
                        datetime.now(UTC).isoformat(),
                    ),
                )
            await db.commit()
        return file_data

    async def get_file(self, session_id: str, file_id: str) -> Dict[str, Any]:
        """Get file metadata by session_id and file_id."""
        logger.info(f"Looking up file in database - session_id: {session_id}, file_id: {file_id}")
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM files WHERE session_id = ? AND id = ?", (session_id, file_id)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    logger.info(f"Found file in database: {dict(row)}")
                    return dict(row)
                else:
                    logger.error(f"File not found in database - session_id: {session_id}, file_id: {file_id}")
                    raise FileNotFoundError(f"File {file_id} not found in database")

    async def list_files(self, session_id: str) -> List[Dict[str, Any]]:
        """List all files for a session."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM files WHERE session_id = ?", (session_id,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def delete_file(self, session_id: str, file_id: str) -> bool:
        """Delete a file record."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM files WHERE session_id = ? AND id = ?", (session_id, file_id))
            await db.commit()
            return cursor.rowcount > 0

    async def get_old_files(self, max_age_hours: int = 24) -> List[Dict[str, Any]]:
        """Get file records older than the specified number of hours."""
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM files WHERE last_modified < ?", (cutoff.isoformat(),)) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def delete_files_by_ids(self, file_ids: List[str]) -> int:
        """Delete file records by their ids. Returns the number of deleted rows."""
        if not file_ids:
            return 0
        async with aiosqlite.connect(self.db_path) as db:
            placeholders = ", ".join("?" for _ in file_ids)
            cursor = await db.execute(f"DELETE FROM files WHERE id IN ({placeholders})", file_ids)
            await db.commit()
            return cursor.rowcount


# Create a singleton instance
db_manager = DatabaseManager()
