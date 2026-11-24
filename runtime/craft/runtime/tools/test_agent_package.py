"""Package alias handling must fail before cloning or touching source files."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import build_agent_package


class PackagePathTests(unittest.TestCase):
    def package(self, root):
        base=root/'base';manifest=base/'lib/dobe/bundle.json';manifest.parent.mkdir(parents=True)
        source=base/'lib/dobe/python/lib/python3.13/encodings/example.py';source.parent.mkdir(parents=True)
        source.write_text('value = 1\n')
        cache=source.parent/'__pycache__/example.cpython-313.pyc';cache.parent.mkdir();cache.write_bytes(b'original cache')
        files={p.relative_to(base).as_posix():build_agent_package.file_record(p) for p in (source,cache)}
        manifest.write_text(json.dumps({'files':files}))
        return base,source,cache

    def test_changed_cache_requires_explicit_omission_and_verified_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            base,source,cache=self.package(Path(temporary));cache.write_bytes(b'changed cache')
            with self.assertRaisesRegex(ValueError,'manifest mismatch'):build_agent_package.inspect_base(base)
            proof=build_agent_package.inspect_base(base,True)
            self.assertIn(cache.relative_to(base).as_posix(),proof['omitted_files'])
            self.assertEqual(cache.read_bytes(),b'changed cache')
            source.write_text('value = 2\n')
            with self.assertRaises(ValueError):build_agent_package.inspect_base(base,True)

    def test_unrecorded_executable_cannot_be_laundered(self):
        with tempfile.TemporaryDirectory() as temporary:
            base,source,cache=self.package(Path(temporary));(base/'unexpected.py').write_text('pass')
            with self.assertRaisesRegex(ValueError,'Unrecorded package file'):build_agent_package.inspect_base(base,True)

    def test_recorded_internal_symlink_verifies_without_dereferencing_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            base,source,cache=self.package(Path(temporary));link=source.with_name('alias.py');link.symlink_to(source.name)
            manifest=base/'lib/dobe/bundle.json';receipt=json.loads(manifest.read_text())
            receipt['files'][link.relative_to(base).as_posix()]={'symlink':source.name};manifest.write_text(json.dumps(receipt))
            build_agent_package.inspect_base(base)
            link.unlink();link.write_text(source.read_text())
            with self.assertRaisesRegex(ValueError,'manifest mismatch'):build_agent_package.inspect_base(base)

    def test_manifest_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);base,source,cache=self.package(root)
            outside=root/'outside';outside.write_text('outside')
            manifest=base/'lib/dobe/bundle.json';receipt=json.loads(manifest.read_text())
            receipt['files']['../outside']=build_agent_package.file_record(outside);manifest.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError,'Unsafe package manifest path'):build_agent_package.inspect_base(base,True)

    def test_derived_package_retains_provenance_and_original_bytes(self):
        import shutil
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);base,source,cache=self.package(root);output=root/'output'
            cache.write_bytes(b'changed cache');extra=cache.with_name('example.cpython-313.opt-1.pyc');extra.write_bytes(b'extra cache')
            def clone(command,check):shutil.copytree(base,output,dirs_exist_ok=True)
            arguments=['build_agent_package','--base',str(base),'--output',str(output),'--omit-python-bytecode']
            with patch('sys.argv',arguments),patch('build_agent_package.subprocess.run',side_effect=clone),patch('build_agent_package.overlay'):
                build_agent_package.main()
            self.assertEqual(cache.read_bytes(),b'changed cache');self.assertEqual(extra.read_bytes(),b'extra cache')
            self.assertFalse((output/cache.relative_to(base)).exists());self.assertFalse((output/extra.relative_to(base)).exists())
            receipt=json.loads((output/'lib/dobe/bundle.json').read_text())
            self.assertEqual(len(receipt['development_derivation']['omitted_files']),2)
            self.assertEqual((output/source.relative_to(base)).read_bytes(),source.read_bytes())
            build_agent_package.inspect_base(output)

    def test_copy_race_is_rejected_and_output_retained(self):
        import shutil
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);base,source,cache=self.package(root);output=root/'output'
            def copy_changed(command,check):
                shutil.copytree(base,output,dirs_exist_ok=True)
                (output/source.relative_to(base)).write_text('changed during copy')
            with patch('sys.argv',['build_agent_package','--base',str(base),'--output',str(output)]),patch('build_agent_package.subprocess.run',side_effect=copy_changed):
                with self.assertRaisesRegex(ValueError,'manifest mismatch'):build_agent_package.main()
            self.assertTrue(output.exists());self.assertEqual(source.read_text(),'value = 1\n')

    def test_parent_alias_cannot_hide_output_inside_base(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);base=root/'base';base.mkdir();alias=root/'alias';alias.symlink_to(base,target_is_directory=True)
            with patch('sys.argv',['build_agent_package','--base',str(base),'--output',str(alias/'nested')]),patch('build_agent_package.subprocess.run') as copy:
                with self.assertRaises(ValueError):build_agent_package.main()
            copy.assert_not_called();self.assertEqual(list(base.iterdir()),[])

    def test_existing_and_dangling_aliases_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);base=root/'base';base.mkdir();existing=root/'existing';existing.mkdir()
            alias=root/'alias';alias.symlink_to(root/'missing')
            for output in (existing,alias):
                with patch('sys.argv',['build_agent_package','--base',str(base),'--output',str(output)]),patch('build_agent_package.subprocess.run') as copy:
                    with self.assertRaises(ValueError):build_agent_package.main()
                copy.assert_not_called()
            self.assertTrue(existing.is_dir());self.assertTrue(alias.is_symlink())

    def test_partial_clone_is_retained_and_never_overwritten_on_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);base,source,cache=self.package(root);output=root/'output'
            def fail_copy(command,check):
                self.assertTrue(output.is_dir())
                self.assertEqual(command[2],str(base.resolve())+'/.')
                (output/'partial-evidence').write_text('retained')
                raise RuntimeError('synthetic copy failure')
            arguments=['build_agent_package','--base',str(base),'--output',str(output)]
            with patch('sys.argv',arguments),patch('build_agent_package.subprocess.run',side_effect=fail_copy):
                with self.assertRaises(RuntimeError):build_agent_package.main()
            with patch('sys.argv',arguments),patch('build_agent_package.subprocess.run') as copy:
                with self.assertRaises(ValueError):build_agent_package.main()
            copy.assert_not_called();self.assertEqual((output/'partial-evidence').read_text(),'retained')


if __name__=='__main__':unittest.main()
