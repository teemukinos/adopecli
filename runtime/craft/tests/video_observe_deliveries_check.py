#!/usr/bin/env python3
"""Replay declares the same Video deliveries as native execution; no engine runs.

Native video.execute publishes every file qualify() writes under exports/,
including exports/decode-inspection.json for bounded timelines. Portable import
compares the bundle's declared deliveries with video.observe(), so observe must
declare that inspection exactly when qualify() writes it.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'craft/runtime')]
from studio_runtime import video

NATIVE = ('document.fcproj', 'objects.json', 'sequence.json', 'title-diagnostics.json', 'dependencies.json')


class FakeEngine:
    def __init__(self, root, *, executable):
        self.root = root

    def command(self, name, params):
        if name == 'file.open':
            return {'missingMedia': 0, 'migrated': False, 'schemaVersion': 17}
        Path(params['path']).write_text((self.root/'native/document.fcproj').read_text())
        return {}

    def close(self):
        pass


class VideoObserveDeliveries(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()/'replay'
        for folder in ('native', 'assets', 'exports'):
            (self.root/folder).mkdir(parents=True)
        for name in NATIVE:
            (self.root/'native'/name).write_text('{}\n')
        (self.root/'native/document.fcproj').write_text('{"schema": 17}\n')
        (self.root/'assets/clip').write_bytes(b'asset')

    def observe(self, frames, width, height):
        def qualify(root, mapping, *, executable=None):
            settings = {'width': width, 'height': height, 'frame_rate': {'num': 24, 'den': 1}}
            (root/'native/sequence.json').write_text(json.dumps({'durationFrames': frames, 'settings': settings}))
            for name in ('document.mp4', 'probe.json', 'frame-0.png'):
                (root/'exports'/name).write_bytes(b'x')
            if video.decode_inspected(frames, settings):
                (root/'exports/decode-inspection.json').write_text('{}\n')
            return {'passed': True, 'sampled_native_frames': {'0': 'digest'}}

        with patch.object(video, 'portable_native', return_value=['clip']), \
                patch.object(video, 'Engine', FakeEngine), patch.object(video, 'qualify', qualify):
            result = video.observe(self.root, executable='/fixed/dobe-video')
        exports = {row['path'] for row in result['artifacts'] if row['role'] == 'export'}
        written = {'exports/'+p.name for p in (self.root/'exports').iterdir()}
        return exports, written

    def test_bounded_timeline_declares_decode_inspection(self):
        exports, written = self.observe(24, 256, 128)
        self.assertIn('exports/decode-inspection.json', exports)
        self.assertEqual(exports, written)

    def test_long_timeline_declares_no_decode_inspection(self):
        exports, written = self.observe(601, 256, 128)
        self.assertNotIn('exports/decode-inspection.json', exports)
        self.assertEqual(exports, written)

    def test_large_picture_declares_no_decode_inspection(self):
        exports, written = self.observe(24, 7680, 4320)
        self.assertNotIn('exports/decode-inspection.json', exports)
        self.assertEqual(exports, written)


if __name__ == '__main__':
    unittest.main()
