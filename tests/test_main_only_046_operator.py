"""Main-only identity and refusal tests without opening persistent Main data."""
import pytest
from pathlib import Path

from scripts import main_only_046_operator as operator


def arguments():
    return ['--project', str(operator.MAIN_ROOT),
            '--database', str(operator.MAIN_ROOT / 'manuscript.db'),
            '--confirm-main', operator.preparation.CONFIRMATION,
            '--storage-root', str(operator.MAIN_ROOT / 'uploads'),
            '--storage-root', str(operator.MAIN_ROOT / '.gsub_sample_storage'),
            '--backup', '/unread-backup', '--restore', '/unread-restore',
            '--maintenance-manifest', '/unread-manifest']


def synthetic_identity(monkeypatch):
    # Identity comparison is pure; this temporary clone path is not opened.
    monkeypatch.setattr(operator, 'MAIN_ROOT', Path(operator.__file__).resolve().parents[1])


def test_unconfigured_copy_refuses_identity():
    with pytest.raises(ValueError, match='Exact original Main'):
        operator.validate_identity(operator.MAIN_ROOT, operator.MAIN_ROOT / 'manuscript.db', operator.preparation.CONFIRMATION)


def test_exact_main_identity_only(monkeypatch):
    synthetic_identity(monkeypatch)
    operator.validate_identity(operator.MAIN_ROOT, operator.MAIN_ROOT / 'manuscript.db', operator.preparation.CONFIRMATION)
    for name in ('Demo', 'Main-Collaboration', 'other'):
        project = operator.MAIN_ROOT.parent / name
        with pytest.raises(ValueError, match='Exact original Main'):
            operator.validate_identity(project, project / 'manuscript.db', operator.preparation.CONFIRMATION)
    with pytest.raises(ValueError, match='Exact original Main'):
        operator.validate_identity(operator.MAIN_ROOT, operator.MAIN_ROOT / 'other.db', operator.preparation.CONFIRMATION)
    with pytest.raises(ValueError, match='Exact original Main'):
        operator.validate_identity(operator.MAIN_ROOT, operator.MAIN_ROOT / 'manuscript.db', 'wrong')


def test_even_matching_preflight_and_manifest_argument_cannot_enable_main(monkeypatch, capsys):
    synthetic_identity(monkeypatch)
    called = []
    monkeypatch.setattr(operator.preparation, 'validate', lambda *args, **kwargs: called.append(True) or {})
    assert operator.main(arguments()) == 2
    assert called == [True]
    assert 'no Main transaction is available' in capsys.readouterr().err


def test_missing_manifest_is_rejected_by_parser():
    with pytest.raises(SystemExit) as result:
        operator.main(arguments()[:-2])
    assert result.value.code == 2


def test_preflight_failure_stops_before_any_transaction(monkeypatch, capsys):
    synthetic_identity(monkeypatch)
    def refuse(*args, **kwargs):
        raise ValueError('Synthetic missing backup')
    monkeypatch.setattr(operator.preparation, 'validate', refuse)
    assert operator.main(arguments()) == 1
    assert 'Synthetic missing backup' in capsys.readouterr().err
