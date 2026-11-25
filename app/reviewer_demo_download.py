"""Internal dependency for synthetic, explicitly enabled artifact-download tests.

No production configuration or request data can construct this context. Trusted
application code must supply a proof adapter, provenance adapter and private
storage; none is provided by default.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class DemoArtifactContext:
    proof: object
    provenance: object
    storage: object


def reviewer_demo_artifact_context():
    return None


class AuthenticatedReviewerAuthority:
    """Bind the isolated reader to the principal resolved by FastAPI auth."""
    def __init__(self, principal):
        self._principal = principal

    def authorize(self, db, principal, action, manuscript_id, *, prepared_by=None):
        if principal is not self._principal or action != 'read_artifact':
            raise ValueError('Reviewer unavailable')
        return principal.user_id


class AuthenticatedEditorialAuthority:
    def __init__(self, principal):
        self._principal = principal

    def authorize(self, db, principal, action, manuscript_id, *, prepared_by=None):
        if principal is not self._principal or action != 'bind':
            raise ValueError('Editorial access unavailable')
        return principal.user_id
