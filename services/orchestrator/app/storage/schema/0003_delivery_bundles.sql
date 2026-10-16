CREATE TABLE a_document_responses (
    id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
    step_id TEXT NOT NULL REFERENCES steps(id),
    revision_id TEXT NOT NULL UNIQUE REFERENCES artifact_revisions(id),
    provider_profile_id TEXT NOT NULL REFERENCES provider_profiles(id),
    route_snapshot_id TEXT NOT NULL,
    raw_response_sha256 TEXT NOT NULL CHECK(length(raw_response_sha256)=64),
    body_sha256 TEXT NOT NULL CHECK(length(body_sha256)=64),
    manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(task_id,attempt_id) REFERENCES task_runs(task_id,attempt_id),
    UNIQUE(step_id,revision_id)
);
CREATE TABLE document_models (
    revision_id TEXT PRIMARY KEY NOT NULL REFERENCES artifact_revisions(id),
    source_version_id TEXT NOT NULL REFERENCES artifact_revisions(id),
    model_json TEXT NOT NULL CHECK(json_valid(model_json)),
    model_sha256 TEXT NOT NULL CHECK(length(model_sha256)=64),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE delivery_bundles (
    id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL, turn_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL REFERENCES artifact_revisions(id),
    route_snapshot_id TEXT NOT NULL, title TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('STAGING','VERIFIED','PUBLISHED','CORRUPT')),
    bundle_json TEXT NOT NULL CHECK(json_valid(bundle_json)),
    manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256)=64),
    requested_formats_json TEXT NOT NULL CHECK(json_valid(requested_formats_json)),
    dependency_fence_json TEXT NOT NULL CHECK(json_valid(dependency_fence_json)),
    approval_id TEXT, review_check_id TEXT REFERENCES checks(id),
    published_at TEXT, stale INTEGER NOT NULL DEFAULT 0 CHECK(stale IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(task_id,attempt_id) REFERENCES task_runs(task_id,attempt_id),
    FOREIGN KEY(turn_id,conversation_id) REFERENCES turns(id,conversation_id),
    CHECK(state!='PUBLISHED' OR (approval_id IS NOT NULL AND review_check_id IS NOT NULL AND published_at IS NOT NULL))
);
CREATE TABLE delivery_bundle_artifacts (
    bundle_id TEXT NOT NULL REFERENCES delivery_bundles(id),
    artifact_id TEXT NOT NULL REFERENCES artifact_revisions(id),
    source_version_id TEXT NOT NULL REFERENCES artifact_revisions(id),
    artifact_pair_id TEXT, format TEXT NOT NULL, language TEXT NOT NULL,
    file_name TEXT NOT NULL,
    qa_check_id TEXT NOT NULL REFERENCES checks(id),
    preview_artifact_id TEXT REFERENCES artifact_revisions(id),
    PRIMARY KEY(bundle_id,artifact_id), UNIQUE(bundle_id,format,language,artifact_pair_id)
);
CREATE TABLE delivery_bundle_heads (
    turn_id TEXT PRIMARY KEY NOT NULL REFERENCES turns(id),
    bundle_id TEXT NOT NULL UNIQUE REFERENCES delivery_bundles(id)
);
CREATE TRIGGER a_document_responses_immutable BEFORE UPDATE ON a_document_responses BEGIN
    SELECT RAISE(ABORT,'A_DOCUMENT_RESPONSE_IMMUTABLE');
END;
CREATE TRIGGER document_models_immutable BEFORE UPDATE ON document_models BEGIN
    SELECT RAISE(ABORT,'DOCUMENT_MODEL_IMMUTABLE');
END;
CREATE TRIGGER bundle_artifacts_immutable BEFORE UPDATE ON delivery_bundle_artifacts BEGIN
    SELECT RAISE(ABORT,'BUNDLE_MEMBERSHIP_IMMUTABLE');
END;
CREATE TRIGGER published_bundle_frozen BEFORE UPDATE OF id,task_id,attempt_id,conversation_id,turn_id,source_version_id,route_snapshot_id,title,bundle_json,manifest_sha256,requested_formats_json,dependency_fence_json,approval_id,review_check_id,published_at ON delivery_bundles
WHEN OLD.state='PUBLISHED' BEGIN
    SELECT RAISE(ABORT,'PUBLISHED_BUNDLE_IMMUTABLE');
END;
CREATE TRIGGER bundle_membership_scope BEFORE INSERT ON delivery_bundle_artifacts BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM delivery_bundles b JOIN artifact_revisions a ON a.id=NEW.artifact_id
        WHERE b.id=NEW.bundle_id AND b.state='STAGING'
        AND a.task_id=b.task_id AND a.attempt_id=b.attempt_id
        AND NEW.source_version_id=b.source_version_id
    ) THEN RAISE(ABORT,'BUNDLE_ARTIFACT_SCOPE_MISMATCH') END;
END;
