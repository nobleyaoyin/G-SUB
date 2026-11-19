"""Editor TXT drafts use only disposable SQLite and synthetic files."""
import unittest
import importlib
from unittest.mock import patch
from app import models
import app.routers.eic as eic
from tests.test_reviewer_download import ReviewerDownloadsTest
from tests.test_final_workflow import FinalWorkflowTest


class EditorTextTests(unittest.TestCase):
    def setUp(self):
        self.f=ReviewerDownloadsTest('runTest'); self.f.setUp(); self.addCleanup(self.f.tearDown)
        importlib.import_module('migrations.014_online_document_versions').migrate(self.f.db_path)
        self.p=patch.object(eic,'BASE_DIR',self.f.root);self.p.start();self.addCleanup(self.p.stop)
        f=self.f
        self.original=f.write('uploads/manuscripts/2/source.txt',b'Synthetic original')
        m=models.Manuscript(manuscript_id=2,title='Synthetic',abstract='Synthetic',author_id=f.author.user_id,status='initial_editing',review_round=1,file_path=self.original)
        f.db.add(m);f.db.flush();f.db.add(models.InitialEditorInvitation(manuscript_id=2,editor_id=f.editor.user_id,invited_by=f.editor.user_id,status='accepted'));f.db.commit()
        self.url='/eic/manuscripts/2/online-text/initial'

    def test_save_stale_download_preserves_source_and_stage(self):
        f=self.f; f.current=f.editor
        opened=f.client.get(self.url);self.assertEqual(opened.status_code,200,opened.text)
        self.assertEqual(opened.json()['content'],'Synthetic original')
        token=opened.json()['version'];result=f.client.post(self.url,json={'content':'Synthetic draft','expected_version':token});self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(f.client.post(self.url,json={'content':'Stale','expected_version':token}).status_code,409)
        current=f.client.get(self.url).json();self.assertEqual(current['content'],'Synthetic draft');self.assertEqual(len(current['history']),1)
        self.assertEqual(f.client.post(self.url,json={'content':'Second draft','expected_version':current['version']}).status_code,200)
        current=f.client.get(self.url).json();self.assertEqual([v['number'] for v in current['history']],[1,2]);self.assertEqual(current['content'],'Second draft')
        self.assertEqual(f.client.get(self.url+'/'+current['history'][0]['filename']).content,b'Synthetic draft')
        download=f.client.get(self.url+'/'+current['history'][1]['filename']);self.assertEqual(download.content,b'Second draft')
        self.assertEqual((f.root/self.original).read_bytes(),b'Synthetic original')
        f.db.expire_all();self.assertEqual(f.db.get(models.Manuscript,2).status,'initial_editing')
        self.assertEqual(f.db.query(models.InitialEditingSubmission).filter_by(manuscript_id=2).count(),0)
        result=f.client.post('/eic/initial-editing/2/submit',data={'comments':'Explicit submission'},files={'file':('draft.txt',download.content,'text/plain')})
        self.assertEqual(result.status_code,201,result.text)
        self.assertEqual(f.client.get(self.url).status_code,409)

    def test_roles_scope_and_source_changes(self):
        f=self.f
        for actor in (f.author,f.reviewer):
            f.current=actor;self.assertEqual(f.client.get(self.url).status_code,403)
        other=models.User(name='Unassigned editor',email='unassigned-editor@example.com',password_hash='x',role='editor');f.db.add(other);f.db.commit();f.current=other
        self.assertEqual(f.client.get(self.url).status_code,404)
        f.current=f.editor;token=f.client.get(self.url).json()['version']
        (f.root/self.original).write_bytes(b'Changed synthetic source')
        self.assertEqual(f.client.post(self.url,json={'content':'Stale','expected_version':token}).status_code,409)
        m=f.db.get(models.Manuscript,2);m.status='ready_for_peer_review';f.db.commit();self.assertEqual(f.client.get(self.url).status_code,404)

    def test_selected_draft_submission_rejects_stale_or_modified_content(self):
        f=self.f; f.current=f.editor
        first=f.client.get(self.url).json()
        self.assertEqual(f.client.post(self.url,json={'content':'First draft','expected_version':first['version']}).status_code,200)
        selected=f.client.get(self.url).json()
        self.assertEqual(f.client.post(self.url,json={'content':'Newer draft','expected_version':selected['version']}).status_code,200)
        endpoint='/eic/initial-editing/2/submit'
        def submit(version, content):
            return f.client.post(endpoint,data={'comments':'Submission','expected_online_version':version},files={'file':('draft.txt',content,'text/plain')})
        self.assertEqual(submit(selected['version'],b'First draft').status_code,409)
        latest=f.client.get(self.url).json()
        self.assertEqual(submit(latest['version'],b'Different content').status_code,409)
        f.db.expire_all()
        self.assertEqual(f.db.query(models.InitialEditingSubmission).filter_by(manuscript_id=2).count(),0)
        self.assertEqual(submit(latest['version'],b'Newer draft').status_code,201)

    def test_ambiguous_commit_keeps_submitted_file(self):
        f=self.f; f.current=f.editor
        commit=f.db.commit
        def committed_then_lost_acknowledgement():
            commit()
            raise RuntimeError('Synthetic lost acknowledgement')
        with patch.object(f.db,'commit',side_effect=committed_then_lost_acknowledgement):
            with self.assertRaises(RuntimeError):
                f.client.post('/eic/initial-editing/2/submit',data={'comments':'Explicit'},files={'file':('draft.txt',b'Synthetic submitted text','text/plain')})
        f.db.expire_all()
        submission=f.db.query(models.InitialEditingSubmission).filter_by(manuscript_id=2).one()
        self.assertEqual((f.root/submission.file_path).read_bytes(),b'Synthetic submitted text')

    def test_unsupported_source_and_invalid_download(self):
        f=self.f;f.current=f.editor
        m=f.db.get(models.Manuscript,2);m.file_path=f.write('uploads/manuscripts/2/test.pdf',b'%PDF-test');f.db.commit()
        self.assertEqual(f.client.get(self.url).status_code,415)
        m.file_path=f.write('uploads/manuscripts/2/test.docx',b'synthetic docx placeholder');f.db.commit()
        self.assertEqual(f.client.get(self.url).status_code,415)
        m.file_path=self.original;f.db.commit();self.assertEqual(f.client.get(self.url+'/not-a-draft.txt').status_code,404)

    def test_invitation_and_file_safety(self):
        f=self.f;f.current=f.editor
        invitation=f.db.query(models.InitialEditorInvitation).filter_by(manuscript_id=2).one()
        invitation.status='pending';f.db.commit();self.assertEqual(f.client.get(self.url).status_code,404)
        invitation.status='declined';f.db.commit();self.assertEqual(f.client.get(self.url).status_code,404)
        invitation.status='accepted';f.db.commit();token=f.client.get(self.url).json()['version']
        self.assertEqual(f.client.post(self.url,json={'content':'','expected_version':token}).status_code,400)
        link=f.root/'uploads/manuscripts/2/link.txt';link.symlink_to(f.root/self.original)
        m=f.db.get(models.Manuscript,2);m.file_path=str(link.relative_to(f.root));f.db.commit()
        self.assertEqual(f.client.get(self.url).status_code,409)


class FinalEditorTextTests(unittest.TestCase):
    def test_accepted_final_editor_uses_confirmed_round_source(self):
        f=FinalWorkflowTest('runTest');f.setUp();self.addCleanup(f.tearDown)
        importlib.import_module('migrations.014_online_document_versions').migrate(f.db_path)
        with patch.object(eic,'BASE_DIR',f.root):
            txt=f.write(f'uploads/initial_editing/{f.mid}/confirmed.txt',b'Confirmed synthetic text')
            edit=f.db.query(models.InitialEditingSubmission).filter_by(manuscript_id=f.mid).one();edit.file_path=txt
            confirmation=f.db.query(models.PreReviewConfirmation).filter_by(manuscript_id=f.mid).one();confirmation.file_path=txt;f.db.commit()
            item=f.reach_agreement();f.current=f.author
            self.assertEqual(f.client.post(f"/agreements/{item['agreement_id']}/respond",json={'decision':'accept','agreement_version':item['agreement_version']}).status_code,200)
            invite=f.invite(f.editor);self.assertEqual(invite.status_code,201,invite.text)
            self.assertEqual(f.respond(f.editor,invite.json()['invitation_id'],'accept').status_code,200)
            url=f'/eic/manuscripts/{f.mid}/online-text/final';f.current=f.editor;opened=f.client.get(url)
            self.assertEqual(opened.status_code,200,opened.text);self.assertEqual(opened.json()['content'],'Confirmed synthetic text')
            self.assertEqual(f.client.post(url,json={'content':'Final synthetic draft','expected_version':opened.json()['version']}).status_code,200)
            f.db.expire_all();self.assertEqual(f.db.get(models.Manuscript,f.mid).status,'final_editing')
            self.assertEqual(f.db.query(models.FinalEditingSubmission).filter_by(manuscript_id=f.mid).count(),0)
            current=f.client.get(url).json();saved=f.client.get(url+'/'+current['history'][-1]['filename'])
            endpoint=f'/eic/final-editing/{f.mid}/submit'
            stale=f.client.post(endpoint,data={'comments':'Explicit','expected_online_version':opened.json()['version']},files={'file':('final.txt',saved.content,'text/plain')})
            self.assertEqual(stale.status_code,409)
            wrong=f.client.post(endpoint,data={'comments':'Explicit','expected_online_version':current['version']},files={'file':('final.txt',b'Modified','text/plain')})
            self.assertEqual(wrong.status_code,409)
            submission=f.client.post(endpoint,data={'comments':'Explicit','expected_online_version':current['version']},files={'file':('final.txt',saved.content,'text/plain')})
            self.assertEqual(submission.status_code,201,submission.text)
            self.assertEqual(f.client.get(url).status_code,409)

if __name__=='__main__': unittest.main()
