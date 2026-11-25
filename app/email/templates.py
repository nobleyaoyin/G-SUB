"""Versioned plain-text templates for workflow email."""
from collections.abc import Mapping

from .types import EmailMessage


def render_template(key: str, version: str, recipient: str, context: Mapping) -> EmailMessage:
    if key not in (
        "synthetic_test",
        "reviewer_invitation",
        "manuscript_submitted",
        "review_submitted",
        "revision_requested",
        "manuscript_decision",
    ):
        raise ValueError("Unknown template")
    if version != "v1":
        raise ValueError("Unsupported template version")
    if not isinstance(context, Mapping):
        raise ValueError("Unexpected template context")

    if key == "synthetic_test":
        if context:
            raise ValueError("Unexpected template context")
        subject = "G-Sub synthetic test"
        body = "This is a synthetic test message. No email has been delivered."
    elif key == "reviewer_invitation":
        if set(context) not in (set(), {"manuscript_id"}):
            raise ValueError("Unexpected template context")
        manuscript_id = context.get("manuscript_id")
        if manuscript_id is not None and (type(manuscript_id) is not int or manuscript_id <= 0):
            raise ValueError("Invalid manuscript ID")
        return EmailMessage(
            recipient=recipient,
            subject=(
                f"G-Sub — Invitation to Review Manuscript #{manuscript_id}"
                if manuscript_id is not None
                else "G-Sub — Invitation to Review a Manuscript"
            ),
            text_body=(
                "Dear Reviewer,\n\n"
                + (
                    f"A review invitation for manuscript #{manuscript_id} "
                    if manuscript_id is not None
                    else "A manuscript review invitation "
                )
                + "is available in G-Sub. "
                + "Please sign in to G-Sub to review the invitation and "
                + "choose whether to accept or decline.\n\n"
                + "Thank you for considering this request.\n\n"
                + "G-Sub Editorial Team"
            ),
            template_key=key,
            template_version=version,
        )
    elif key == "manuscript_submitted":
        manuscript_id = _positive_int(context, "manuscript_id")
        subject = f"G-Sub received manuscript #{manuscript_id}"
        body = (
            "Your manuscript submission was received successfully.\n\n"
            f"Manuscript ID: {manuscript_id}\n"
            "Sign in to G-Sub to follow its status."
        )
    elif key == "review_submitted":
        manuscript_id = _positive_int(context, "manuscript_id")
        review_round = _positive_int(context, "review_round")
        subject = f"G-Sub review submitted for manuscript #{manuscript_id}"
        body = (
            "A reviewer submitted a review.\n\n"
            f"Manuscript ID: {manuscript_id}\n"
            f"Review round: {review_round}\n"
            "Sign in to G-Sub to view the review."
        )
    elif key == "revision_requested":
        manuscript_id = _positive_int(context, "manuscript_id")
        subject = f"G-Sub revision requested for manuscript #{manuscript_id}"
        body = (
            "A revision has been requested for your manuscript.\n\n"
            f"Manuscript ID: {manuscript_id}\n"
            "Sign in to G-Sub to view the request and next steps."
        )
    else:
        manuscript_id = _positive_int(context, "manuscript_id")
        decision = context.get("decision")
        if decision not in ("accepted", "rejected"):
            raise ValueError("Invalid manuscript decision")
        if set(context) != {"manuscript_id", "decision"}:
            raise ValueError("Unexpected template context")
        subject = f"G-Sub manuscript #{manuscript_id} {decision}"
        body = (
            f"Your manuscript has been {decision}.\n\n"
            f"Manuscript ID: {manuscript_id}\n"
            "Sign in to G-Sub to view the decision."
        )

    if key in ("manuscript_submitted", "review_submitted", "revision_requested"):
        expected = {
            "manuscript_submitted": {"manuscript_id"},
            "review_submitted": {"manuscript_id", "review_round"},
            "revision_requested": {"manuscript_id"},
        }[key]
        if set(context) != expected:
            raise ValueError("Unexpected template context")

    return EmailMessage(
        recipient=recipient,
        subject=subject,
        text_body=body,
        template_key=key,
        template_version=version,
    )


def _positive_int(context: Mapping, key: str) -> int:
    value = context.get(key)
    if type(value) is not int or value <= 0:
        raise ValueError(f"Invalid {key.replace('_', ' ')}")
    return value
