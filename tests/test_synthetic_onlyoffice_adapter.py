import io
import os
import sqlite3
import subprocess
import sys
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import urlsplit

import jwt
from fastapi.testclient import TestClient
from synthetic_onlyoffice.adapter import create_synthetic_app, fetch_saved_document
from synthetic_onlyoffice.store import SyntheticStore


def docx(text='Synthetic'):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
    return out.getvalue()


class SyntheticAdapterTest(unittest.TestCase):
    def setUp(self):
        self.source = docx()
        self.edited = docx('Edited')
        self.app, self.tokens = create_synthetic_app(self.source, fetcher=lambda url, port: self.edited)
        self.client = TestClient(self.app)

    def auth(self, role='author'):
        return {'Authorization': 'Bearer ' + self.tokens[role]}

    def session(self, role='author'):
        r = self.client.post('/manuscripts/synthetic-1/editor', headers=self.auth(role))
        self.assertEqual(r.status_code, 200)
        return r.json()['config']

    def callback(self, config, status=2, url='http://127.0.0.1:8088/cache/files/result.docx', body_token=False):
        body = {'key': config['document']['key'], 'status': status, 'url': url}
        if status in (6, 7):
            body['forcesavetype'] = 1
        claims = {**body, 'operation': 'callback'} if body_token else {'payload': body, 'operation': 'callback'}
        signed = jwt.encode(claims, self.app.state.synthetic_secret, algorithm='HS256')
        if body_token:
            return self.client.post('/callbacks/' + body['key'], json={'token': signed})
        return self.client.post('/callbacks/' + body['key'], json=body, headers={'Authorization': 'Bearer ' + signed})

    def test_author_editor_and_cross_manuscript(self):
        self.session('author')
        self.session('editor')
        self.assertEqual(self.client.post('/manuscripts/synthetic-2/editor', headers=self.auth()).status_code, 403)
        self.assertEqual(self.client.post('/manuscripts/synthetic-1/editor', headers=self.auth('other')).status_code, 403)
        self.assertEqual(self.client.get('/manuscripts/synthetic-1/versions').status_code, 403)
        self.assertEqual(self.client.get('/manuscripts/synthetic-2/versions/1', headers=self.auth()).status_code, 403)

    def test_document_capability_expired_tampered_and_cross_session(self):
        cfg = self.session()
        target = urlsplit(cfg['document']['url'])
        self.assertEqual(self.client.get(target.path + '?' + target.query).content, self.source)
        key = cfg['document']['key']
        expired = jwt.encode({'aud': 'document', 'key': key, 'exp': int(time.time()) - 1}, self.app.state.synthetic_secret, algorithm='HS256')
        self.assertEqual(self.client.get('/documents/' + key, params={'token': expired}).status_code, 403)
        self.assertEqual(self.client.get('/documents/' + key, params={'token': expired + 'x'}).status_code, 403)
        self.assertEqual(self.client.get('/documents/another?' + target.query).status_code, 403)

    def test_saved_versions_replay_and_stale(self):
        old, current = self.session(), self.session('editor')
        self.assertEqual(self.callback(current).json(), {'error': 0})
        self.assertEqual(self.callback(current).json(), {'error': 0})
        self.assertEqual(self.callback(current, url='http://127.0.0.1:8088/cache/files/other').status_code, 409)
        self.assertEqual(self.callback(old).status_code, 409)
        versions = self.client.get('/manuscripts/synthetic-1/versions', headers=self.auth()).json()
        self.assertEqual([v['number'] for v in versions], [1, 2])
        self.assertEqual(self.client.get('/manuscripts/synthetic-1/versions/1', headers=self.auth()).content, self.source)
        self.assertEqual(self.client.get('/manuscripts/synthetic-1/versions/2', headers=self.auth()).content, self.edited)

    def test_callback_url_restrictions(self):
        urls = ['http://localhost:8088/cache/files/x', 'http://127.0.0.1:9999/cache/files/x', 'http://10.0.0.1:8088/cache/files/x', 'http://127.0.0.1:8088@evil.test/cache/files/x', 'file:///cache/files/x', 'http://127.0.0.1:8088/other', 'http://[::1]:8088/cache/files/x', 'http://127.0.0.1:8088/cache/files/%2e%2e/admin']
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.callback(self.session(), url=url).status_code, 400)

    def test_callback_signature_and_statuses(self):
        cfg = self.session()
        self.assertEqual(self.client.post('/callbacks/' + cfg['document']['key'], json={'key': cfg['document']['key'], 'status': 2}).status_code, 403)
        self.assertEqual(self.callback(cfg, status=1, url=None).json(), {'error': 0})
        for status in (3, 7):
            self.assertEqual(self.callback(cfg, status=status, url=None).json(), {'error': 0})
        self.assertEqual(self.callback(cfg, status=5, url=None).status_code, 400)
        self.assertEqual(self.callback(cfg, status=6).json(), {'error': 0})
        self.assertEqual(self.callback(cfg, status=4, url=None).json(), {'error': 0})

    def test_callback_rejects_expired_and_mismatched_claims(self):
        cfg = self.session()
        key = cfg['document']['key']
        body = {'key': key, 'status': 2, 'url': 'http://127.0.0.1:8088/cache/files/test'}
        for claims in ({'payload': body, 'operation': 'callback', 'exp': int(time.time()) - 1}, {'payload': {**body, 'status': 6}, 'operation': 'callback'}):
            token = jwt.encode(claims, self.app.state.synthetic_secret, algorithm='HS256')
            result = self.client.post('/callbacks/' + key, json=body, headers={'Authorization': 'Bearer ' + token})
            self.assertEqual(result.status_code, 403)

    def test_documented_body_token_and_force_saves_then_final(self):
        cfg = self.session()
        self.assertEqual(self.callback(cfg, status=6, body_token=True).json(), {'error': 0})
        self.assertEqual(self.callback(cfg, status=6, body_token=True).json(), {'error': 0})
        self.assertEqual(self.callback(cfg, status=6, url='http://127.0.0.1:8088/cache/files/next', body_token=True).json(), {'error': 0})
        self.assertEqual(self.callback(cfg, status=2, url='http://127.0.0.1:8088/cache/files/final', body_token=True).json(), {'error': 0})
        versions = self.client.get('/manuscripts/synthetic-1/versions', headers=self.auth()).json()
        self.assertEqual(len(versions), 2)  # identical bytes do not create duplicates
        self.assertEqual(self.callback(cfg, status=6, url='http://127.0.0.1:8088/cache/files/new').status_code, 409)

    def test_callback_wrong_secret_and_wrong_operation(self):
        cfg = self.session()
        key = cfg['document']['key']
        body = {'key': key, 'status': 1}
        for secret, purpose in (('incorrect-synthetic-secret-over-32-bytes-long', 'callback'), (self.app.state.synthetic_secret, 'download')):
            token = jwt.encode({'payload': body, 'operation': purpose}, secret, algorithm='HS256')
            self.assertEqual(self.client.post('/callbacks/' + key, json=body, headers={'Authorization': 'Bearer ' + token}).status_code, 403)

    def test_distinct_force_save_versions_and_final_save(self):
        original=docx(); documents={name:docx(name) for name in ('first','second','final')}
        self.app, self.tokens = create_synthetic_app(original, fetcher=lambda url, port: documents[url.rsplit('/', 1)[-1]])
        self.client = TestClient(self.app)
        cfg = self.session()
        for status, name in ((6, 'first'), (6, 'second'), (2, 'final')):
            url = 'http://127.0.0.1:8088/cache/files/' + name
            self.assertEqual(self.callback(cfg, status=status, url=url).json(), {'error': 0})
        self.assertEqual(self.callback(cfg, status=2, url='http://127.0.0.1:8088/cache/files/final').json(), {'error': 0})
        versions = self.client.get('/manuscripts/synthetic-1/versions', headers=self.auth()).json()
        self.assertEqual([v['number'] for v in versions], [1, 2, 3, 4])
        for version, content in enumerate((original, documents['first'], documents['second'], documents['final']), 1):
            self.assertEqual(self.client.get(f'/manuscripts/synthetic-1/versions/{version}', headers=self.auth()).content, content)

    def test_session_expiry_rejects_signed_callback(self):
        with patch('synthetic_onlyoffice.adapter.time.time', return_value=100):
            cfg = self.session()
        with patch('synthetic_onlyoffice.adapter.time.time', return_value=3701):
            self.assertEqual(self.callback(cfg).status_code, 403)

    def test_signed_configuration_matches_editor_config(self):
        cfg = self.session()
        signed = jwt.decode(cfg['token'], self.app.state.synthetic_secret, algorithms=['HS256'])
        self.assertEqual(signed['document'], cfg['document'])
        self.assertEqual(signed['editorConfig'], cfg['editorConfig'])

    def test_invalid_docx_and_bounded_size(self):
        for data in (b'not a docx', b'x' * (10 * 1024 * 1024 + 1)):
            with self.assertRaises(ValueError):
                create_synthetic_app(data)
        self.app, self.tokens = create_synthetic_app(docx(), fetcher=lambda u, p: b'not docx')
        self.client = TestClient(self.app)
        self.assertEqual(self.callback(self.session()).status_code, 400)
        self.assertEqual(len(self.client.get('/manuscripts/synthetic-1/versions', headers=self.auth()).json()), 1)

    def test_missing_office_document_relationship_is_rejected(self):
        source = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(docx())) as original, zipfile.ZipFile(source, 'w') as broken:
            for name in original.namelist():
                content = original.read(name)
                if name == '_rels/.rels':
                    content = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
                broken.writestr(name, content)
        with self.assertRaises(ValueError):
            create_synthetic_app(source.getvalue())

    def test_host_gateway_is_explicitly_enabled(self):
        with self.assertRaises(ValueError):
            create_synthetic_app(docx(), adapter_origin='http://host.docker.internal:8090')
        app, _ = create_synthetic_app(docx(), adapter_origin='http://host.docker.internal:8090', allow_test_host_gateway=True)
        self.assertTrue(app.state.synthetic_root.is_dir())

    def test_restart_durable_replay_and_subprocess_recovery(self):
        cfg = self.session()
        self.assertEqual(self.callback(cfg).json(), {'error': 0})
        root = self.app.state.synthetic_root
        self.client.close()
        self.app, recovered_tokens = create_synthetic_app(self.source, resume_root=root, fetcher=lambda u, p: self.fail('Replay must not fetch'))
        self.assertEqual(recovered_tokens, self.tokens)
        self.client = TestClient(self.app)
        self.assertEqual(self.callback(cfg).json(), {'error': 0})
        versions = self.client.get('/manuscripts/synthetic-1/versions', headers=self.auth()).json()
        self.assertEqual(len(versions), 2)
        self.assertEqual(self.client.get('/manuscripts/synthetic-1/versions/1', headers=self.auth()).content, self.source)
        import hashlib
        data = self.client.get('/manuscripts/synthetic-1/versions/2', headers=self.auth()).content
        self.assertEqual(hashlib.sha256(data).hexdigest(), versions[1]['sha256'])
        # A separate Python interpreter opens the existing synthetic fixture.
        program = '''import sys,jwt\nfrom pathlib import Path\nfrom fastapi.testclient import TestClient\nfrom synthetic_onlyoffice.adapter import create_synthetic_app\ndef forbidden(*args): raise AssertionError('replay must not fetch')\nroot=Path(sys.argv[1]); source=(root / sys.argv[2]).read_bytes()\napp,tokens=create_synthetic_app(source,resume_root=root,fetcher=forbidden)\nc=TestClient(app)\nr=c.get('/manuscripts/synthetic-1/versions',headers={'Authorization':'Bearer '+tokens['author']})\nassert r.status_code==200 and len(r.json())==2\nbody={'key':sys.argv[3],'status':2,'url':'http://127.0.0.1:8088/cache/files/result.docx'}\ntoken=jwt.encode({'payload':body,'operation':'callback'},app.state.synthetic_secret,algorithm='HS256')\nr=c.post('/callbacks/'+sys.argv[3],json=body,headers={'Authorization':'Bearer '+token})\nassert r.status_code==200 and r.json()=={'error':0}\n'''
        with sqlite3.connect(root / 'synthetic.sqlite') as c:
            original_name = c.execute('SELECT name FROM versions WHERE number=1').fetchone()[0]
        env = {**os.environ, 'PYTHON_DOTENV_DISABLED': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run([sys.executable, '-c', program, str(root), original_name, cfg['document']['key']], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_injected_db_failure_leaves_orphan_and_rolls_back(self):
        cfg = self.session()
        root = self.app.state.synthetic_root
        original = SyntheticStore.write_version
        def fail_after_insert(store, c, data, number):
            original(store, c, data, number)
            raise sqlite3.OperationalError('synthetic injected failure')
        with patch.object(SyntheticStore, 'write_version', fail_after_insert):
            with self.assertRaises(sqlite3.OperationalError):
                self.callback(cfg)
        self.assertEqual(len(self.client.get('/manuscripts/synthetic-1/versions', headers=self.auth()).json()), 1)
        self.assertEqual(len(list(root.glob('*.docx'))), 2)
        self.assertEqual(self.client.get('/manuscripts/synthetic-1/versions/1', headers=self.auth()).content, self.source)
        self.assertEqual(self.callback(cfg).json(), {'error': 0})

    def test_concurrent_sessions_and_revocation(self):
        one, two = self.session(), self.session('editor')
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda cfg: self.callback(cfg).status_code, (one, two)))
        self.assertEqual(sorted(statuses), [200, 409])
        third = self.session()
        key = third['document']['key']
        self.assertEqual(self.client.post('/manuscripts/synthetic-1/sessions/'+key+'/revoke', headers=self.auth('editor')).status_code, 404)
        self.assertEqual(self.client.post('/manuscripts/synthetic-1/sessions/'+key+'/revoke', headers=self.auth()).status_code, 200)
        self.assertEqual(self.callback(third).status_code, 403)

    def test_stale_and_revoked_sessions_remain_rejected_after_restart(self):
        stale, saved = self.session(), self.session('editor')
        self.assertEqual(self.callback(saved).status_code, 200)
        revoked = self.session()
        key = revoked['document']['key']
        self.assertEqual(self.client.post('/manuscripts/synthetic-1/sessions/' + key + '/revoke', headers=self.auth()).status_code, 200)
        self.app, self.tokens = create_synthetic_app(None, resume_root=self.app.state.synthetic_root, fetcher=lambda u, p: docx('Edited'))
        self.client = TestClient(self.app)
        self.assertEqual(self.callback(stale).status_code, 409)
        self.assertEqual(self.callback(revoked).status_code, 403)

    def test_interrupted_file_write_does_not_allocate_version(self):
        cfg = self.session()
        with patch('synthetic_onlyoffice.store.os.fsync', side_effect=OSError('synthetic interrupted write')):
            with self.assertRaises(OSError):
                self.callback(cfg)
        self.assertEqual(len(self.client.get('/manuscripts/synthetic-1/versions', headers=self.auth()).json()), 1)
        self.assertEqual(self.client.get('/manuscripts/synthetic-1/versions/1', headers=self.auth()).content, self.source)

    def test_redirect_is_rejected(self):
        class Reply:
            status = 302
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Reply()
            def close(self): pass
        with patch('synthetic_onlyoffice.adapter.http.client.HTTPConnection', Connection):
            with self.assertRaises(ValueError):
                fetch_saved_document('http://127.0.0.1:8088/cache/files/x', 8088)


if __name__ == '__main__':
    unittest.main()
