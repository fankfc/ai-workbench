import json
import sqlite3
import subprocess
import sys
import os

import pytest

from app.storage.database import Database, transaction
from app.runtime.outbox import Outbox, OutboxError, enqueue_event
from test_state_machine import initialize_runtime


def enqueue(path, key="pending1", **kwargs):
    connection = Database(path).connect()
    try:
        with transaction(connection):
            return enqueue_event(connection,"task1","a1","response.pending",{"origin":"internal"},
                                 deduplication_key=key, public_payload={"status":"pending"}, **kwargs)
    finally:
        connection.close()


def test_outbox_enqueues_validated_public_event_with_stable_envelope(tmp_path):
    path = initialize_runtime(tmp_path)
    row = enqueue(path)
    public = json.loads(row["public_event_json"])
    assert public["event_id"] == row["event_id"]
    assert public["sequence"] == row["conversation_sequence"] == 1
    assert public["conversation_id"] == "c1" and public["attempt_id"] == "a1"
    assert Outbox(path).pending()[0]["event_id"] == row["event_id"]


def test_outbox_deduplicates_exact_same_operation_but_rejects_reused_key(tmp_path):
    path = initialize_runtime(tmp_path)
    assert enqueue(path)["event_id"] == enqueue(path)["event_id"]
    connection = Database(path).connect()
    try:
        with transaction(connection):
            with pytest.raises(OutboxError, match="DEDUPLICATION_KEY_CONFLICT"):
                enqueue_event(connection,"task1","a1","response.pending",{"changed":True},
                              deduplication_key="pending1",public_payload={"status":"pending"})
        assert connection.execute("SELECT count(*) FROM outbox_events").fetchone()[0] == 1
    finally:
        connection.close()


def test_outbox_replay_uses_conversation_cursor_across_turns(tmp_path):
    path = initialize_runtime(tmp_path)
    first = enqueue(path)
    connection = Database(path).connect()
    try:
        connection.execute("""INSERT INTO turns(id,conversation_id,task_id,provider_profile_id,client_request_id,user_text)
                           VALUES('t2','c1','task2','p1','request2','第二轮')""")
        connection.execute("""INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id,state)
                           VALUES('task2','a2','t2','p1','RECEIVED')""")
        with transaction(connection):
            second = enqueue_event(connection,"task2","a2","response.pending",{},deduplication_key="pending2",public_payload={"status":"pending"})
        assert second["sequence"] == 1
        assert second["conversation_sequence"] == 2
        assert [event["sequence"] for event in Outbox(path).replay("c1")] == [1,2]
        assert Outbox(path).replay("c1", after_seq=first["conversation_sequence"])[0]["task_id"] == "task2"
    finally:
        connection.close()


def test_outbox_failure_after_commit_keeps_pending_event_and_never_restarts_model(tmp_path):
    path = initialize_runtime(tmp_path)
    row = enqueue(path)
    def fail(event):
        raise RuntimeError("transport unavailable")
    with pytest.raises(RuntimeError, match="transport unavailable"):
        Outbox(path).dispatch(fail)
    assert Outbox(path).pending()[0]["event_id"] == row["event_id"]
    sent = []
    assert Outbox(path).dispatch(sent.append) == 1
    assert sent[0]["event_id"] == row["event_id"]
    assert Outbox(path).pending() == []


def test_outbox_repeated_send_before_ack_uses_same_event_id_for_receiver_dedup(tmp_path):
    path = initialize_runtime(tmp_path)
    row = enqueue(path)
    seen = set()
    published = []
    def receiver_then_crash(event):
        if event["event_id"] not in seen:
            seen.add(event["event_id"])
            published.append(event)
        raise RuntimeError("crash before ack")
    for _ in range(2):
        with pytest.raises(RuntimeError, match="crash before ack"):
            Outbox(path).dispatch(receiver_then_crash)
    assert len(published) == 1
    Outbox(path).acknowledge(row["event_id"])
    assert Outbox(path).pending() == []


def test_internal_events_are_not_sent_or_replayed_publicly(tmp_path):
    path = initialize_runtime(tmp_path)
    connection = Database(path).connect()
    try:
        with transaction(connection):
            enqueue_event(connection,"task1","a1","model.delta",{"text":"SECRET"},deduplication_key="internal1")
    finally:
        connection.close()
    sent = []
    assert Outbox(path).dispatch(sent.append) == 0
    assert sent == [] and Outbox(path).replay("c1") == []
    assert Outbox(path).pending() == []


def test_invalid_public_payload_rolls_back_and_cannot_leak_model_delta(tmp_path):
    path = initialize_runtime(tmp_path)
    connection = Database(path).connect()
    try:
        with pytest.raises(ValueError):
            with transaction(connection):
                enqueue_event(connection,"task1","a1","model.delta",{"text":"SECRET"},
                              deduplication_key="bad",public_payload={"text":"SECRET"})
        assert connection.execute("SELECT count(*) FROM outbox_events").fetchone()[0] == 0
    finally:
        connection.close()


def run_crash_window(tmp_path,point,code):
    path = initialize_runtime(tmp_path)
    received = tmp_path / "receiver.jsonl"
    script = """
import json,os,sys
from app.storage.database import Database,transaction
from app.runtime.state_machine import StateMachine
from app.runtime.outbox import Outbox,enqueue_event
import app.runtime.state_machine as state_module
point=sys.argv[3]
if point=='before-commit':
    class CrashDatabase(Database):
        def connect(self):
            connection=super().connect()
            connection.create_function('die',0,lambda:os._exit(81))
            return connection
    state_module.Database=CrashDatabase
    connection=CrashDatabase(sys.argv[1]).connect()
    connection.execute("CREATE TRIGGER crash BEFORE INSERT ON outbox_events BEGIN SELECT die(); END")
    connection.close()
StateMachine(sys.argv[1]).transition('task1','a1','RECEIVED','INPUT_PREPARING','1.0')
connection=Database(sys.argv[1]).connect()
with transaction(connection):
    enqueue_event(connection,'task1','a1','response.pending',{},deduplication_key='public1',public_payload={'status':'pending'})
connection.close()
if point=='after-commit':
    os._exit(82)
def send(event):
    with open(sys.argv[2],'a',encoding='utf-8') as handle:
        handle.write(json.dumps(event)+'\\n')
        handle.flush()
        os.fsync(handle.fileno())
    os._exit(83)
Outbox(sys.argv[1]).dispatch(send)
"""
    result = subprocess.run([sys.executable,"-c",script,str(path),str(received),point],capture_output=True,text=True,timeout=20)
    assert result.returncode == code, result.stderr
    connection = Database(path).connect()
    try:
        state = connection.execute("SELECT state FROM task_runs").fetchone()[0]
        count = connection.execute("SELECT count(*) FROM outbox_events").fetchone()[0]
        assert state == ("RECEIVED" if point == "before-commit" else "INPUT_PREPARING")
        assert count == (0 if point == "before-commit" else 2)
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()
    if point == "before-commit":
        assert Outbox(path).pending() == []
        return {"point":point,"exit_code":result.returncode,"task_state":state,"event_count":count,"receiver_count":0,"pending_count":0}
    def deduplicating_receiver(event):
        seen = {json.loads(line)["event_id"] for line in received.read_text(encoding="utf-8").splitlines()} if received.exists() else set()
        if event["event_id"] not in seen:
            with received.open("a",encoding="utf-8") as handle:
                handle.write(json.dumps(event)+"\n")
                handle.flush()
                os.fsync(handle.fileno())
    assert Outbox(path).dispatch(deduplicating_receiver) == 1
    assert Outbox(path).dispatch(deduplicating_receiver) == 0
    assert len(received.read_text(encoding="utf-8").splitlines()) == 1
    assert Outbox(path).pending() == []
    return {"point":point,"exit_code":result.returncode,"task_state":state,"event_count":count,"receiver_count":1,"pending_count":0,
            "receiver_event_id":json.loads(received.read_text(encoding="utf-8").splitlines()[0])["event_id"]}


@pytest.mark.parametrize("point,code", [("before-commit",81),("after-commit",82),("send-before-ack",83)])
def test_real_process_crash_windows_preserve_state_and_delivery_identity(tmp_path,point,code):
    run_crash_window(tmp_path,point,code)


def test_unapproved_answer_public_schema_cannot_authorize_dispatch_or_replay(tmp_path):
    path = initialize_runtime(tmp_path)
    connection = Database(path).connect()
    try:
        with transaction(connection):
            enqueue_event(connection,"task1","a1","answer.published",{"text":"INTERNAL_CANARY"},deduplication_key="fake-answer",
                          public_payload={"message_id":"fake","text":"INTERNAL_CANARY","language":"zh-CN",
                                          "content_version_id":"invented","approval_id":"invented"})
    finally:
        connection.close()
    sent = []
    assert Outbox(path).dispatch(sent.append) == 0
    assert sent == [] and Outbox(path).replay("c1") == []


def test_outbox_accepted_message_reads_source_turn_instead_of_public_claim(tmp_path):
    path = initialize_runtime(tmp_path)
    connection = Database(path).connect()
    try:
        with transaction(connection):
            enqueue_event(connection,"task1","a1","message.accepted",{},deduplication_key="fake-message",
                          public_payload={"message_id":"invented","text":"INTERNAL_CANARY","language":"en"})
    finally:
        connection.close()
    replay = Outbox(path).replay("c1")
    sent = []
    assert Outbox(path).dispatch(sent.append) == 1
    assert replay[0]["payload"]["text"] == sent[0]["payload"]["text"] == "输入"
    assert replay[0]["payload"]["message_id"] == "t1" and replay[0]["payload"]["language"] == "zh-CN"


def test_outbox_internal_error_claim_uses_fixed_chinese_public_template(tmp_path):
    path = initialize_runtime(tmp_path)
    connection = Database(path).connect()
    try:
        with transaction(connection):
            enqueue_event(connection,"task1","a1","request.failed",{"error_code":"PROVIDER_UNAVAILABLE","raw":"CANARY"},
                          deduplication_key="failure",public_payload={"error_code":"PROVIDER_UNAVAILABLE","text":"CANARY","language":"zh-CN","action":"none"})
    finally:
        connection.close()
    sent = []
    assert Outbox(path).dispatch(sent.append) == 1
    assert sent[0]["payload"]["text"] == "模型连接暂不可用，请检查连接。"
    assert "CANARY" not in json.dumps(sent)
