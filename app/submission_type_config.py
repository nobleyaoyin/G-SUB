"""General-purpose defaults; deployments may configure their own journal list."""
import os

DEFAULT_SUBMISSION_TYPES = (
    "Original Research Article",
    "Review Article",
    "Short Communication",
    "Case Report",
    "Methods / Technical Note",
    "Perspective / Commentary",
    "Letter to the Editor",
)


def available_submission_types():
    configured = os.environ.get("GSUB_SUBMISSION_TYPES")
    if configured is None:
        return list(DEFAULT_SUBMISSION_TYPES)
    return list(dict.fromkeys(item.strip() for item in configured.split(",") if item.strip()))
