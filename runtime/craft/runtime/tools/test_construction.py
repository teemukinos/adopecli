"""Local contract tests; execution evidence lives in construction_acceptance.py."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from studio_runtime import construction, construction_schema as schema, construction_rive

FIXTURES=Path(__file__).resolve().parents[1]/'fixtures/construction'
def fixture(name='ring'):return json.loads((FIXTURES/(name+'.json')).read_text())
class ConstructionTests(unittest.TestCase):
    def test_closed_offline_policy(self):
        for mutation in ({'network':'online','media_generation':'disabled'},{'network':'offline','media_generation':'enabled'}):
            d=fixture();d['policy']=mutation
            with self.assertRaises(ValueError):schema.validate(d)
    def test_public_code_is_not_an_operation(self):
        d=fixture();d['components'][0]['parameters']['script']='import os'
        with self.assertRaises(ValueError):schema.validate(d)
    def test_cycles_and_external_artifacts(self):
        for value in ('../outside','/tmp/out','a/../../out','a\\out'):
            d=fixture();d['components'][0]['inputs']={'a'*32:{'component':'intro','artifact':value}}
            with self.assertRaises(ValueError):schema.validate(d)
        d=fixture();d['components'][0]['inputs']={'a'*32:{'component':'intro','artifact':'exports/preview.png'}}
        with self.assertRaises(ValueError):schema.validate(d)
    def test_optimistic_revision_preserves_input(self):
        d=fixture();original=copy.deepcopy(d)
        edit={'component':'intro','action':'set','path':['parameters','frames'],'before':240,'value':288}
        changed=schema.revise(d,[edit]);self.assertEqual(d,original);self.assertEqual(changed['components'][0]['parameters']['frames'],288)
        edit['before']=241
        with self.assertRaises(ValueError):schema.revise(d,[edit])
    def test_asset_traversal_rejected_before_materialization(self):
        with self.assertRaises(ValueError):construction.assets('construct.edit',{'import_assets':['../../outside']})
    def test_unchanged_rive_ids_survive_reordering(self):
        d=fixture('interactive')['components'][0]['parameters'];_,before=construction_rive.compile_document(d)
        d['objects'].reverse();d['states'].reverse();_,after=construction_rive.compile_document(d)
        self.assertEqual(before,after)
    def test_output_target_is_closed(self):
        with self.assertRaises(ValueError):construction.validate('construct.render',{'outputs':[{'component':'intro','format':'shell'}]},'revision')
    def test_symlink_artifact_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'link').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):construction.inventory(root)
    def test_missing_native_profile_is_not_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):construction.run_native(Path(temp),{'engine':'vector','parameters':{}},'verify')
    def test_invalid_group_opacity_is_explicit(self):
        d=fixture();d['components'][0]['parameters']['objects'].append({'id':'group','kind':'group','keys':{'opacity':[[0,0,'LINEAR']]}})
        with self.assertRaises(ValueError):schema.validate(d)
if __name__=='__main__':unittest.main()
