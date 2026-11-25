"""Private metadata preparation never substitutes for human content review."""
import hashlib
import io
import zipfile
import pytest
from app.reviewer_candidate_docx import prepare_docx_metadata, PreparationError
from test_batch38_eic_proof import fixture
from test_batch40_reviewer_candidates import ready, CHECKS


def word_document(body='Neutral study text', extra=None):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('word/document.xml',f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{body}</w:t></w:r></w:p></w:body></w:document>')
        z.writestr('docProps/core.xml','<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>Synthetic Author</dc:creator><dc:title>Identifying title</dc:title></cp:coreProperties>')
        z.writestr('docProps/app.xml','<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Company>Synthetic Institution</Company></Properties>')
        if extra:z.writestr(extra,b'<synthetic/>')
    return output.getvalue()


def test_metadata_removed_but_content_still_requires_human_review():
    original=word_document('Synthetic Author appears in the content')
    prepared=prepare_docx_metadata(original)
    assert original!=prepared
    with zipfile.ZipFile(io.BytesIO(prepared)) as z:
        assert b'Synthetic Author' not in z.read('docProps/core.xml')
        assert b'Identifying title' not in z.read('docProps/core.xml')
        assert b'Synthetic Institution' not in z.read('docProps/app.xml')
        assert b'Synthetic Author appears in the content' in z.read('word/document.xml')
    with zipfile.ZipFile(io.BytesIO(original)) as z:assert b'Synthetic Author' in z.read('docProps/core.xml')

@pytest.mark.parametrize('extra',['word/comments.xml','word/media/image1.png','word/embeddings/object1.bin','customXml/item1.xml'])
def test_unhandled_content_is_rejected(extra):
    with pytest.raises(PreparationError):prepare_docx_metadata(word_document(extra=extra))

def test_tracked_changes_and_external_relationships_are_rejected():
    tracked=word_document('<w:ins w:author="Synthetic"><w:r/></w:ins>')
    with pytest.raises(PreparationError):prepare_docx_metadata(tracked)
    original=word_document(); data=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as src, zipfile.ZipFile(data,'w') as dst:
        for item in src.infolist():dst.writestr(item.filename,src.read(item))
        dst.writestr('word/_rels/document.xml.rels','<Relationships><Relationship TargetMode="External" Target="https://invalid.example/"/></Relationships>')
    with pytest.raises(PreparationError):prepare_docx_metadata(data.getvalue())

def test_malformed_docx_fails_closed():
    with pytest.raises(PreparationError):prepare_docx_metadata(b'not a docx')

def test_private_candidate_human_approval_binding_and_exact_reviewer_download(fixture):
    from importlib import import_module
    f,chief,headers,aid,sid,_,_=ready(fixture)
    import_module('migrations.038_candidate_preparation_provenance').migrate(f.db_path)
    content=word_document();url=f'/eic/manuscripts/{f.mid}/reviewer-candidates'
    data={'review_round':1,'source_id':sid,'artifact_version':1,'fmt':'docx','metadata_preparation':'docx-v1'}
    response=f.client.post(url,headers=headers(chief),data=data,files={'file':('synthetic.docx',content,'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert response.status_code==201,response.text
    result=response.json();assert result['status']=='private_unverified' and result['human_content_review_required'] is True
    base=f"/eic/manuscripts/{f.mid}/reviewer-candidates/{result['candidate_id']}"
    assert f.client.get(base+'/content',headers=headers(f.reviewer)).status_code==403
    prepared=f.client.get(base+'/content',headers=headers(chief));assert prepared.status_code==200
    assert hashlib.sha256(prepared.content).hexdigest()==result['sha256']
    with zipfile.ZipFile(io.BytesIO(prepared.content)) as z:assert b'Synthetic Author' not in z.read('docProps/core.xml')
    assert f.client.post(base+'/approve',headers=headers(chief)).status_code==409
    info=f.client.get(base+'/processing',headers=headers(chief)).json()
    context={'expected_sha256':info['prepared_sha256'],'expected_artifact_version':info['artifact_version'],'expected_review_round':info['review_round']}
    assert f.client.post(base+'/verify',headers=headers(chief),json={**CHECKS,'filename_verified':True,**context}).status_code==200
    assert f.client.post(base+'/approve',headers=headers(chief),json={**context,'confirmed':True}).status_code==200
    assert f.client.post(base+'/publish',headers=headers(chief)).status_code==200
    assert f.client.post(base+f'/bind/{aid}',headers=headers(chief)).status_code==200
    delivered=f.client.get(f'/assignments/{aid}/download',headers=headers(f.reviewer))
    assert delivered.status_code==200 and delivered.content==prepared.content
    assert delivered.headers['content-disposition']=='attachment; filename="review-document.docx"'
    assert f.author.name not in str(delivered.headers) and f.author.email not in str(delivered.headers)
    assert f.client.get(f'/assignments/{aid}/download',headers=headers(f.other)).status_code==409
    assert f.client.get(f'/assignments/{aid}/download',headers=headers(f.author)).status_code==403

def test_unsupported_or_unsafe_preparation_never_creates_candidate(fixture):
    import sqlite3
    from importlib import import_module
    f,chief,headers,_,sid,_,_=ready(fixture)
    import_module('migrations.038_candidate_preparation_provenance').migrate(f.db_path)
    url=f'/eic/manuscripts/{f.mid}/reviewer-candidates'
    common={'review_round':1,'source_id':sid,'artifact_version':1}
    denied=f.client.post(url,headers=headers(f.reviewer),data={**common,'fmt':'docx','metadata_preparation':'docx-v1'},files={'file':('candidate.docx',word_document(),'application/octet-stream')})
    assert denied.status_code==403
    pdf=f.client.post(url,headers=headers(chief),data={**common,'fmt':'pdf','metadata_preparation':'docx-v1'},files={'file':('candidate.pdf',b'%PDF-synthetic','application/pdf')})
    assert pdf.status_code==400
    unsafe=f.client.post(url,headers=headers(chief),data={**common,'fmt':'docx','metadata_preparation':'docx-v1'},files={'file':('candidate.docx',word_document(extra='word/comments.xml'),'application/octet-stream')})
    assert unsafe.status_code==409
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('select count(*) from reviewer_candidate_reservations').fetchone()[0]==0
