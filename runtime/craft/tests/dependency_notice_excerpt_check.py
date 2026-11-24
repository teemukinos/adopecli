"""Local boundary checks for checksum-pinned source notice excerpts.

The Cargo events and package are synthetic; no compiler, upstream source or
network access is required. Actual archive/build evidence is recorded separately.
"""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'dependency_notices', Path(__file__).resolve().parents[1] / 'engines/dependency_notices.py')
notices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notices)


class SourceNoticeChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='source-notice-check-')
        self.root = Path(self.temporary.name).resolve()
        self.saved_pins = copy.deepcopy(notices.REGISTRY_SOURCE_NOTICES)
        self.source = self.root / 'source'
        self.fonts = self.root / 'fonts'
        self.cargo = self.root / 'cargo'
        for p in (self.source, self.fonts, self.cargo):
            p.mkdir()
        self.source.joinpath('Cargo.toml').write_text(
            '[package]\nname="fixture-engine"\nversion="0.1.0"\nlicense="MIT"\n')
        self.source.joinpath('LICENSE').write_text('Synthetic engine notice, not a license grant.\n')
        self.header = b'/* Synthetic fixture attribution and terms.\r\n Keep these bytes. */'
        self.member = self.header + b'\n\npub fn fixture() {}\n'
        self.manifest = b'[package]\nname="fixture-dependency"\nversion="1.0.0"\nlicense="MIT"\n'
        self.archive = self.cargo / 'registry/cache/example-index/fixture-dependency-1.0.0.crate'
        self.archive.parent.mkdir(parents=True)
        self.registry_manifest = self.cargo / 'registry/src/example-index/fixture-dependency-1.0.0/Cargo.toml'
        self.registry_manifest.parent.mkdir(parents=True)
        self.registry_manifest.write_bytes(self.manifest)
        self.destination = 'SOURCE-NOTICES/src/lib.rs.header.txt'
        self.pin = {'source_path': 'src/lib.rs', 'source_bytes': len(self.member),
                    'source_sha256': notices.sha(self.member), 'offset': 0,
                    'bytes': len(self.header), 'sha256': notices.sha(self.header)}
        self.package_archive()
        self.messages = self.root / 'messages.jsonl'
        self.messages.write_text(''.join(json.dumps(x) + '\n' for x in [
            {'reason': 'compiler-artifact', 'package_id': 'path+' + self.source.as_uri() + '#fixture-engine@0.1.0',
             'manifest_path': str(self.source / 'Cargo.toml'), 'features': [],
             'target': {'name': 'fixture-engine', 'kind': ['bin']}, 'executable': str(self.root / 'never-executed')},
            {'reason': 'compiler-artifact', 'package_id': 'registry+https://github.com/rust-lang/crates.io-index#fixture-dependency@1.0.0',
             'manifest_path': str(self.registry_manifest), 'features': [],
             'target': {'name': 'fixture_dependency', 'kind': ['lib']}, 'executable': None},
            {'reason': 'build-finished', 'success': True}]))
        self.output = self.root / 'pack/notices/dependencies'

    def tearDown(self):
        notices.REGISTRY_SOURCE_NOTICES.clear()
        notices.REGISTRY_SOURCE_NOTICES.update(self.saved_pins)
        self.temporary.cleanup()

    def package_archive(self, *, link=False, extra=None):
        with tarfile.open(self.archive, 'w:gz') as archive:
            for name, data in {'Cargo.toml': self.manifest, 'src/lib.rs': self.member, **(extra or {})}.items():
                entry = tarfile.TarInfo('fixture-dependency-1.0.0/' + name)
                if link and name == 'src/lib.rs':
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = 'outside'
                    archive.addfile(entry)
                else:
                    entry.size = len(data)
                    archive.addfile(entry, io.BytesIO(data))
        checksum = notices.sha(self.archive.read_bytes())
        self.key = ('fixture-dependency', '1.0.0', checksum)
        notices.REGISTRY_SOURCE_NOTICES[self.key] = {self.destination: self.pin}
        self.source.joinpath('Cargo.lock').write_text(
            'version=4\n[[package]]\nname="fixture-engine"\nversion="0.1.0"\n'
            '[[package]]\nname="fixture-dependency"\nversion="1.0.0"\n'
            'source="registry+https://github.com/rust-lang/crates.io-index"\nchecksum="' + checksum + '"\n')

    def collect(self):
        return notices.collect(self.messages, self.source, self.fonts, self.cargo, self.output, 'fixture-engine')

    def receipt(self, report):
        self.output.joinpath('inventory.json').write_text(json.dumps(report))
        data = self.output.joinpath('inventory.json').read_bytes()
        return {'product': 'fixture-engine', 'source_lock': {'cargo_lock_sha256': report['cargo_lock_sha256']},
                'dependencies': {'inventory': 'notices/dependencies/inventory.json', 'compiler_packages': 2,
                                 'notice_collection_complete': True, 'binary_linkage_determined': False,
                                 'redistribution_approved': False},
                'files': {'notices/dependencies/inventory.json': {'bytes': len(data), 'sha256': notices.sha(data)}}}

    def registry(self, report):
        return next(x for x in report['packages'] if x['name'] == 'fixture-dependency')

    def test_exact_bytes_provenance_and_preview_gate(self):
        report = self.collect()
        self.assertTrue(report['notice_collection_complete'])
        row = self.registry(report)
        self.assertEqual(row['source_notice_excerpts'], {self.destination: self.pin})
        self.assertEqual((self.output / next(iter(row['notice_files']))).read_bytes(), self.header)
        self.assertEqual(notices.require_inventory(self.root / 'pack', self.receipt(report)), report)
        self.assertFalse(report['redistribution_approved'])
        self.assertFalse(report['binary_linkage_determined'])

    def test_no_inference_for_unpinned_archive(self):
        del notices.REGISTRY_SOURCE_NOTICES[self.key]
        report = self.collect()
        self.assertFalse(report['notice_collection_complete'])
        self.assertFalse(self.registry(report)['notice_files'])
        self.assertEqual([x['reason'] for x in report['issues']], ['notice_files_missing'])

    def test_source_pin_mismatch_refuses_before_output(self):
        self.pin['source_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'exact source pin'):
            self.collect()
        self.assertFalse(self.output.exists())

    def test_excerpt_pin_mismatch_refuses(self):
        self.pin['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'exact byte pin'):
            self.collect()

    def test_out_of_bounds_and_boolean_offsets_refuse(self):
        for offset in (-1, len(self.member), True):
            with self.subTest(offset=offset):
                self.pin['offset'] = offset
                with self.assertRaisesRegex(ValueError, 'outside its pinned member'):
                    self.collect()

    def test_source_link_and_destination_collision_refuse(self):
        self.package_archive(link=True)
        with self.assertRaisesRegex(ValueError, 'bounded regular archive member'):
            self.collect()
        self.package_archive(extra={self.destination: b'Collision'})
        with self.assertRaisesRegex(ValueError, 'collides'):
            self.collect()

    def test_changed_archive_and_manifest_refuse(self):
        original = self.archive.read_bytes()
        self.archive.write_bytes(original + b'changed')
        with self.assertRaisesRegex(ValueError, 'archive checksum differs'):
            self.collect()
        self.archive.write_bytes(original)
        self.registry_manifest.write_bytes(self.manifest + b'\n# changed')
        with self.assertRaisesRegex(ValueError, 'compiled registry manifest differs'):
            self.collect()

    def test_rehashed_inventory_cannot_remove_or_change_provenance(self):
        report = self.collect()
        for mutation in ('remove', 'offset'):
            changed = copy.deepcopy(report)
            row = self.registry(changed)
            if mutation == 'remove':
                del row['source_notice_excerpts']
            else:
                row['source_notice_excerpts'][self.destination]['offset'] = 1
            with self.subTest(mutation=mutation):
                with self.assertRaisesRegex(ValueError, 'pinned provenance'):
                    notices.require_inventory(self.root / 'pack', self.receipt(changed))

    def test_rehashed_notice_cannot_replace_pinned_bytes(self):
        report = self.collect()
        row = self.registry(report)
        path = next(iter(row['notice_files']))
        changed = self.header.replace(b'\r\n', b'\n')
        (self.output / path).write_bytes(changed)
        row['notice_files'][path] = {'bytes': len(changed), 'sha256': notices.sha(changed)}
        with self.assertRaisesRegex(ValueError, 'exact byte pin'):
            notices.require_inventory(self.root / 'pack', self.receipt(report))

    def test_rehashed_inventory_cannot_omit_or_rename_excerpt(self):
        report = self.collect()
        changed = copy.deepcopy(report)
        row = self.registry(changed)
        path = next(iter(row['notice_files']))
        replacement = path.replace(self.destination, 'unrelated.txt')
        (self.output / replacement).write_bytes(self.header)
        row['notice_files'] = {replacement: row['notice_files'][path]}
        with self.assertRaisesRegex(ValueError, 'omits a pinned excerpt'):
            notices.require_inventory(self.root / 'pack', self.receipt(changed))


if __name__ == '__main__':
    unittest.main()
