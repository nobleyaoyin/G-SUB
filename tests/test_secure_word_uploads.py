"""Bounded, synthetic format validation; never opens project data."""
import io
import struct
import unittest
import zipfile
from unittest.mock import patch

from fastapi import HTTPException
from app.routers.manuscripts import validate_manuscript_file
from app import models
import app.routers.eic as eic
import app.routers.formatting as formatting
from tests import test_final_workflow


def docx_bytes(extra=b''):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')
        if extra: z.writestr('word/extra', extra)
    return data.getvalue()


def doc_bytes():
    """Small synthetic CFB with Word and table streams, not an actual manuscript."""
    free, end, fat = 0xffffffff, 0xfffffffe, 0xfffffffd
    h = bytearray(512)
    h[:8] = bytes.fromhex('d0cf11e0a1b11ae1')
    struct.pack_into('<HHHHH', h, 24, 0x3e, 3, 0xfffe, 9, 6)
    struct.pack_into('<IIIIIIIII', h, 40, 0, 1, 0, 0, 4096, end, 0, end, 0)
    struct.pack_into('<109I', h, 76, 1, *([free] * 108))
    def entry(name, kind, left, right, child, start, size):
        x = bytearray(128); n = (name + '\0').encode('utf-16le'); x[:len(n)] = n
        struct.pack_into('<HBBIII', x, 64, len(n), kind, 1, left, right, child)
        struct.pack_into('<IQ', x, 116, start, size)
        return x
    directory = b''.join([entry('Root Entry', 5, free, free, 1, end, 0),
        entry('WordDocument', 2, free, 2, free, 2, 4096),
        entry('0Table', 2, free, free, free, 10, 4096), bytes(128)])
    sectors = [end, fat] + list(range(3, 10)) + [end] + list(range(11, 18)) + [end]
    allocation = struct.pack('<128I', *(sectors + [free] * (128 - len(sectors))))
    word = bytearray(4096); word[:2] = b'\xec\xa5'
    return bytes(h) + directory + allocation + bytes(word) + bytes(4096)


class SecureWordTests(unittest.TestCase):
    def test_valid_word_containers_and_existing_pdf(self):
        for name, data in [('a.docx', docx_bytes()), ('a.doc', doc_bytes()), ('a.pdf', b'%PDF-synthetic'), ('a.txt', b'example')]:
            with self.subTest(name=name): self.assertEqual(validate_manuscript_file(name, data)[0], '.' + name.rsplit('.', 1)[1])

    def test_malformed_and_mismatched(self):
        for name, data in [('a.doc', bytes.fromhex('d0cf11e0a1b11ae1') + b'x'), ('a.docx', b'%PDF-fake'), ('a.pdf', b'hello'), ('a.txt', b'\xff')]:
            with self.subTest(name=name), self.assertRaises(HTTPException): validate_manuscript_file(name, data)

    def test_bounded_zip_and_bad_xml(self):
        with self.assertRaises(HTTPException): validate_manuscript_file('a.docx', docx_bytes(b'x' * (17 * 1024 * 1024)))
        content = io.BytesIO()
        with zipfile.ZipFile(content, 'w') as z:
            z.writestr('[Content_Types].xml', '<!DOCTYPE Types><Types/>')
            z.writestr('word/document.xml', '<document/>')
        with self.assertRaises(HTTPException): validate_manuscript_file('a.docx', content.getvalue())

    def test_size_limit(self):
        self.assertEqual(validate_manuscript_file('a.txt', b'x' * (10 * 1024 * 1024))[0], '.txt')
        with self.assertRaises(HTTPException) as cm: validate_manuscript_file('a.txt', b'x' * (10 * 1024 * 1024 + 1))
        self.assertEqual(cm.exception.status_code, 413)

    def test_final_word_approval_and_formatter_source(self):
        for extension, data, mime in [('docx', docx_bytes(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'), ('doc', doc_bytes(), 'application/msword')]:
            with self.subTest(extension=extension):
                f = test_final_workflow.FinalWorkflowTest('test_invitation_replacement_corrections_and_confirmation')
                f.setUp()
                try:
                    with patch.object(eic, 'BASE_DIR', f.root), patch.object(formatting, 'BASE_DIR', f.root):
                        agreement = f.reach_agreement(); f.current = f.author
                        self.assertEqual(f.client.post(f"/agreements/{agreement['agreement_id']}/respond", json={'decision':'accept', 'agreement_version':agreement['agreement_version']}).status_code, 200)
                        invitation = f.invite(f.editor).json()['invitation_id']
                        self.assertEqual(f.respond(f.editor, invitation, 'accept').status_code, 200)
                        f.current = f.editor
                        res = f.client.post(f'/eic/final-editing/{f.mid}/submit', data={'comments':'Edited'}, files={'file':('source.' + extension, data, mime)})
                        self.assertEqual(res.status_code, 201, res.text); sid = res.json()['submission_id']
                        for who, role in ((f.chief, 'eic'), (f.author, 'author')):
                            self.assertEqual(f.review(who, sid, role, 'approve').status_code, 200)
                        f.current = f.author
                        res = f.client.get(f'/eic/final-editing/submissions/{sid}/download')
                        self.assertEqual(res.content, data); self.assertTrue(res.headers['content-type'].startswith(mime)); self.assertIn('.' + extension, res.headers['content-disposition'])
                        formatter = models.User(name='Formatter', email='formatter@example.test', password_hash='x', role='formatter')
                        f.db.add(formatter); f.db.commit(); f.current = f.chief
                        inv = f.client.post('/formatting/invite', json={'manuscript_id': f.mid, 'formatter_id': formatter.user_id}).json()['invitation_id']
                        f.current = formatter
                        self.assertEqual(f.client.post(f'/formatting/invitations/{inv}/respond', json={'decision':'accept'}).status_code, 200)
                        res = f.client.get(f'/formatting/invitations/{inv}/input')
                        self.assertEqual(res.content, data); self.assertTrue(res.headers['content-type'].startswith(mime))
                finally:
                    f.tearDown()
