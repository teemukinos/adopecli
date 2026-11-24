"""Local link-evidence boundaries; synthetic files are never executed."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'link_map', Path(__file__).resolve().parents[1] / 'engines/link_map.py')
link = importlib.util.module_from_spec(spec)
spec.loader.exec_module(link)


class LinkMapChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='link-map-check-')
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / 'target'
        self.toolchain = self.root / 'toolchain'
        self.target.mkdir()
        self.toolchain.mkdir()
        self.binary = self.target / 'engine'
        self.linked = self.target / 'intermediate'
        self.binary.write_bytes(b'synthetic binary bytes, never executable')
        self.linked.write_bytes(self.binary.read_bytes())
        self.archive = self.target / 'libdependency.rlib'
        self.archive.write_bytes(b'synthetic archive container, never linked')
        self.map = self.root / 'link.map'
        self.messages = self.root / 'messages.jsonl'
        self.events = [
            {'reason': 'compiler-artifact', 'package_id': 'registry+fixture#dependency@1',
             'filenames': [str(self.archive)], 'target': {'kind': ['lib']}, 'fresh': True},
            {'reason': 'compiler-artifact', 'package_id': 'path+fixture#engine@1',
             'filenames': [str(self.binary)], 'executable': str(self.binary),
             'target': {'kind': ['bin']}, 'fresh': False},
            {'reason': 'build-finished', 'success': True},
        ]
        self.map_bytes = (
            f'# Path: {self.linked}\n# Arch: arm64\n# Object files:\n'
            f'[  0] linker synthesized\n[  1] {self.archive}(dependency.o)\n'
            '# Sections:\n# Address\tSize    \tSegment\tSection\n'
            '0x1000\t0x20\t__TEXT\t__text\n'
            '# Symbols:\n# Address\tSize    \tFile  Name\n'
            '0x1000\t0x10\t[  1] live_symbol\n'
            '# Dead Stripped Symbols:\n#        \tSize    \tFile  Name\n'
            '<<dead>>\t0x10\t[  1] dead_symbol\n').encode()
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        self.map.write_bytes(self.map_bytes)
        self.messages.write_text(''.join(json.dumps(x) + '\n' for x in self.events))

    def collect(self):
        return link.collect(self.map, self.messages, self.binary, self.target, self.toolchain)

    def test_exact_binary_archive_and_event_bindings(self):
        result = self.collect()
        self.assertEqual(result['binary']['sha256'], link.digest(self.binary))
        self.assertEqual(result['archives'][0]['sha256'], link.digest(self.archive))
        self.assertEqual(result['summary']['cargo_packages_with_live_archive_symbols'], 1)
        self.assertEqual(result['summary']['dead_symbol_records'], 1)
        self.assertEqual(result['packages_without_mapped_archive_members'], ['path+fixture#engine@1'])
        self.assertFalse(result['binary_linkage_determined'])
        self.assertFalse(result['redistribution_approved'])

    def test_literal_symbol_bytes_are_not_utf8_or_headers(self):
        self.map_bytes = self.map_bytes.replace(b'live_symbol', b'literal string: \xc0\x01# Path: private')
        self.save()
        self.assertEqual(self.collect()['summary']['live_symbol_records'], 1)

    def test_mismatched_linker_output_refused(self):
        self.linked.write_bytes(b'a different binary')
        with self.assertRaisesRegex(ValueError, 'packaged binary'):
            self.collect()

    def test_ambiguous_archive_ownership_refused(self):
        self.events.insert(1, {**self.events[0], 'package_id': 'another-package'})
        self.save()
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.collect()

    def test_failed_missing_or_duplicate_finish_refused(self):
        original = self.events.copy()
        for ending in ([], [{'reason': 'build-finished', 'success': False}],
                       [original[-1], original[-1]]):
            with self.subTest(ending=ending):
                self.events = original[:-1] + ending
                self.save()
                with self.assertRaises(ValueError):
                    self.collect()

    def test_fresh_or_ambiguous_final_binary_refused(self):
        original = self.events.copy()
        for events in ([original[0], {**original[1], 'fresh': True}, original[2]],
                       [original[0], original[1], original[1], original[2]]):
            self.events = events
            self.save()
            with self.assertRaises(ValueError):
                self.collect()

    def test_duplicate_object_and_unknown_symbol_index_refused(self):
        original = self.map_bytes
        for data in (original.replace(b'# Sections:', b'[  1] duplicate\n# Sections:'),
                     original.replace(b'[  1] live_symbol', b'[ 99] live_symbol')):
            self.map_bytes = data
            self.save()
            with self.assertRaises(ValueError):
                self.collect()

    def test_unknown_or_misordered_sections_refused(self):
        original = self.map_bytes
        for data in (original.replace(b'# Symbols:', b'# Unknown Symbols:'),
                     original.replace(b'# Sections:', b'# Symbols:'),
                     original.replace(b'# Arch: arm64', b'# Arch: x86_64')):
            self.map_bytes = data
            self.save()
            with self.assertRaises(ValueError):
                self.collect()

    def test_linker_path_cannot_read_outside_target(self):
        outside = self.root / 'outside'
        outside.write_bytes(self.binary.read_bytes())
        self.map_bytes = self.map_bytes.replace(str(self.linked).encode(), str(outside).encode())
        self.save()
        with self.assertRaisesRegex(ValueError, 'escapes'):
            self.collect()

    def test_archive_symlink_refused(self):
        outside = self.root / 'original'
        self.archive.rename(outside)
        self.archive.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.collect()

    def test_toolchain_archive_stays_separate_from_cargo_packages(self):
        std = self.toolchain / 'libstd.rlib'
        std.write_bytes(b'synthetic toolchain archive')
        self.map_bytes = self.map_bytes.replace(str(self.archive).encode(), str(std).encode())
        self.save()
        result = self.collect()
        self.assertEqual(result['summary']['cargo_packages_with_archive_members'], 0)
        self.assertEqual(result['objects'][1]['kind'], 'toolchain_archive_member')
        self.assertEqual(result['archives'][0]['sha256'], link.digest(std))

    def test_unknown_external_archive_remains_unresolved_and_unread(self):
        outside = self.root / 'not-retained.rlib'
        self.map_bytes = self.map_bytes.replace(str(self.archive).encode(), str(outside).encode())
        self.save()
        result = self.collect()
        self.assertEqual(result['objects'][1]['kind'], 'unresolved_archive_member')
        self.assertEqual(result['archives'], [])
        self.assertFalse(result['binary_linkage_determined'])

    def test_oversized_map_and_line_refused(self):
        saved = link.MAX_BYTES, link.MAX_LINE
        try:
            link.MAX_BYTES = 1
            with self.assertRaisesRegex(ValueError, 'byte limit'):
                self.collect()
            link.MAX_BYTES, link.MAX_LINE = saved[0], 4
            with self.assertRaisesRegex(ValueError, 'line exceeds'):
                self.collect()
        finally:
            link.MAX_BYTES, link.MAX_LINE = saved

    def test_final_target_options_and_unsupported_hosts(self):
        self.assertEqual(link.rustc_options('aarch64-apple-darwin', self.root / 'space name/map'),
                         ['--', '-C', 'link-arg=-Wl,-map,' + str(self.root / 'space name/map')])
        for host, path in [('x86_64-unknown-linux-gnu', self.map),
                           ('aarch64-apple-darwin', self.root / 'comma,name/map')]:
            with self.assertRaises(ValueError):
                link.rustc_options(host, path)


if __name__ == '__main__':
    unittest.main()
