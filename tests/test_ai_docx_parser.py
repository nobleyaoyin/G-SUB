"""Isolated synthetic tests for DOCX text extraction."""

import io
import unittest
import warnings
import zipfile

from app.ai_docx_parser import (
    extract_docx_text,
    MAX_DOCUMENT_BYTES,
    MAX_EXTRACTED_CHARACTERS,
)

CT = (
    '<Types xmlns="http://schemas.openxmlformats.org/'
    'package/2006/content-types">'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.'
    'wordprocessingml.document.main+xml"/>'
    '</Types>'
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_docx(body, *, types=CT, extra=None):
    document = (
        f'<w:document xmlns:w="{W}">'
        f'<w:body>{body}</w:body>'
        '</w:document>'
    )
    parts = {
        "[Content_Types].xml": types,
        "word/document.xml": document,
    }
    if extra:
        parts.update(extra)

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return output.getvalue()


class AIDocxParserTests(unittest.TestCase):

    def test_paragraphs(self):
        body = (
            "<w:p><w:r><w:t>Abstract</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Example research.</w:t></w:r></w:p>"
        )
        self.assertEqual(
            extract_docx_text(make_docx(body)),
            "Abstract\nExample research.",
        )

    def test_split_runs(self):
        body = (
            "<w:p><w:r><w:t>Intro</w:t></w:r>"
            "<w:r><w:t>duction</w:t></w:r></w:p>"
        )
        self.assertEqual(
            extract_docx_text(make_docx(body)),
            "Introduction",
        )

    def test_table_cell(self):
        body = (
            "<w:tbl><w:tr><w:tc>"
            "<w:p><w:r><w:t>Table value</w:t></w:r></w:p>"
            "</w:tc></w:tr></w:tbl>"
        )
        self.assertEqual(
            extract_docx_text(make_docx(body)),
            "Table value",
        )

    def test_ignores_header_footer(self):
        body = "<w:p><w:r><w:t>Main text</w:t></w:r></w:p>"
        extra = {
            "word/header1.xml": f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>HEADER</w:t></w:r></w:p></w:hdr>',
            "word/footer1.xml": f'<w:ftr xmlns:w="{W}"><w:p><w:r><w:t>FOOTER</w:t></w:r></w:p></w:ftr>',
        }
        self.assertEqual(
            extract_docx_text(make_docx(body, extra=extra)),
            "Main text",
        )

    def test_ignores_drawing_text(self):
        body = (
            "<w:p><w:r><w:t>Main text</w:t></w:r></w:p>"
            "<w:p><w:r><w:drawing>"
            "<w:t>Hidden drawing text</w:t>"
            "</w:drawing></w:r></w:p>"
        )
        self.assertEqual(
            extract_docx_text(make_docx(body)),
            "Main text",
        )

    def test_empty_input(self):
        with self.assertRaises(ValueError):
            extract_docx_text(b"")

    def test_non_bytes_input(self):
        with self.assertRaises(TypeError):
            extract_docx_text("not bytes")

    def test_invalid_zip(self):
        with self.assertRaises(ValueError):
            extract_docx_text(b"not a zip file")

    def test_missing_document_xml(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("[Content_Types].xml", CT)
        with self.assertRaises(ValueError):
            extract_docx_text(output.getvalue())

    def test_empty_body(self):
        with self.assertRaises(ValueError):
            extract_docx_text(make_docx(""))

    def test_invalid_content_type(self):
        with self.assertRaises(ValueError):
            extract_docx_text(
                make_docx(
                    "<w:p><w:r><w:t>Text</w:t></w:r></w:p>",
                    types="<Types/>",
                )
            )

    def test_doctype_rejected(self):
        malicious = (
            '<!DOCTYPE w:document [<!ENTITY x "unsafe">]>'
            f'<w:document xmlns:w="{W}">'
            '<w:body><w:p><w:r><w:t>Text</w:t></w:r></w:p>'
            '</w:body></w:document>'
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("[Content_Types].xml", CT)
            archive.writestr("word/document.xml", malicious)
        with self.assertRaises(ValueError):
            extract_docx_text(output.getvalue())

    def test_duplicate_zip_entries(self):
        output = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr("[Content_Types].xml", CT)
                archive.writestr("word/document.xml", "first")
                archive.writestr("word/document.xml", "second")
        with self.assertRaises(ValueError):
            extract_docx_text(output.getvalue())

    def test_oversized_input(self):
        with self.assertRaises(ValueError):
            extract_docx_text(b"x" * (MAX_DOCUMENT_BYTES + 1))

    def test_extracted_text_limit(self):
        body = (
            "<w:p><w:r><w:t>"
            + "A" * (MAX_EXTRACTED_CHARACTERS + 1)
            + "</w:t></w:r></w:p>"
        )
        with self.assertRaises(ValueError):
            extract_docx_text(make_docx(body))


    def test_corrupted_unused_zip_entry(self):
        import struct

        body = "<w:p><w:r><w:t>Valid manuscript text</w:t></w:r></w:p>"

        document = (
            f'<w:document xmlns:w="{W}">'
            f'<w:body>{body}</w:body>'
            '</w:document>'
        )

        output = io.BytesIO()

        with zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_STORED
        ) as archive:
            archive.writestr("[Content_Types].xml", CT)
            archive.writestr("word/document.xml", document)
            archive.writestr(
                "word/media/unused.bin",
                b"SYNTHETIC_PAYLOAD",
            )

        damaged = bytearray(output.getvalue())

        with zipfile.ZipFile(io.BytesIO(damaged)) as archive:
            info = archive.getinfo("word/media/unused.bin")
            offset = info.header_offset

            self.assertEqual(
                damaged[offset:offset + 4],
                b"PK\x03\x04",
            )

            name_length, extra_length = struct.unpack_from(
                "<HH", damaged, offset + 26
            )

            data_offset = offset + 30 + name_length + extra_length
            damaged[data_offset] ^= 1

        with zipfile.ZipFile(io.BytesIO(damaged)) as archive:
            self.assertEqual(
                archive.testzip(),
                "word/media/unused.bin",
            )

        with self.assertRaises(ValueError):
            extract_docx_text(bytes(damaged))


    def test_hidden_run_text_is_ignored(self):
        body = (
            "<w:p>"
            "<w:r><w:t>Visible manuscript text.</w:t></w:r>"
            "<w:r>"
            "<w:rPr><w:vanish/></w:rPr>"
            "<w:t>Hidden confidential note.</w:t>"
            "</w:r>"
            "</w:p>"
        )

        self.assertEqual(
            extract_docx_text(make_docx(body)),
            "Visible manuscript text.",
        )


    def test_explicitly_visible_run_text(self):
        body = (
            "<w:p>"
            "<w:r><w:t>Normal text. </w:t></w:r>"
            '<w:r><w:rPr><w:vanish w:val="false"/></w:rPr>'
            "<w:t>Visible text.</w:t></w:r>"
            "</w:p>"
        )

        self.assertEqual(
            extract_docx_text(make_docx(body)),
            "Normal text. Visible text.",
        )


if __name__ == "__main__":
    unittest.main()
