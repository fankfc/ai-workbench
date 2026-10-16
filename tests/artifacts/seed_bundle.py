"""Test-only CLI; substitutes model replies, uses the complete product pipeline."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings
from app.documents.publish import BundlePublisher
from artifacts.helpers import prepare_bilingual


def seed(data_root, token, formats):
    with TestClient(create_app(AppSettings(Path(data_root),token,'fake',False))) as client:
        client.headers['Authorization']='Bearer '+token
        with closing(client.app.state.database.connect()) as c:
            c.execute("INSERT OR IGNORE INTO provider_profiles(id,adapter,model_id,family,connection_id,identity_status,identity_source,connection_version) VALUES ('fake-claude','fake','fixture-claude','claude','fake-claude','verified','fixture-response','test-only')")
        cid=client.post('/v1/conversations',json={'title':'双语报告文件验证'}).json()['id']
        accepted=client.post(f'/v1/conversations/{cid}/turns',json={'text':'请提供完整双语报告文件。','provider_profile_id':'fake-claude','client_request_id':'bundle-fixture'}).json()
        with closing(client.app.state.database.connect()) as c:
            task=dict(c.execute('SELECT * FROM task_runs WHERE task_id=?',(accepted['task_id'],)).fetchone())
        ctx=dict(client=client,cid=cid,task=task['task_id'],attempt=task['attempt_id'],turn=task['turn_id'],route=json.loads(task['route_snapshot_json']))
        ready=prepare_bilingual(ctx)
        publisher=BundlePublisher(client.app.state.database.path,Path(data_root)/'evidence')
        bid=publisher.stage(ctx['task'],ctx['attempt'],'1.0',ready['source'],formats,title='月度报告',translation_revision_id=ready['translation'],review_check_id=ready['review'])
        ready['machine'].transition(ctx['task'],ctx['attempt'],'OUTPUT_PREPARING','READY','1.0')
        card=publisher.publish(bid,answer_releaser=ready['answer'].publish_in_transaction)
        listed=client.get(f'/v1/conversations/{cid}/bundles')
        if listed.status_code!=200 or not listed.json()['items']: raise RuntimeError('PUBLIC_BUNDLE_NOT_VISIBLE')
        return {'cid':cid,'bid':bid,'artifacts':card['artifacts'],'format_pairs':card['format_pairs']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--data-root',required=True); parser.add_argument('--token',required=True)
    parser.add_argument('--formats',default='markdown,pdf,docx'); args=parser.parse_args()
    print(json.dumps(seed(args.data_root,args.token,args.formats.split(',')),ensure_ascii=False))
