"""Copy a quiescent data root, verify it, and leave the original until restart.

Only the managed desktop owner chooses the destination and performs the restart.
An HTTP worker cannot safely retarget already assembled runtime objects in place.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from .database import Database, transaction


class RelocationError(ValueError):
    pass


def _linked(path):
    return path.is_symlink() or path.is_junction()


def destination_for(source, value):
    candidate = Path(value)
    if not candidate.is_absolute():
        raise RelocationError('DESTINATION_MUST_BE_ABSOLUTE')
    source = Path(source).resolve()
    if any(_linked(part) for part in (candidate, *candidate.parents)):
        raise RelocationError('DESTINATION_LINK_FORBIDDEN')
    destination = candidate.resolve()
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise RelocationError('DESTINATION_OVERLAPS_SOURCE')
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise RelocationError('DESTINATION_NOT_EMPTY')
    parent = destination.parent
    while not parent.exists():
        parent = parent.parent
    if not parent.is_dir():
        raise RelocationError('DESTINATION_PARENT_INVALID')
    return destination, parent


def _db_digest(connection):
    digest = hashlib.sha256()
    for statement in connection.iterdump():
        digest.update(statement.encode('utf-8'))
        digest.update(b'\n')
    return digest.hexdigest()


def source_manifest(connection, source):
    source = Path(source).resolve()
    if connection.execute("SELECT COUNT(*) FROM task_runs WHERE state NOT IN ('FAILED','CANCELLED','PUBLISHED') OR cancel_pending_remote=1 OR lease_owner IS NOT NULL").fetchone()[0]:
        raise RelocationError('UNRESOLVED_TASKS')
    files = []
    excluded = {'workbench.sqlite3', 'workbench.sqlite3-wal', 'workbench.sqlite3-shm'}
    for path in sorted(source.rglob('*')):
        if _linked(path) or not path.resolve().is_relative_to(source):
            raise RelocationError('SOURCE_LINK_FORBIDDEN')
        if not path.is_file() or path.relative_to(source).as_posix() in excluded:
            continue
        data = path.read_bytes()
        files.append(dict(path=path.relative_to(source).as_posix(), size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
    manifest = dict(database_sha256=_db_digest(connection), files=files)
    version = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return dict(manifest, version=version, required_bytes=sum(item['size_bytes'] for item in files) + (source / 'workbench.sqlite3').stat().st_size + 1048576)


def prepare(connection, source, destination):
    target, parent = destination_for(source, destination)
    manifest = source_manifest(connection, source)
    if shutil.disk_usage(parent).free < manifest['required_bytes']:
        raise RelocationError('DESTINATION_SPACE_INSUFFICIENT')
    probe = parent / ('.workbench-write-probe-' + uuid4().hex)
    try:
        with probe.open('xb') as stream:
            stream.write(b'writeability check')
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if probe.exists():
            probe.unlink()
    return dict(source=str(Path(source).resolve()), destination=str(target), manifest=manifest)


def copy_file(source, target, expected):
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as reader, target.open('xb') as writer:
        shutil.copyfileobj(reader, writer)
        writer.flush()
        os.fsync(writer.fileno())
    if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        raise RelocationError('COPY_HASH_MISMATCH')


def execute(database, prepared):
    source, target = Path(prepared['source']), Path(prepared['destination'])
    # Refuse path/state changes after the user-visible preview.
    destination_for(source, str(target))
    created = []
    with closing(database.connect()) as fence, transaction(fence):
        current = source_manifest(fence, source)
        if current['version'] != prepared['manifest']['version']:
            raise RelocationError('SOURCE_CHANGED_AFTER_PREVIEW')
        if shutil.disk_usage(target.parent if target.parent.exists() else source.parent).free < current['required_bytes']:
            raise RelocationError('DESTINATION_SPACE_INSUFFICIENT')
        target_existed=target.exists()
        target.mkdir(parents=True, exist_ok=True)
        try:
            destination_db = target / 'workbench.sqlite3'
            created.append(destination_db)
            # Separate read connection can back up while the writer fence is held.
            with closing(database.connect()) as reader, closing(sqlite3.connect(destination_db)) as copied:
                reader.backup(copied)
                if copied.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or copied.execute('PRAGMA foreign_key_check').fetchall():
                    raise RelocationError('DATABASE_COPY_INVALID')
                if _db_digest(copied) != current['database_sha256']:
                    raise RelocationError('DATABASE_COPY_CHANGED')
            for item in current['files']:
                output = target / item['path']
                if not output.resolve().is_relative_to(target.resolve()):
                    raise RelocationError('COPY_PATH_INVALID')
                created.append(output)
                copy_file(source / item['path'], output, item['sha256'])
            if source_manifest(fence, source)['version'] != current['version']:
                raise RelocationError('SOURCE_CHANGED_DURING_COPY')
            return dict(verified=True, restart_required=True, source_retained=True,
                database_sha256=current['database_sha256'], files_verified=len(current['files']),
                version=current['version'])
        except BaseException:
            # Remove only files created by this operation; never remove the root.
            for path in reversed(created):
                if path.resolve().is_relative_to(target.resolve()) and path.exists() and not _linked(path):
                    path.unlink()
            for directory in sorted({parent for path in created for parent in path.parents
                    if parent!=target and parent.is_relative_to(target)},key=lambda item:len(item.parts),reverse=True):
                if directory.is_dir() and not _linked(directory) and not any(directory.iterdir()):
                    directory.rmdir()
            if not target_existed and target.is_dir() and not any(target.iterdir()):
                target.rmdir()
            raise
