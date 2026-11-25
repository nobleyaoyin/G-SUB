"""Policy-independent metadata and advisory extraction checks; no files written."""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai_prescreening import analyze_docx, analyze_txt
from app.routers.manuscripts import MAX_MANUSCRIPT_FILE_SIZE, validate_manuscript_file
from app.schemas import ManuscriptCreate, ManuscriptUpdate
from tests.test_secure_word_uploads import doc_bytes, docx_bytes


def test_unicode_metadata_and_existing_required_field_validation():
    item = ManuscriptCreate(title='  Étude 🌍  ', abstract='  研究\nRésumé  ')
    assert item.title == 'Étude 🌍' and item.abstract == '研究\nRésumé'
    assert ManuscriptUpdate(abstract='  新しい要約  ').abstract == '新しい要約'
    for invalid in ({'title':' ', 'abstract':'valid'}, {'title':'valid', 'abstract':'\t'},
                    {'title':'x' * 256, 'abstract':'valid'}, {'title':'valid', 'abstract':123}):
        with pytest.raises(ValidationError): ManuscriptCreate(**invalid)
    with pytest.raises(ValidationError): ManuscriptUpdate(abstract=' \n ')


@pytest.mark.parametrize('name,content',[
    ('synthetic.pdf', b'%PDF-synthetic'),
    ('synthetic.doc', doc_bytes()),
    ('synthetic.docx', docx_bytes()),
    ('synthetic.txt', 'Résumé 研究'.encode()),
])
def test_supported_upload_formats_do_not_depend_on_word_count_extraction(name, content):
    assert validate_manuscript_file(name, content)[0] == '.' + name.rsplit('.', 1)[1]


def test_advisory_count_and_unextractable_content_are_not_zero_counts():
    analysis = analyze_txt('Résumé 研究'.encode())
    assert analysis['advisory_only'] is True and analysis['word_count'] > 0
    with pytest.raises(ValueError): analyze_txt(b'\xff')
    # Structurally uploadable DOCX can lack an extractable body. Upload
    # acceptance must not be presented as an authoritative zero-word count.
    content = docx_bytes()
    assert validate_manuscript_file('source.docx', content)[0] == '.docx'
    with pytest.raises(ValueError): analyze_docx(content)
    with pytest.raises(HTTPException) as oversized:
        validate_manuscript_file('source.txt', b'x' * (MAX_MANUSCRIPT_FILE_SIZE + 1))
    assert oversized.value.status_code == 413
