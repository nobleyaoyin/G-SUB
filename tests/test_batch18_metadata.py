"""Synthetic, isolated compare-and-set metadata API checks."""
import hashlib
import sqlite3
import tests.test_reviewer_download as fixtures


def digest(value): return hashlib.sha256(value.encode('utf-8')).hexdigest()


def test_independent_metadata_updates_and_stale_compare():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        f.manuscript.status='draft';f.db.commit();f.current=f.author
        path=f'/manuscripts/{f.mid}'
        result=f.client.patch(path,json={'title':'New title'},headers={'X-Expected-Metadata-SHA256':digest('Title')})
        assert result.status_code==200,result.text
        assert result.json()['title']=='New title' and result.json()['abstract']=='Abstract'
        stale=f.client.patch(path,json={'title':'Stale overwrite'},headers={'X-Expected-Metadata-SHA256':digest('Title')})
        assert stale.status_code==409
        result=f.client.patch(path,json={'abstract':'Résumé revised'},headers={'X-Expected-Metadata-SHA256':digest('Abstract')})
        assert result.status_code==200 and result.json()['title']=='New title'
        assert result.json()['abstract']=='Résumé revised'
        with sqlite3.connect(f.db_path) as independent:
            independent.execute('UPDATE manuscripts SET title=? WHERE manuscript_id=?',('Concurrent title',f.mid))
        stale=f.client.patch(path,json={'title':'Overwrite'},headers={'X-Expected-Metadata-SHA256':digest('New title')})
        assert stale.status_code==409
        with sqlite3.connect(f.db_path) as independent:
            assert independent.execute('SELECT title,abstract FROM manuscripts WHERE manuscript_id=?',(f.mid,)).fetchone()==('Concurrent title','Résumé revised')
        assert f.client.patch(path,json={'title':'x','abstract':'y'},headers={'X-Expected-Metadata-SHA256':digest('New title')}).status_code==400
        f.current=f.editor
        assert f.client.patch(path,json={'title':'Forbidden'},headers={'X-Expected-Metadata-SHA256':digest('New title')}).status_code==403
    finally:f.tearDown()
