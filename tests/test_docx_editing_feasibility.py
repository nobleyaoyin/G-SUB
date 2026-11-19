"""Synthetic package checks for the existing DOCX upload and TXT editor boundary."""
import base64
import hashlib
import io
import unittest
import zipfile
from unittest.mock import patch

from app import models
from app.routers.manuscripts import validate_manuscript_file
import app.routers.eic as eic
from tests.test_reviewer_download import ReviewerDownloadsTest


def synthetic_document():
    # Synthetic OOXML parts exercise validator boundaries, not Word rendering.
    types = b'''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/><Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>'''
    doc = b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Synthetic bold paragraph</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Synthetic table cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:r><w:drawing><wp:inline><wp:extent cx="914400" cy="914400"/><wp:docPr id="1" name="Synthetic image"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="image1.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="rId3"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="914400" cy="914400"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p><w:sectPr><w:headerReference w:type="default" r:id="rId1"/><w:footerReference w:type="default" r:id="rId2"/></w:sectPr></w:body></w:document>'''
    header = b'<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Synthetic header</w:t></w:r></w:p></w:hdr>'
    footer = b'<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Synthetic footer</w:t></w:r></w:p></w:ftr>'
    rootrels = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    rels = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/></Relationships>'
    image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aN8AAAAASUVORK5CYII=')
    data = io.BytesIO()
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:
        for name, body in {'[Content_Types].xml':types, '_rels/.rels':rootrels, 'word/document.xml':doc,
            'word/_rels/document.xml.rels':rels, 'word/header1.xml':header, 'word/footer1.xml':footer,
            'word/media/image1.png':image}.items(): archive.writestr(name,body)
    return data.getvalue()


class DocxFeasibilityTest(unittest.TestCase):
    def setUp(self):
        self.fx = ReviewerDownloadsTest('runTest'); self.fx.setUp(); self.addCleanup(self.fx.tearDown)
        self.patch = patch.object(eic,'BASE_DIR',self.fx.root); self.patch.start(); self.addCleanup(self.patch.stop)

    def test_structured_docx_is_accepted_but_online_editor_refuses_it(self):
        f = self.fx; body = synthetic_document(); digest = hashlib.sha256(body).hexdigest()
        extension, mime = validate_manuscript_file('synthetic.docx',body)
        self.assertEqual((extension,mime),('.docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document'))
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertIn(b'<w:b/>',archive.read('word/document.xml'))
            self.assertIn(b'<w:tbl>',archive.read('word/document.xml'))
            self.assertIn('word/media/image1.png',archive.namelist())
            self.assertIn('word/header1.xml',archive.namelist()); self.assertIn('word/footer1.xml',archive.namelist())
        path = f.write(f'uploads/manuscripts/{f.mid}/source.docx',body)
        f.manuscript.file_path=path; f.manuscript.status='draft'; f.db.commit(); f.current=f.author
        self.assertEqual(f.client.get(f'/manuscripts/{f.mid}/online-text').status_code,415)
        f.current=f.reviewer; self.assertEqual(f.client.get(f'/manuscripts/{f.mid}/online-text').status_code,404)
        f.current=f.editor; f.manuscript.status='initial_editing'
        previous=f.db.query(models.InitialEditingSubmission).filter_by(manuscript_id=f.mid).one()
        previous.status='editor_revision_requested'; previous.file_path=path; f.db.commit()
        self.assertEqual(f.client.get(f'/eic/manuscripts/{f.mid}/online-text/initial').status_code,415)
        self.assertEqual(hashlib.sha256((f.root/path).read_bytes()).hexdigest(),digest)
