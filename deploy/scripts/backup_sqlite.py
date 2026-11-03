"""Create a consistent SQLite snapshot while Price-Warner remains running."""

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/database.db"))
    parser.add_argument("--output-dir", type=Path, default=Path("backups"))
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error(f"Database not found: {args.database}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = args.output_dir / f"price-warner-{stamp}.sqlite3"
    if destination.exists():
        parser.error(f"Backup already exists: {destination}")

    previous_umask = os.umask(0o077)
    try:
        source = sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True)
        backup = sqlite3.connect(str(destination))
        try:
            source.backup(backup)
            result = backup.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
        except Exception:
            backup.close()
            destination.unlink(missing_ok=True)
            raise
        else:
            backup.close()
        finally:
            source.close()
    finally:
        os.umask(previous_umask)
    print(f"Backup created: {destination}")


if __name__ == "__main__":
    main()
