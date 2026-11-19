"""Disposable local browser fixture; never points at existing application data."""
import os
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['SECRET_KEY'] = 'synthetic-editor-browser-key-527934'
from pathlib import Path
import tempfile
import importlib
import uvicorn
import app.main as main
from app.security import hash_password
from tests import test_reviewer_metadata_gate as fixtures
from tests.test_reviewer_artifact_binding import T

fixture = fixtures.MetadataGateHTTPTests('test_default_disabled_and_request_inputs_cannot_enable')
fixture.setUp()
root = fixture.fx.fx.fx.path.parent.resolve()
if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not root.name.startswith('gsub-outbox-'):
    raise RuntimeError('Refusing non-disposable fixture root')
importlib.import_module('migrations.014_online_document_versions').migrate(fixture.fx.fx.fx.path)
path = root / 'uploads/manuscripts/80/original.txt'
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text('Synthetic original text', encoding='utf-8')
db = fixture.db
db.execute("UPDATE users SET password_hash=? WHERE user_id IN (1,2)", (hash_password('Synthetic-Test-Password-472!'),))
db.execute("INSERT INTO manuscripts(manuscript_id,title,abstract,author_id,status,review_round,file_path,created_at) VALUES (80,'Synthetic editor draft','Synthetic abstract',1,'draft',1,'uploads/manuscripts/80/original.txt',?)", (T,))
db.commit()
try:
    uvicorn.run(main.app, host='127.0.0.1', port=int(os.environ['EDITOR_BROWSER_PORT']), log_level='error', access_log=False)
finally:
    fixture.doCleanups()
