"""SampleStorage upload, replacement and history via isolated HTTP routes."""
import hashlib
import pytest
from sqlalchemy import text
from tests.test_sample_document_routes import setup
from tests.test_secure_word_uploads import doc_bytes, docx_bytes

@pytest.mark.parametrize('ext,first,second,mime', [
    ('pdf', b'%PDF-sample original research', b'%PDF-sample revised research', 'application/pdf'),
    ('docx', docx_bytes(b'original'), docx_bytes(b'revised'), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    ('doc', doc_bytes(), doc_bytes()+b'revised', 'application/msword'),
    ('txt', b'Original synthetic sample research.', b'Revised synthetic sample research.', 'text/plain'),
])
def test_sample_four_formats_preserve_replacement_and_owner_history(setup, ext, first, second, mime):
    client, current, ids, mid, root, Session = setup
    items=[]
    for data in (first,second):
        response=client.post(f'/manuscripts/{mid}/upload',files={'file':(f'sample.{ext}',data,mime)})
        assert response.status_code==200,response.text
        items.append(response.json())
    assert items[0]['version_id'] != items[1]['version_id']
    listing=client.get(f'/manuscripts/{mid}/versions')
    assert listing.status_code==200
    assert {x['filename'] for x in listing.json()} == {x['filename'] for x in items}
    assert [x['filename'] for x in listing.json() if x['is_current']] == [items[-1]['filename']]
    for item,content in zip(items,(first,second)):
        response=client.get(f"/manuscripts/{mid}/versions/{item['filename']}")
        assert response.status_code==200 and response.content==content
    with Session() as db:
        rows=db.execute(text('SELECT version_id,manuscript_id,review_round,file_format,sha256,created_at FROM sample_document_versions WHERE manuscript_id=:mid ORDER BY created_at,version_id'),{'mid':mid}).mappings().all()
        assert [x['version_id'] for x in rows]==[x['version_id'] for x in items]
        assert all(x['manuscript_id']==mid and x['review_round']==1 and x['file_format']==ext for x in rows)
        assert [x['sha256'] for x in rows]==[hashlib.sha256(x).hexdigest() for x in (first,second)]
    assert not (root/'uploads').exists()
    assert client.get(f"/manuscripts/{mid+100}/versions/{items[0]['filename']}").status_code==404
    current['id']=ids[1]
    assert client.get(f'/manuscripts/{mid}/versions').status_code==403
    assert client.get(f"/manuscripts/{mid}/versions/{items[0]['filename']}").status_code==403
    current['id']=ids[2]
    assert client.get(f'/manuscripts/{mid}/download').status_code==403
