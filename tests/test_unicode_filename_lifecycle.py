"""Synthetic owner upload/filename round-trip; no persistent data."""
from uuid import uuid4
from urllib.parse import unquote
import pytest
from tests.test_manuscript_upload_recovery import isolated
from tests.test_secure_word_uploads import doc_bytes, docx_bytes
from tests.test_author_submission_attachments import client
from sqlalchemy import text

@pytest.mark.parametrize('name', ['研究データ_最終版.txt', 'Résumé_Final.txt', 'Paper Version (Final) 2026.txt'])
def test_owner_unicode_round_trip(isolated, name):
    case = isolated
    request_id = str(uuid4())
    payload = b'Synthetic manuscript data\n'
    upload = case.client.post(f'/manuscripts/{case.mid}/upload', data={'request_id':request_id}, files={'file':(name,payload,'text/plain')})
    assert upload.status_code == 200, upload.text
    receipt = case.client.get(f'/manuscripts/{case.mid}/upload-requests/{request_id}')
    assert receipt.status_code == 200 and receipt.json()['original_filename'] == name
    versions = case.client.get(f'/manuscripts/{case.mid}/versions').json()
    assert len(versions) == 1 and versions[0]['original_filename'] == name
    current = case.client.get(f'/manuscripts/{case.mid}/download')
    historical = case.client.get(f"/manuscripts/{case.mid}/versions/{versions[0]['filename']}")
    assert current.content == historical.content == payload
    for response in (current, historical):
        header = response.headers['content-disposition']
        assert 'filename="manuscript_' in header and "filename*=UTF-8''" in header
        assert unquote(header.split("filename*=UTF-8''", 1)[1]) == name

@pytest.mark.parametrize('name,payload,mime', [
    ('研究論文_測試版本.docx', docx_bytes(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    ('投稿文件_第二版.pdf', b'%PDF-synthetic', 'application/pdf'),
    ('审稿材料_最终版.docx', docx_bytes(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    ('Überprüfung_Manuskript.docx', docx_bytes(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    ('Résumé_Final.docx', docx_bytes(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    ('Research_Paper_Final.docx', docx_bytes(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    ('Paper Version (Final) 2026.pdf', b'%PDF-synthetic', 'application/pdf'),
    ('한국어_문서.doc', doc_bytes(), 'application/msword'),
])
def test_formats_preserve_original_name_and_bytes(isolated, name, payload, mime):
    case = isolated
    request_id = str(uuid4())
    first = case.client.post(f'/manuscripts/{case.mid}/upload', data={'request_id':request_id}, files={'file':(name,payload,mime)})
    assert first.status_code == 200, first.text
    assert case.client.get(f'/manuscripts/{case.mid}/upload-requests/{request_id}').json()['original_filename'] == name
    versions = case.client.get(f'/manuscripts/{case.mid}/versions').json()
    assert versions[0]['original_filename'] == name
    download = case.client.get(f'/manuscripts/{case.mid}/download')
    assert download.content == payload
    assert unquote(download.headers['content-disposition'].split("filename*=UTF-8''",1)[1]) == name

def test_invalid_header_metadata_falls_back_safely():
    from app.filename_headers import content_disposition
    for name in ('../secret.txt', 'bad\r\nInjected.txt', 'folder\\file.txt'):
        header = content_disposition(name, 'document.txt')
        assert header == 'attachment; filename="document.txt"; filename*=UTF-8\'\'document.txt'

def test_path_traversal_name_is_rejected_for_keyed_upload(isolated):
    case = isolated
    response = case.client.post(f'/manuscripts/{case.mid}/upload', data={'request_id':str(uuid4())}, files={'file':('../secret.txt',b'text','text/plain')})
    assert response.status_code == 400

def test_private_attachment_unicode_name_and_owner_download(client):
    http, state, _, _ = client
    draft = http.post('/author/submission-drafts', json={'request_id':str(uuid4())}).json()['id']
    url = f'/author/submission-drafts/{draft}/attachments'
    name = '研究資料_Résumé.txt'
    upload = http.post(url, data={'kind':'supplementary'}, files={'file':(name,b'synthetic','text/plain')})
    assert upload.status_code == 201 and upload.json()['filename'] == name
    response = http.get(f"{url}/{upload.json()['id']}")
    assert response.content == b'synthetic'
    assert 'filename="attachment.txt"' in response.headers['content-disposition']
    assert unquote(response.headers['content-disposition'].split("filename*=UTF-8''",1)[1]) == name
    from app.models import User
    state['user'] = User(user_id=2, role='author')
    assert http.get(f"{url}/{upload.json()['id']}").status_code == 404

def test_nfc_name_persists_and_decomposed_retry_is_idempotent(isolated):
    case = isolated
    request_id = str(uuid4())
    url = f'/manuscripts/{case.mid}/upload'
    decomposed, composed = 'Re\u0301sume\u0301.txt', 'Résumé.txt'
    def send(name):
        return case.client.post(url, data={'request_id':request_id}, files={'file':(name,b'synthetic','text/plain')})
    assert send(decomposed).status_code == 200
    assert case.client.get(f'/manuscripts/{case.mid}/upload-requests/{request_id}').json()['original_filename'] == composed
    assert send(composed).status_code == 200
    assert len(case.client.get(f'/manuscripts/{case.mid}/versions').json()) == 1
    with case.Session() as db:
        db.execute(text('UPDATE manuscript_upload_requests SET original_filename=:name WHERE request_id=:id'), {'name':decomposed,'id':request_id})
        db.commit()
    assert send(composed).status_code == 200
    assert case.client.get(f'/manuscripts/{case.mid}/upload-requests/{request_id}').json()['original_filename'] == decomposed

def test_nfc_attachment_retry_preserves_history(client):
    http, _, _, _ = client
    draft = http.post('/author/submission-drafts', json={'request_id':str(uuid4())}).json()['id']
    url = f'/author/submission-drafts/{draft}/attachments'
    key = str(uuid4())
    def send(name):
        return http.post(url, data={'kind':'supplementary','request_id':key}, files={'file':(name,b'synthetic','text/plain')})
    assert send('Re\u0301sume\u0301.txt').json()['filename'] == 'Résumé.txt'
    assert send('Résumé.txt').status_code == 200
    assert len(http.get(url).json()) == 1
