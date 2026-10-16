"""Finish a durable local release at startup; never restart a model request."""
from contextlib import closing
import json
from pathlib import Path

from app.storage.database import Database, transaction
from .outbox import enqueue_event
from .publication import NativePublisher, PublicationBlocked
from .state_machine import checkpoint_for, require_current_attempt
from .workspace import WorkspaceManager, _reject_reparse


def _owned(row, checkpoint):
    if row['lease_owner'] is None:
        return True
    handoff = checkpoint.get('planning_handoff') if isinstance(checkpoint, dict) else None
    return isinstance(handoff, dict) and row['lease_owner'] == handoff.get('workflow_owner')


def _ready(connection, snapshot):
    row = require_current_attempt(connection, snapshot['task_id'], snapshot['attempt_id'], snapshot['contract_version'])
    checkpoint = checkpoint_for(row)
    if row['state'] != 'READY' or row['cancel_requested']:
        raise PublicationBlocked('READY_UNCANCELLED_REQUIRED')
    if not _owned(row, checkpoint):
        raise PublicationBlocked('FOREIGN_PUBLICATION_OWNER')
    # A historical task-level reference need not still be queryable. A current
    # invocation, however, must have its completion durably captured locally.
    from .recovery import _remote_context
    context = _remote_context(connection, row)
    active = checkpoint.get('active_external_request')
    if (context.get('remote_context_error') or active is not None
            and (active.get('accepted') is not True or active.get('status') != 'completed')):
        raise PublicationBlocked('REMOTE_COMPLETION_NOT_PERSISTED')
    return row, checkpoint


def resume_staged_publication(database_path, snapshot, provider_mode):
    database = Database(database_path)
    result = dict(task_id=snapshot['task_id'], attempt_id=snapshot['attempt_id'],
                  remote_status=snapshot['remote_status'])
    try:
        with closing(database.connect()) as connection:
            row, checkpoint = _ready(connection, snapshot)
            route = json.loads(row['route_snapshot_json'])
            if (provider_mode not in {'real', 'fake'}
                    or (provider_mode == 'fake') != (route.get('test_only') is True)):
                raise PublicationBlocked('PUBLICATION_PROVIDER_MODE_MISMATCH')
            release = checkpoint.get('public_release', {})
            check = connection.execute('SELECT details_json FROM checks WHERE id=? AND task_id=? AND attempt_id=?',
                (release.get('review_check_id'), row['task_id'], row['attempt_id'])).fetchone()
            if check is None:
                raise PublicationBlocked('CURRENT_A_REVIEW_REQUIRED')
            details = json.loads(check['details_json'])
            evidence_root = details.get('evidence_root')
            if evidence_root is None:
                evidence_root = WorkspaceManager(database.path.parent).create(row['task_id'], row['attempt_id']).area('evidence')
            evidence_root = Path(evidence_root)
            _reject_reparse(evidence_root)
            evidence_root.resolve().relative_to(database.path.parent.resolve())
            family = route.get('model_family')
            if family == 'claude':
                from .answer_publication import AnswerPublisher
                publisher = AnswerPublisher(database.path, evidence_root)
            elif family == 'gpt':
                publisher = NativePublisher(database.path, evidence_root)
            else:
                raise PublicationBlocked('SUPPORTED_A_ROUTE_REQUIRED')

        def release_answer(connection, task, *, bundle_id=None):
            current, _ = _ready(connection, snapshot)
            if (current['task_id'], current['attempt_id']) != (task['task_id'], task['attempt_id']):
                raise PublicationBlocked('PUBLICATION_TASK_MISMATCH')
            return publisher.publish_in_transaction(connection, current, bundle_id=bundle_id)

        if checkpoint.get('requested_formats') or checkpoint.get('document_request'):
            from app.documents.publish import BundlePublisher
            bundle_id = checkpoint.get('native_document', {}).get('bundle_id')
            if not bundle_id:
                raise PublicationBlocked('COMPLETE_DOCUMENT_BUNDLE_REQUIRED')
            with closing(database.connect()) as connection:
                bundle = connection.execute('SELECT task_id,attempt_id,state FROM delivery_bundles WHERE id=?', (bundle_id,)).fetchone()
                if (bundle is None or (bundle['task_id'], bundle['attempt_id'], bundle['state'])
                        != (snapshot['task_id'], snapshot['attempt_id'], 'VERIFIED')):
                    raise PublicationBlocked('CURRENT_VERIFIED_BUNDLE_REQUIRED')
            BundlePublisher(database.path, evidence_root).publish(bundle_id, answer_releaser=release_answer)
        else:
            with closing(database.connect()) as connection, transaction(connection):
                current, _ = _ready(connection, snapshot)
                release_answer(connection, current)
        with closing(database.connect()) as connection:
            committed = require_current_attempt(connection, snapshot['task_id'], snapshot['attempt_id'])
            if committed['state'] != 'PUBLISHED':
                raise PublicationBlocked('LOCAL_PUBLICATION_NOT_COMMITTED')
        result.update(decision='local_publication_resumed', state='PUBLISHED')
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        # Re-read before touching state: another attempt, cancellation, or owner
        # wins over this startup observation. Never requeue the original request.
        with closing(database.connect()) as connection, transaction(connection):
            try:
                current = require_current_attempt(connection, snapshot['task_id'], snapshot['attempt_id'])
            except ValueError:
                return dict(result, decision='stale_attempt', state=snapshot['state'])
            if current['state'] != 'READY' or current['cancel_requested']:
                return dict(result, decision='terminal_preserved', state=current['state'])
            try:
                checkpoint = checkpoint_for(current)
            except (ValueError, TypeError):
                checkpoint = None
            if not _owned(current, checkpoint):
                return dict(result, decision='local_publication_deferred', state=current['state'])
            if checkpoint is not None:
                checkpoint.pop('release_registry', None)
                checkpoint['recovery_decision'] = 'blocked_local_publication'
            # Retain malformed checkpoint bytes for diagnosis; blocking must
            # not replace the user's persisted evidence with an invented view.
            connection.execute("UPDATE task_runs SET state='BLOCKED',checkpoint_json=?,lease_owner=NULL,lease_expires_at=NULL WHERE task_id=? AND attempt_id=?",
                (json.dumps(checkpoint) if checkpoint is not None else current['checkpoint_json'], current['task_id'], current['attempt_id']))
            enqueue_event(connection, current['task_id'], current['attempt_id'], 'request.failed',
                {'error_code': 'VALIDATION_FAILED'}, deduplication_key='startup-publication-blocked:' + current['attempt_id'])
            result.update(decision='blocked_local_publication', state='BLOCKED')
    return result
