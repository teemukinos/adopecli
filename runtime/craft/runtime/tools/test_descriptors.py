import contextlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from studio_runtime import capabilities, descriptors, mcp

RUNTIME = Path(__file__).resolve().parents[1]
PLACEHOLDER_SOURCE = '0' * 31 + '1'
KEYWORDS = {'type', 'properties', 'required', 'additionalProperties', 'items', 'minItems', 'maxItems', 'enum',
            'const', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'minLength', 'maxLength',
            'pattern', 'anyOf', 'oneOf', 'description', 'title', 'default', 'examples', '$comment'}
TYPES = {'object': lambda v: isinstance(v, dict), 'array': lambda v: isinstance(v, list),
         'string': lambda v: isinstance(v, str), 'boolean': lambda v: isinstance(v, bool),
         'null': lambda v: v is None,
         'number': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
         'integer': lambda v: isinstance(v, int) and not isinstance(v, bool) or isinstance(v, float) and v.is_integer()}


def subschemas(schema):
    yield from (schema.get('properties') or {}).values()
    if isinstance(schema.get('additionalProperties'), dict):
        yield schema['additionalProperties']
    if 'items' in schema:
        yield schema['items']
    yield from schema.get('anyOf', ())
    yield from schema.get('oneOf', ())


def unknown_keywords(schema):
    found = set(schema) - KEYWORDS
    for sub in subschemas(schema):
        found |= unknown_keywords(sub)
    return found


def matches(value, schema):
    """Minimal validator for the keyword subset above (the bundled Python has no jsonschema)."""
    kinds = schema.get('type')
    if kinds is not None and not any(TYPES[k](value) for k in ([kinds] if isinstance(kinds, str) else kinds)):
        return False
    if 'const' in schema and value != schema['const'] or 'enum' in schema and value not in schema['enum']:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get('minimum', value) or value > schema.get('maximum', value):
            return False
        if 'exclusiveMinimum' in schema and value <= schema['exclusiveMinimum']:
            return False
        if 'exclusiveMaximum' in schema and value >= schema['exclusiveMaximum']:
            return False
    if isinstance(value, str):
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', len(value)):
            return False
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            return False
    if isinstance(value, list):
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', len(value)):
            return False
        if 'items' in schema and not all(matches(v, schema['items']) for v in value):
            return False
    if isinstance(value, dict):
        properties, extra = schema.get('properties', {}), schema.get('additionalProperties', True)
        if any(name not in value for name in schema.get('required', ())):
            return False
        for name, item in value.items():
            if name in properties:
                if not matches(item, properties[name]):
                    return False
            elif extra is False or isinstance(extra, dict) and not matches(item, extra):
                return False
    if 'anyOf' in schema and not any(matches(value, sub) for sub in schema['anyOf']):
        return False
    if 'oneOf' in schema and sum(matches(value, sub) for sub in schema['oneOf']) != 1:
        return False
    return True


def native_accepts(operation, parameters, source):
    try:
        capabilities.validate(operation, parameters, source)
        return True
    except Exception:
        return False


def cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with tempfile.TemporaryDirectory() as state, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        from studio_runtime.__main__ import main
        code = main(['--state', state, *args], product='dobe')
    return code, out.getvalue(), err.getvalue()


class DescriptorTest(unittest.TestCase):
    def test_one_descriptor_per_operation_in_order(self):
        result = descriptors.describe_all()
        self.assertEqual(result['schema_version'], 1)
        self.assertEqual([d['operation'] for d in result['operations']], list(capabilities.OPERATIONS))
        self.assertEqual(list(descriptors._entries()), list(capabilities.OPERATIONS))

    def test_descriptor_shape_and_schema_keywords(self):
        for d in descriptors.describe_all()['operations']:
            with self.subTest(d['operation']):
                self.assertEqual(sorted(d), ['example', 'family', 'operation', 'parameters', 'rules', 'schema_version',
                                             'source_required', 'summary'])
                self.assertEqual(d['family'], d['operation'].split('.')[0])
                self.assertTrue(10 <= len(d['summary']) <= 200)
                self.assertNotIn('dobe', d['summary'].lower())
                schema = d['parameters']
                self.assertEqual(schema['type'], 'object')
                self.assertIs(schema['additionalProperties'], False, 'unknown parameters are refused')
                self.assertEqual(unknown_keywords(schema), set())
                self.assertTrue(set(schema.get('required', ())) <= set(schema['properties']))

    def test_example_passes_schema_and_validator(self):
        for d in descriptors.describe_all()['operations']:
            with self.subTest(d['operation']):
                op, example = d['operation'], d['example']
                self.assertTrue(matches(example, d['parameters']), 'schema refuses the example')
                source = PLACEHOLDER_SOURCE if d['source_required'] else None
                self.assertTrue(native_accepts(op, example, source), 'validator refuses the example')
                self.assertEqual(d['source_required'], not native_accepts(op, example, None))

    def test_schema_refuses_what_the_validator_refuses_at_the_top_level(self):
        for d in descriptors.describe_all()['operations']:
            op, example, schema = d['operation'], d['example'], d['parameters']
            source = PLACEHOLDER_SOURCE if d['source_required'] else None
            with self.subTest(op, mutation='unknown key'):
                self.assertFalse(matches({**example, 'zz_unknown': 1}, schema))
                self.assertFalse(native_accepts(op, {**example, 'zz_unknown': 1}, source))
            for name in example:
                dropped = {k: v for k, v in example.items() if k != name}
                with self.subTest(op, mutation='drop ' + name):
                    self.assertEqual(matches(dropped, schema), native_accepts(op, dropped, source))

    def test_rules_follow_the_descriptor(self):
        self.assertEqual(descriptors.rules(False, {}), ['one_create_per_project'])
        self.assertEqual(descriptors.rules(True, {'required': ['expected_sha256']}),
                         ['source_required', 'revise_from_head', 'edit_requires_previous_hash'])
        write_edit = descriptors.describe('write.edit')
        self.assertIn('edit_requires_previous_hash', write_edit['rules'])

    def test_unknown_operation_is_an_error(self):
        with self.assertRaises(ValueError):
            descriptors.describe('no-such.operation')
        code, out, err = cli('describe', 'no-such.operation')
        self.assertEqual((code, out), (1, ''))
        self.assertEqual(sorted(json.loads(err)), ['error', 'message'])
        self.assertEqual(cli('describe')[0], 1)

    def test_cli_mcp_and_capabilities_agree(self):
        code, out, _ = cli('describe', 'vector.create')
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), json.dumps(descriptors.describe('vector.create'), sort_keys=True))
        code, out, _ = cli('describe', '--all')
        self.assertEqual(json.loads(out), descriptors.describe_all())
        text = json.dumps(mcp.invoke(None, 'studio_describe_operation', {'operation': 'vector.create'}, product='dobe'))
        self.assertEqual(text, json.dumps(descriptors.describe('vector.create')))
        caps = capabilities.describe(product='dobe')
        self.assertEqual(caps['operation_summaries'], descriptors.summaries())
        self.assertEqual(caps['describe'], 'dope describe OPERATION')

    def test_mcp_lists_the_public_describe_tool(self):
        lines = [{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}},
                 {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                  'params': {'name': 'dope_describe_operation', 'arguments': {'operation': 'pdf.inspect'}}}]
        with tempfile.TemporaryDirectory() as state:
            done = subprocess.run(
                [sys.executable, '-I', '-B', '-c',
                 'import sys; sys.path.insert(0, sys.argv[1]); from studio_runtime.__main__ import main; '
                 'sys.exit(main(sys.argv[2:], product="dobe"))', str(RUNTIME), '--state', state, 'mcp'],
                input=''.join(json.dumps(line) + '\n' for line in lines), capture_output=True, text=True, timeout=120)
        replies = {r['id']: r for r in map(json.loads, done.stdout.splitlines())}
        tool = next(t for t in replies[1]['result']['tools'] if t['name'] == 'dope_describe_operation')
        self.assertEqual(list(tool['inputSchema']['properties']), ['operation'])
        self.assertEqual(json.loads(replies[2]['result']['content'][0]['text']), descriptors.describe('pdf.inspect'))


if __name__ == '__main__':
    unittest.main()
