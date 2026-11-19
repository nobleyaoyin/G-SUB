"""Isolated G-SUB DOCX routes; ONLYOFFICE fetch is mocked, no service is contacted."""
import importlib
import io
import os
import unittest
import zipfile
from unittest.mock import patch

import jwt
from fastapi import HTTPException
from app import models, onlyoffice_docx
from tests.academic_docx_fixture import academic_docx
from tests import test_reviewer_download, test_final_workflow

SECRET = 'synthetic-onlyoffice-test-secret-over-32-bytes'
CONFIG = {'GSUB_ONLYOFFICE_ENABLED':'1', 'GSUB_ONLYOFFICE_SECRET':SECRET,
          'GSUB_ONLYOFFICE_SERVER_ORIGIN':'http://127.0.0.1:8088', 'GSUB_ONLYOFFICE_APP_ORIGIN':'http://127.0.0.1:8090'}


def modified_docx(data):
    out=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(out,'w') as modified:
        for name in original.namelist():
            content=original.read(name)
            if name == 'word/document.xml': content=content.replace(b'Synthetic Academic Manuscript',b'Synthetic Changed Manuscript')
            modified.writestr(name,content)
    return out.getvalue()


class DocxIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.f = test_reviewer_download.ReviewerDownloadsTest('runTest'); self.f.setUp(); self.addCleanup(self.f.tearDown)
        for n in ('014_online_document_versions', '016_onlyoffice_sessions'):
            module = importlib.import_module('migrations.' + n); module.migrate(self.f.db_path); module.migrate(self.f.db_path)
        for p in (patch.dict(os.environ, CONFIG), patch.object(onlyoffice_docx, 'BASE_DIR', self.f.root)):
            p.start(); self.addCleanup(p.stop)
        f = self.f
        self.content = academic_docx()
        self.source = f.write('uploads/manuscripts/2/source.docx', self.content)
        m = models.Manuscript(manuscript_id=2,title='Synthetic',abstract='Synthetic',author_id=f.author.user_id,status='revision_required',review_round=1,file_path=self.source)
        f.db.add(m); f.db.commit()

    def callback(self, sid, status=2, url='http://127.0.0.1:8088/cache/files/synthetic'):
        body = {'key':sid,'status':status,'url':url}
        if status == 6: body['forcesavetype'] = 1
        token = jwt.encode({'payload':body,'operation':'callback'}, SECRET, algorithm='HS256')
        return self.f.client.post('/onlyoffice/callbacks/'+sid, json=body, headers={'Authorization':'Bearer '+token})

    def test_configured_backend_origin_is_used_for_documents_and_callbacks(self):
        self.f.current = self.f.author
        configured = {'GSUB_ONLYOFFICE_SERVER_ORIGIN':'http://127.0.0.1:8080',
                      'GSUB_ONLYOFFICE_APP_ORIGIN':'http://host.docker.internal:8000'}
        with patch.dict(os.environ, configured):
            response = self.f.client.post('/onlyoffice/manuscripts/2/author/sessions')
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['editorOrigin'], configured['GSUB_ONLYOFFICE_SERVER_ORIGIN'])
        self.assertTrue(data['config']['document']['url'].startswith('http://host.docker.internal:8000/onlyoffice/documents/'))
        self.assertTrue(data['config']['editorConfig']['callbackUrl'].startswith('http://host.docker.internal:8000/onlyoffice/callbacks/'))

    def test_gateway_prefix_in_signed_document_and_callback_urls(self):
        self.f.current = self.f.author
        with patch.dict(os.environ, {'GSUB_ONLYOFFICE_APP_ORIGIN': 'http://host.docker.internal:8765/api'}):
            response = self.f.client.post('/onlyoffice/manuscripts/2/author/sessions')
        self.assertEqual(response.status_code, 200, response.text)
        config = response.json()['config']
        self.assertTrue(config['document']['url'].startswith('http://host.docker.internal:8765/api/onlyoffice/documents/'))
        self.assertTrue(config['editorConfig']['callbackUrl'].startswith('http://host.docker.internal:8765/api/onlyoffice/callbacks/'))
        for path in ('/api/other', '/api/../', '/other'):
            with patch.dict(os.environ, {'GSUB_ONLYOFFICE_APP_ORIGIN': 'http://host.docker.internal:8765' + path}):
                with self.assertRaises(HTTPException): onlyoffice_docx.config()

    def test_author_session_save_history_replay_and_stage_change(self):
        f = self.f; f.current = f.author
        base = '/onlyoffice/manuscripts/2/author'
        self.assertTrue(f.client.get(base+'/availability').json()['available'])
        opened = f.client.post(base+'/sessions'); self.assertEqual(opened.status_code,200,opened.text)
        cfg = opened.json(); sid = cfg['session']
        from urllib.parse import urlsplit
        uri = urlsplit(cfg['config']['document']['url'])
        self.assertEqual(f.client.get(uri.path+'?'+uri.query).content,self.content)
        saved = self.content.replace(b'not-present',b'not-present')  # Synthetic document; no conversion.
        with patch.object(onlyoffice_docx,'fetch',return_value=saved):
            self.assertEqual(self.callback(sid,6).json(),{'error':0})
            self.assertEqual(self.callback(sid,6).json(),{'error':0})
        history = f.client.get(base+'/versions').json(); self.assertEqual(len(history),1)
        self.assertEqual(f.client.get(base+'/versions/'+history[0]['id']).content,saved)
        self.assertEqual((f.root/self.source).read_bytes(),self.content)
        f.db.expire_all(); self.assertEqual(f.db.get(models.Manuscript,2).status,'revision_required')
        f.db.get(models.Manuscript,2).status='submitted'; f.db.commit()
        self.assertEqual(f.client.get(uri.path+'?'+uri.query).status_code,409)
        self.assertEqual(self.callback(sid,2).status_code,409)

    def test_status_preview_and_selected_author_resubmission(self):
        f=self.f; f.current=f.author; base='/onlyoffice/manuscripts/2/author'
        sid=f.client.post(base+'/sessions').json()['session']
        self.assertEqual(f.client.get(base+'/sessions/'+sid+'/status').json()['state'],'waiting')
        with patch.object(onlyoffice_docx,'fetch',return_value=self.content):
            self.assertEqual(self.callback(sid,6).status_code,200)
        status=f.client.get(base+'/sessions/'+sid+'/status').json()
        self.assertEqual(status['state'],'saved'); vid=status['version']['id']
        preview=f.client.post(base+'/versions/'+vid+'/preview'); self.assertEqual(preview.status_code,200,preview.text)
        cfg=preview.json()['config']; self.assertEqual(cfg['editorConfig']['mode'],'view'); self.assertFalse(cfg['document']['permissions']['edit'])
        from urllib.parse import urlsplit
        uri=urlsplit(cfg['document']['url']); self.assertEqual(f.client.get(uri.path+'?'+uri.query).content,self.content)
        f.current=f.reviewer; self.assertNotEqual(f.client.post(base+'/versions/'+vid+'/preview').status_code,200)
        self.assertNotEqual(f.client.get(base+'/sessions/'+sid+'/status').status_code,200)
        f.current=f.author
        result=f.client.post('/manuscripts/2/resubmit?selected_docx_version='+vid,json={'title':'Synthetic revised','abstract':'Synthetic abstract'})
        self.assertEqual(result.status_code,200,result.text)
        f.db.expire_all(); self.assertEqual(f.db.get(models.Manuscript,2).status,'revised')
        self.assertNotEqual(f.client.get(uri.path+'?'+uri.query).status_code,200)

    def test_failed_status_and_selected_editor_submission(self):
        f=self.f; f.db.get(models.Manuscript,2).status='initial_editing'
        f.db.add(models.InitialEditorInvitation(manuscript_id=2,editor_id=f.editor.user_id,invited_by=f.editor.user_id,status='accepted')); f.db.commit()
        f.current=f.editor; base='/onlyoffice/manuscripts/2/initial'
        sid=f.client.post(base+'/sessions').json()['session']
        self.assertEqual(self.callback(sid,7).status_code,200)
        self.assertEqual(f.client.get(base+'/sessions/'+sid+'/status').json()['state'],'error')
        with patch.object(onlyoffice_docx,'fetch',return_value=self.content): self.assertEqual(self.callback(sid,6).status_code,200)
        vid=f.client.get(base+'/sessions/'+sid+'/status').json()['version']['id']
        result=f.client.post('/eic/initial-editing/2/submit',data={'comments':'Synthetic','expected_online_version':'docx:'+vid},files={'file':('draft.docx',self.content,onlyoffice_docx.MIME)})
        self.assertEqual(result.status_code,201,result.text)

    def test_stale_author_selection_and_preview_cross_manuscript(self):
        f=self.f; f.current=f.author; base='/onlyoffice/manuscripts/2/author'
        sid=f.client.post(base+'/sessions').json()['session']
        with patch.object(onlyoffice_docx,'fetch',return_value=self.content): self.assertEqual(self.callback(sid,6).status_code,200)
        first=f.client.get(base+'/versions').json()[0]['id']
        with patch.object(onlyoffice_docx,'fetch',return_value=modified_docx(self.content)):
            self.assertEqual(self.callback(sid,6,url='http://127.0.0.1:8088/cache/files/second').status_code,200)
        self.assertNotEqual(f.client.post('/onlyoffice/manuscripts/999/author/versions/'+first+'/preview').status_code,200)
        result=f.client.post('/manuscripts/2/resubmit?selected_docx_version='+first,json={'title':'Synthetic','abstract':'Synthetic'})
        self.assertEqual(result.status_code,409)
        f.db.expire_all(); self.assertEqual(f.db.get(models.Manuscript,2).status,'revision_required')
        self.assertEqual((f.root/self.source).read_bytes(),self.content)

    def test_author_initial_revision_selected_draft(self):
        f=self.f; f.current=f.author; m=f.db.get(models.Manuscript,2); m.status='initial_revision_required'
        eic=models.User(name='Synthetic EIC',email='eic-initial@example.invalid',password_hash='x',role='eic')
        f.db.add(eic); f.db.flush(); f.db.add(models.EICInitialScan(manuscript_id=2,eic_id=eic.user_id,decision='revision_required',comments='Synthetic')); f.db.commit()
        base='/onlyoffice/manuscripts/2/author'; sid=f.client.post(base+'/sessions').json()['session']
        with patch.object(onlyoffice_docx,'fetch',return_value=self.content): self.assertEqual(self.callback(sid,6).status_code,200)
        vid=f.client.get(base+'/versions').json()[0]['id']
        result=f.client.post('/manuscripts/2/initial-resubmit?selected_docx_version='+vid,json={})
        self.assertEqual(result.status_code,200,result.text)
        f.db.expire_all(); self.assertEqual(f.db.get(models.Manuscript,2).status,'submitted')

    def test_stale_editor_selection_and_modified_upload_rejected(self):
        f=self.f; f.db.get(models.Manuscript,2).status='initial_editing'
        f.db.add(models.InitialEditorInvitation(manuscript_id=2,editor_id=f.editor.user_id,invited_by=f.editor.user_id,status='accepted')); f.db.commit()
        f.current=f.editor; base='/onlyoffice/manuscripts/2/initial'; sid=f.client.post(base+'/sessions').json()['session']
        with patch.object(onlyoffice_docx,'fetch',return_value=self.content): self.assertEqual(self.callback(sid,6).status_code,200)
        first=f.client.get(base+'/versions').json()[0]['id']; changed=modified_docx(self.content)
        with patch.object(onlyoffice_docx,'fetch',return_value=changed): self.assertEqual(self.callback(sid,6,url='http://127.0.0.1:8088/cache/files/new').status_code,200)
        second=f.client.get(base+'/versions').json()[-1]['id']
        endpoint='/eic/initial-editing/2/submit'
        for vid,content in ((first,self.content),(second,self.content)):
            result=f.client.post(endpoint,data={'comments':'Synthetic','expected_online_version':'docx:'+vid},files={'file':('draft.docx',content,onlyoffice_docx.MIME)})
            self.assertEqual(result.status_code,409,result.text)
        f.db.expire_all(); self.assertEqual(f.db.get(models.Manuscript,2).status,'initial_editing')

    def test_unauthorized_disabled_and_stale_sessions(self):
        f=self.f; base='/onlyoffice/manuscripts/2/author'
        f.current=f.reviewer; self.assertEqual(f.client.post(base+'/sessions').status_code,404)
        f.current=f.author
        with patch.dict(os.environ,{'GSUB_ONLYOFFICE_ENABLED':'0'}):
            self.assertFalse(f.client.get(base+'/availability').json()['available'])
            self.assertEqual(f.client.post(base+'/sessions').status_code,503)
        a=f.client.post(base+'/sessions').json()['session']; b=f.client.post(base+'/sessions').json()['session']
        self.assertEqual(f.client.post('/onlyoffice/callbacks/'+a,json={'key':a,'status':2}).status_code,403)
        with patch.object(onlyoffice_docx,'fetch',return_value=self.content):
            self.assertEqual(self.callback(a).status_code,200)
            self.assertEqual(self.callback(b).status_code,409)

    def test_initial_editor_and_revocation(self):
        f=self.f
        f.db.get(models.Manuscript,2).status='initial_editing'
        f.db.add(models.InitialEditorInvitation(manuscript_id=2,editor_id=f.editor.user_id,invited_by=f.editor.user_id,status='accepted')); f.db.commit()
        base='/onlyoffice/manuscripts/2/initial'; f.current=f.editor
        session=f.client.post(base+'/sessions'); self.assertEqual(session.status_code,200,session.text)
        sid=session.json()['session']
        f.current=f.author; self.assertEqual(f.client.post(base+'/sessions').status_code,404)
        f.current=f.editor
        with patch.object(onlyoffice_docx,'fetch',return_value=self.content):
            self.assertEqual(self.callback(sid,6).status_code,200)
        self.assertEqual(len(f.client.get(base+'/versions').json()),1)
        f.db.expire_all(); self.assertEqual(f.db.get(models.Manuscript,2).status,'initial_editing')
        self.assertEqual(f.client.post(base+'/sessions/'+sid+'/revoke').status_code,200)
        self.assertEqual(self.callback(sid).status_code,403)

    def test_source_changes_expiry_and_unassigned_editor(self):
        f=self.f; f.current=f.author; base='/onlyoffice/manuscripts/2/author'
        sid=f.client.post(base+'/sessions').json()['session']
        from sqlalchemy import text
        f.db.execute(text('UPDATE onlyoffice_sessions SET expires_at=1 WHERE session_id=:sid'), {'sid':sid}); f.db.commit()
        self.assertEqual(self.callback(sid).status_code,403)
        sid=f.client.post(base+'/sessions').json()['session']
        (f.root/self.source).write_bytes(academic_docx() + b'changed')
        self.assertEqual(self.callback(sid).status_code,409)
        f.db.get(models.Manuscript,2).status='initial_editing'; f.db.commit(); f.current=f.editor
        self.assertEqual(f.client.post('/onlyoffice/manuscripts/2/initial/sessions').status_code,404)

    def test_callback_url_rejects_private_host_and_redirect(self):
        from fastapi import HTTPException
        for url in ('http://10.0.0.1:8088/cache/files/x','http://localhost:8088/cache/files/x','http://127.0.0.1:8088/cache/files/%2e%2e/admin'):
            with self.subTest(url=url), self.assertRaises(HTTPException): onlyoffice_docx.fetch(url,'http://127.0.0.1:8088')
        class Reply: status=302
        class Conn:
            def __init__(self,*args,**kwargs): pass
            def request(self,*args,**kwargs): pass
            def getresponse(self): return Reply()
            def close(self): pass
        with patch('app.onlyoffice_docx.http.client.HTTPConnection', Conn), self.assertRaises(HTTPException):
            onlyoffice_docx.fetch('http://127.0.0.1:8088/cache/files/x','http://127.0.0.1:8088')

    def test_competing_editors_cannot_silently_save(self):
        f=self.f; f.db.get(models.Manuscript,2).status='initial_editing'
        other=models.User(name='Synthetic editor',email='second-editor@example.invalid',password_hash='x',role='editor')
        f.db.add(other); f.db.flush()
        for editor in (f.editor,other):
            f.db.add(models.InitialEditorInvitation(manuscript_id=2,editor_id=editor.user_id,invited_by=f.editor.user_id,status='accepted'))
        f.db.commit(); base='/onlyoffice/manuscripts/2/initial'
        f.current=f.editor; first=f.client.post(base+'/sessions').json()['session']
        f.current=other; second=f.client.post(base+'/sessions').json()['session']
        with patch.object(onlyoffice_docx,'fetch',return_value=self.content):
            self.assertEqual(self.callback(first).status_code,200)
            self.assertEqual(self.callback(second).status_code,409)
        self.assertEqual(f.client.post(base+'/sessions').status_code,409)


class FinalDocxIntegrationTest(unittest.TestCase):
    def test_accepted_final_editor(self):
        f=test_final_workflow.FinalWorkflowTest('runTest'); f.setUp(); self.addCleanup(f.tearDown)
        for n in ('014_online_document_versions','016_onlyoffice_sessions'): importlib.import_module('migrations.'+n).migrate(f.db_path)
        with patch.dict(os.environ, CONFIG), patch.object(onlyoffice_docx,'BASE_DIR',f.root):
            content=academic_docx(); doc=f.write(f'uploads/initial_editing/{f.mid}/confirmed.docx',content)
            edit=f.db.query(models.InitialEditingSubmission).filter_by(manuscript_id=f.mid).one(); edit.file_path=doc
            confirmation=f.db.query(models.PreReviewConfirmation).filter_by(manuscript_id=f.mid).one(); confirmation.file_path=doc; f.db.commit()
            item=f.reach_agreement(); f.current=f.author
            self.assertEqual(f.client.post(f"/agreements/{item['agreement_id']}/respond",json={'decision':'accept','agreement_version':item['agreement_version']}).status_code,200)
            invite=f.invite(f.editor); self.assertEqual(invite.status_code,201,invite.text)
            self.assertEqual(f.respond(f.editor,invite.json()['invitation_id'],'accept').status_code,200)
            f.current=f.editor; response=f.client.post(f'/onlyoffice/manuscripts/{f.mid}/final/sessions')
            self.assertEqual(response.status_code,200,response.text)
            sid=response.json()['session']; body={'key':sid,'status':2,'url':'http://127.0.0.1:8088/cache/files/final'}
            token=jwt.encode({'payload':body,'operation':'callback'},SECRET,algorithm='HS256')
            with patch.object(onlyoffice_docx,'fetch',return_value=content):
                saved=f.client.post('/onlyoffice/callbacks/'+sid,json=body,headers={'Authorization':'Bearer '+token})
            self.assertEqual(saved.status_code,200,saved.text)
            self.assertEqual(len(f.client.get(f'/onlyoffice/manuscripts/{f.mid}/final/versions').json()),1)
            f.db.expire_all(); self.assertEqual(f.db.get(models.Manuscript,f.mid).status,'final_editing')
            vid=f.client.get(f'/onlyoffice/manuscripts/{f.mid}/final/versions').json()[0]['id']
            result=f.client.post(f'/eic/final-editing/{f.mid}/submit',data={'comments':'Synthetic','expected_online_version':'docx:'+vid},files={'file':('draft.docx',content,onlyoffice_docx.MIME)})
            self.assertEqual(result.status_code,201,result.text)


if __name__ == '__main__': unittest.main()
