"""Restore a verified SQLite backup while API and worker services are stopped.

The script refuses databases with WAL/journal sidecar files. It preserves the
previous database in a timestamped backup, then atomically installs the restore.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def checked_backup(source: Path, destination: Path) -> None:
    with sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True) as original:
        with sqlite3.connect(str(destination)) as copy:
            original.backup(copy)
            if copy.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise RuntimeError("SQLite integrity check failed")
            copy.commit()


def restore(backup: Path, database: Path, archive_dir: Path, confirmed: bool = False) -> Path | None:
    if not confirmed:
        raise ValueError("Pass --confirm only after stopping the API and worker")
    if not backup.is_file():
        raise FileNotFoundError(f"Backup does not exist: {backup}")
    if backup.resolve() == database.resolve():
        raise ValueError("Backup and destination cannot be the same file")
    if database.is_symlink():
        raise ValueError("Restoring through a database symlink is not supported")
    if not database.parent.is_dir():
        raise FileNotFoundError(f"Database directory does not exist: {database.parent}")
    for extension in ("-wal", "-shm", "-journal"):
        if Path(str(database) + extension).exists():
            raise RuntimeError(f"Database sidecar exists ({extension}); stop services and resolve it first")

    old_umask = os.umask(0o077)
    staged = None
    prior_copy = None
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        previous = archive_dir / f"before-restore-{timestamp}.sqlite3"
        with tempfile.NamedTemporaryFile(prefix=".price-warner-restore-", suffix=".sqlite3",
                                         dir=database.parent, delete=False) as temporary:
            staged = Path(temporary.name)
        checked_backup(backup, staged)
        os.chmod(staged, 0o600)
        if database.exists():
            if not database.is_file():
                raise ValueError("Destination is not a regular database file")
            with tempfile.NamedTemporaryFile(prefix=".price-warner-prior-", suffix=".sqlite3",
                                             dir=archive_dir, delete=False) as temporary:
                prior_copy = Path(temporary.name)
            try:
                checked_backup(database, prior_copy)
            except sqlite3.DatabaseError:
                prior_copy.unlink(missing_ok=True)
                shutil.copyfile(database, prior_copy)
            os.chmod(prior_copy, 0o600)
            os.replace(prior_copy, previous)
            prior_copy = None
        os.replace(staged, database)
        staged = None
        return previous if previous.is_file() else None
    finally:
        os.umask(old_umask)
        if staged is not None:
            staged.unlink(missing_ok=True)
        if prior_copy is not None:
            prior_copy.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="Existing SQLite backup to restore")
    parser.add_argument("--database", type=Path, default=Path("data/database.db"))
    parser.add_argument("--archive-dir", type=Path, default=Path("backups"))
    parser.add_argument("--confirm", action="store_true", help="Confirm services have been stopped")
    args = parser.parse_args()
    try:
        previous = restore(args.backup, args.database, args.archive_dir, args.confirm)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(f"Restored database: {args.database}")
    if previous:
        print(f"Previous database saved to: {previous}")
    print("Keep the original .env and SMTP_ENCRYPTION_KEY. Restart API and worker now.")


if __name__ == "__main__":
    main()
