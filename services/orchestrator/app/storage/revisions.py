"""Persist DAG activation separately from immutable byte staging.

Immutable artifact rows and blobs remain historical. Activation is one writer
transaction and selectively invalidates derived revisions/checks/translations.
"""
from contextlib import nullcontext
import json
import sqlite3

from app.runtime.dependencies import DependencyGraph
from .blobs import BlobStore, read_artifact
from .database import transaction


def _task(connection, task_id, attempt_id):
    row = connection.execute("SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?", (task_id, attempt_id)).fetchone()
    if row is None:
        raise ValueError("TASK_ATTEMPT_NOT_FOUND")
    return row


def _graph(connection, task_id, attempt_id):
    checkpoint = json.loads(_task(connection, task_id, attempt_id)["checkpoint_json"])
    if not isinstance(checkpoint, dict):
        raise ValueError("DEPENDENCY_GRAPH_INVALID")
    return checkpoint, DependencyGraph(checkpoint.get("dependency_graph"))


def _revision(connection, task_id, attempt_id, revision_id):
    row = connection.execute("SELECT * FROM artifact_revisions WHERE id=? AND task_id=? AND attempt_id=?", (revision_id, task_id, attempt_id)).fetchone()
    if row is None:
        raise ValueError("REVISION_NOT_FOUND_IN_ATTEMPT")
    return row


def _stored_dependencies(row):
    values = json.loads(row["dependencies_json"])
    if not isinstance(values, list) or any(not isinstance(value, dict) or not isinstance(value.get("artifact_version_id"), str) for value in values):
        raise ValueError("REVISION_DEPENDENCIES_INVALID")
    result = {value["artifact_version_id"] for value in values}
    if row["source_version_id"] is not None:
        result.add(row["source_version_id"])
    return result


def activate_revision(connection: sqlite3.Connection, store: BlobStore, task_id: str, attempt_id: str, logical_id: str, revision_id: str, upstream_versions: dict[str, str]) -> dict:
    boundary = nullcontext(connection) if connection.in_transaction else transaction(connection)
    with boundary:
        task = _task(connection, task_id, attempt_id)
        if task["cancel_requested"]:
            raise ValueError("TASK_CANCELLED")
        checkpoint, graph = _graph(connection, task_id, attempt_id)
        revision = _revision(connection, task_id, attempt_id, revision_id)
        read_artifact(connection, store, revision_id)
        if _stored_dependencies(revision) != set(upstream_versions.values()):
            raise ValueError("REVISION_DEPENDENCY_BINDING_MISMATCH")
        for upstream_id in upstream_versions.values():
            _revision(connection, task_id, attempt_id, upstream_id)
            read_artifact(connection, store, upstream_id)
        affected = graph.register(logical_id, revision_id, upstream_versions)
        checkpoint["dependency_graph"] = graph.to_dict()
        checkpoint["dependency_version"] = graph.version
        if affected:
            placeholders = ",".join("?" for _ in affected)
            connection.execute(f"UPDATE checks SET details_json=json_set(details_json,'$.stale',json('true'),'$.invalidated_by_graph_version',?) WHERE task_id=? AND attempt_id=? AND (artifact_version_id IN ({placeholders}) OR job_id IN (SELECT job_id FROM translation_units WHERE task_id=? AND attempt_id=? AND source_version_id IN ({placeholders})))", (graph.version,task_id,attempt_id,*affected,task_id,attempt_id,*affected))
            connection.execute(f"UPDATE translation_units SET status='STALE' WHERE task_id=? AND attempt_id=? AND source_version_id IN ({placeholders})", (task_id,attempt_id,*affected))
            if checkpoint.get("current_revision_id") in affected or (isinstance(checkpoint.get("public_release"), dict) and checkpoint["public_release"].get("revision_id") in affected):
                checkpoint["stale"] = True
                checkpoint["publication_blocked"] = True
        connection.execute("UPDATE task_runs SET checkpoint_json=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE task_id=? AND attempt_id=?", (json.dumps(checkpoint,ensure_ascii=False,separators=(",",":"),allow_nan=False),task_id,attempt_id))
        return {"graph_version":graph.version,"logical_id":logical_id,"revision_id":revision_id,"invalidated_revision_ids":list(affected)}


def is_current_revision(connection: sqlite3.Connection, task_id: str, attempt_id: str, revision_id: str) -> bool:
    try:
        checkpoint, graph = _graph(connection, task_id, attempt_id)
        if "dependency_graph" not in checkpoint or not graph.is_current(revision_id):
            return False
        row = _revision(connection,task_id,attempt_id,revision_id)
        node = next(node for node in graph.nodes.values() if node["revision_id"] == revision_id)
        return _stored_dependencies(row) == set(node["dependencies"].values())
    except (ValueError,TypeError,KeyError,StopIteration,sqlite3.Error):
        return False


def snapshot_fence(connection: sqlite3.Connection, task_id: str, attempt_id: str, revision_ids: list[str]) -> dict:
    _, graph = _graph(connection, task_id, attempt_id)
    if not revision_ids or len(set(revision_ids)) != len(revision_ids):
        raise ValueError("PUBLICATION_REVISIONS_REQUIRED")
    versions = {}
    for revision_id in revision_ids:
        if not is_current_revision(connection,task_id,attempt_id,revision_id):
            raise ValueError("REVISION_NOT_CURRENT:" + revision_id)
        versions[revision_id] = _revision(connection,task_id,attempt_id,revision_id)["byte_sha256"]
    return {"task_id":task_id,"attempt_id":attempt_id,"graph_version":graph.version,"revisions":versions}


def require_publication_fence(connection: sqlite3.Connection, task_id: str, attempt_id: str, fence: dict) -> None:
    if not connection.in_transaction:
        raise ValueError("PUBLICATION_TRANSACTION_REQUIRED")
    task = _task(connection,task_id,attempt_id)
    if task["cancel_requested"]:
        raise ValueError("TASK_CANCELLED")
    latest = connection.execute("SELECT attempt_id FROM task_runs WHERE task_id=? ORDER BY attempt_number DESC,created_at DESC LIMIT 1", (task_id,)).fetchone()
    if latest is None or latest[0] != attempt_id:
        raise ValueError("PUBLICATION_ATTEMPT_CHANGED")
    _, graph = _graph(connection,task_id,attempt_id)
    if not isinstance(fence,dict) or fence.get("task_id") != task_id or fence.get("attempt_id") != attempt_id or type(fence.get("graph_version")) is not int or fence["graph_version"] != graph.version:
        raise ValueError("PUBLICATION_VERSION_CHANGED")
    versions = fence.get("revisions")
    if not isinstance(versions,dict) or not versions:
        raise ValueError("PUBLICATION_REVISIONS_REQUIRED")
    for revision_id,digest in versions.items():
        if not is_current_revision(connection,task_id,attempt_id,revision_id) or _revision(connection,task_id,attempt_id,revision_id)["byte_sha256"] != digest:
            raise ValueError("PUBLICATION_VERSION_CHANGED")
