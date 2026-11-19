"""Formatter notes and staff-comments authorization using disposable fixtures."""
from unittest.mock import patch
import app.routers.eic as eic
import app.routers.formatting as formatting
from tests import test_formatting


def test_accepted_formatter_can_access_but_other_formatter_cannot():
    f=test_formatting.FormattingTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root),patch.object(formatting,'BASE_DIR',f.root):
            f.prepare_final()
            response=f.f_invite(f.formatter);assert response.status_code==201,response.text
            iid=response.json()['invitation_id']
            f.current=f.formatter
            for path in ('notes','general-comments'):
                assert f.client.get(f'/manuscripts/{f.mid}/{path}').status_code==403
            assert f.f_action(f.formatter,f'/formatting/invitations/{iid}/respond',{'decision':'accept'}).status_code==200
            f.current=f.formatter
            for path in ('notes','general-comments'):
                assert f.client.get(f'/manuscripts/{f.mid}/{path}').status_code==200
                assert f.client.post(f'/manuscripts/{f.mid}/{path}',json={'content':'Synthetic private content'}).status_code==201
            f.current=f.other_formatter
            for path in ('notes','general-comments'):
                assert f.client.get(f'/manuscripts/{f.mid}/{path}').status_code==403
            f.current=f.chief
            assert f.client.get(f'/manuscripts/{f.mid}/notes').json()==[]
            assert len(f.client.get(f'/manuscripts/{f.mid}/general-comments').json())==1
    finally:f.tearDown()
