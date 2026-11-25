"""Protected EIC lifecycle enforcement using an explicitly synthetic prototype principal."""
import sqlite3
from app.models import User
from app.lifecycle_prototype import lifecycle_change
from test_batch38_eic_proof import fixture
from tests.test_lifecycle_prototype import principal, AUTHORITY


def test_synthetic_enrollment_disable_and_role_gates(fixture):
    f, chief, headers, _, _, _, _ = fixture
    candidate=f'/eic/manuscripts/{f.mid}/reviewer-candidate-reconciliation'
    # Existing fixture bootstraps an explicitly synthetic first EIC; it is not a production workflow.
    import importlib
    importlib.import_module('migrations.023_reviewer_candidate_intake').migrate(f.db_path)
    target=User(name='Synthetic EIC Target', email='sprint10-eic@example.com', password_hash='x', role='eic')
    f.db.add(target); f.db.commit(); uid=target.user_id
    assert f.client.get('/eic/editors',headers=headers(target)).status_code==200
    assert f.client.get(candidate,headers=headers(target)).status_code==403
    assert f.client.get(candidate,headers=headers(f.reviewer)).status_code==403
    assert f.client.get(candidate,headers=headers(f.author)).status_code==403
    with sqlite3.connect(f.db_path, timeout=.2) as raw:
        raw.execute('PRAGMA foreign_keys=ON')
        state=lifecycle_change(raw,principal(chief.user_id),uid,'enroll',authority=AUTHORITY,expected_sequence=0,expected_generation=0)
        assert state.state=='active'
    assert f.client.get(candidate,headers=headers(target)).status_code==200
    with sqlite3.connect(f.db_path, timeout=.2) as raw:
        raw.execute('PRAGMA foreign_keys=ON')
        state=lifecycle_change(raw,principal(chief.user_id),uid,'disable',authority=AUTHORITY,expected_sequence=1,expected_generation=1)
        assert state.state=='disabled'
    assert f.client.get(candidate,headers=headers(target)).status_code==403
    # Legacy EIC routes do not enforce this prototype lifecycle; record the boundary explicitly.
    assert f.client.get('/eic/editors',headers=headers(target)).status_code==200
