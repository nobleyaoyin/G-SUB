"""Safe, local DOCX text extraction for advisory pre-screening."""

import io
import zipfile
import xml.etree.ElementTree as ET

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_ENTRY_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 2048
MAX_EXTRACTED_CHARACTERS = 1_000_000

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"

DOCUMENT_XML = "word/document.xml"
CONTENT_TYPES_XML = "[Content_Types].xml"
DOCUMENT_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.document.main+xml"
)


def extract_docx_text(content: bytes) -> str:
    """Extract body paragraph and table text without external resources."""
    if not isinstance(content, bytes):
        raise TypeError("Document content must be bytes")
    if not content:
        raise ValueError("Document is empty")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("Document exceeds the 10 MB limit")

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}

            if len(entries) > MAX_ENTRIES or len(names) != len(entries):
                raise ValueError("Unsafe DOCX container")

            total_size = 0
            for entry in entries:
                total_size += entry.file_size

                if total_size > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("Unsafe DOCX container")

                if (
                    entry.file_size > MAX_ENTRY_BYTES
                    or entry.flag_bits & 1
                    or entry.filename.startswith(("/", "\\"))
                    or "\\" in entry.filename
                    or ".." in entry.filename.split("/")
                ):
                    raise ValueError("Unsafe DOCX container")

            if DOCUMENT_XML not in names or CONTENT_TYPES_XML not in names:
                raise ValueError("Missing DOCX structure")

            # Verify CRC integrity of every ZIP entry before extraction.
            if archive.testzip() is not None:
                raise ValueError("Corrupted DOCX archive")

            # Read only the two XML parts needed for extraction.
            types_data = archive.read(CONTENT_TYPES_XML)
            document_data = archive.read(DOCUMENT_XML)

            for data in (types_data, document_data):
                if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                    raise ValueError("Unsafe DOCX XML")

            types_root = ET.fromstring(types_data)
            document_root = ET.fromstring(document_data)

            if types_root.tag != CT + "Types":
                raise ValueError("Invalid DOCX content types")
            if document_root.tag != W + "document":
                raise ValueError("Invalid DOCX document XML")

            valid_type = any(
                part.tag == CT + "Override"
                and part.get("PartName") == "/word/document.xml"
                and part.get("ContentType") == DOCUMENT_CONTENT_TYPE
                for part in types_root
            )
            if not valid_type:
                raise ValueError("Missing Word document content type")

            body = document_root.find(W + "body")
            if body is None:
                raise ValueError("Missing DOCX body")

            paragraphs = []
            total_characters = 0

            for paragraph in body.iter(W + "p"):
                # Only direct Word text nodes; ignore drawings and field instructions.
                fragments = []
                for run in paragraph.findall(W + "r"):
                    properties = run.find(W + "rPr")

                    if properties is not None:
                        hidden = properties.find(W + "vanish")

                        if hidden is not None:
                            value = hidden.get(W + "val", "true")

                            if value.lower() not in (
                                "false", "0", "off"
                            ):
                                continue

                    for node in run.findall(W + "t"):
                        fragments.append(node.text or "")
                line = "".join(fragments)

                total_characters += len(line)
                if total_characters > MAX_EXTRACTED_CHARACTERS:
                    raise ValueError("Extracted text exceeds safety limit")

                if line.strip():
                    paragraphs.append(line)

            text = "\n".join(paragraphs)

            if not text.strip():
                raise ValueError("DOCX contains no extractable body text")

            return text

    except (
        zipfile.BadZipFile,
        RuntimeError,
        ET.ParseError,
        NotImplementedError,
        OSError,
        EOFError,
    ) as exc:
        raise ValueError("Invalid DOCX file") from exc
