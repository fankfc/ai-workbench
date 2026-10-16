CREATE TABLE route_snapshots (
    id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT NOT NULL, turn_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
    snapshot_sha256 TEXT NOT NULL CHECK(length(snapshot_sha256)=64),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(task_id,attempt_id) REFERENCES task_runs(task_id,attempt_id),
    UNIQUE(turn_id,attempt_id)
);
CREATE TRIGGER route_snapshot_immutable BEFORE UPDATE ON route_snapshots BEGIN
    SELECT RAISE(ABORT,'ROUTE_SNAPSHOT_IMMUTABLE');
END;
CREATE TABLE route_invalidations (
    route_snapshot_id TEXT PRIMARY KEY REFERENCES route_snapshots(id),
    reason TEXT NOT NULL, observed_json TEXT NOT NULL CHECK(json_valid(observed_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE translation_jobs (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, attempt_id TEXT NOT NULL, turn_id TEXT NOT NULL,
    route_snapshot_id TEXT NOT NULL REFERENCES route_snapshots(id),
    job_json TEXT NOT NULL CHECK(json_valid(job_json)),
    source_ref TEXT NOT NULL, source_sha256 TEXT NOT NULL,
    source_version_id TEXT, source_locator TEXT NOT NULL,
    direction TEXT NOT NULL, context_sha256 TEXT NOT NULL,
    glossary_version TEXT NOT NULL, policy_version TEXT NOT NULL, translator_model_version TEXT NOT NULL,
    cache_key TEXT NOT NULL, segments_json TEXT NOT NULL CHECK(json_valid(segments_json)),
    status TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count BETWEEN 0 AND 3),
    target_ref TEXT, target_sha256 TEXT, qa_id TEXT, clarification TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(task_id,attempt_id) REFERENCES task_runs(task_id,attempt_id)
);
CREATE INDEX translation_jobs_recovery ON translation_jobs(task_id,attempt_id,status);
CREATE TABLE translation_candidates (
    job_id TEXT NOT NULL REFERENCES translation_jobs(id), candidate INTEGER NOT NULL CHECK(candidate BETWEEN 1 AND 3),
    blocks_json TEXT NOT NULL CHECK(json_valid(blocks_json)), target_ref TEXT,
    qa_json TEXT NOT NULL CHECK(json_valid(qa_json)), difference_json TEXT NOT NULL CHECK(json_valid(difference_json)),
    PRIMARY KEY(job_id,candidate)
);
CREATE TABLE translation_calls (
    request_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES translation_jobs(id),
    phase TEXT NOT NULL CHECK(phase IN ('translate','check')), candidate INTEGER NOT NULL CHECK(candidate BETWEEN 1 AND 3),
    connection_attempt INTEGER NOT NULL CHECK(connection_attempt BETWEEN 1 AND 3),
    status TEXT NOT NULL, response_json TEXT, usage_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(usage_json)),
    UNIQUE(job_id,phase,candidate,connection_attempt)
);
CREATE TABLE translation_cache (
    cache_key TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL, target_ref TEXT NOT NULL, target_sha256 TEXT NOT NULL,
    blocks_json TEXT NOT NULL CHECK(json_valid(blocks_json)), qa_json TEXT NOT NULL CHECK(json_valid(qa_json)),
    glossary_version TEXT NOT NULL, dependency_json TEXT NOT NULL CHECK(json_valid(dependency_json)),
    valid INTEGER NOT NULL DEFAULT 1 CHECK(valid IN (0,1))
);
CREATE TABLE translation_glossaries (
    task_id TEXT NOT NULL, version TEXT NOT NULL, domain TEXT NOT NULL,
    entries_json TEXT NOT NULL CHECK(json_valid(entries_json)), reason TEXT NOT NULL,
    affected_blocks_json TEXT NOT NULL CHECK(json_valid(affected_blocks_json)), PRIMARY KEY(task_id,version)
);
CREATE TRIGGER glossary_immutable BEFORE UPDATE ON translation_glossaries BEGIN
    SELECT RAISE(ABORT,'GLOSSARY_VERSION_IMMUTABLE');
END;
CREATE TABLE bilingual_history (
    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id), task_id TEXT NOT NULL,
    turn_id TEXT NOT NULL REFERENCES turns(id), source_role TEXT NOT NULL, language TEXT NOT NULL,
    raw_content_ref TEXT NOT NULL, content_sha256 TEXT NOT NULL,
    parent_message_id TEXT, route_snapshot_id TEXT NOT NULL REFERENCES route_snapshots(id),
    visibility TEXT NOT NULL CHECK(visibility IN ('user','internal','attachment')),
    english_ref TEXT, english_sha256 TEXT, job_id TEXT REFERENCES translation_jobs(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
