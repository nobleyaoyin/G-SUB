"""Application-owned reviewer artifact context with fail-closed availability.

Only server startup code may configure app.state.reviewer_artifact_context.
No context is configured by default; missing evidence never releases bytes.
"""
from dataclasses import dataclass
from fastapi import Request
from app.main_reviewer_authority import AuthenticatedEditorialAuthority, AuthenticatedReviewerAuthority
from app.reviewer_artifact_storage import ArtifactStorage


@dataclass(frozen=True)
class ReviewerArtifactContext:
    proof: object
    provenance: object
    storage: ArtifactStorage

    def __post_init__(self):
        if not callable(getattr(self.proof, 'verify_prospective', None)):
            raise ValueError('Trusted source proof provider required')
        if not callable(getattr(self.provenance, 'open_attested_source', None)):
            raise ValueError('Trusted source provenance provider required')
        if type(self.storage) is not ArtifactStorage:
            raise ValueError('Private artifact storage required')


def reviewer_artifact_context(request: Request) -> ReviewerArtifactContext | None:
    context = getattr(request.app.state, 'reviewer_artifact_context', None)
    if context is None:
        return None
    if type(context) is not ReviewerArtifactContext:
        raise RuntimeError('Reviewer artifact context is misconfigured')
    return context
