"""Full accepted history and immutable attachment text within one conversation."""
import json
import hashlib
from app.api.public_events import public_events
from app.documents.parse import parse_document
from app.storage.blobs import BlobStore


def prepare_conversation_source(connection, database_path, task, workspace):
    current = connection.execute('SELECT rowid AS ordering,* FROM turns WHERE id=?', (task['turn_id'],)).fetchone()
    turns = connection.execute('SELECT rowid AS ordering,* FROM turns WHERE conversation_id=? AND rowid<=? ORDER BY rowid',
                               (current['conversation_id'], current['ordering'])).fetchall()
    store = BlobStore(database_path.parent / 'blobs')
    cutoff = connection.execute("SELECT MIN(conversation_sequence) FROM outbox_events WHERE turn_id=? AND kind='message.accepted'", (current['id'],)).fetchone()[0]
    answers = public_events(connection, store, current['conversation_id'])
    approved_history=[]
    for event in answers:
        if event['sequence'] >= cutoff:
            continue
        if event['kind']=='answer.published':
            approved_history.append(event)
        elif event['kind']=='input.required':
            # Template prompts are UI status. An actual A clarification has a
            # separately frozen source/translation/publication proof.
            from app.translation.clarification import validate_publication
            try:
                validate_publication(connection,store,event['event_id'],historical=True)
            except (ValueError,KeyError):
                continue
            approved_history.append(event)
    answers=approved_history
    parts, manifest = [], []
    for turn in turns:
        parts.append(turn['user_text'] if len(turns) == 1 else '用户原话：\n' + turn['user_text'])
        attachments = connection.execute('SELECT a.* FROM attachments a JOIN turn_attachments t ON t.attachment_id=a.id WHERE t.turn_id=? ORDER BY t.ordinal', (turn['id'],)).fetchall()
        for item in attachments:
            raw = store.read(item['sha256'])
            suffix = item['name'].rsplit('.', 1)[-1].lower()
            source_ref = 'input/attachment_' + item['id'] + '.' + suffix
            if workspace.resolve(source_ref).exists():
                if workspace.read('service', source_ref) != raw:
                    raise ValueError('ATTACHMENT_SOURCE_CHANGED')
            else:
                workspace.ingest_source(source_ref.removeprefix('input/'), raw)
            if suffix in {'txt', 'csv', 'json', 'md'}:
                text = raw.decode('utf-8-sig')
                block_scope = []
            else:
                model = parse_document(raw, suffix, source_version_id=item['id'], language='mul')
                if not model.complete:
                    raise ValueError('INPUT_DOCUMENT_NEEDS_CLARIFICATION')
                text = '\n\n'.join(block.content for block in model.blocks)
                block_scope = [dict(block_id=block.block_id,source_locator=block.source_locator,
                    source_sha256=block.source_sha256,kind=block.kind) for block in model.blocks]
            # Binary originals are immutable evidence. Models read only this
            # complete, derived UTF-8 view; incomplete parses never reach A.
            text_ref='input/attachment_'+item['id']+'.parsed.md'
            encoded=text.encode('utf-8')
            if workspace.resolve(text_ref).exists():
                if workspace.read('service',text_ref)!=encoded:
                    raise ValueError('ATTACHMENT_DERIVED_SOURCE_CHANGED')
            else:
                workspace.ingest_source(text_ref.removeprefix('input/'),encoded)
            parts.append('附件 ' + item['name'] + ' 的完整内容：\n' + text)
            manifest.append(dict(attachment_id=item['id'], source_ref=source_ref, source_sha256=item['sha256'],
                text_ref=text_ref,text_sha256=hashlib.sha256(encoded).hexdigest(),text_format='markdown',
                coverage='full',parsed=True,block_scope=block_scope))
        for answer in answers:
            if answer['turn_id'] == turn['id']:
                label='此前批准的回答：' if answer['kind']=='answer.published' else '此前必要的澄清问题：'
                parts.append(label+'\n' + answer['payload']['text'])
    return '\n\n'.join(parts), manifest
