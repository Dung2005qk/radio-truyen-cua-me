import os
import time
import logging
import typing
from pathlib import Path

# --- Module-level Configuration and Logging ---

log = logging.getLogger(__name__)

def _get_env_var(name: str, default: int) -> int:
    """Safely retrieves and casts an integer environment variable."""
    value_str = os.getenv(name)
    if value_str is None:
        return default
    try:
        return int(value_str)
    except (ValueError, TypeError):
        log.warning(
            f"Invalid value for env var '{name}': '{value_str}'. "
            f"Using default value: {default}."
        )
        return default

# Directory where audio cache files are stored.
CACHE_DIR_NAME = "audio_cache"
# Absolute path to the cache directory.
CACHE_DIR_PATH = Path(__file__).resolve().parent.parent / CACHE_DIR_NAME

# Configuration for cleanup routines, loaded from environment variables.
CACHE_MAX_AGE_DAYS = _get_env_var("CACHE_MAX_AGE_DAYS", 7)
CACHE_MAX_SIZE_MB = _get_env_var("CACHE_MAX_SIZE_MB", 400)
CACHE_CLEANUP_TARGET_PERCENT = _get_env_var("CACHE_CLEANUP_TARGET_PERCENT", 70)

# Pre-calculated byte values and constants for efficiency.
CACHE_MAX_SIZE_BYTES = CACHE_MAX_SIZE_MB * 1024 * 1024
CACHE_CLEANUP_TARGET_BYTES = CACHE_MAX_SIZE_BYTES * (CACHE_CLEANUP_TARGET_PERCENT / 100)
SECONDS_IN_A_DAY = 86400
STALE_TEMP_FILE_SECONDS = 3600  # 1 hour


# --- Public API Functions ---

def setup_cache_directory() -> None:
    """
    Ensures the cache directory exists. Should be called once on application startup.
    """
    try:
        CACHE_DIR_PATH.mkdir(parents=True, exist_ok=True)
        log.info(f"Cache directory ensured at: {CACHE_DIR_PATH}")
    except OSError as e:
        log.critical(f"Failed to create or access cache directory at {CACHE_DIR_PATH}. Error: {e}")
        raise


def get_path_from_key(key: str) -> Path:
    """
    Converts a unique key into a full, OS-agnostic file path for the final cache file.
    """
    return CACHE_DIR_PATH / f"{key}.mp3"


def check_cache_exists(file_path: Path) -> bool:
    """
    Checks if a cache file exists. This function has no side effects.
    """
    return file_path.is_file()


def touch_cache_file(file_path: Path) -> None:
    """
    Updates a file's access and modification time to mark it as recently used.
    This is crucial for the LRU (Least Recently Used) cleanup strategy.
    """
    try:
        # 'touch' the file to update its modification time.
        os.utime(file_path, None)
    except OSError as e:
        log.error(f"Failed to touch cache file {file_path}: {e}")


def stream_from_path(file_path: Path) -> typing.Generator[bytes, None, None]:
    """
    Streams a file from the cache in chunks.
    This is a generator function to avoid loading the whole file into memory.
    It defensively handles FileNotFoundError to mitigate race conditions with cleanup jobs.
    """
    try:
        with file_path.open('rb') as f:
            while chunk := f.read(8192):
                yield chunk
    except FileNotFoundError:
        log.warning(f"Cache file {file_path} was deleted during access (race condition).")
        return
    except OSError as e:
        log.error(f"Error reading from cache file {file_path}: {e}")
        return


# --- Core Cleanup Logic ---

def run_cleanup_routine() -> None:
    """
    Executes the full cache cleanup process.
    This is the main entry point for automated housekeeping tasks (e.g., cron jobs).
    """
    if not CACHE_DIR_PATH.exists():
        log.info("Cache directory does not exist, skipping cleanup.")
        return

    log.info("Starting cache cleanup routine...")
    deleted_by_age = _cleanup_by_age()
    if deleted_by_age > 0:
        log.info(f"Cleanup by age: Removed {deleted_by_age} old or stale file(s).")

    deleted_by_size = _cleanup_by_size()
    if deleted_by_size > 0:
        log.info(f"Cleanup by size: Removed {deleted_by_size} file(s) to free up space.")

    log.info("Cache cleanup routine finished.")


def _cleanup_by_age() -> int:
    """
    (Private) Deletes files older than CACHE_MAX_AGE_DAYS and stale temporary files.
    Stale files (.tmp, .lock) are removed if they are older than STALE_TEMP_FILE_SECONDS.
    """
    deleted_count = 0
    now = time.time()
    cutoff_time = now - (CACHE_MAX_AGE_DAYS * SECONDS_IN_A_DAY)
    stale_cutoff_time = now - STALE_TEMP_FILE_SECONDS

    try:
        for path in CACHE_DIR_PATH.iterdir():
            try:
                stat_result = path.stat()
                mtime = stat_result.st_mtime

                is_stale_temp_file = (path.suffix in {'.tmp', '.lock'}) and (mtime < stale_cutoff_time)
                is_old_cache_file = mtime < cutoff_time

                if is_old_cache_file or is_stale_temp_file:
                    path.unlink()
                    deleted_count += 1
            except FileNotFoundError:
                # File was deleted by another process, ignore.
                continue
            except OSError as e:
                log.error(f"Could not process or delete file {path} during age cleanup: {e}")
    except OSError as e:
        log.error(f"Could not scan cache directory for age cleanup: {e}")

    return deleted_count


def _cleanup_by_size() -> int:
    """
    (Private) If total cache size exceeds the limit, deletes the least recently used
    files until the total size is below the target percentage.
    """
    files_to_scan = []
    total_size = 0

    try:
        for path in CACHE_DIR_PATH.iterdir():
            if not path.is_file():
                continue
            try:
                stat = path.stat()
                files_to_scan.append({'path': path, 'size': stat.st_size, 'mtime': stat.st_mtime})
                total_size += stat.st_size
            except FileNotFoundError:
                continue
            except OSError as e:
                log.error(f"Could not stat file {path} during size scan: {e}")
    except OSError as e:
        log.error(f"Could not scan cache directory for size cleanup: {e}")
        return 0

    if total_size < CACHE_MAX_SIZE_BYTES:
        return 0

    log.info(
        f"Cache size ({total_size / 1024**2:.2f}MB) exceeds limit "
        f"({CACHE_MAX_SIZE_MB}MB). Starting LRU cleanup."
    )

    files_to_scan.sort(key=lambda x: x['mtime'])

    deleted_count = 0
    for file_info in files_to_scan:
        if total_size < CACHE_CLEANUP_TARGET_BYTES:
            break
        try:
            file_info['path'].unlink()
            total_size -= file_info['size']
            deleted_count += 1
        except FileNotFoundError:
            # File already deleted, but we must still account for the size reduction.
            total_size -= file_info['size']
            continue
        except OSError as e:
            log.error(f"Could not delete file {file_info['path']} during size cleanup: {e}")

    log.info(f"Finished LRU cleanup. New size: {total_size / 1024**2:.2f}MB.")
    return deleted_count