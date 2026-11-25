"""Shared stage-upload filename boundary on synthetic files only."""
import pytest
from fastapi import HTTPException
from app.routers.manuscripts import validate_manuscript_file
from app.filename_headers import normalize_upload_filename
from tests.test_secure_word_uploads import doc_bytes, docx_bytes

@pytest.mark.parametrize('name,content,extension', [
 ('研究論文_測試版本.docx',docx_bytes(),'.docx'),
 ('投稿文件_第二版.pdf',b'%PDF-synthetic','.pdf'),
 ('审稿材料_最终版.docx',docx_bytes(),'.docx'),
 ('研究データ_最終版.txt',b'synthetic','.txt'),
 ('Re\u0301sume\u0301_Final.docx',docx_bytes(),'.docx'),
 ('Paper Version (Final) 2026.pdf',b'%PDF-synthetic','.pdf'),
 ('한국어_문서.doc',doc_bytes(),'.doc'),
])
def test_common_validator_accepts_synthetic_unicode_names(name,content,extension):
    assert validate_manuscript_file(name,content)[0] == extension
    assert normalize_upload_filename(name) == __import__('unicodedata').normalize('NFC',name)

@pytest.mark.parametrize('name', ['../paper.txt', 'folder\\paper.txt', 'bad\x00name.txt', 'bad\u0085name.txt', ''])
def test_common_validator_rejects_unsafe_names(name):
    with pytest.raises(HTTPException) as error:
        validate_manuscript_file(name,b'synthetic')
    assert error.value.status_code == 400

def test_historical_names_keep_legacy_validation():
    assert validate_manuscript_file('legacy\u0085name.txt',b'synthetic',historical=True)[0] == '.txt'
