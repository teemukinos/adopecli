"""Local regressions for PDF name binding when the engine renumbers its lists.

The PDF engine lists text and annotations sorted by position and renumbers them after
an insertion or a move. Adding a shape above an earlier one used to bind the new name
to "the last item on the page", an older object, and fail with
"duplicate PDF object target" (found in the 23 November 2026 creative showcase).
"""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_runtime.pdf import assert_untouched_records, rebind


def annotation(ident, top):
    return {'page': 1, 'id': ident, 'type': 'Square', 'rect': [340, top, 500, top + 10],
            'fill_rgb': [0.9, 0.3, 0.2], 'stroke_rgb': None, 'stroke_width': 0, 'restylable': True}


def text(words, top):
    return {'page': 1, 'type': 'text', 'text': words, 'rect': [40, top, 300, top + 20],
            'precise_rect': [40, top, 300, top + 20], 'rgb': [0, 0, 0], 'align': 'left',
            'paragraph_alignments': []}


def engine_state(texts=(), comments=()):
    """Mimic the engine: each list sorted by position, indices renumbered from 1."""
    def number(items):
        return [dict(item, index=i) for i, item in enumerate(sorted(items, key=lambda v: v['rect'][1]), 1)]
    return {'content': number(texts), 'comments': number(comments)}


class Rebind(unittest.TestCase):
    def add_annotations(self, tops):
        mapping, items, state = {}, [], engine_state()
        for n, top in enumerate(tops):
            items.append(annotation(f'a{n}', top))
            after = engine_state(comments=items)
            new = rebind(mapping, state, after, 'annotation', 1)
            mapping[f'shape{n}'] = {'type': 'annotation', 'page': 1, 'index': new['index'], 'id': new['id']}
            state = after
        return mapping, state

    def test_out_of_order_additions_bind_each_name_to_its_own_annotation(self):
        # Descending, mixed and ascending orders: the old "last item" rule failed the first two.
        for tops in ((400, 300, 200), (300, 200, 400), (200, 300, 400)):
            with self.subTest(tops=tops):
                mapping, state = self.add_annotations(tops)
                for n, top in enumerate(tops):
                    item = next(v for v in state['comments'] if v['index'] == mapping[f'shape{n}']['index'])
                    self.assertEqual((item['id'], item['rect'][1]), (f'a{n}', top))
                self.assertEqual(len({m['index'] for m in mapping.values()}), len(tops))

    def test_out_of_order_text_additions_rebind_existing_names(self):
        mapping, items, state = {}, [], engine_state()
        for n, (words, top) in enumerate((('Sunday', 500), ('Friday', 100), ('Saturday', 300))):
            items.append(text(words, top))
            after = engine_state(texts=items)
            new = rebind(mapping, state, after, 'text', 1)
            mapping[words] = {'type': 'text', 'page': 1, 'index': new['index']}
            state = after
        for words, item in mapping.items():
            self.assertEqual(next(v for v in state['content'] if v['index'] == item['index'])['text'], words)

    def test_moving_text_past_another_rebinds_both(self):
        items = [text('Title', 100), text('Footer', 700)]
        state = engine_state(texts=items)
        mapping = {'title': {'type': 'text', 'page': 1, 'index': 1}, 'footer': {'type': 'text', 'page': 1, 'index': 2}}
        moved = [text('Title', 800), items[1]]
        after = engine_state(texts=moved)
        changed = rebind(mapping, state, after, 'text', 1, changed='title')
        self.assertEqual(changed['text'], 'Title')
        self.assertEqual(mapping, {'title': {'type': 'text', 'page': 1, 'index': 2}, 'footer': {'type': 'text', 'page': 1, 'index': 1}})

    def test_unexpected_text_change_is_refused(self):
        items = [text('Title', 100), text('Footer', 700)]
        state = engine_state(texts=items)
        mapping = {'title': {'type': 'text', 'page': 1, 'index': 1}, 'footer': {'type': 'text', 'page': 1, 'index': 2}}
        broken = engine_state(texts=[text('Title', 100), text('Changed footer', 700), text('New', 400)])
        with self.assertRaises(ValueError):
            rebind(mapping, state, broken, 'text', 1)

    def test_vanished_annotation_is_refused(self):
        state = engine_state(comments=[annotation('a', 100), annotation('b', 200)])
        mapping = {'a': {'type': 'annotation', 'page': 1, 'index': 1, 'id': 'a'},
                   'b': {'type': 'annotation', 'page': 1, 'index': 2, 'id': 'b'}}
        after = engine_state(comments=[annotation('a', 100), annotation('c', 50)])
        with self.assertRaises(ValueError):
            rebind(mapping, state, after, 'annotation', 1)


class UntouchedRecords(unittest.TestCase):
    def setUp(self):
        self.before = engine_state(texts=[text('Title', 100)], comments=[annotation('a', 300)])
        self.before_mapping = {'title': {'type': 'text', 'page': 1, 'index': 1},
                               'a': {'type': 'annotation', 'page': 1, 'index': 1, 'id': 'a'}}

    def test_insertion_above_existing_records_is_not_an_untargeted_change(self):
        after = engine_state(texts=[text('Title', 100)], comments=[annotation('a', 300), annotation('b', 50)])
        mapping = copy.deepcopy(self.before_mapping)
        mapping['a']['index'] = 2
        mapping['b'] = {'type': 'annotation', 'page': 1, 'index': 1, 'id': 'b'}
        params = {'additions': [{'name': 'b'}]}
        assert_untouched_records(self.before_mapping, mapping, self.before, after, params)

    def test_untargeted_change_and_unrequested_record_are_refused(self):
        params = {'additions': []}
        changed = engine_state(texts=[text('Title', 120)], comments=[annotation('a', 300)])
        with self.assertRaises(ValueError):
            assert_untouched_records(self.before_mapping, self.before_mapping, self.before, changed, params)
        extra = engine_state(texts=[text('Title', 100)], comments=[annotation('a', 300), annotation('x', 600)])
        with self.assertRaises(ValueError):
            assert_untouched_records(self.before_mapping, self.before_mapping, self.before, extra, params)


if __name__ == '__main__':
    unittest.main()
