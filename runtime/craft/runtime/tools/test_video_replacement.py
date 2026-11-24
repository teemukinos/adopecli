"""Local asset-boundary regressions for editable Video media replacement."""
from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_runtime import video
from studio_runtime.store import Conflict, NotFound, Store


class ReplacementAssets(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / 'state')
        self.project = self.store.create_project('local', 'Replacement')['id']
        self.source = self.root / 'original.bin'
        self.source.write_bytes(b'original media bytes')
        self.asset = self.store.import_asset('local', self.project, self.source)['id']
        self.destination = self.root / 'retained.bin'
        self.store.materialize_asset('local', self.project, self.asset, self.destination)

    def reuse(self, project=None):
        return self.store.materialize_asset('local', project or self.project, self.asset,
                                            self.destination, allow_existing=True)

    def test_exact_authorized_reuse_does_not_replace_the_file(self):
        before = self.destination.stat()
        self.assertEqual(self.reuse()['id'], self.asset)
        after = self.destination.stat()
        self.assertEqual((before.st_ino, before.st_mtime_ns, before.st_ctime_ns),
                         (after.st_ino, after.st_mtime_ns, after.st_ctime_ns))
        self.assertEqual(self.destination.read_bytes(), self.source.read_bytes())

    def test_existing_file_is_still_refused_by_default(self):
        with self.assertRaises(FileExistsError):
            self.store.materialize_asset('local', self.project, self.asset, self.destination)

    def test_same_size_different_content_is_not_overwritten(self):
        changed = b'x' * self.destination.stat().st_size
        self.destination.write_bytes(changed)
        with self.assertRaises(Conflict):
            self.reuse()
        self.assertEqual(self.destination.read_bytes(), changed)

    def test_matching_bytes_do_not_authorize_another_project(self):
        other = self.store.create_project('local', 'Other project')['id']
        with self.assertRaises(NotFound):
            self.reuse(other)
        self.assertEqual(self.destination.read_bytes(), self.source.read_bytes())

    def test_symlink_is_not_followed(self):
        self.destination.unlink()
        self.destination.symlink_to(self.source)
        with self.assertRaises(OSError):
            self.reuse()
        self.assertTrue(self.destination.is_symlink())
        self.assertEqual(self.source.read_bytes(), b'original media bytes')

    def test_hardlink_is_not_admitted(self):
        self.destination.unlink()
        os.link(self.source, self.destination)
        with self.assertRaises(Conflict):
            self.reuse()
        self.assertEqual(self.source.read_bytes(), b'original media bytes')

    def test_fifo_is_refused_without_waiting_for_a_writer(self):
        self.destination.unlink()
        os.mkfifo(self.destination)
        with self.assertRaises(Conflict):
            self.reuse()

    def test_missing_authoritative_blob_is_not_replaced_by_a_receipt(self):
        row = self.store.get_asset('local', self.project, self.asset)
        (self.store.blobs / row['sha256']).unlink()
        with self.assertRaises(FileNotFoundError):
            self.reuse()

    def test_replacement_schema_refuses_paths_and_duplicate_targets(self):
        for asset in ('../outside', '/tmp/outside', 123):
            with self.assertRaises(ValueError):
                video.validate('video.edit', {'edits': [{'type': 'media', 'name': 'ending', 'asset': asset}]}, 'revision')
        edit = {'type': 'media', 'name': 'ending', 'asset': self.asset}
        with self.assertRaises(ValueError):
            video.validate('video.edit', {'edits': [edit, edit]}, 'revision')


if __name__ == '__main__':
    unittest.main()
