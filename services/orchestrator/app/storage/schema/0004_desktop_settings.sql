CREATE TABLE desktop_settings (
    id INTEGER PRIMARY KEY CHECK(id=1),
    version INTEGER NOT NULL CHECK(version>=1),
    preferences_json TEXT NOT NULL CHECK(json_valid(preferences_json))
);
INSERT INTO desktop_settings(id,version,preferences_json) VALUES(1,1,'{"theme":"system","font_size":16,"send_shortcut":"enter","close_behavior":"quit"}');
ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0,1));
ALTER TABLE conversations ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1));
CREATE TABLE attachments (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    name TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    size_bytes INTEGER NOT NULL CHECK(size_bytes>0),
    status TEXT NOT NULL CHECK(status IN ('ready','blocked')),
    deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE turn_attachments (
    turn_id TEXT NOT NULL REFERENCES turns(id),
    attachment_id TEXT NOT NULL REFERENCES attachments(id),
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    PRIMARY KEY(turn_id,attachment_id), UNIQUE(turn_id,ordinal)
);
CREATE TRIGGER attachment_bytes_immutable BEFORE UPDATE OF id,conversation_id,name,sha256,size_bytes,status ON attachments BEGIN
    SELECT RAISE(ABORT,'ATTACHMENT_REFERENCE_IMMUTABLE');
END;
CREATE TRIGGER turn_attachment_immutable BEFORE UPDATE ON turn_attachments BEGIN
    SELECT RAISE(ABORT,'TURN_ATTACHMENT_IMMUTABLE');
END;
