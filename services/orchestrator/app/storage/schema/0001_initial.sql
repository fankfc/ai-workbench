CREATE TABLE conversations (
    id TEXT PRIMARY KEY NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE provider_profiles (
    id TEXT PRIMARY KEY NOT NULL,
    adapter TEXT NOT NULL, model_id TEXT NOT NULL, family TEXT NOT NULL,
    connection_id TEXT NOT NULL, identity_status TEXT NOT NULL,
    identity_source TEXT, connection_version TEXT NOT NULL,
    provider_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(provider_json)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE turns (
    id TEXT PRIMARY KEY NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    task_id TEXT NOT NULL UNIQUE,
    provider_profile_id TEXT NOT NULL REFERENCES provider_profiles(id),
    client_request_id TEXT NOT NULL, user_text TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'zh-CN',
    route_snapshot_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(route_snapshot_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(conversation_id,client_request_id), UNIQUE(id,conversation_id), UNIQUE(id,task_id)
);
CREATE TABLE task_runs (
    task_id TEXT NOT NULL, attempt_id TEXT NOT NULL, turn_id TEXT NOT NULL,
    provider_profile_id TEXT NOT NULL REFERENCES provider_profiles(id),
    contract_version TEXT NOT NULL DEFAULT '1.0', state TEXT NOT NULL DEFAULT 'CREATED',
    attempt_number INTEGER NOT NULL DEFAULT 1 CHECK(attempt_number >= 1),
    route_snapshot_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(route_snapshot_json)),
    external_request_id TEXT, external_execution_id TEXT, pid INTEGER,
    remote_status TEXT NOT NULL DEFAULT 'unknown',
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
    external_stop_confirmed INTEGER CHECK(external_stop_confirmed IN (0,1)),
    cancel_pending_remote INTEGER NOT NULL DEFAULT 0 CHECK(cancel_pending_remote IN (0,1)),
    last_sequence INTEGER NOT NULL DEFAULT 0 CHECK(last_sequence >= 0),
    checkpoint_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(checkpoint_json)),
    lease_owner TEXT, lease_expires_at TEXT, started_at TEXT, completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(task_id,attempt_id),
    FOREIGN KEY(turn_id,task_id) REFERENCES turns(id,task_id),
    UNIQUE(provider_profile_id,external_request_id)
);
CREATE TABLE steps (
    id TEXT PRIMARY KEY NOT NULL, task_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
    step_key TEXT NOT NULL, role TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING',
    contract_version TEXT NOT NULL DEFAULT '1.0',
    provider_profile_id TEXT REFERENCES provider_profiles(id),
    external_request_id TEXT, external_execution_id TEXT,
    request_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(request_json)),
    checkpoint_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(checkpoint_json)),
    started_at TEXT, completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(task_id,attempt_id) REFERENCES task_runs(task_id,attempt_id),
    UNIQUE(task_id,attempt_id,step_key), UNIQUE(provider_profile_id,external_request_id)
);
CREATE TABLE artifact_revisions (
    id TEXT PRIMARY KEY NOT NULL, task_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL, language TEXT NOT NULL, immutable_uri TEXT NOT NULL,
    byte_sha256 TEXT NOT NULL CHECK(length(byte_sha256)=64 AND byte_sha256 NOT GLOB '*[^0-9a-f]*'),
    canonical_content_sha256 TEXT NOT NULL CHECK(length(canonical_content_sha256)=64 AND canonical_content_sha256 NOT GLOB '*[^0-9a-f]*'),
    size_bytes INTEGER NOT NULL CHECK(size_bytes>=0),
    source_version_id TEXT REFERENCES artifact_revisions(id),
    origin_authors_json TEXT NOT NULL CHECK(json_valid(origin_authors_json)),
    canonical_issued_by TEXT NOT NULL,
    reviewed_by_json TEXT NOT NULL CHECK(json_valid(reviewed_by_json)), rendered_by TEXT NOT NULL,
    a_response_ref TEXT, dependencies_json TEXT NOT NULL CHECK(json_valid(dependencies_json)),
    provenance_json TEXT NOT NULL CHECK(json_valid(provenance_json)),
    source_request_json TEXT CHECK(source_request_json IS NULL OR json_valid(source_request_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(task_id,attempt_id) REFERENCES task_runs(task_id,attempt_id),
    CHECK(immutable_uri='blob:sha256:' || byte_sha256),
    CHECK(canonical_issued_by!='A' OR a_response_ref IS NOT NULL)
);
CREATE TABLE translation_units (
    id TEXT PRIMARY KEY NOT NULL, task_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
    turn_id TEXT NOT NULL, job_id TEXT NOT NULL, block_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL REFERENCES artifact_revisions(id), source_locator TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'),
    target_ref TEXT, target_sha256 TEXT CHECK(target_sha256 IS NULL OR (length(target_sha256)=64 AND target_sha256 NOT GLOB '*[^0-9a-f]*')),
    source_language TEXT NOT NULL, target_language TEXT NOT NULL,
    glossary_version TEXT NOT NULL, policy_version TEXT NOT NULL, purpose TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count BETWEEN 0 AND 3),
    budget_id TEXT NOT NULL,
    protected_span_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(protected_span_ids_json)),
    uncertainty_codes_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(uncertainty_codes_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(task_id,attempt_id) REFERENCES task_runs(task_id,attempt_id),
    FOREIGN KEY(turn_id,task_id) REFERENCES turns(id,task_id),
    UNIQUE(job_id,block_id), CHECK(status!='READY' OR (target_ref IS NOT NULL AND target_sha256 IS NOT NULL))
);
CREATE TABLE checks (
    id TEXT PRIMARY KEY NOT NULL, task_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
    artifact_version_id TEXT REFERENCES artifact_revisions(id), job_id TEXT,
    check_kind TEXT NOT NULL, result TEXT NOT NULL CHECK(result IN ('pass','fail','not_verified','blocked')),
    severity TEXT NOT NULL DEFAULT 'none', check_version TEXT NOT NULL, verifier_model TEXT,
    evidence_ref TEXT, details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(task_id,attempt_id) REFERENCES task_runs(task_id,attempt_id)
);
CREATE TABLE usage_entries (
    id TEXT PRIMARY KEY NOT NULL, task_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
    step_id TEXT REFERENCES steps(id), provider_profile_id TEXT NOT NULL REFERENCES provider_profiles(id),
    external_request_id TEXT NOT NULL, metric TEXT NOT NULL,
    quantity REAL NOT NULL CHECK(quantity>=0), unit TEXT NOT NULL,
    cost_amount REAL CHECK(cost_amount IS NULL OR cost_amount>=0), currency TEXT, budget_id TEXT,
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(task_id,attempt_id) REFERENCES task_runs(task_id,attempt_id),
    UNIQUE(provider_profile_id,external_request_id,metric)
);
CREATE TABLE outbox_events (
    event_id TEXT PRIMARY KEY NOT NULL, conversation_id TEXT NOT NULL REFERENCES conversations(id),
    turn_id TEXT NOT NULL, task_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence>=1), conversation_sequence INTEGER NOT NULL CHECK(conversation_sequence>=1),
    kind TEXT NOT NULL, contract_version TEXT NOT NULL DEFAULT '1.0',
    internal_payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(internal_payload_json)),
    public_event_json TEXT CHECK(public_event_json IS NULL OR json_valid(public_event_json)),
    deduplication_key TEXT NOT NULL UNIQUE, delivery_state TEXT NOT NULL DEFAULT 'PENDING',
    delivery_attempts INTEGER NOT NULL DEFAULT 0 CHECK(delivery_attempts>=0), delivered_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(task_id,attempt_id) REFERENCES task_runs(task_id,attempt_id),
    FOREIGN KEY(turn_id,conversation_id) REFERENCES turns(id,conversation_id),
    FOREIGN KEY(turn_id,task_id) REFERENCES turns(id,task_id),
    UNIQUE(task_id,attempt_id,sequence), UNIQUE(conversation_id,conversation_sequence),
    CHECK(public_event_json IS NULL OR kind IN ('message.accepted','response.pending','answer.published','artifacts.published','request.failed','request.cancelled','input.required'))
);
CREATE INDEX task_runs_state ON task_runs(state);
CREATE INDEX turns_conversation ON turns(conversation_id,created_at);
CREATE INDEX outbox_pending ON outbox_events(delivery_state,conversation_id,conversation_sequence);
CREATE TRIGGER turns_immutable BEFORE UPDATE ON turns BEGIN
    SELECT RAISE(ABORT,'TURN_SNAPSHOT_IMMUTABLE');
END;
CREATE TRIGGER task_identity_immutable BEFORE UPDATE OF task_id,attempt_id,turn_id,provider_profile_id,contract_version,attempt_number,route_snapshot_json ON task_runs BEGIN
    SELECT RAISE(ABORT,'TASK_SNAPSHOT_IMMUTABLE');
END;
CREATE TRIGGER task_external_request_immutable BEFORE UPDATE OF external_request_id ON task_runs
WHEN OLD.external_request_id IS NOT NULL AND NEW.external_request_id IS NOT OLD.external_request_id BEGIN
    SELECT RAISE(ABORT,'EXTERNAL_REQUEST_IMMUTABLE');
END;
CREATE TRIGGER step_identity_immutable BEFORE UPDATE OF id,task_id,attempt_id,step_key,role,contract_version,provider_profile_id,external_request_id,request_json ON steps BEGIN
    SELECT RAISE(ABORT,'STEP_REQUEST_IMMUTABLE');
END;
CREATE TRIGGER artifact_revision_immutable BEFORE UPDATE ON artifact_revisions BEGIN
    SELECT RAISE(ABORT,'ARTIFACT_REVISION_IMMUTABLE');
END;
CREATE TRIGGER outbox_event_immutable BEFORE UPDATE OF event_id,conversation_id,turn_id,task_id,attempt_id,sequence,conversation_sequence,kind,contract_version,internal_payload_json,public_event_json,deduplication_key ON outbox_events BEGIN
    SELECT RAISE(ABORT,'OUTBOX_EVENT_IMMUTABLE');
END;
