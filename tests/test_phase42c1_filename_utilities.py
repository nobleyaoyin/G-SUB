"""Synthetic filename validation and header contract."""
from urllib.parse import unquote
import pytest
from app.filename_headers import normalize_upload_filename, content_disposition

@pytest.mark.parametrize('name', ['研究論文_測試版本.docx', '研究データ_最終版.txt', '한국어_문서.doc', 'Résumé_Final.docx', 'Paper Version (Final) 2026.pdf', 'archive.final.docx', 'without-extension', '😀.txt'])
def test_unicode_names_and_headers(name):
    assert normalize_upload_filename(name) == name
    header = content_disposition(name,'document.txt')
    assert 'filename="document.txt"' in header
    assert unquote(header.split("filename*=UTF-8''",1)[1]) == name

def test_nfc_and_no_legacy_rewrite():
    legacy='Re\u0301sume\u0301.txt'
    assert normalize_upload_filename(legacy) == 'Résumé.txt'
    assert unquote(content_disposition(legacy,'document.txt').split("filename*=UTF-8''",1)[1]) == legacy

@pytest.mark.parametrize('name', ['', '../x.txt', 'folder\\x.txt', 'bad\r\nname.txt', '\nname.txt', 'bad\u0085.txt', 'bad\x7f.txt', 'bad\ud800.txt', 'CON.txt', 'con .pdf', 'COM1.doc', 'Lpt³.txt', 'NUL', 'foo.', 'a'*256+'.txt', 'a:b.txt', 'a?.txt'])
def test_invalid_new_names_rejected(name):
    with pytest.raises(ValueError): normalize_upload_filename(name)
    assert content_disposition(name,'document.txt').endswith("filename*=UTF-8''document.txt")

def test_safe_fallback_required_and_no_double_decode():
    with pytest.raises(ValueError): content_disposition('good.txt','CON.txt')
    header=content_disposition('%2F.txt','document.txt')
    assert unquote(header.split("filename*=UTF-8''",1)[1]) == '%2F.txt'
