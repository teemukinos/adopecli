#!/usr/bin/env python3
"""Synthetic host-contract checks; no foreign engine execution is claimed."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'craft/runtime'))
from studio_runtime import inspect_host as host, inspect_source as source


class HostContract(unittest.TestCase):
    def setUp(self):
        # Raw native-style number tokens exercise preservation, not a substitute
        # for the separate real-engine evidence-ID reconstruction checks.
        self.value = {'evidence': {'id': 'ev_'+'0'*64, 'subject': {'kind':'wasm','sha256':'a'*64},
            'environment': {'clean_room':False,'engine':'builtin','engine_version':'0.6.1','host':'macos-aarch64'},
            'summary':'Fixture only', 'carries_target_content':True,
            'result': {'float':1.25,'nested':[1,True,None],'text':'quoted "text"\n😀'}}}
        self.original = host.rehost(source.encoded(self.value),'macos-aarch64')
        self.foreign = host.rehost(self.original,'linux-x86_64')

    def test_only_host_and_id_change(self):
        before=json.loads(self.original);after=json.loads(self.foreign)
        self.assertNotEqual(before['evidence']['id'],after['evidence']['id'])
        after['evidence']['id']=before['evidence']['id']
        after['evidence']['environment']['host']='macos-aarch64'
        self.assertEqual(before,after)
        self.assertEqual(host.rehost(self.foreign,'macos-aarch64'),self.original)

    def test_same_host_is_exact(self):
        self.assertIsNone(host.compare(self.original,self.original))
        with self.assertRaises(ValueError):host.compare(self.original,self.original+b'\n')

    def test_cross_host_has_explicit_receipt(self):
        value=host.compare(self.original,self.foreign)
        self.assertEqual(value,{'profile':host.PROFILE,'source_host':'macos-aarch64',
                               'replay_host':'linux-x86_64','replayed_report_sha256':source.sha(self.foreign)})

    def test_all_report_fields_still_compare(self):
        for key,value in (('summary','changed'),('result',{}),('carries_target_content',False),('id','ev_'+'1'*64)):
            altered=json.loads(self.original);altered['evidence'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):host.compare(source.encoded(altered),self.foreign)

    def test_host_change_without_identity_reconstruction_refused(self):
        altered=json.loads(self.original);altered['evidence']['environment']['host']='linux-x86_64'
        with self.assertRaises(ValueError):host.compare(source.encoded(altered),self.original)

    def test_unknown_host_and_environment_refused(self):
        for value in ('windows-x86_64','linux-aarch64','macos-x86_64','',None):
            with self.subTest(host=value),self.assertRaises(ValueError):host.rehost(self.original,value)
        altered=json.loads(self.original);altered['evidence']['environment']['clean_room']=0
        with self.assertRaises(ValueError):host.rehost(source.encoded(altered),'linux-x86_64')

    def test_number_tokens_preserved(self):
        raw=self.original.replace(b'1.25',b'-0.0').replace(b'[1,true,null]',b'[1e-7,1e+16,18446744073709551615]')
        changed=host.rehost(raw,'linux-x86_64')
        self.assertIn(b'-0.0',changed)
        self.assertIn(b'[1e-7,1e+16,18446744073709551615]',changed)

    def test_utf16_canonical_key_order(self):
        self.assertEqual(host.encode({'ﬁ':host.Number('2'),'😀':host.Number('1')},canonical=True),'{"😀":1,"ﬁ":2}')

    def test_non_native_serialization_refused(self):
        with self.assertRaisesRegex(ValueError,'serialization'):host.rehost(self.original+b'\n','linux-x86_64')
        duplicate=b'{"evidence":{},"evidence":{}}'
        with self.assertRaises(ValueError):host.rehost(duplicate,'linux-x86_64')

    def test_retained_receipt_checks_migration_digest(self):
        migration=host.compare(self.foreign,self.original)
        fresh={'binary_sha256':'b'*64,'complete_report_equal':False,'host_migration':migration}
        with patch.object(host,'current',return_value='macos-aarch64'):
            self.assertEqual(host.retained_receipt(fresh,fresh,self.foreign),fresh)
            changed=copy.deepcopy(fresh);changed['host_migration']['replayed_report_sha256']='0'*64
            with self.assertRaises(ValueError):host.retained_receipt(fresh,changed,self.foreign)

    def test_foreign_binary_claim_is_bounded_historical_data(self):
        fresh={'binary_sha256':'b'*64,'complete_report_equal':False,
               'host_migration':host.compare(self.foreign,self.original)}
        old={'binary_sha256':'c'*64,'complete_report_equal':True}
        with patch.object(host,'current',return_value='macos-aarch64'):
            self.assertEqual(host.retained_receipt(fresh,old,self.foreign),old)
            with self.assertRaises(ValueError):host.retained_receipt(fresh,{**old,'binary_sha256':'bad'},self.foreign)
            # Same-host provenance cannot replace the current pinned binary.
            current={'binary_sha256':'b'*64,'complete_report_equal':True}
            self.assertEqual(host.retained_receipt(current,old,self.original),current)


if __name__=='__main__':unittest.main()
