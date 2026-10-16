"""Mark unpublished dependent bundles stale; published versions remain history."""
import json

from app.storage.revisions import is_current_revision


def reconcile_bundles(connection, task_id, attempt_id):
    changed=[]
    for row in connection.execute('SELECT * FROM delivery_bundles WHERE task_id=? AND attempt_id=?',(task_id,attempt_id)):
        ids=json.loads(row['dependency_fence_json'])['revisions']
        stale=not all(is_current_revision(connection,task_id,attempt_id,rid) for rid in ids)
        if stale and not row['stale']:
            connection.execute('UPDATE delivery_bundles SET stale=1 WHERE id=?',(row['id'],)); changed.append(row['id'])
    return changed


def reconcile_missing_blobs(connection,store):
    from .publish import bundle_card
    corrupt=[]
    for row in connection.execute("SELECT * FROM delivery_bundles WHERE state='PUBLISHED'"):
        try: bundle_card(connection,store,row)
        except (ValueError,OSError):
            connection.execute("UPDATE delivery_bundles SET state='CORRUPT' WHERE id=?",(row['id'],)); corrupt.append(row['id'])
    return corrupt
