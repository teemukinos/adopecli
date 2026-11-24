"""Regression checks for exact, bounded Slides text-color revisions."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_runtime import slides_recipes, slides_revision, slides_source


class ColorRevision(unittest.TestCase):
    def setUp(self):
        result = slides_recipes.compile_recipe({'recipe': 'production_proposal', 'version': 1,
            'title': 'Material study', 'sections': [{'heading': 'Direction', 'paragraphs': ['Keep the camera fixed.']}]})
        self.document = result['document']
        self.path = result['selectors']['sections'][0]['heading']['runs'][0]
        self.data = result['data']

    def revise(self, value, *, expected=None):
        before = slides_revision.locate(self.document, self.path)['props']
        change = {'kind': 'run.properties', 'path': self.path,
                  'expected': copy.deepcopy(before) if expected is None else expected, 'set': {'fill': value}}
        return slides_revision.revise_bytes(self.data, slides_source.sha(self.data), [change])

    def test_color_changes_only_selected_fill_and_survives_replay(self):
        fill = slides_recipes.solid('#A44A32')
        changed = self.revise(fill)
        predicted = copy.deepcopy(self.document)
        slides_revision.locate(predicted, self.path)['props']['fill'] = fill
        self.assertEqual(changed['document'], predicted)
        self.assertEqual(json.loads(self.data), self.document)
        self.assertEqual(slides_revision.revise_bytes(self.data, slides_source.sha(self.data), changed['edits'])['data'], changed['data'])

    def test_clear_and_no_fill_have_distinct_exact_values(self):
        for value in (None, {'kind': 'none'}):
            with self.subTest(value=value):
                changed = self.revise(value)
                self.assertEqual(slides_revision.locate(changed['document'], self.path)['props']['fill'], value)

    def test_invalid_colors_and_unqualified_fills_are_refused_atomically(self):
        solid = slides_recipes.solid('#A44A32')
        cases = [{'kind': 'gradient'}, {'kind': 'picture', 'path': '/tmp/unowned'},
                 {'kind': 'none', 'color': solid['color']}, {**solid, 'extra': True},
                 {'kind': 'solid', 'color': {'base': {'kind': 'scheme', 'value': 'accent1'}}}]
        for channel in (True, -1, 256, 12.5):
            invalid = copy.deepcopy(solid); invalid['color']['base']['rgb']['r'] = channel; cases.append(invalid)
        for value in cases:
            with self.subTest(value=value):
                original = copy.deepcopy(value)
                with self.assertRaises(ValueError): self.revise(value)
                self.assertEqual(value, original)
                self.assertEqual(json.loads(self.data), self.document)

    def test_stale_style_cannot_recolor_a_new_revision(self):
        old = copy.deepcopy(slides_revision.locate(self.document, self.path)['props'])
        old['bold'] = not old['bold']
        with self.assertRaisesRegex(ValueError, 'expectation'):
            self.revise(slides_recipes.solid('#A44A32'), expected=old)


if __name__ == '__main__':
    unittest.main()
