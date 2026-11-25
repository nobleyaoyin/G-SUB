"""Two independent connections to disposable shared-memory SQLite only."""
import json
import sqlite3
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app import models
from app.reviewer_metadata_gate import MetadataMode
from app.routers import assignments
from tests.test_phase_2f_reviewer_projections import api_factory
from tests.test_phase_2f_reviewer_document_release import setup_file


@pytest.mark.parametrize('change', ['owner', 'status', 'invitation', 'round_binding'])
def test_list_and_evaluator_use_one_database_snapshot(api_factory, monkeypatch, tmp_path, change):
    _, _, source_engine, _, _ = setup_file(api_factory, monkeypatch, tmp_path, 'single')
    uri = f'file:gsub_r1_{uuid4().hex}?mode=memory&cache=shared'
    anchor = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=0)
    source = source_engine.raw_connection()
    source.driver_connection.backup(anchor)
    source.close()
    assert anchor.execute('PRAGMA database_list').fetchall()[0][2] == ''
    engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=0))
    @event.listens_for(engine, 'connect')
    def fk(conn, _):
        conn.execute('PRAGMA foreign_keys=ON')
    writer = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=0)
    writer.execute('PRAGMA foreign_keys=ON')
    commands = {
        'owner': 'UPDATE review_assignments SET reviewer_id=5 WHERE assignment_id=1',
        'status': "UPDATE review_assignments SET status='cancelled' WHERE assignment_id=1",
        'invitation': "UPDATE reviewer_invitations SET status='pending' WHERE assignment_id=1",
        'round_binding': 'UPDATE review_round_files SET review_round=3 WHERE round_file_id=1',
    }
    original = assignments.reviewer_document_available
    state = {'wrote': False}
    def mutate_then_evaluate(*args):
        try:
            writer.execute(commands[change])
            writer.commit()
            state['wrote'] = True
        except sqlite3.OperationalError as exc:
            assert 'locked' in str(exc).lower()
            writer.rollback()
        return original(*args)
    monkeypatch.setattr(assignments, 'reviewer_document_available', mutate_then_evaluate)
    try:
        with Session(engine) as db:
            user = db.get(models.User, 2)
            result = assignments.get_my_assignments(user, db, MetadataMode.DISABLED, None)
            rows = json.loads(result.body)
        if state['wrote']:
            assert not rows or rows[0]['review_file_available'] is False
        else:
            assert rows[0]['review_file_available'] is True
    finally:
        engine.dispose(); writer.close(); anchor.close()
