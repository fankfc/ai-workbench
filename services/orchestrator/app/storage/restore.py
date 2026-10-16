"""Restore to a verified sibling root; the desktop owner performs the switch."""
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from .backup import (BackupError, reject_links, validate_backup, assert_quiescent,
                     copy_verified, discard_owned, inspect_database, verify_references, sha_file)
from .database import Database, transaction
from .migrations import migrate
from .directory_commit import DirectoryCommitBlocked, commit_owned_directory


def restore_backup(bundle_path: Path, data_root: Path) -> dict:
    """Never overwrite live files, even after a successful restore.

    Hold a SQLite writer fence across copy/migration, then return a destination
    for the managed owner. HTTP integration remains frozen until restart.
    """
    source = reject_links(data_root)
    if not source.is_dir() or not (source / 'workbench.sqlite3').is_file():
        raise BackupError('RESTORE_LIVE_DATABASE_MISSING')
    bundle = reject_links(bundle_path)
    if source == bundle or source.is_relative_to(bundle) or bundle.is_relative_to(source):
        raise BackupError('BACKUP_RESTORE_OVERLAPS_SOURCE')
    report = validate_backup(bundle)
    parent = reject_links(source.parent)
    if shutil.disk_usage(parent).free < report['size_bytes'] * 2 + 1048576:
        raise BackupError('RESTORE_SPACE_INSUFFICIENT')
    pending = parent / ('.pending-' + uuid4().hex)
    destination = parent / (source.name + '-restored-' + uuid4().hex[:12])
    pending.mkdir()
    try:
        with closing(Database(source / 'workbench.sqlite3').connect()) as fence, transaction(fence):
            assert_quiescent(fence, restoring=True)
            for name, digest in report['hashes'].items(): copy_verified(bundle / name, pending / name, digest)
            if validate_backup(bundle)['manifest_sha256'] != report['manifest_sha256']:
                raise BackupError('BACKUP_CHANGED_AFTER_VALIDATION')
            with closing(Database(pending / 'workbench.sqlite3').connect()) as c:
                migrated_version = migrate(c)
                c.execute('REINDEX')
                verify_references(c, pending)
                checkpoint = c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                if checkpoint[0] != 0: raise BackupError('RESTORE_CHECKPOINT_PENDING')
            inspect_database(pending / 'workbench.sqlite3')
            restored_hashes = {name: sha_file(pending / name) for name in report['hashes']}
        commit_owned_directory(pending, destination, parent)
        return dict(verified=True, restore_state='VERIFIED', restart_required=True, source_retained=True,
            destination=str(destination), files_verified=report['files_verified'],
            original_schema_version=report['schema_version'], schema_version=migrated_version,
            credential_restored=False, reconnect_required=True, derived_indexes='sqlite_indexes_rebuilt',
            hashes=restored_hashes, original_hashes=report['hashes'])
    except DirectoryCommitBlocked:
        raise
    except BaseException:
        discard_owned(pending, parent)
        raise
