"""Portable backend smoke tests; worker uses only a new temporary data root.

Run with either ``python -m unittest discover -s tests -p test_isolated_backend_smoke.py``
using that project's own virtual environment, or as part of its pytest suite.
"""
import json
import os
import secrets
from pathlib import Path
import subprocess
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]


def worker():
    # Set these before importing app.database/security; never use repository data.
    import io
    import time
    import tempfile
    import zipfile
    import jwt
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from fastapi.testclient import TestClient
    import app.config as config

    with tempfile.TemporaryDirectory(prefix='gsub-isolated-smoke-') as temp:
        root = Path(temp).resolve()
        config.DATA_ROOT = root
        config.PROJECT_ROOT = root
        # The collaboration engine validates this path at import time. Create
        # a new private disposable placeholder before importing it; the test
        # still overrides the request database with its separate synthetic DB.
        data_dir = root / '.test-data'
        data_dir.mkdir(mode=0o700)
        configured_db = data_dir / 'configured.sqlite'
        descriptor = os.open(configured_db, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        os.environ['COLLABORATION_DATABASE'] = str(configured_db)
        from app.database import Base, get_db
        from app import models
        from app.security import SECRET_KEY, hash_password
        from app.main import app
        from app.routers import manuscripts

        manuscripts.BASE_DIR = root
        engine = create_engine(f'sqlite:///{root / "synthetic.sqlite"}', connect_args={'check_same_thread': False})
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        with Session() as db:
            password_hash = hash_password('synthetic-password-only')
            author = models.User(name='Synthetic author', email='author@example.com', password_hash=password_hash, role='author')
            other = models.User(name='Synthetic other', email='other@example.com', password_hash=password_hash, role='author')
            reviewer = models.User(name='Synthetic reviewer', email='reviewer@example.com', password_hash=password_hash, role='reviewer')
            db.add_all([author, other, reviewer]); db.flush()
            manuscript = models.Manuscript(title='Synthetic manuscript', abstract='Synthetic abstract', author_id=author.user_id, status='draft', review_round=1)
            db.add(manuscript); db.flush()
            notification = models.Notification(user_id=author.user_id, manuscript_id=manuscript.manuscript_id, notification_type='synthetic', message='Synthetic message', is_read=False)
            db.add(notification); db.commit()
            mid, nid = manuscript.manuscript_id, notification.notification_id

        def test_db():
            with Session() as db:
                yield db
        app.dependency_overrides[get_db] = test_db
        client = TestClient(app)
        try:
            def login(email):
                response = client.post('/users/login', json={'email': email, 'password': 'synthetic-password-only'})
                assert response.status_code == 200, f'login failed: {response.status_code}'
                return {'Authorization': 'Bearer ' + response.json()['access_token']}
            author_headers = login('author@example.com')
            other_headers = login('other@example.com')
            reviewer_headers = login('reviewer@example.com')
            bad = client.post('/users/login', json={'email':'author@example.com','password':'wrong'})
            no_auth = client.get(f'/manuscripts/{mid}')
            invalid = client.get('/users/me', headers={'Authorization': 'Bearer invalid'})
            expired_token = jwt.encode({'sub': str(author.user_id), 'exp': int(time.time()) - 60}, SECRET_KEY, algorithm='HS256')
            expired = client.get('/users/me', headers={'Authorization': 'Bearer ' + expired_token})
            created = client.post('/manuscripts/', headers=author_headers, json={'title':'Another synthetic draft','abstract':'Synthetic abstract'})
            owner = client.get(f'/manuscripts/{mid}', headers=author_headers)
            outsider = client.get(f'/manuscripts/{mid}', headers=other_headers)
            rejected_upload = client.post(f'/manuscripts/{mid}/upload', headers=other_headers, files={'file':('synthetic.txt',b'Synthetic data','text/plain')})
            reviewer_upload = client.post(f'/manuscripts/{mid}/upload', headers=reviewer_headers, files={'file':('synthetic.txt',b'Synthetic data','text/plain')})
            uploaded = client.post(f'/manuscripts/{mid}/upload', headers=author_headers, files={'file':('synthetic.txt',b'Synthetic data','text/plain')})
            downloaded = client.get(f'/manuscripts/{mid}/download', headers=author_headers)
            empty = client.post(f'/manuscripts/{mid}/upload', headers=author_headers, files={'file':('empty.txt',b'','text/plain')})
            invalid_type = client.post(f'/manuscripts/{mid}/upload', headers=author_headers, files={'file':('invalid.exe',b'content','application/octet-stream')})
            oversized = client.post(f'/manuscripts/{mid}/upload', headers=author_headers, files={'file':('large.txt',b'x' * (10 * 1024 * 1024 + 1),'text/plain')})
            pdf = client.post(f'/manuscripts/{mid}/upload', headers=author_headers, files={'file':('synthetic.pdf',b'%PDF-synthetic','application/pdf')})
            docx_bytes = io.BytesIO()
            with zipfile.ZipFile(docx_bytes, 'w') as archive:
                archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
                archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>')
            docx = client.post(f'/manuscripts/{mid}/upload', headers=author_headers, files={'file':('synthetic.docx',docx_bytes.getvalue(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
            other_download = client.get(f'/manuscripts/{mid}/download', headers=other_headers)
            unread_before = client.get('/notifications/unread-count', headers=author_headers)
            notice_list = client.get('/notifications/my', headers=other_headers)
            notice_denied = client.patch(f'/notifications/{nid}/read', headers=other_headers)
            notice_read = client.patch(f'/notifications/{nid}/read', headers=author_headers)
            unread_after = client.get('/notifications/unread-count', headers=author_headers)
            with Session() as db:
                stored = db.scalar(select(models.Manuscript).where(models.Manuscript.manuscript_id == mid))
                safe_path = (root / stored.file_path).resolve() if stored.file_path else None
                safe = bool(safe_path and safe_path.is_relative_to(root / 'uploads') and safe_path.is_file())
            result = {
                'login': bad.status_code == 401 and no_auth.status_code == 401 and invalid.status_code == 401 and expired.status_code == 401,
                'ownership': owner.status_code == 200 and outsider.status_code == 404 and rejected_upload.status_code == 403 and reviewer_upload.status_code == 403,
                'files': created.status_code == 201 and uploaded.status_code == 200 and downloaded.status_code == 200 and downloaded.content == b'Synthetic data' and other_download.status_code in (403, 404) and safe,
                'validation': empty.status_code == 400 and invalid_type.status_code == 400 and oversized.status_code == 413 and pdf.status_code == 200 and docx.status_code == 200,
                'notifications': notice_list.status_code == 200 and notice_list.json() == [] and notice_denied.status_code == 403 and notice_read.status_code == 200 and unread_before.json()['unread_count'] == 1 and unread_after.json()['unread_count'] == 0,
            }
            print(json.dumps(result, sort_keys=True))
        finally:
            client.close(); app.dependency_overrides.clear(); engine.dispose()


class IsolatedBackendSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(PROJECT),
               'PYTHON_DOTENV_DISABLED': '1', 'PYTHONDONTWRITEBYTECODE': '1',
               'SECRET_KEY': secrets.token_hex(32), 'MANUSCRIPT_MODE': 'development',
               'GSUB_CAPTCHA_MODE': 'off'}
        if os.environ.get('TMPDIR'):
            env['TMPDIR'] = os.environ['TMPDIR']
        run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'], cwd=PROJECT,
                             env=env, capture_output=True, text=True, timeout=60)
        if run.returncode:
            raise AssertionError(f'Isolated smoke worker failed ({run.returncode}): {run.stderr[-2000:]}')
        cls.result = json.loads(run.stdout.strip().splitlines()[-1])

    def test_password_and_missing_authentication(self): self.assertTrue(self.result['login'])
    def test_manuscript_role_and_ownership(self): self.assertTrue(self.result['ownership'])
    def test_private_upload_and_download(self): self.assertTrue(self.result['files'])
    def test_format_and_size_validation(self): self.assertTrue(self.result['validation'])
    def test_notification_ownership(self): self.assertTrue(self.result['notifications'])


if __name__ == '__main__':
    if sys.argv[1:] == ['--worker']:
        worker()
    else:
        unittest.main()
