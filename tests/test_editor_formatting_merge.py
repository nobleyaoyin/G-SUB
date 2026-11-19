"""Verify that Editors can perform formatting without a separate Formatter role."""

from unittest.mock import patch

import app.routers.eic as eic
import app.routers.formatting as formatting
from test_formatting import FormattingTest


class EditorFormattingMergeTest(FormattingTest):
    def test_editor_formatting_workflow(self):
        with patch.object(eic, "BASE_DIR", self.root), patch.object(
            formatting, "BASE_DIR", self.root
        ):
            self.prepare_final()

            response = self.f_invite(self.alternate)
            self.assertEqual(response.status_code, 201, response.text)
            invitation_id = response.json()["invitation_id"]

            self.current = self.alternate
            response = self.client.get("/formatting/my")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(
                any(item["manuscript_id"] == self.mid for item in response.json())
            )

            self.current = self.editor
            self.assertEqual(
                self.client.get(
                    f"/formatting/manuscripts/{self.mid}"
                ).status_code,
                403,
            )

            self.assertEqual(
                self.f_action(
                    self.editor,
                    f"/formatting/invitations/{invitation_id}/respond",
                    {"decision": "accept"},
                ).status_code,
                403,
            )

            response = self.f_action(
                self.alternate,
                f"/formatting/invitations/{invitation_id}/respond",
                {"decision": "accept"},
            )
            self.assertEqual(response.status_code, 200, response.text)

            self.current = self.alternate
            response = self.client.get(
                f"/formatting/invitations/{invitation_id}/input"
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.content, b"%PDF-approved-final")

            response = self.client.post(
                f"/formatting/invitations/{invitation_id}/submit",
                data={"comments": "Formatted by editor"},
                files={
                    "file": (
                        "formatted.pdf",
                        b"%PDF-editor-layout",
                        "application/pdf",
                    )
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            submission_id = response.json()["submission_id"]

            self.current = self.editor
            self.assertEqual(
                self.client.get(
                    f"/formatting/submissions/{submission_id}/download"
                ).status_code,
                403,
            )

            response = self.f_action(
                self.author,
                f"/formatting/submissions/{submission_id}/author-review",
                {"decision": "approve", "comments": "Approved"},
            )
            self.assertEqual(response.status_code, 200, response.text)

            response = self.f_action(
                self.chief,
                f"/formatting/submissions/{submission_id}/eic-review",
                {"decision": "approve", "comments": "Approved"},
            )
            self.assertEqual(response.status_code, 200, response.text)

            print("Editor formatting workflow completed successfully.")
