"""Submission author defaults, overridable per deployment without journal claims."""
import json
import os
import re

from fastapi import HTTPException

DEFAULT_POLICY = {
    "corresponding_author_required": ["first_name", "last_name", "email", "institution", "country"],
    "coauthor_required": ["first_name", "last_name", "institution", "country"],
    "cover_letter_required": False,
    "keywords_required": True,
}
_FIELDS = {"first_name", "last_name", "email", "institution", "country", "prefix", "phone", "orcid", "department", "city", "region", "postal_code"}
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def submission_policy():
    raw = os.environ.get("GSUB_SUBMISSION_POLICY")
    if raw is None:
        return {key: list(value) if isinstance(value, list) else value for key, value in DEFAULT_POLICY.items()}
    try:
        override = json.loads(raw)
        if not isinstance(override, dict) or set(override) - set(DEFAULT_POLICY):
            raise ValueError()
        result = {**DEFAULT_POLICY, **override}
        for key in ("corresponding_author_required", "coauthor_required"):
            if not isinstance(result[key], list) or any(not isinstance(item, str) or item not in _FIELDS for item in result[key]):
                raise ValueError()
        if any(type(result[key]) is not bool for key in ("cover_letter_required", "keywords_required")):
            raise ValueError()
        return result
    except (TypeError, ValueError):
        raise HTTPException(503, "Submission requirements are unavailable.")


def validate_authors(payload, policy):
    """Return field-addressable errors; author order is explicit, never inferred."""
    errors = []
    corresponding = payload.get("corresponding_author")
    coauthors = payload.get("coauthors") or []
    position = payload.get("corresponding_author_position")
    if not isinstance(corresponding, dict):
        errors.append({"step": 7, "field": "corresponding_author", "message": "Enter the corresponding author."})
        corresponding = {}
    if not isinstance(coauthors, list):
        errors.append({"step": 8, "field": "coauthors", "message": "Check the author list."})
        coauthors = []
    if type(position) is not int or not 0 <= position <= len(coauthors):
        errors.append({"step": 7, "field": "corresponding_author_position", "message": "Choose the corresponding author's position in the author list."})
    seen_records = set()
    for person, required, step, path in [(corresponding, policy["corresponding_author_required"], 7, "corresponding_author"), *[(person, policy["coauthor_required"], 8, f"coauthors.{index}") for index, person in enumerate(coauthors)]]:
        if not isinstance(person, dict):
            errors.append({"step": step, "field": path, "message": "Check this author's details."})
            continue
        if person:
            record = json.dumps(person, sort_keys=True, ensure_ascii=False)
            if record in seen_records:
                errors.append({"step": step, "field": path, "message": "This author entry duplicates another entry."})
            seen_records.add(record)
        institutions = person.get("institutions") or []
        affiliation_fields = {"institution", "country", "department", "city", "region", "postal_code"}
        candidates = [item for item in institutions if isinstance(item, dict)] if isinstance(institutions, list) else []
        first = next((item for item in candidates if all(isinstance(item.get("name" if key == "institution" else key), str) and item.get("name" if key == "institution" else key).strip() for key in required if key in affiliation_fields)), candidates[0] if candidates else {})
        for key in required:
            value = first.get("name" if key == "institution" else key) if key in {"institution", "country", "department", "city", "region", "postal_code"} else person.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append({"step": step, "field": f"{path}.{key}", "message": f"{key.replace('_', ' ').capitalize()} is required."})
        email = person.get("email")
        if email is not None and (not isinstance(email, str) or (email.strip() and not _EMAIL.fullmatch(email.strip()))):
            errors.append({"step": step, "field": f"{path}.email", "message": "Enter a valid email address."})
    return errors
