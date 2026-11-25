"""Immutable registry of agreement templates; no approved terms supplied."""
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType


@dataclass(frozen=True)
class AgreementTemplate:
    version: str
    text: str
    approval_status: str
    approval_reference: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None

    @property
    def content_sha256(self):
        return sha256(self.text.encode('utf-8')).hexdigest()


_PROTOTYPE = AgreementTemplate(
    version='placeholder-v1',
    text=('Prototype placeholder: the actual author agreement and its terms have not '
          'been supplied. This response records a workflow test choice only and is '
          'not a legal or publication agreement.'),
    approval_status='prototype',
)
TEMPLATES = MappingProxyType({_PROTOTYPE.version: _PROTOTYPE})
AGREEMENT_VERSION = _PROTOTYPE.version
AGREEMENT_TEXT = _PROTOTYPE.text


def _has_approval_evidence(template):
    """Approval labels require nonempty attribution, date and reference."""
    return all(isinstance(value, str) and value.strip() for value in (
        template.approval_reference, template.approved_by, template.approved_at,
    ))


def issuance_template(mode):
    """Never issue unapproved content outside the supported prototype modes."""
    template = TEMPLATES[AGREEMENT_VERSION]
    if template.approval_status == 'approved' and not _has_approval_evidence(template):
        raise RuntimeError('Agreement approval evidence is required')
    if mode not in ('development', 'demo') and template.approval_status != 'approved':
        raise RuntimeError('Approved author agreement template is required')
    return template


def snapshot_status(version, text):
    """Unknown or altered historical snapshots must never be called approved."""
    template = TEMPLATES.get(version)
    if template is None or template.text != text:
        return 'unverified'
    if template.approval_status == 'approved' and not _has_approval_evidence(template):
        return 'unverified'
    if template.approval_status not in ('prototype', 'approved'):
        return 'unverified'
    return template.approval_status
