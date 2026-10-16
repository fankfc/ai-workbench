import json
from app.runtime.public_projection import ProjectionContext, project_event

def public_events(connection, store, conversation_id, after_seq=0):
    rows = connection.execute('SELECT * FROM outbox_events WHERE conversation_id=? AND conversation_sequence>? ORDER BY conversation_sequence', (conversation_id,after_seq)).fetchall()
    output = []
    for row in rows:
        event = dict(task_id=row['task_id'],attempt_id=row['attempt_id'],sequence=row['sequence'],kind=row['kind'],payload=json.loads(row['internal_payload_json']))
        projected = project_event(event,context=ProjectionContext(connection,row['event_id'],store))
        if projected is not None:
            output.append(projected)
    return output
