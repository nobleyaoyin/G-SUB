"""Demonstrate actual SQLite and upload behavior on isolated test data."""
from contextlib import closing
import sqlite3

import pytest
from sqlalchemy.exc import OperationalError

from tests.test_reviewer_download import ReviewerDownloadsTest


def test_sqlite_lock_does_not_prevent_legacy_upload_file_publication():
    fixture = ReviewerDownloadsTest()
    fixture.setUp()
    try:
        fixture.current = fixture.author
        fixture.manuscript.status = 'draft'
        fixture.db.commit()
        directory = fixture.root / 'uploads' / 'manuscripts' / str(fixture.mid)
        before = set(directory.iterdir()) if directory.exists() else set()
        with closing(sqlite3.connect(fixture.db_path, timeout=0.1)) as lock:
            lock.execute('BEGIN IMMEDIATE')
            try:
                # Without request_id this existing route can publish a file
                # before its later database commit is blocked.
                with pytest.raises(OperationalError, match='locked'):
                    fixture.client.post(f'/manuscripts/{fixture.mid}/upload', files={
                        'file': ('synthetic.txt', b'Synthetic barrier evidence.\n', 'text/plain')
                    })
                after = set(directory.iterdir()) if directory.exists() else set()
                created = after - before
                assert len(created) == 1
                assert next(iter(created)).read_bytes() == b'Synthetic barrier evidence.\n'
            finally:
                lock.rollback()
    finally:
        fixture.tearDown()
