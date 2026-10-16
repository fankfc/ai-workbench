"""Conservative blob collection fenced by the database writer and a snapshot."""
import hashlib
import json
import re

HEX = re.compile(r'(?<![a-f0-9])[a-f0-9]{64}(?![a-f0-9])')


def inventory(connection, store):
    references = set()
    tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for table in tables:
        # Internal schema names only; include caches/checkpoints/backup references.
        quoted = '"' + table.replace('"', '""') + '"'
        for row in connection.execute('SELECT * FROM ' + quoted):
            for value in row:
                if isinstance(value, str):
                    references.update(HEX.findall(value))
    files = []
    if store.root.exists():
        for path in sorted(store.root.glob('[0-9a-f][0-9a-f]/*')):
            if HEX.fullmatch(path.name) and not path.is_symlink() and path.is_file():
                if not path.resolve().is_relative_to(store.root.resolve()):
                    continue
                stat = path.stat()
                files.append(dict(sha256=path.name, size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns,
                                  referenced=path.name in references))
    active = connection.execute("SELECT COUNT(*) FROM task_runs WHERE state NOT IN ('FAILED','CANCELLED','PUBLISHED') OR cancel_pending_remote=1 OR lease_owner IS NOT NULL").fetchone()[0]
    encoded = json.dumps(dict(files=files, references=sorted(references), active=active), sort_keys=True, separators=(',', ':')).encode()
    return dict(version=hashlib.sha256(encoded).hexdigest(), files=files, active=active)


def preview(connection, store):
    current = inventory(connection, store)
    return dict(version=current['version'], items=[{key: row[key] for key in ('sha256', 'size_bytes')} for row in current['files'] if not row['referenced']] if not current['active'] else [],
                blocked=bool(current['active']), reason='存在运行中或待核对任务，暂不可清理。' if current['active'] else None)


def cleanup(connection, store, version, hashes):
    current = preview(connection, store)
    if current['version'] != version or current['blocked']:
        raise ValueError('CLEANUP_SNAPSHOT_STALE')
    allowed = {item['sha256'] for item in current['items']}
    if not set(hashes).issubset(allowed):
        raise ValueError('CLEANUP_REFERENCE_CHANGED')
    removed = []
    for digest in dict.fromkeys(hashes):
        store.path_for(digest).unlink()
        removed.append(digest)
    return dict(removed=removed)
