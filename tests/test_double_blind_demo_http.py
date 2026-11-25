"""Actual HTTP flow with synthetic, prospective fixture proof and private files."""
import unittest
import app.main as main
from app import reviewer_artifact_service as service, reviewer_artifact_evidence as evidence
from app.reviewer_artifact_storage import ArtifactStorage
from app.reviewer_demo_download import DemoArtifactContext, reviewer_demo_artifact_context
from tests import test_blind_demo_eic_http as fixtures, test_reviewer_artifact_service as artifact_fixtures, test_artifact_evidence
from tests.test_reviewer_artifact_binding import T


class DoubleBlindDemoTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.EICDemoHTTPTests('test_disabled_and_authorization');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.db=self.f.db; self.f.f.enable()
        self.db.execute("INSERT INTO review_round_files(round_file_id,manuscript_id,review_round,source_kind,confirmation_id,file_path,created_at) VALUES (3,3,1,'initial_editing',3,'uploads/initial_editing/3/source.pdf',?)",(T,));self.db.commit()
        source=artifact_fixtures.SyntheticProvenance(self.f.root,3,3,'uploads/initial_editing/3/source.pdf')
        proof=test_artifact_evidence.SyntheticPriorProof(source)
        proof.proof='b'*32
        private=self.f.root/'demo-private';private.mkdir(mode=0o700);storage=ArtifactStorage(private);self.addCleanup(storage.close)
        authority=artifact_fixtures.SyntheticAuthority(3,5)
        self.db.execute('BEGIN IMMEDIATE')
        sid=evidence.capture_source(self.db,authority.eic,authority,proof,source,3,3,0)
        self.art=service.prepare(self.db,authority.editor,authority,source,storage,3,3,b'Anonymous synthetic text','txt',1)
        evidence.approve_with_evidence(self.db,authority.eic,authority,source,storage,self.art.artifact_id,sid,1,checklist_acknowledged=True)
        self.db.commit()
        self.context=DemoArtifactContext(proof,source,storage)
        main.app.dependency_overrides[reviewer_demo_artifact_context]=lambda:self.context
        self.assertEqual(self.f.req('PUT','/assignments/demo-policy/3',json={'mode':'double_blind'}).status_code,200)

    def invite(self):
        return self.f.req('POST','/assignments/demo-invitations',json={'manuscript_id':3,'reviewer_id':2,'review_round':1})

    def test_full_http_flow(self):
        invite=self.invite();self.assertEqual(invite.status_code,201,invite.text);aid=invite.json()['assignment_id']
        self.assertTrue(self.f.req('GET','/assignments/demo-policy/3').json()['locked'])
        msg=self.db.execute("SELECT message FROM notifications WHERE manuscript_id=3 AND user_id=2").fetchone()[0];self.assertEqual(msg,'You have a reviewer invitation.')
        pending=self.f.req('GET','/assignments/my',user=2);self.assertEqual(pending.status_code,200,pending.text);self.assertNotIn('author_id',pending.json()[0])
        self.assertEqual(self.f.req('POST',f'/assignments/demo-invitations/{aid}/bind-artifact').status_code,409)
        self.assertEqual(self.f.req('POST',f'/assignments/{aid}/invitation-response',user=2,json={'decision':'accept'}).status_code,200)
        self.assertEqual(self.f.req('POST',f'/assignments/demo-invitations/{aid}/bind-artifact',user=1).status_code,403)
        bind=self.f.req('POST',f'/assignments/demo-invitations/{aid}/bind-artifact');self.assertEqual(bind.status_code,200,bind.text)
        self.assertEqual(self.f.req('POST',f'/assignments/demo-invitations/{aid}/bind-artifact').status_code,409)
        details=self.f.req('GET','/manuscripts/3',user=2);self.assertEqual(details.json(),{'manuscript_id':3,'review_round':1})
        self.assertNotIn('author_id',self.f.req('GET','/assignments/my',user=2).json()[0])
        download=self.f.req('GET',f'/assignments/{aid}/download',user=2);self.assertEqual(download.status_code,200,download.text);self.assertEqual(download.content,b'Anonymous synthetic text')
        self.assertEqual(self.f.req('GET','/manuscripts/3/download',user=2).status_code,403)
        self.assertEqual(self.f.req('GET',f'/assignments/{aid}/download',user=4).status_code,409)
        review=self.f.req('POST','/reviews/',user=2,json={'assignment_id':aid,'comments':'Synthetic review','recommendation':'revision'});self.assertEqual(review.status_code,201,review.text)
        self.assertEqual(self.f.req('GET','/reviews/manuscript/3',user=1).status_code,403)

    def test_corrupt_artifact_prevents_invitation(self):
        path=self.f.root/'demo-private'/self.art.storage_id;path.chmod(0o600);path.write_bytes(b'X'*len(b'Anonymous synthetic text'))
        self.assertEqual(self.invite().status_code,409)
        self.assertEqual(self.db.execute('SELECT count(*) FROM review_assignments WHERE manuscript_id=3').fetchone()[0],0)
        self.assertFalse(self.f.req('GET','/assignments/demo-policy/3').json()['locked'])

    def test_missing_context_or_evidence_fails_closed(self):
        main.app.dependency_overrides.pop(reviewer_demo_artifact_context)
        self.assertEqual(self.invite().status_code,409)
        main.app.dependency_overrides[reviewer_demo_artifact_context]=lambda:self.context
        self.context.proof.proof='c'*32
        self.assertEqual(self.invite().status_code,409)
        self.assertEqual(self.db.execute('SELECT count(*) FROM review_assignments WHERE manuscript_id=3').fetchone()[0],0)

    def test_no_binding_prevents_review_and_download(self):
        aid=self.invite().json()['assignment_id'];self.f.req('POST',f'/assignments/{aid}/invitation-response',user=2,json={'decision':'accept'})
        self.assertEqual(self.f.req('GET',f'/assignments/{aid}/download',user=2).status_code,409)
        self.assertEqual(self.f.req('POST','/reviews/',user=2,json={'assignment_id':aid,'comments':'x','recommendation':'revision'}).status_code,409)

    def test_invalidation_prevents_download_and_review(self):
        aid=self.invite().json()['assignment_id'];self.f.req('POST',f'/assignments/{aid}/invitation-response',user=2,json={'decision':'accept'})
        self.assertEqual(self.f.req('POST',f'/assignments/demo-invitations/{aid}/bind-artifact').status_code,200)
        self.db.execute("INSERT INTO reviewer_invitation_invalidations VALUES ('revoked-demo',?,'cancelled',NULL,5,?,'editorial_cancellation')",(aid,T));self.db.commit()
        self.assertEqual(self.f.req('GET',f'/assignments/{aid}/download',user=2).status_code,409)
        self.assertEqual(self.f.req('POST','/reviews/',user=2,json={'assignment_id':aid,'comments':'x','recommendation':'revision'}).status_code,409)

if __name__=='__main__': unittest.main()
