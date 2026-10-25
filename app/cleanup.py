import os
import shutil
import time
import logging
from pathlib import Path
from typing import Union, Sequence
from fastapi import UploadFile

logger = logging.getLogger("screener.cleanup")


async def safe_close_upload(file: UploadFile) -> None:
    """
    Menutup UploadFile dan memastikan file spool/temporary Starlette
    di disk OS langsung dihapus dari memori/filesystem.
    """
    if file:
        try:
            await file.close()
        except Exception as e:
            logger.debug(f"Gagal menutup upload file {file.filename}: {e}")


def remove_path(path: Union[str, Path]) -> None:
    """
    Menghapus file atau direktori sementara setelah response dikembalikan ke client.
    """
    if not path:
        return
    try:
        p = Path(path)
        if p.is_file() or p.is_symlink():
            p.unlink(missing_ok=True)
            logger.debug(f"Residual file terhapus: {p}")
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            logger.debug(f"Residual direktori terhapus: {p}")
    except Exception as e:
        logger.warning(f"Gagal menghapus residual path {path}: {e}")


def cleanup_residuals(paths: Sequence[Union[str, Path]]) -> None:
    """
    Handler background task untuk menghapus sekumpulan file/direktori residual.
    """
    for p in paths:
        remove_path(p)


def clean_stale_files(directory: Union[str, Path], max_age_seconds: int = 3600) -> int:
    """
    Membersihkan file yatim/stale di folder temporary (misal jika ada proses crash sebelumnya).
    Dipanggil saat startup aplikasi atau shutdown.
    """
    d = Path(directory)
    if not d.exists() or not d.is_dir():
        return 0
    now = time.time()
    count = 0
    for item in d.iterdir():
        try:
            if item.is_file() and (now - item.stat().st_mtime > max_age_seconds):
                item.unlink(missing_ok=True)
                count += 1
            elif item.is_dir() and (now - item.stat().st_mtime > max_age_seconds):
                shutil.rmtree(item, ignore_errors=True)
                count += 1
        except Exception:
            pass
    if count:
        logger.info(f"Dibersihkan {count} file stale residual di {directory}")
    return count
