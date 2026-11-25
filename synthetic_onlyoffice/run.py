"""Start a localhost-only, synthetic fixture; never used by the G-SUB server."""
import io
import json
import os
import zipfile

import uvicorn

from synthetic_onlyoffice.adapter import create_synthetic_app
from synthetic_onlyoffice.academic_fixture import academic_docx


def main():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Synthetic test manuscript</w:t></w:r></w:p></w:body></w:document>')
    gateway_test = os.environ.get('GSUB_SYNTHETIC_HOST_GATEWAY') == '1'
    resume_root = os.environ.get('GSUB_SYNTHETIC_RESUME_ROOT')
    source = None if resume_root else (academic_docx() if os.environ.get('GSUB_SYNTHETIC_ACADEMIC') == '1' else stream.getvalue())
    app, actors = create_synthetic_app(source,
        adapter_origin='http://host.docker.internal:8090' if gateway_test else 'http://127.0.0.1:8090',
        allow_test_host_gateway=gateway_test, resume_root=resume_root)
    # This file contains disposable credentials and must never be copied into a report.
    path = app.state.synthetic_root / 'synthetic-credentials.json'
    if not resume_root:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump({'actors': actors, 'onlyoffice_jwt_secret': app.state.synthetic_secret}, handle)
        env_path = app.state.synthetic_root / 'onlyoffice.env'
        env_fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(env_fd, 'w') as handle:
            handle.write('JWT_ENABLED=true\nJWT_SECRET=' + app.state.synthetic_secret + '\n')
    print('Synthetic credentials are stored in the private temporary fixture root:', path, flush=True)
    uvicorn.run(app, host='127.0.0.1', port=8090, log_level='warning', access_log=False)


if __name__ == '__main__':
    main()
