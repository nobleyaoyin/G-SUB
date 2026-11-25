"""Migration target validation using only newly-created synthetic files."""
import importlib
import os

import pytest


MIGRATIONS = (
    '033_stage_dialogue', '034_agreement_snapshot_guards',
    '035_sample_document_storage', '036_sample_initial_editing',
    '037_sample_final_formatting', '038_candidate_preparation_provenance',
    '039_lifecycle_administration', '040_lifecycle_succession',
)


@pytest.mark.parametrize('migration_name', MIGRATIONS)
@pytest.mark.parametrize('alias_kind', ('symlink', 'hardlink', 'directory'))
def test_invalid_target_rejected_before_sqlite_open(tmp_path, monkeypatch, migration_name, alias_kind):
    module = importlib.import_module('migrations.' + migration_name)
    source = tmp_path / 'synthetic.sqlite'
    source.write_bytes(b'synthetic placeholder')
    target = tmp_path / 'candidate'
    if alias_kind == 'symlink':
        target.symlink_to(source)
    elif alias_kind == 'hardlink':
        os.link(source, target)
    else:
        target.mkdir()

    def unexpected_open(*args, **kwargs):
        pytest.fail('SQLite must not open an invalid migration target')

    monkeypatch.setattr(module.sqlite3, 'connect', unexpected_open)
    with pytest.raises(ValueError, match='standalone regular'):
        module.migrate(target)
    assert source.read_bytes() == b'synthetic placeholder'


@pytest.mark.parametrize('migration_name', MIGRATIONS[:5])
def test_downgrade_rejects_symlink_before_sqlite_open(tmp_path, monkeypatch, migration_name):
    module = importlib.import_module('migrations.' + migration_name)
    source = tmp_path / 'synthetic.sqlite'
    source.write_bytes(b'synthetic placeholder')
    target = tmp_path / 'candidate'
    target.symlink_to(source)

    def unexpected_open(*args, **kwargs):
        pytest.fail('SQLite must not open an invalid migration target')

    monkeypatch.setattr(module.sqlite3, 'connect', unexpected_open)
    with pytest.raises(ValueError, match='standalone regular'):
        module.downgrade_empty(target)


@pytest.mark.parametrize('migration_name', MIGRATIONS[2:5])
def test_explicit_main_override_still_reaches_sqlite_for_regular_file(tmp_path, monkeypatch, migration_name):
    module = importlib.import_module('migrations.' + migration_name)
    module_dir = tmp_path / 'migrations'
    module_dir.mkdir()
    monkeypatch.setattr(module, '__file__', str(module_dir / (migration_name + '.py')))
    target = tmp_path / 'manuscript.db'
    target.write_bytes(b'synthetic placeholder')

    class OpenReached(Exception):
        pass

    def stop_at_open(*args, **kwargs):
        raise OpenReached

    monkeypatch.setattr(module.sqlite3, 'connect', stop_at_open)
    with pytest.raises(ValueError, match='Persistent Main'):
        module.migrate(target)
    with pytest.raises(OpenReached):
        module.migrate(target, authorize_main=True)
    assert target.read_bytes() == b'synthetic placeholder'
