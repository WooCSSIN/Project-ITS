"""
MinIO Retention Policy — Cron job xóa frames cũ quá N ngày.

Chạy định kỳ (ví dụ mỗi ngày 1 lần qua Task Scheduler / crontab)
hoặc tích hợp vào FastAPI startup với APScheduler.

Usage:
    # Chạy trực tiếp:
    python -m utils.minio_retention_cleanup --days 30

    # Hoặc import:
    from utils.minio_retention_cleanup import MinioRetentionCleaner
    cleaner = MinioRetentionCleaner(retention_days=30)
    cleaner.run()
"""
import os
import sys
import logging
import argparse
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class MinioRetentionCleaner:
    """Xóa các object trong MinIO bucket cũ hơn N ngày."""

    def __init__(self, retention_days: int = 30, bucket_name: str = None, dry_run: bool = False):
        """
        Args:
            retention_days: Số ngày giữ lại. Object cũ hơn sẽ bị xóa.
            bucket_name: Tên bucket. Mặc định lấy từ config.
            dry_run: Nếu True, chỉ log mà không xóa thực sự (dùng để test).
        """
        from minio import Minio
        from core.config import settings_server

        self.retention_days = retention_days
        self.dry_run = dry_run
        self.bucket_name = bucket_name or settings_server.MINIO_BUCKET

        self._client = Minio(
            endpoint=settings_server.MINIO_ENDPOINT,
            access_key=settings_server.MINIO_ACCESS_KEY,
            secret_key=settings_server.MINIO_SECRET_KEY,
            secure=settings_server.MINIO_SECURE,
        )

    def run(self) -> dict:
        """
        Thực hiện cleanup.
        Returns dict với thống kê: {total_scanned, deleted, errors, skipped}.
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        stats = {"total_scanned": 0, "deleted": 0, "errors": 0, "skipped": 0, "bytes_freed": 0}

        logger.info("═" * 60)
        logger.info("MinIO Retention Cleanup")
        logger.info("  Bucket: %s", self.bucket_name)
        logger.info("  Retention: %d days", self.retention_days)
        logger.info("  Cutoff: %s", cutoff_time.isoformat())
        logger.info("  Dry run: %s", self.dry_run)
        logger.info("═" * 60)

        if not self._client.bucket_exists(self.bucket_name):
            logger.warning("Bucket '%s' does not exist. Nothing to clean.", self.bucket_name)
            return stats

        # Liệt kê tất cả objects trong bucket
        objects = self._client.list_objects(self.bucket_name, recursive=True)

        # Gom các objects cần xóa (batch delete hiệu quả hơn)
        from minio.deleteobjects import DeleteObject
        delete_batch = []
        BATCH_SIZE = 1000  # MinIO cho phép delete tối đa 1000 objects/lần

        for obj in objects:
            stats["total_scanned"] += 1

            # Kiểm tra tuổi object
            if obj.last_modified and obj.last_modified < cutoff_time:
                if self.dry_run:
                    logger.info("[DRY RUN] Would delete: %s (modified: %s, size: %d bytes)",
                                obj.object_name, obj.last_modified, obj.size or 0)
                    stats["deleted"] += 1
                    stats["bytes_freed"] += obj.size or 0
                else:
                    delete_batch.append(DeleteObject(obj.object_name))
                    stats["bytes_freed"] += obj.size or 0

                    # Flush batch khi đầy
                    if len(delete_batch) >= BATCH_SIZE:
                        self._flush_delete_batch(delete_batch, stats)
                        delete_batch = []
            else:
                stats["skipped"] += 1

        # Flush batch còn lại
        if delete_batch and not self.dry_run:
            self._flush_delete_batch(delete_batch, stats)

        # Thống kê
        mb_freed = stats["bytes_freed"] / (1024 * 1024)
        logger.info("─" * 60)
        logger.info("Cleanup completed:")
        logger.info("  Total scanned: %d", stats["total_scanned"])
        logger.info("  Deleted: %d", stats["deleted"])
        logger.info("  Skipped (within retention): %d", stats["skipped"])
        logger.info("  Errors: %d", stats["errors"])
        logger.info("  Space freed: %.2f MB", mb_freed)
        logger.info("─" * 60)

        return stats

    def _flush_delete_batch(self, delete_batch: list, stats: dict):
        """Xóa một batch objects từ MinIO."""
        try:
            errors = self._client.remove_objects(self.bucket_name, delete_batch)
            error_count = 0
            for err in errors:
                logger.error("Lỗi xóa object %s: %s", err.name, err.message)
                error_count += 1

            deleted = len(delete_batch) - error_count
            stats["deleted"] += deleted
            stats["errors"] += error_count

            if deleted > 0:
                logger.info("Deleted batch: %d objects", deleted)

        except Exception as e:
            logger.exception("Lỗi khi xóa batch objects: %s", e)
            stats["errors"] += len(delete_batch)


# ═══════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Thêm app vào path
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)

    from core.logging_config import setup_logging
    setup_logging()

    parser = argparse.ArgumentParser(description="MinIO Retention Cleanup — Xóa frames cũ")
    parser.add_argument("--days", type=int, default=30, help="Số ngày giữ lại (mặc định: 30)")
    parser.add_argument("--bucket", type=str, default=None, help="Tên bucket (mặc định: từ config)")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ log, không xóa thực sự")
    args = parser.parse_args()

    cleaner = MinioRetentionCleaner(
        retention_days=args.days,
        bucket_name=args.bucket,
        dry_run=args.dry_run,
    )
    result = cleaner.run()
    print(f"\nResult: {result}")
