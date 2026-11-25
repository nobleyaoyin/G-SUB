"""Synthetic Main review-copy delivery; no automatic anonymization claim."""
import hashlib
import io
import zipfile

from test_batch38_eic_proof import fixture
from test_batch40_reviewer_candidates import CHECKS, ready


def anonymous_candidate():
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Anonymous synthetic study</w:t></w:r></w:p></w:body></w:document>')
        archive.writestr('docProps/core.xml', '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>')
    return output.getvalue()


def test_assigned_reviewer_receives_inspected_review_copy_without_original_overwrite(fixture):
    f, chief, headers, aid, source_id, _, private = ready(fixture)
    original = f.root / f.pdf
    before = hashlib.sha256(original.read_bytes()).digest()
    candidate = anonymous_candidate()
    response = f.client.post(f'/eic/manuscripts/{f.mid}/reviewer-candidates', headers=headers(chief), data={'review_round': 1, 'source_id': source_id, 'artifact_version': 1, 'fmt': 'docx'}, files={'file': ('identifying-original-name.docx', candidate, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert response.status_code == 201, response.text
    base = f"/eic/manuscripts/{f.mid}/reviewer-candidates/{response.json()['candidate_id']}"
    assert f.client.post(base + '/verify', headers=headers(chief), json=CHECKS).status_code == 200
    assert f.client.post(base + '/approve', headers=headers(chief)).status_code == 200
    assert f.client.post(base + '/publish', headers=headers(chief)).status_code == 200
    assert f.client.post(base + f'/bind/{aid}', headers=headers(chief)).status_code == 200
    downloaded = f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer))
    assert downloaded.status_code == 200
    assert downloaded.content == candidate
    assert downloaded.headers['content-disposition'] == 'attachment; filename="review-document.docx"'
    assert b'identifying-original-name' not in str(downloaded.headers).encode()
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        parts = b' '.join(archive.read(name) for name in archive.namelist())
        assert b'Anonymous synthetic study' in parts
        assert f.author.name.encode() not in parts and f.author.email.encode() not in parts
        assert b'<dc:creator>' not in parts and b'<cp:lastModifiedBy>' not in parts
    assert f.client.get(f'/assignments/{aid}/download', headers=headers(f.other)).status_code == 409
    assert hashlib.sha256(original.read_bytes()).digest() == before
