"""Local request-boundary regressions for publication artwork replacement."""
from pathlib import Path
import copy
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_runtime import layout


class LayoutReplacementRequests(unittest.TestCase):
    def setUp(self):
        self.edit = {'name': 'cover', 'action': 'replace_image', 'asset': 'a' * 32,
                     'expected_sha256': 'b' * 64, 'fit': 'contain'}

    def validate(self, edit):
        layout.validate('layout.edit', {'edits': [edit]}, 'source')

    def test_every_fitting_mode_keeps_one_project_asset_input(self):
        for fit in ('contain', 'cover', 'stretch'):
            edit = {**self.edit, 'fit': fit}
            self.validate(edit)
            self.assertEqual(layout.assets('layout.edit', {'edits': [edit]}),
                             {'a' * 32: 'assets/' + 'a' * 32 + '.image'})

    def test_all_preconditions_are_required(self):
        for key in self.edit:
            edit = dict(self.edit); del edit[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.validate(edit)

    def test_no_paths_unknown_fields_or_ambiguous_hashes(self):
        for key, values in {'asset': ['../image', '/tmp/image', 1, None],
                            'expected_sha256': ['B' * 64, 'b' * 63, None, 1],
                            'fit': ['auto', [], None]}.items():
            for value in values:
                with self.subTest(field=key, value=value), self.assertRaises(ValueError):
                    self.validate({**self.edit, key: value})
        with self.assertRaises(ValueError):
            self.validate({**self.edit, 'path': '/tmp/image'})

    def test_duplicate_targets_are_refused_before_materialization(self):
        with self.assertRaises(ValueError):
            layout.validate('layout.edit', {'edits': [self.edit, copy.deepcopy(self.edit)]}, 'source')

    def test_text_only_edits_import_no_assets(self):
        params = {'edits': [{'name': 'heading', 'action': 'move', 'dx': 0, 'dy': 2}]}
        layout.validate('layout.edit', params, 'source')
        self.assertEqual(layout.assets('layout.edit', params), {})

    def test_native_options_that_placement_would_reset_are_refused(self):
        frame = {'shape': 'rectangle', 'path': {'subpaths': [{'closed': True,
                 'anchors': [{'p': p} for p in ([0, 0], [240, 0], [240, 120], [0, 120])]}]},
                 'content': {'type': 'graphic', 'asset': 1, 'size': [240, 120],
                             'xf': [1, 0, 0, 1, 0, 0], 'autoFit': 'none',
                             'fitAlign': 4, 'crop': [0, 0, 0, 0]}}
        for field, value in [('clip', {}), ('wrap', {}), ('fill', {}), ('layerOptions', {}),
                             ('autoFit', 'fitProportionally'), ('fitAlign', 0),
                             ('crop', [1, 0, 0, 0])]:
            changed = copy.deepcopy(frame); changed['content'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                layout.replacement_content(changed, 2, [120, 120], 'contain')
        changed = copy.deepcopy(frame)
        changed['path']['subpaths'][0]['anchors'][0]['out'] = [40, 20]
        with self.assertRaises(ValueError):
            layout.replacement_content(changed, 2, [120, 120], 'contain')


if __name__ == '__main__':
    unittest.main()
