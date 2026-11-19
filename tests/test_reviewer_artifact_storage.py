"""Private storage checks: synthetic bytes and disposable private directories."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import reviewer_artifact_storage as storage
from tests.test_secure_word_uploads import doc_bytes, docx_bytes


class ArtifactStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.path.realpath(tempfile.gettempdir()))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'private'
        self.root.mkdir(mode=0o700)
        self.store = storage.ArtifactStorage(self.root)
        self.addCleanup(self.store.close)

    def test_supported_formats_metadata_and_permissions(self):
        for fmt, content in [('pdf',b'%PDF-synthetic'), ('docx',docx_bytes()), ('doc',doc_bytes()), ('txt','Synthetic résumé'.encode())]:
            with self.subTest(fmt=fmt):
                meta = self.store.publish(content, fmt)
                self.assertEqual(meta.format,fmt); self.assertEqual(meta.byte_size,len(content))
                self.assertEqual(meta.sha256,hashlib.sha256(content).hexdigest())
                self.assertEqual(self.store.read_verified(meta),content)
                self.assertEqual((self.root/meta.storage_id).stat().st_mode & 0o777,0o400)
                self.assertRegex(meta.storage_id,r'^[0-9a-f]{32}$')

    def test_invalid_malformed_and_bounds(self):
        for fmt, content in [('exe',b'x'),('pdf',b'not pdf'),('doc',b'bad'),('docx',b'%PDF-x'),('txt',b'\xff'),('txt',b'')]:
            with self.subTest(fmt=fmt), self.assertRaises(storage.StorageError): self.store.publish(content,fmt)
        self.assertEqual(self.store.publish(b'x'*storage.MAX_MANUSCRIPT_FILE_SIZE,'txt').byte_size,storage.MAX_MANUSCRIPT_FILE_SIZE)
        with self.assertRaises(storage.StorageError): self.store.publish(b'x'*(storage.MAX_MANUSCRIPT_FILE_SIZE+1),'txt')

    def test_mismatch_replacement_missing_and_no_fallback(self):
        source = Path(self.temp.name)/'source.txt'; source.write_bytes(b'synthetic source')
        meta = self.store.publish(b'synthetic artifact','txt')
        for wrong in (replace(meta,sha256='a'*64), replace(meta,byte_size=meta.byte_size+1), replace(meta,format='pdf')):
            with self.assertRaises(storage.StorageError): self.store.read_verified(wrong)
        path = self.root/meta.storage_id; path.chmod(0o600); path.write_bytes(b'X'*meta.byte_size)
        with self.assertRaises(storage.StorageError): self.store.read_verified(meta)
        path.unlink()
        with self.assertRaises(storage.StorageError): self.store.read_verified(meta)
        self.assertEqual(source.read_bytes(),b'synthetic source')

    def test_source_descriptor_read_and_corruption(self):
        source = Path(self.temp.name)/'source.txt'; content=b'synthetic source'; source.write_bytes(content)
        fd = os.open(source,os.O_RDONLY)
        try:
            digest=hashlib.sha256(content).hexdigest()
            self.assertEqual(storage.inspect_source_fd(fd,'txt'),(digest,len(content),content))
            self.assertEqual(storage.read_verified_fd(fd,digest,len(content),'txt'),content)
            with self.assertRaises(storage.StorageError): storage.read_verified_fd(fd,'0'*64,len(content),'txt')
            source.write_bytes(b'synthetic change')
            with self.assertRaises(storage.StorageError): storage.read_verified_fd(fd,digest,len(content),'txt')
        finally: os.close(fd)
        self.assertEqual(source.read_bytes(),b'synthetic change')

    def test_traversal_symlinks_and_public_roots_rejected(self):
        meta = self.store.publish(b'synthetic','txt')
        for candidate in ('../source','/etc/passwd',meta.storage_id+'/x','f'*31,'A'*32):
            with self.subTest(candidate=candidate), self.assertRaises(storage.StorageError): self.store.read_verified(replace(meta,storage_id=candidate))
        target=Path(self.temp.name)/'target'; target.write_bytes(b'synthetic')
        (self.root/('f'*32)).symlink_to(target)
        with self.assertRaises(storage.StorageError): self.store.read_verified(replace(meta,storage_id='f'*32))
        root_link=Path(self.temp.name)/'link'; root_link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(storage.StorageError): storage.ArtifactStorage(root_link)
        public=Path(self.temp.name)/'public'; public.mkdir(mode=0o700)
        with self.assertRaises(storage.StorageError): storage.ArtifactStorage(public)
        with self.assertRaises(storage.StorageError): storage.ArtifactStorage(self.root/'..'/'private')

    def test_directory_permissions_must_be_private(self):
        self.root.chmod(0o755)
        with self.assertRaises(storage.StorageError): storage.ArtifactStorage(self.root)
        self.root.chmod(0o700)

    def test_duplicate_storage_identifier_never_overwrites(self):
        ids=[SimpleNamespace(hex='a'*32),SimpleNamespace(hex='b'*32),SimpleNamespace(hex='a'*32),SimpleNamespace(hex='c'*32)]
        with patch.object(storage,'uuid4',side_effect=ids):
            first=self.store.publish(b'original','txt')
            with self.assertRaises(storage.StorageError): self.store.publish(b'different','txt')
        self.assertEqual(self.store.read_verified(first),b'original')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),[first.storage_id])

    def test_interrupted_staging_and_publication_failure(self):
        with patch.object(storage.os,'write',side_effect=OSError('synthetic')):
            with self.assertRaises(storage.StorageError): self.store.publish(b'synthetic','txt')
        self.assertEqual(list(self.root.iterdir()),[])
        with patch.object(storage.os,'link',side_effect=OSError('synthetic')):
            with self.assertRaises(storage.PublicationOutcomeUnknown): self.store.publish(b'synthetic','txt')
        self.assertEqual(list(self.root.iterdir()),[])

    def test_uncertain_published_file_is_preserved(self):
        real_link = os.link
        def link_then_error(*args, **kwargs):
            real_link(*args, **kwargs); raise OSError('synthetic acknowledgement failure')
        with patch.object(storage.os,'link',side_effect=link_then_error):
            with self.assertRaises(storage.PublicationOutcomeUnknown) as result: self.store.publish(b'synthetic','txt')
        saved=self.root/result.exception.storage_id
        self.assertTrue(saved.is_file()); self.assertEqual(saved.read_bytes(),b'synthetic')

    def test_verified_snapshot_survives_path_replacement_after_open(self):
        content=b'synthetic'; meta=self.store.publish(content,'txt')
        path=self.root/meta.storage_id; replacement=self.root/'replacement'; replacement.write_bytes(b'modified!')
        original_pread=os.pread; invoked=[]
        def replace_on_read(fd,size,offset):
            if not invoked: invoked.append(True); os.replace(replacement,path)
            return original_pread(fd,size,offset)
        with patch.object(storage.os,'pread',side_effect=replace_on_read):
            self.assertEqual(self.store.read_verified(meta),content)
        with self.assertRaises(storage.StorageError): self.store.read_verified(meta)

    def test_close_and_non_regular_file(self):
        meta=self.store.publish(b'synthetic','txt')
        fifo=self.root/('f'*32); os.mkfifo(fifo,0o600)
        with self.assertRaises(storage.StorageError): self.store.read_verified(replace(meta,storage_id='f'*32))
        self.store.close()
        with self.assertRaises(storage.StorageError): self.store.read_verified(meta)


if __name__ == '__main__': unittest.main()
