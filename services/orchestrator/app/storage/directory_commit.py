"""Commit one owned staging directory; retry only Windows sharing failures."""
import os
from pathlib import Path
import re
import stat
import time

_WINDOWS = os.name == 'nt'
_DELAYS = (.02, .04, .08, .16)


class DirectoryCommitBlocked(OSError):
    """Ownership is uncertain or commit is busy: retain staging, do not delete."""


class DirectoryCommitBusy(DirectoryCommitBlocked):
    def __init__(self, error):
        super().__init__('DIRECTORY_COMMIT_BUSY')
        self.winerror = getattr(error, 'winerror', None)


def _plain(path):
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise DirectoryCommitBlocked('DIRECTORY_COMMIT_REPARSE_DENIED')
    return path.resolve()


def _identity(path):
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode):
        raise DirectoryCommitBlocked('DIRECTORY_COMMIT_DIRECTORY_REQUIRED')
    return info.st_dev, info.st_ino


def commit_owned_directory(source, destination, parent):
    source, destination, parent = (Path(path).absolute() for path in (source, destination, parent))
    if not re.fullmatch(r'\.pending-[a-f0-9]{32}', source.name):
        raise DirectoryCommitBlocked('DIRECTORY_COMMIT_OWNED_STAGING_REQUIRED')
    original_paths = source, destination, parent
    identity = parent_identity = None
    for attempt in range(len(_DELAYS)+1):
        try:
            paths = tuple(_plain(path) for path in original_paths)
            if paths != original_paths or source.parent != parent or destination.parent != parent or source == destination:
                raise DirectoryCommitBlocked('DIRECTORY_COMMIT_SCOPE_CHANGED')
            if destination.exists() or destination.is_symlink():
                raise DirectoryCommitBlocked('DIRECTORY_COMMIT_DESTINATION_EXISTS')
            current, current_parent = _identity(source), _identity(parent)
            if identity is not None and (current != identity or current_parent != parent_identity):
                raise DirectoryCommitBlocked('DIRECTORY_COMMIT_OWNERSHIP_CHANGED')
            identity, parent_identity = current, current_parent
        except DirectoryCommitBlocked:
            raise
        except OSError as error:
            raise DirectoryCommitBlocked('DIRECTORY_COMMIT_SCOPE_UNAVAILABLE') from error
        try:
            return source.rename(destination)
        except OSError as error:
            if not _WINDOWS or getattr(error, 'winerror', None) not in {5, 32, 33}:
                raise
            if attempt == len(_DELAYS):
                raise DirectoryCommitBusy(error) from error
            time.sleep(_DELAYS[attempt])
