import asyncio
from loguru import logger
from typing import List, Optional

from ..shared.config import get_settings
from ..shared.const import UPLOAD_PATH
from .database import db_manager

settings = get_settings()

class CleanupService:
    def __init__(self):
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def cleanup_files(self):
        """Cleanup files older than the configured max age."""
        try:
            old_files = await db_manager.get_old_files(
                max_age_hours=settings.CLEANUP_FILE_MAX_AGE // 3600  # Convert seconds to hours
            )

            # Delete disk files first; only drop DB rows for files actually
            # gone from disk so failures are retried on the next run.
            deleted_ids: List[str] = []
            for file_info in old_files:
                try:
                    file_path = UPLOAD_PATH / file_info["filepath"]
                    if file_path.exists():
                        file_path.unlink()
                        logger.info(f"Deleted file: {file_path}")

                    deleted_ids.append(file_info["id"])

                    # Clean up empty session directories
                    session_dir = file_path.parent
                    if session_dir.exists() and not any(session_dir.iterdir()):
                        session_dir.rmdir()
                        logger.info(f"Removed empty session directory: {session_dir}")

                except Exception as e:
                    logger.error(f"Error deleting file {file_info['filepath']}: {e}")

            await db_manager.delete_files_by_ids(deleted_ids)

            if deleted_ids:
                logger.info(f"Cleaned up {len(deleted_ids)} old files")

        except Exception as e:
            logger.error(f"Error during file cleanup: {e}")

    async def _cleanup_loop(self):
        """Background task that runs the cleanup periodically."""
        while self._running:
            try:
                await self.cleanup_files()
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
            
            await asyncio.sleep(settings.CLEANUP_RUN_INTERVAL)

    async def start(self):
        """Start the cleanup service."""
        if self._cleanup_task is None:
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("File cleanup service started")

    async def stop(self):
        """Stop the cleanup service."""
        if self._cleanup_task is not None:
            self._running = False
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("File cleanup service stopped")

# Create a singleton instance
cleanup_service = CleanupService() 