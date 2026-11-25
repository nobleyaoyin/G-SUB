import pytest

from app.email import service


@pytest.fixture(autouse=True)
def disable_workflow_email_delivery(monkeypatch):
    monkeypatch.setattr(service, "load_smtp_settings", lambda: None)
