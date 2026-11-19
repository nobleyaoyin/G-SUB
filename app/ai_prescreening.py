"""Local advisory-only manuscript pre-screening prototype."""

import re

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024

SECTIONS = {
    "abstract": r"abstract",
    "introduction": r"introduction",
    "methods": r"methods?|methodology|materials and methods",
    "results": r"results?|findings",
    "conclusion": r"conclusions?",
}

HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s+|\d+(?:\.\d+)*[.)]?\s+)?"
    r"(?P<heading>[A-Za-z][A-Za-z &-]{1,70})\s*:?\s*$",
    re.IGNORECASE,
)


def analyze_txt(content: bytes) -> dict:
    """Analyze UTF-8 TXT without network access or persistence."""
    if not isinstance(content, bytes):
        raise TypeError("Document content must be bytes")
    if not content:
        raise ValueError("Document is empty")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("Document exceeds the 10 MB limit")

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Document must be UTF-8 encoded") from exc

    if not text.strip():
        raise ValueError("Document contains no readable text")
    if any(
        ord(c) < 32 and c not in "\t\n\r" or 127 <= ord(c) <= 159
        for c in text
    ):
        raise ValueError("Unsupported control characters")

    lines = text.splitlines()
    detected = set()

    for line in lines:
        match = HEADING_RE.fullmatch(line)
        if match:
            heading = match.group("heading").strip().lower()
            for section, pattern in SECTIONS.items():
                if re.fullmatch(pattern, heading):
                    detected.add(section)

    findings = []

    def add(category, code, severity, message):
        findings.append({
            "category": category,
            "code": code,
            "severity": severity,
            "message": message,
        })

    for section in SECTIONS:
        if section not in detected:
            add("structure", f"missing_{section}", "warning",
                f"Could not identify a {section} heading.")

    if lines and not lines[0].strip():
        add("formatting", "leading_blank_line", "info",
            "The document starts with a blank line.")

    if any(len(line) > 120 for line in lines):
        add("formatting", "long_line", "info",
            "Some text lines exceed 120 characters.")

    if re.search(r" {3,}", text):
        add("formatting", "repeated_spaces", "info",
            "Repeated spaces were detected.")

    if re.search(r"\b([A-Za-z]+)\s+\1\b", text, re.IGNORECASE):
        add("language", "repeated_word", "info",
            "A consecutive repeated word was detected.")

    return {
        "status": "completed",
        "engine": "local_rules_v1",
        "advisory_only": True,
        "heading_detection": "heuristic",
        "format": "txt",
        "word_count": len(re.findall(r"\b[\w'-]+\b", text)),
        "sections_detected": sorted(detected),
        "findings": findings,
    }


def analyze_docx(content: bytes) -> dict:
    """Analyze DOCX locally using the existing advisory rules."""
    from app.ai_docx_parser import extract_docx_text

    text = extract_docx_text(content)
    result = analyze_txt(text.encode("utf-8"))
    result["format"] = "docx"

    return result
