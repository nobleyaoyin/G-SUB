"""Formatter Unicode uploads against isolated existing workflow fixtures."""
from unittest.mock import patch
from tests.test_formatting import FormattingTest
from tests.test_secure_word_uploads import docx_bytes, doc_bytes
import app.routers.eic as eic
import app.routers.formatting as formatting


def test_formatter_unicode_upload_download_bytes():
    case = FormattingTest('runTest')
    case.setUp()
    try:
        with patch.object(eic,'BASE_DIR',case.root), patch.object(formatting,'BASE_DIR',case.root):
            case.prepare_final()
            invitation = case.f_invite(case.formatter).json()['invitation_id']
            assert case.f_action(case.formatter,f'/formatting/invitations/{invitation}/respond',{'decision':'accept'}).status_code == 200
            formats = [('投稿文件_第二版.pdf',b'%PDF-synthetic','application/pdf'),('研究論文_測試版本.docx',docx_bytes(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),('한국어_문서.doc',doc_bytes(),'application/msword'),('研究データ_最終版.txt',b'synthetic text','text/plain')]
            for index,(name,content,mime) in enumerate(formats):
                case.current=case.formatter
                response=case.client.post(f'/formatting/invitations/{invitation}/submit',data={'comments':'Synthetic'},files={'file':(name,content,mime)})
                assert response.status_code == 201,response.text
                sid=response.json()['submission_id']
                case.current=case.author
                download=case.client.get(f'/formatting/submissions/{sid}/download')
                assert download.status_code == 200 and download.content == content
                if index < len(formats)-1:
                    assert case.f_action(case.author,f'/formatting/submissions/{sid}/author-review',{'decision':'request_revision','comments':'Next'}).status_code == 200
    finally:
        case.tearDown()
