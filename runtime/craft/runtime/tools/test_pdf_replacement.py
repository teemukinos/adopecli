"""Local regressions for the runtime boundary around native PDF replacement."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_runtime.pdf import assert_replacement_record


class ReplacementScope(unittest.TestCase):
    def setUp(self):
        self.old = {'type': 'text', 'page': 1, 'index': 2, 'text': 'Draft wording',
                    'font': 'Helvetica', 'size': 24, 'rgb': [0.2, 0.2, 0.2],
                    'bold': True, 'italic': False, 'align': 'left', 'char_spacing': 0,
                    'paragraph_alignments': [], 'rect': [48, 120, 564, 148.8],
                    'precise_rect': [48, 120, 564, 148.8]}

    def test_unchanged_record_and_requested_reflow_are_allowed(self):
        assert_replacement_record(self.old, copy.deepcopy(self.old))
        changed = copy.deepcopy(self.old)
        changed.update(text='Longer replacement\nwording', rect=[48, 120, 564, 177.6],
                       precise_rect=[48, 120, 564, 177.6])
        assert_replacement_record(self.old, changed)

    def test_replacement_cannot_change_identity_style_or_placement(self):
        mutations = {'page': 2, 'index': 3, 'font': 'Courier', 'size': 30,
                     'rgb': [1, 0, 0], 'bold': False, 'italic': True, 'align': 'right',
                     'char_spacing': 2, 'precise_rect': [49, 120, 564, 148.8]}
        for field, value in mutations.items():
            with self.subTest(field=field):
                changed = copy.deepcopy(self.old)
                changed.update(text='Final wording')
                changed[field] = value
                with self.assertRaises(ValueError):
                    assert_replacement_record(self.old, changed)

    def test_unchanged_wording_does_not_permit_other_changes(self):
        for field, value in {'rect': [48, 120, 564, 200], 'paragraph_alignments': ['right']}.items():
            with self.subTest(field=field):
                changed = copy.deepcopy(self.old)
                changed[field] = value
                with self.assertRaises(ValueError):
                    assert_replacement_record(self.old, changed)

    def test_missing_or_retyped_item_is_refused(self):
        for changed in (None, dict(self.old, type='image')):
            with self.assertRaises(ValueError):
                assert_replacement_record(self.old, changed)


if __name__ == '__main__':
    unittest.main()
