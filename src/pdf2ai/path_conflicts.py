"""Detect actual filesystem aliases, including case and Unicode name variants."""
import os
from pathlib import Path
import tempfile


def paths_conflict(first, second):
    first, second = Path(first), Path(second)
    if os.fspath(first.resolve()) == os.fspath(second.resolve()):
        return True
    try:
        return os.path.samefile(first, second)
    except (FileNotFoundError, NotADirectoryError):
        return False


def duplicate_destinations(paths):
    paths = [Path(path) for path in paths]
    if len({os.fspath(path.resolve()) for path in paths}) != len(paths):
        return True
    groups = {}
    for path in paths:
        parent = path.parent.stat()
        groups.setdefault((parent.st_dev, parent.st_ino), []).append(path)
    for group in groups.values():
        if len(group) < 2:
            continue
        # Probe names inside an isolated temporary directory on the destination
        # filesystem. This respects its actual case/Unicode rules rather than
        # guessing from the OS or rejecting distinct names on a sensitive volume.
        with tempfile.TemporaryDirectory(prefix='.pdf2ai-path-check-', dir=group[0].parent) as directory:
            for path in group:
                try:
                    descriptor = os.open(Path(directory)/path.name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError:
                    return True
                else:
                    os.close(descriptor)
    return False
