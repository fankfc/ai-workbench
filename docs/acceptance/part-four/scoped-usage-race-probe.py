"""Deterministic local queue schedules; no process, model, network or source edits."""
from pathlib import Path
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'services' / 'orchestrator'))
from app.providers import scoped_codex_worker as worker


def trace(kind):
    value = dict(type=kind, response=dict(id='resp_fixture', object='response',
        status='completed', model='gpt-fixture'))
    return json.dumps(dict(target='codex_api::sse::responses', level='TRACE',
        fields=dict(message='SSE event: ' + json.dumps(value)))).encode()


def schedule(identity_before_error):
    boot = dict(action='invoke', timeout_seconds=6, max_output_bytes=2_000_000,
        nonce='usage_race_fixture', expected_model='gpt-fixture')
    value = worker.Worker(boot)
    packets = []
    value.emit = lambda kind, **fields: packets.append(dict(kind=kind, **fields))
    peer = worker.PipePeer([], ROOT, time.monotonic() + 6, 2_000_000,
        lambda *_: None, 'restricted')
    value.peer = peer
    peer.notifications = value.notification
    value.thread_id, value.turn_id = 'thread_fixture', 'turn_fixture'
    value.submitted = value.accepted = True
    value.notification('rawResponse/completed', dict(threadId=value.thread_id,
        turnId=value.turn_id, responseId='resp_fixture',
        usage=dict(inputTokens=30, outputTokens=3, totalTokens=33, reasoningOutputTokens=1)))
    pending_identity = [trace('response.created'), trace('response.completed')]
    if identity_before_error:
        for frame in pending_identity:
            peer.sse.feed(frame)
        value.maybe_started()
    else:
        # The stderr reader can enqueue its already-written trace only after
        # the stdout reader has delivered the fatal notification.
        def finish_readers():
            while pending_identity:
                peer.frames.put(('stderr', pending_identity.pop(0)))
        peer.close = finish_readers
    if identity_before_error:
        peer.close = lambda: None
    peer.call = lambda *_: {}
    value.observed = lambda *_: None
    value.prepare = lambda: []
    value.invoke = lambda _: peer.pump(wait=0)
    peer.frames.put(('stdout', json.dumps(dict(method='error', params=dict(
        threadId=value.thread_id, turnId=value.turn_id, message='PRIVATE_CANARY'))).encode()))
    code = value.run()
    return dict(schedule='identity_before_error' if identity_before_error else 'identity_during_failure_drain',
        exit_code=code, started_request_id=value.started_id,
        final_sse_identity=peer.sse.completed, final_raw_receipt_count=value.raw_receipt_count,
        final_receipt_count=len(value.receipts), frames=packets)


if __name__ == '__main__':
    results = [schedule(True), schedule(False)]
    print(json.dumps(dict(scope='synthetic local queue schedule, no provider execution', results=results),
        ensure_ascii=True, indent=2))
