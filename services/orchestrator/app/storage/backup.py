"""SQLite online snapshots with a frozen, verified set of immutable references.

The portable format is a directory with manifest.json, exported as a ZIP by
the private API. ZIP input is untrusted and never passed to extractall().
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
from uuid import uuid4
import zipfile

from .blobs import BlobStore, read_artifact
from .cleanup import HEX, inventory
from .database import Database, transaction
from .migrations import Migration, migrate
from .directory_commit import DirectoryCommitBlocked, commit_owned_directory

FORMAT_VERSION = 1
APP_VERSION = '0.1.0'
MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 20000
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
SECRET_NAMES = {'.env', 'credentials', 'credentials.json', 'auth.json', 'secrets.json'}


class BackupError(ValueError):
    pass


def reject_links(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        try: info = part.lstat()
        except FileNotFoundError: continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise BackupError('BACKUP_LINK_FORBIDDEN')
    return path.resolve()


def safe_name(name):
    if not isinstance(name, str) or not name or any(c in name for c in '\\:%<>"|?*') or any(ord(c) < 32 for c in name):
        raise BackupError('BACKUP_PATH_INVALID')
    parts = name.split('/')
    if any(not p or p in {'.', '..'} or p.rstrip(' .') != p or p.split('.')[0].upper() in RESERVED or p.lower() in SECRET_NAMES for p in parts):
        raise BackupError('BACKUP_PATH_INVALID')
    allowed = name in {'manifest.json', 'workbench.sqlite3'}
    allowed |= bool(re.fullmatch(r'blobs/[a-f0-9]{2}/[a-f0-9]{64}', name))
    allowed |= len(parts) >= 2 and parts[0] == 'evidence'
    allowed |= (len(parts) >= 5 and parts[0] == 'tasks' and
                all(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', p) for p in parts[1:3]) and
                parts[3] in {'input', 'a', 'b', 'translation', 'evidence', 'artifacts'})
    allowed |= len(parts) == 4 and parts[0] == 'tasks' and parts[-1] == '.source-manifest.json' and all(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', p) for p in parts[1:3])
    if not allowed:
        raise BackupError('BACKUP_PATH_NOT_MANAGED')
    return name


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
    return digest.hexdigest()


def schema_chain():
    return [Migration(int(p.name.split('_')[0]), p.stem, p.read_text(encoding='utf-8'))
            for p in sorted((Path(__file__).parent / 'schema').glob('[0-9]*_*.sql'))]


def _schema_objects(connection):
    return list(connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"))


def inspect_database(path):
    """Inspect read-only, attest known schema SQL, and reject future versions."""
    try:
        connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
        with closing(connection):
            connection.execute('PRAGMA trusted_schema=OFF')
            if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or connection.execute('PRAGMA foreign_key_check').fetchall():
                raise BackupError('BACKUP_DATABASE_INVALID')
            history = connection.execute('SELECT version,name,sha256 FROM schema_version ORDER BY version').fetchall()
            chain = schema_chain()
            if not history or len(history) > len(chain): raise BackupError('BACKUP_SCHEMA_INCOMPATIBLE')
            expected = [(m.version, m.name, hashlib.sha256(m.sql.encode()).hexdigest()) for m in chain[:len(history)]]
            if history != expected: raise BackupError('BACKUP_SCHEMA_HISTORY_INVALID')
            with closing(sqlite3.connect(':memory:', isolation_level=None)) as pristine:
                migrate(pristine, chain[:len(history)])
                if _schema_objects(connection) != _schema_objects(pristine):
                    raise BackupError('BACKUP_SCHEMA_OBJECTS_CHANGED')
            return len(history)
    except sqlite3.Error as error:
        raise BackupError('BACKUP_DATABASE_INVALID') from error


def assert_quiescent(connection, *, restoring=False):
    # A writer fence prevents new claims. Already leased tasks can write files
    # independently of HTTP, so refuse them rather than snapshotting their work.
    conditions = "lease_owner IS NOT NULL OR cancel_pending_remote=1 OR remote_status='running' OR state IN ('INPUT_PREPARING','PLANNING','EXECUTING','VALIDATING','REVIEWING','OUTPUT_PREPARING','READY')"
    if restoring: conditions += " OR state='RECEIVED'"
    if connection.execute('SELECT COUNT(*) FROM task_runs WHERE ' + conditions).fetchone()[0]:
        raise BackupError('BACKUP_TASKS_NOT_QUIESCENT')


def _secret_config(value):
    if isinstance(value, dict):
        return any((k.lower() in {'api_key', 'access_token', 'refresh_token', 'password', 'authorization', 'credentials', 'secret'} and v not in (None, '', {})) or _secret_config(v) for k, v in value.items())
    return isinstance(value, list) and any(_secret_config(v) for v in value)


def references(connection, root):
    store = BlobStore(root / 'blobs')
    required = set()
    for row in connection.execute('SELECT provider_json FROM provider_profiles'):
        if _secret_config(json.loads(row[0])): raise BackupError('BACKUP_CREDENTIAL_CONFIG_FORBIDDEN')
    for table, column in [('artifact_revisions', 'byte_sha256'), ('attachments', 'sha256'), ('a_document_responses', 'raw_response_sha256')]:
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            required.update(row[0] for row in connection.execute(f'SELECT {column} FROM {table}'))
    tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for table in tables:
        for row in connection.execute('SELECT * FROM "' + table.replace('"', '""') + '"'):
            for value in row:
                if not isinstance(value, str): continue
                required.update(re.findall(r'blob:sha256:([a-f0-9]{64})', value))
                try: parsed = json.loads(value)
                except (ValueError, TypeError): continue
                def pages(node):
                    if isinstance(node, dict):
                        for key, child in node.items():
                            if key == 'page_images_sha256' and isinstance(child, list): required.update(child)
                            else: pages(child)
                    elif isinstance(node, list):
                        for child in node: pages(child)
                pages(parsed)
    # Conservatively include existing hashes embedded in frozen checkpoints or
    # provenance, without treating unrelated contract/content hashes as blobs.
    required.update(item['sha256'] for item in inventory(connection, store)['files'] if item['referenced'])
    for digest in required:
        reject_links(store.path_for(digest))
        store.verify(digest)
    return sorted(required)


def verify_task_sources(connection, root):
    """Close workspace references from persisted task metadata, not ZIP lists.

    A missing manifest cannot erase a contract's required input. Original input
    hashes are independently pinned by contracts, planning, material/language
    proofs, steps, checks and linked artifact contexts where available.
    """
    def source_manifest(workspace):
        path = reject_links(workspace / '.source-manifest.json')
        if not path.is_file(): raise BackupError('BACKUP_SOURCE_MANIFEST_MISSING')
        values = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(values, dict): raise BackupError('BACKUP_SOURCE_MANIFEST_INVALID')
        for name, digest in values.items():
            if not isinstance(name, str) or not name.startswith('input/') or not isinstance(digest, str) or not HEX.fullmatch(digest):
                raise BackupError('BACKUP_SOURCE_MANIFEST_INVALID')
            relative = workspace.relative_to(root).as_posix() + '/' + name
            safe_name(relative)
            source = reject_links(root / relative)
            if not source.is_file() or sha_file(source) != digest: raise BackupError('BACKUP_SOURCE_BYTES_CHANGED')
        for path in (workspace / 'input').rglob('*'):
            reject_links(path)
            if path.is_file() and path.relative_to(workspace).as_posix() not in values:
                raise BackupError('BACKUP_UNTRACKED_INPUT')
        return values

    manifests = {}
    for path in root.glob('tasks/*/*/.source-manifest.json'):
        manifests[path.parent] = source_manifest(path.parent)
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for task in connection.execute('SELECT task_id,attempt_id,checkpoint_json FROM task_runs'):
        task_id, attempt_id, raw = task
        if any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', v) for v in (task_id, attempt_id)):
            raise BackupError('BACKUP_TASK_SCOPE_INVALID')
        workspace = root / 'tasks' / task_id / attempt_id
        expected = {}
        def register(ref, digest=None):
            if not isinstance(ref, str) or not re.match(r'^(input|a|b|translation|evidence|artifacts)/', ref): return
            safe_name(workspace.relative_to(root).as_posix() + '/' + ref)
            if digest is not None and (not isinstance(digest, str) or not HEX.fullmatch(digest)):
                raise BackupError('BACKUP_TASK_SOURCE_HASH_INVALID')
            if ref in expected and expected[ref] is not None and digest is not None and expected[ref] != digest:
                raise BackupError('BACKUP_TASK_SOURCE_HASH_CONFLICT')
            if ref not in expected or digest is not None: expected[ref] = digest
        def walk(node):
            if isinstance(node, list):
                for child in node: walk(child)
            elif isinstance(node, dict):
                for ref_key, hash_key in [('ref', 'sha256'), ('source_ref', 'source_sha256'),
                        ('text_ref', 'text_sha256'), ('view_ref', 'view_sha256'),
                        ('data_ref', 'source_sha256'), ('content_ref', 'content_sha256')]:
                    if ref_key in node: register(node[ref_key], node.get(hash_key))
                hashes = node.get('source_hashes')
                if isinstance(hashes, dict):
                    for ref, digest in hashes.items(): register(ref, digest)
                for key in ('source_refs', 'data_refs', 'evidence_refs', 'input_refs', 'workspace_ref'):
                    refs = node.get(key, [])
                    for ref in refs if isinstance(refs, list) else [refs]: register(ref)
                for key, child in node.items():
                    if key != 'task_profile': walk(child)
        checkpoint = json.loads(raw)
        if not isinstance(checkpoint, dict): raise BackupError('BACKUP_TASK_CONTEXT_INVALID')
        walk(checkpoint)
        # Declared profile refs can legitimately be unresolved before planning.
        # A completed input/planning context proves they were materialized.
        language = checkpoint.get('language_context')
        prepared = any(checkpoint.get(key) for key in ('a_planning', 'task_contract', 'workflow', 'composite_run')) or isinstance(language, dict) and language.get('status') == 'READY'
        profile = checkpoint.get('task_profile')
        if prepared and isinstance(profile, dict): walk(profile.get('inputs', {}))
        for table, columns in [('steps', ('request_json', 'checkpoint_json')),
                ('checks', ('details_json',)), ('artifact_revisions', ('provenance_json', 'source_request_json'))]:
            if table not in tables: continue
            for row in connection.execute('SELECT ' + ','.join(columns) + ' FROM ' + table + ' WHERE task_id=? AND attempt_id=?', (task_id, attempt_id)):
                for value in row:
                    if value is not None: walk(json.loads(value))
        if 'translation_jobs' in tables:
            for row in connection.execute('SELECT source_ref,source_sha256,source_locator FROM translation_jobs WHERE task_id=? AND attempt_id=?', (task_id, attempt_id)):
                register(row[0], row[1])
                if isinstance(row[2], str) and row[2].startswith('input/'):
                    register(row[2], row[1])
        if any(ref.startswith('input/') for ref in expected):
            values = manifests.get(workspace)
            if values is None:
                values = source_manifest(workspace); manifests[workspace] = values
        else: values = manifests.get(workspace, {})
        for ref, digest in expected.items():
            path = reject_links(workspace / ref)
            if not path.is_file(): raise BackupError('BACKUP_TASK_SOURCE_MISSING')
            measured = sha_file(path)
            if digest is not None and digest != measured: raise BackupError('BACKUP_TASK_SOURCE_BYTES_CHANGED')
            if ref.startswith('input/') and (ref not in values or values[ref] != measured):
                raise BackupError('BACKUP_TASK_SOURCE_MANIFEST_MISMATCH')


def verify_references(connection, root):
    refs = references(connection, root)
    for row in connection.execute('SELECT id FROM artifact_revisions'):
        read_artifact(connection, BlobStore(root / 'blobs'), row[0])
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='delivery_bundles'").fetchone():
        from app.documents.publish import _verify_bundle, bundle_card
        for row in connection.execute('SELECT * FROM delivery_bundles'):
            if row['state'] == 'PUBLISHED': bundle_card(connection, BlobStore(root / 'blobs'), row)
            elif row['state'] in {'VERIFIED', 'STAGING'}: _verify_bundle(connection, BlobStore(root / 'blobs'), row['id'], None, current=False)
            else: raise BackupError('BACKUP_CORRUPT_BUNDLE')
    verify_task_sources(connection, root)
    return refs


def copy_verified(source, target, expected):
    reject_links(source)
    reject_links(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as reader, target.open('xb') as writer:
        shutil.copyfileobj(reader, writer)
        writer.flush()
        os.fsync(writer.fileno())
    if sha_file(target) != expected or sha_file(source) != expected:
        raise BackupError('BACKUP_COPY_HASH_MISMATCH')


def discard_owned(path, parent):
    # Only this operation's UUID staging directory may be recursively removed.
    path, parent = Path(path).absolute(), reject_links(parent)
    if path.name.startswith('.pending-') and reject_links(path).parent == parent and path.is_dir():
        for child in path.rglob('*'): reject_links(child)
        shutil.rmtree(path)


def _file_item(path, root):
    name = safe_name(path.relative_to(root).as_posix())
    return dict(path=name, size_bytes=path.stat().st_size, sha256=sha_file(path))


def create_backup(data_root: Path, staging_root: Path) -> Path:
    source, staging = reject_links(data_root), reject_links(staging_root)
    if source == staging or staging.is_relative_to(source) or source.is_relative_to(staging): raise BackupError('BACKUP_STAGING_OVERLAPS_SOURCE')
    if not (source / 'workbench.sqlite3').is_file(): raise BackupError('BACKUP_DATABASE_MISSING')
    staging.mkdir(parents=True, exist_ok=True)
    pending = staging / ('.pending-' + uuid4().hex)
    committed = staging / ('backup-' + uuid4().hex)
    pending.mkdir()
    try:
        database = Database(source / 'workbench.sqlite3')
        with closing(database.connect()) as fence, transaction(fence):
            assert_quiescent(fence)
            with closing(database.connect()) as reader, closing(sqlite3.connect(pending / 'workbench.sqlite3')) as destination:
                reader.backup(destination)
            version = inspect_database(pending / 'workbench.sqlite3')
            with closing(sqlite3.connect(pending / 'workbench.sqlite3')) as snapshot:
                snapshot.row_factory = sqlite3.Row
                # This cache is derivable; keep jobs/history/artifacts, purge its
                # rows and freed pages from the portable snapshot only.
                if version >= 2:
                    snapshot.execute('PRAGMA secure_delete=ON')
                    snapshot.execute('DELETE FROM translation_cache')
                    snapshot.commit()
                    snapshot.execute('VACUUM')
                refs = references(snapshot, source)
                files = [source / 'blobs' / digest[:2] / digest for digest in refs]
                tasks = list(snapshot.execute('SELECT task_id,attempt_id FROM task_runs'))
                if any(not isinstance(part, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', part) for row in tasks for part in row):
                    raise BackupError('BACKUP_TASK_SCOPE_INVALID')
                scopes = [source / 'evidence'] + [source / 'tasks' / row[0] / row[1] for row in tasks]
                for scope in scopes:
                    reject_links(scope)
                    if not scope.exists(): continue
                    for path in scope.rglob('*'):
                        reject_links(path)
                        if path.is_file() and path.name not in {'.lease-lock', '.write-leases.json'} and not path.name.startswith('.write-'):
                            safe_name(path.relative_to(source).as_posix())
                            files.append(path)
                items = [_file_item(p, source) for p in sorted(set(files))]
                required_bytes = sum(item['size_bytes'] for item in items) + (pending / 'workbench.sqlite3').stat().st_size
                if len(items) + 1 > MAX_FILES or required_bytes > MAX_BYTES: raise BackupError('BACKUP_SIZE_LIMIT')
                if shutil.disk_usage(staging).free < required_bytes + 1048576: raise BackupError('BACKUP_SPACE_INSUFFICIENT')
                for item in items: copy_verified(source / item['path'], pending / item['path'], item['sha256'])
            items.insert(0, _file_item(pending / 'workbench.sqlite3', pending))
            manifest = dict(format_version=FORMAT_VERSION, app_version=APP_VERSION, schema_version=version,
                created_at=datetime.now(timezone.utc).isoformat(), credentials_included=False, files=items)
            with (pending / 'manifest.json').open('x', encoding='utf-8') as stream:
                json.dump(manifest, stream, ensure_ascii=False, sort_keys=True)
                stream.flush(); os.fsync(stream.fileno())
            validate_backup(pending)
            # A last read catches an independent workspace writer during copy.
            for item in items[1:]:
                if sha_file(source / item['path']) != item['sha256']: raise BackupError('BACKUP_SOURCE_CHANGED')
        commit_owned_directory(pending, committed, staging)
        return committed
    except DirectoryCommitBlocked:
        raise
    except BaseException:
        discard_owned(pending, staging)
        raise


def validate_backup(bundle_path: Path) -> dict:
    try:
        root = reject_links(bundle_path)
        if not root.is_dir(): raise BackupError('BACKUP_DIRECTORY_REQUIRED')
        manifest_path = reject_links(root / 'manifest.json')
        if manifest_path.stat().st_size > MAX_MANIFEST_BYTES: raise BackupError('BACKUP_MANIFEST_LIMIT')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(manifest, dict) or set(manifest) != {'format_version', 'app_version', 'schema_version', 'created_at', 'credentials_included', 'files'}:
            raise BackupError('BACKUP_MANIFEST_INVALID')
        if manifest['format_version'] != FORMAT_VERSION or manifest['credentials_included'] is not False or not isinstance(manifest['app_version'], str) or not isinstance(manifest['created_at'], str):
            raise BackupError('BACKUP_FORMAT_UNSUPPORTED')
        if type(manifest['schema_version']) is not int or not isinstance(manifest['files'], list) or not 1 <= len(manifest['files']) <= MAX_FILES:
            raise BackupError('BACKUP_MANIFEST_INVALID')
        expected, hashes, total = set(), {}, 0
        for item in manifest['files']:
            if not isinstance(item, dict) or set(item) != {'path', 'size_bytes', 'sha256'}: raise BackupError('BACKUP_MANIFEST_INVALID')
            name = safe_name(item['path'])
            if name == 'manifest.json' or name.casefold() in expected or type(item['size_bytes']) is not int or item['size_bytes'] < 0 or not isinstance(item['sha256'], str) or not HEX.fullmatch(item['sha256']):
                raise BackupError('BACKUP_MANIFEST_INVALID')
            expected.add(name.casefold()); total += item['size_bytes']
            if total > MAX_BYTES: raise BackupError('BACKUP_SIZE_LIMIT')
            path = reject_links(root / name)
            if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size != item['size_bytes'] or sha_file(path) != item['sha256']:
                raise BackupError('BACKUP_FILE_HASH_MISMATCH')
            hashes[name] = item['sha256']
        actual = set()
        for path in root.rglob('*'):
            reject_links(path)
            if path.is_file(): actual.add(safe_name(path.relative_to(root).as_posix()).casefold())
        if actual != expected | {'manifest.json'} or 'workbench.sqlite3' not in hashes: raise BackupError('BACKUP_FILE_SET_MISMATCH')
        version = inspect_database(root / 'workbench.sqlite3')
        if version != manifest['schema_version']: raise BackupError('BACKUP_SCHEMA_VERSION_MISMATCH')
        with closing(sqlite3.connect((root / 'workbench.sqlite3').as_uri() + '?mode=ro&immutable=1', uri=True)) as c:
            c.row_factory = sqlite3.Row
            refs = verify_references(c, root)
        return dict(verified=True, schema_version=version, app_version=manifest['app_version'], files_verified=len(hashes),
            size_bytes=total, hashes=hashes, referenced_blobs=len(refs), credentials_included=False,
            manifest_sha256=sha_file(manifest_path))
    except (OSError, sqlite3.Error, TypeError, KeyError, json.JSONDecodeError, RecursionError) as error:
        raise BackupError('BACKUP_INVALID') from error


def export_backup(bundle_path):
    report = validate_backup(bundle_path)
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ['manifest.json', *report['hashes']]:
            data = (Path(bundle_path) / name).read_bytes()
            expected = report['manifest_sha256'] if name == 'manifest.json' else report['hashes'][name]
            if hashlib.sha256(data).hexdigest() != expected: raise BackupError('BACKUP_CHANGED_AFTER_VALIDATION')
            archive.writestr(name, data)
    return content.getvalue()


def import_backup(content, staging_root):
    if not isinstance(content, bytes) or len(content) > MAX_BYTES: raise BackupError('BACKUP_SIZE_LIMIT')
    staging = reject_links(staging_root); staging.mkdir(parents=True, exist_ok=True)
    pending = staging / ('.pending-' + uuid4().hex)
    committed = staging / ('backup-' + uuid4().hex)
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names, total = set(), 0
            members = archive.infolist()
            if not 1 <= len(members) <= MAX_FILES + 1: raise BackupError('BACKUP_FILE_LIMIT')
            for item in members:
                name = safe_name(item.filename)
                mode = item.external_attr >> 16
                if (name.casefold() in names or item.is_dir() or item.flag_bits & 1 or
                        stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                    raise BackupError('BACKUP_ZIP_MEMBER_INVALID')
                names.add(name.casefold()); total += item.file_size
                if total > MAX_BYTES or (name == 'manifest.json' and item.file_size > MAX_MANIFEST_BYTES): raise BackupError('BACKUP_SIZE_LIMIT')
            if shutil.disk_usage(staging).free < total + 1048576: raise BackupError('BACKUP_SPACE_INSUFFICIENT')
            pending.mkdir()
            for item in members:
                target = pending / item.filename
                reject_links(target); target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as reader, target.open('xb') as writer:
                    copied = 0
                    while chunk := reader.read(1024 * 1024):
                        copied += len(chunk)
                        if copied > item.file_size: raise BackupError('BACKUP_ZIP_SIZE_CHANGED')
                        writer.write(chunk)
                    if copied != item.file_size: raise BackupError('BACKUP_ZIP_SIZE_CHANGED')
                    writer.flush(); os.fsync(writer.fileno())
        validate_backup(pending)
        commit_owned_directory(pending, committed, staging)
        return committed
    except DirectoryCommitBlocked:
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError) as error:
        discard_owned(pending, staging)
        raise BackupError('BACKUP_ARCHIVE_INVALID') from error
    except BaseException:
        discard_owned(pending, staging)
        raise
