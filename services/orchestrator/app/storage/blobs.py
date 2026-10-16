"""Immutable byte references."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from app.contracts.artifacts import ArtifactVersion
from .database import transaction


@dataclass(frozen=True)
class BlobRef:
    sha256: str
    size_bytes: int
    relative_path: str


class BlobError(ValueError):
    pass


class BlobStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, data: bytes) -> BlobRef:
        if not isinstance(data, bytes):
            raise TypeError("BLOB_BYTES_REQUIRED")
        digest = hashlib.sha256(data).hexdigest()
        destination = self.path_for(digest)
        if destination.exists() or destination.is_symlink():
            return self.verify(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent, suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # A hard link is an atomic create-if-absent, unlike replace/rename.
                os.link(temporary, destination)
            except FileExistsError:
                pass
            return self.verify(digest)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def read(self, sha256: str) -> bytes:
        path = self.path_for(sha256)
        if path.is_symlink():
            raise BlobError("BLOB_SYMLINK_FORBIDDEN")
        try:
            data = path.read_bytes()
        except FileNotFoundError as error:
            raise BlobError("BLOB_MISSING") from error
        if hashlib.sha256(data).hexdigest() != sha256:
            raise BlobError("BLOB_HASH_MISMATCH")
        return data

    def verify(self, sha256: str) -> BlobRef:
        data = self.read(sha256)
        return BlobRef(sha256, len(data), self.path_for(sha256).relative_to(self.root).as_posix())

    def path_for(self, sha256: str) -> Path:
        if not isinstance(sha256, str) or re.fullmatch(r"[a-f0-9]{64}", sha256) is None:
            raise BlobError("INVALID_BLOB_HASH")
        path = self.root / sha256[:2] / sha256
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise BlobError("BLOB_PATH_OUTSIDE_ROOT")
        return path

    def uri_for(self, sha256: str) -> str:
        self.path_for(sha256)
        return f"blob:sha256:{sha256}"


def store_artifact(
    connection: sqlite3.Connection, store: BlobStore, data: bytes, artifact: ArtifactVersion,
    *, attempt_id: str, provenance: dict, source_request: dict | None = None,
) -> BlobRef:
    """Persist content before registering it; rollback may leave a safe orphan."""
    artifact = ArtifactVersion.model_validate(artifact.model_dump())
    digest = hashlib.sha256(data).hexdigest()
    if artifact.byte_sha256 != digest or artifact.immutable_uri != store.uri_for(digest):
        raise BlobError("ARTIFACT_BLOB_REFERENCE_MISMATCH")
    if not isinstance(provenance, dict) or (source_request is not None and not isinstance(source_request, dict)):
        raise TypeError("ARTIFACT_PROVENANCE_OBJECT_REQUIRED")
    provenance_json = _json(provenance)
    source_request_json = _json(source_request) if source_request is not None else None
    with transaction(connection):
        for dependency in artifact.dependencies:
            if connection.execute("SELECT id FROM artifact_revisions WHERE id=?",
                                  (dependency.artifact_version_id,)).fetchone() is None:
                raise BlobError("ARTIFACT_DEPENDENCY_MISSING")
            read_artifact(connection, store, dependency.artifact_version_id)
        if artifact.source_version_id is not None:
            read_artifact(connection, store, artifact.source_version_id)
        ref = store.put(data)
        connection.execute("""INSERT INTO artifact_revisions(
            id,task_id,attempt_id,artifact_kind,language,immutable_uri,byte_sha256,
            canonical_content_sha256,size_bytes,source_version_id,origin_authors_json,
            canonical_issued_by,reviewed_by_json,rendered_by,a_response_ref,
            dependencies_json,provenance_json,source_request_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            artifact.id, artifact.task_id, attempt_id, artifact.artifact_kind, artifact.language,
            artifact.immutable_uri, artifact.byte_sha256, artifact.canonical_content_sha256,
            ref.size_bytes, artifact.source_version_id, _json(artifact.origin_authors),
            artifact.canonical_issued_by, _json(artifact.reviewed_by), artifact.rendered_by,
            artifact.a_response_ref, _json([value.model_dump() for value in artifact.dependencies]),
            provenance_json, source_request_json,
        ))
    return ref


def read_artifact(connection: sqlite3.Connection, store: BlobStore, artifact_id: str) -> bytes:
    row = connection.execute(
        "SELECT immutable_uri,byte_sha256,size_bytes FROM artifact_revisions WHERE id=?", (artifact_id,),
    ).fetchone()
    if row is None:
        raise BlobError("ARTIFACT_NOT_FOUND")
    if row[0] != store.uri_for(row[1]):
        raise BlobError("ARTIFACT_BLOB_REFERENCE_MISMATCH")
    data = store.read(row[1])
    if len(data) != row[2]:
        raise BlobError("ARTIFACT_BLOB_SIZE_MISMATCH")
    return data


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
