"""Isolated tests for local advisory manuscript pre-screening."""

import unittest

from app.ai_prescreening import analyze_txt, MAX_DOCUMENT_BYTES


class AIPrescreeningTests(unittest.TestCase):

    def test_complete_document(self):
        document = b"""Example Manuscript

Abstract
This paper presents a simple experiment.

Introduction
We introduce the research problem.

Methods
We describe the experimental method.

Results
We report the results.

Conclusion
We summarize the findings.
"""
        result = analyze_txt(document)

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["advisory_only"])
        self.assertEqual(result["engine"], "local_rules_v1")
        self.assertEqual(
            set(result["sections_detected"]),
            {"abstract", "introduction", "methods", "results", "conclusion"},
        )
        self.assertEqual(result["findings"], [])

    def test_missing_methods(self):
        result = analyze_txt(
            b"Abstract\nText\nIntroduction\nText\nResults\nText\nConclusion\nText"
        )
        codes = {f["code"] for f in result["findings"]}
        self.assertIn("missing_methods", codes)

    def test_repeated_word(self):
        result = analyze_txt(b"Abstract\nThis is is an experiment.")
        codes = {f["code"] for f in result["findings"]}
        self.assertIn("repeated_word", codes)

    def test_repeated_spaces(self):
        result = analyze_txt(b"Abstract\nThis   sentence has extra spaces.")
        codes = {f["code"] for f in result["findings"]}
        self.assertIn("repeated_spaces", codes)

    def test_long_line(self):
        result = analyze_txt(b"Abstract\n" + b"A" * 121)
        codes = {f["code"] for f in result["findings"]}
        self.assertIn("long_line", codes)

    def test_leading_blank_line(self):
        result = analyze_txt(b"\nAbstract\nSome content.")
        codes = {f["code"] for f in result["findings"]}
        self.assertIn("leading_blank_line", codes)

    def test_empty_document(self):
        with self.assertRaises(ValueError):
            analyze_txt(b"")

    def test_whitespace_only(self):
        with self.assertRaises(ValueError):
            analyze_txt(b" \n\t ")

    def test_invalid_utf8(self):
        with self.assertRaises(ValueError):
            analyze_txt(b"\xff\xfe\xfa")

    def test_oversized_document(self):
        with self.assertRaises(ValueError):
            analyze_txt(b"A" * (MAX_DOCUMENT_BYTES + 1))

    def test_control_characters(self):
        with self.assertRaises(ValueError):
            analyze_txt(b"Abstract\nHello\x00World")

    def test_non_bytes_input(self):
        with self.assertRaises(TypeError):
            analyze_txt("Abstract\nText")

    def test_numbered_headings(self):
        result = analyze_txt(
            b"1 Introduction\nText\n2 Methods\nText\n3 Results\nText"
        )
        self.assertIn("introduction", result["sections_detected"])
        self.assertIn("methods", result["sections_detected"])
        self.assertIn("results", result["sections_detected"])

    def test_markdown_headings(self):
        result = analyze_txt(
            b"# Abstract\nText\n## Introduction\nText\n### Methods\nText"
        )
        self.assertIn("abstract", result["sections_detected"])
        self.assertIn("introduction", result["sections_detected"])
        self.assertIn("methods", result["sections_detected"])


    def test_cross_line_repeated_word(self):
        result = analyze_txt(
            b"Abstract\nThis is\nis an example."
        )
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("repeated_word", codes)

    def test_heading_detection_is_heuristic(self):
        result = analyze_txt(
            b"Abstract\nIntroduction\nMethods\nResults\nConclusion"
        )
        self.assertEqual(
            result["heading_detection"],
            "heuristic",
        )


    def test_analyze_docx_format(self):
        from app.ai_prescreening import analyze_docx
        from tests.test_ai_docx_parser import make_docx

        body = (
            "<w:p><w:r><w:t>Abstract</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Introduction</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Methods</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Results</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Conclusion</w:t></w:r></w:p>"
        )

        result = analyze_docx(make_docx(body))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["format"], "docx")
        self.assertEqual(len(result["sections_detected"]), 5)
        self.assertEqual(result["findings"], [])


    def test_analyze_docx_empty(self):
        from app.ai_prescreening import analyze_docx

        with self.assertRaises(ValueError):
            analyze_docx(b"")

    def test_analyze_docx_invalid_zip(self):
        from app.ai_prescreening import analyze_docx

        with self.assertRaises(ValueError):
            analyze_docx(b"not a docx file")

    def test_analyze_docx_whitespace_only(self):
        from app.ai_prescreening import analyze_docx

        with self.assertRaises(ValueError):
            analyze_docx(b"   ")


if __name__ == "__main__":
    unittest.main()
