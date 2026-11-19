"""Security checks for Editors assigned to Formatting."""

import unittest
from unittest.mock import patch

from tests import test_formatting
import app.routers.eic as eic
import app.routers.formatting as formatting


class EditorFormattingProgressTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_formatting.FormattingTest(
            "test_formatting_and_publication"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_assigned_editor_progress_and_unassigned_denial(self):
        f = self.fixture

        with patch.object(eic, "BASE_DIR", f.root), patch.object(
            formatting, "BASE_DIR", f.root
        ):
            f.prepare_final()

            response = f.f_invite(f.alternate)
            self.assertEqual(response.status_code, 201, response.text)
            invitation_id = response.json()["invitation_id"]

            f.current = f.alternate
            response = f.client.get(f"/manuscripts/{f.mid}/progress")
            self.assertEqual(response.status_code, 404)

            response = f.f_action(
                f.alternate,
                f"/formatting/invitations/{invitation_id}/respond",
                {"decision": "accept"},
            )
            self.assertEqual(response.status_code, 200, response.text)

            f.current = f.alternate
            response = f.client.get(f"/manuscripts/{f.mid}/progress")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["current_stage"], "Formatting")

            f.current = f.editor
            response = f.client.get(f"/manuscripts/{f.mid}/progress")
            self.assertEqual(response.status_code, 200, response.text)

            f.current = f.alternate
            response = f.client.get(f"/manuscripts/{f.mid}/pdf")
            self.assertIn(response.status_code, (403, 404))


if __name__ == "__main__":
    unittest.main()
