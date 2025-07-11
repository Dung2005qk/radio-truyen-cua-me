import logging
import os
import sys
from pathlib import Path

# --- Locking Mechanism and Module Imports ---
# This lock file prevents multiple instances of the cleanup script from running simultaneously.
# It is placed in a system-wide temporary directory to be independent of the project path.
LOCK_DIR = Path(os.getenv('TEMP', '/tmp'))
LOCK_FILE = LOCK_DIR / 'radio_truyen_cleanup.lock'
lock_fd = None  # File descriptor for the lock

# --- Main Application Logic ---
def main():
    """
    The main entry point for the cleanup script. It sets up the environment,
    configures logging, and executes the cache cleanup logic in a safe,
    non-concurrent manner.
    """
    # 1. Configure logging as the very first action to capture all subsequent events.
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        stream=sys.stdout
    )

    # Now, import modules that may use logging or environment variables.
    from dotenv import load_dotenv
    from modules.Cache_manager import setup_cache_directory, run_cleanup_routine

    log = logging.getLogger(__name__)

    global lock_fd
    try:
        # 2. Acquire an exclusive lock to prevent concurrent execution.
        # This operation is atomic on POSIX-compliant systems.
        lock_fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        log.warning(f"Cleanup script is already running (lock file exists: {LOCK_FILE}). Exiting.")
        return  # Exit gracefully if another instance is active.
    except PermissionError:
        log.critical(f"Could not create lock file at {LOCK_FILE}. Check permissions. Exiting.")
        return

    try:
        # 3. Load environment variables from a .env file, specifying an absolute path.
        # This ensures reliability when run from different working directories (e.g., cron).
        dotenv_path = Path(__file__).resolve().parent / '.env'
        if dotenv_path.is_file():
            log.info(f"Loading environment variables from {dotenv_path}")
            load_dotenv(dotenv_path=dotenv_path)
        else:
            log.info(".env file not found. Using default values or system environment variables.")
        
        log.info("---[ CACHE CLEANUP SCRIPT STARTED ]---")

        # 4. Ensure the target directory exists.
        setup_cache_directory()

        # 5. Execute the main cleanup routine.
        run_cleanup_routine()

    except Exception as e:
        log.critical(
            f"A critical error occurred, and the cleanup script was halted: {e}",
            exc_info=True
        )
    finally:
        # 6. Always release the lock by closing the file descriptor and deleting the file.
        if lock_fd is not None:
            os.close(lock_fd)
            LOCK_FILE.unlink(missing_ok=True)
        log.info("---[ CACHE CLEANUP SCRIPT FINISHED ]---")


if __name__ == "__main__":
    # To run this script correctly, stand in the project's root directory
    # (the one containing 'modules') and execute: python -m cleanup
    main()