"""Reading and writing the tool's JSON files."""
import json
import os
import time
from pathlib import Path


def write_json(path: Path, data) -> None:
    """Write to a temporary file beside it, then swap it in, so a crash midway leaves the old file whole."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    # Windows refuses to replace a file another program has open for a moment (a virus scan, the indexer).
    for attempt in range(10):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.05)


def read_json(path: Path, default=None):
    """The file's data, or `default` when it's missing or unreadable (a cache is rebuilt rather than trusted)."""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default
