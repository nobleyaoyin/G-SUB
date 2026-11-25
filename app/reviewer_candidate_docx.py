"""Conservative metadata preparation for an EIC-private DOCX candidate.

This is not content anonymization. Candidate text, headers and references can
still identify people. The existing human verification and approval gates are
mandatory, and no reviewer access is granted by this function.
"""
from io import BytesIO
import zipfile
from xml.etree import ElementTree as ET
from fastapi import HTTPException
from app.routers.manuscripts import validate_manuscript_file, MAX_MANUSCRIPT_FILE_SIZE


class PreparationError(ValueError):
    pass


_EMPTY_PROPERTIES = {
    'docProps/core.xml': b'<?xml version="1.0" encoding="UTF-8"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>',
    'docProps/app.xml': b'<?xml version="1.0" encoding="UTF-8"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"/>',
    'docProps/custom.xml': b'<?xml version="1.0" encoding="UTF-8"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"/>',
}
_FORBIDDEN_PART_PREFIXES = ('word/comments', 'word/people', 'word/embeddings/', 'word/media/', 'customxml/', 'docprops/thumbnail')
_REVISION_TAGS = frozenset({'ins','del','moveFrom','moveTo','commentRangeStart','commentRangeEnd','commentReference','delText','trackRevisions'})


def prepare_docx_metadata(content: bytes) -> bytes:
    """Prepare separate bytes; reject unhandled identity-bearing structures."""
    try:
        validate_manuscript_file('candidate.docx', content)
        output = BytesIO()
        with zipfile.ZipFile(BytesIO(content)) as source, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                name = item.filename
                folded = name.casefold()
                if folded.startswith(_FORBIDDEN_PART_PREFIXES) or folded.endswith(('vbaproject.bin', '.ole')):
                    raise PreparationError('Unsupported embedded or review content requires manual preparation')
                if folded.startswith('docprops/') and name not in _EMPTY_PROPERTIES:
                    raise PreparationError('Unsupported document property requires manual preparation')
                data = source.read(item)
                if name in _EMPTY_PROPERTIES:
                    data = _EMPTY_PROPERTIES[name]
                elif folded.endswith(('.xml', '.rels')):
                    if b'\x00' in data or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                        raise PreparationError('Unsupported XML requires manual preparation')
                    node = ET.fromstring(data)
                    for element in node.iter():
                        local = element.tag.rsplit('}', 1)[-1] if isinstance(element.tag, str) else ''
                        if local in _REVISION_TAGS or any(k.rsplit('}', 1)[-1].casefold() in {'author','initials','lastmodifiedby'} for k in element.attrib):
                            raise PreparationError('Tracked changes or author metadata require manual preparation')
                        if any(k.rsplit('}', 1)[-1] == 'TargetMode' and v.casefold() == 'external' for k,v in element.attrib.items()):
                            raise PreparationError('External relationship requires manual preparation')
                target.writestr(name, data)
        result = output.getvalue()
        if len(result) > MAX_MANUSCRIPT_FILE_SIZE:
            raise PreparationError('Prepared document exceeds the size limit')
        validate_manuscript_file('prepared.docx', result)
        return result
    except PreparationError:
        raise
    except (HTTPException, zipfile.BadZipFile, ET.ParseError, OSError, ValueError, RuntimeError, NotImplementedError, EOFError) as error:
        raise PreparationError('DOCX preparation unavailable') from error
