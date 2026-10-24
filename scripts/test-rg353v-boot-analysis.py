#!/usr/bin/env python3
import sys
sys.dont_write_bytecode=True
import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('analysis',Path(__file__).with_name('analyze-rg353v-boot.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class AnalysisTests(unittest.TestCase):
    def test_partition_accounts_for_gaps_and_spans_exactly(self):
        result=m.partition(1.,5.,[{'name':'b','start_s':3.,'end_s':4.},{'name':'a','start_s':1.5,'end_s':2.}])
        self.assertEqual(sum(x['duration_ms'] for x in result),4000.)
        self.assertEqual([x['duration_ms'] for x in result],[500.,500.,1000.,1000.,1000.])
    def test_parallel_children_are_rejected_instead_of_summed(self):
        with self.assertRaisesRegex(ValueError,'Overlapping'):
            m.partition(0.,4.,[{'name':'a','start_s':1.,'end_s':3.},{'name':'b','start_s':2.,'end_s':4.}])
    def test_outside_or_invalid_parent_is_rejected(self):
        with self.assertRaises(ValueError):m.partition(5.,1.,[])
        with self.assertRaises(ValueError):m.partition(1.,2.,[{'name':'a','start_s':0.,'end_s':1.}])
    def test_critical_path_excludes_parallel_services_and_clips_exposure(self):
        units=[{'Id':'-.slice','start_s':1.,'end_s':1.}, {'Id':'a.service','start_s':1.5,'end_s':3.}, {'Id':'b.service','start_s':2.,'end_s':4.}, {'Id':'parallel.service','start_s':1.,'end_s':8.}]
        r={'critical_chain':'slot-rg353v.service @4s\n b.service @2s\n a.service @1s\n -.slice @0s','summary':{'stages':[{}, {}, {'start_s':1.,'end_s':5.}], 'units':units}}
        result=m.critical_path(r)
        self.assertEqual(sum(x['duration_ms'] for x in result),4000.)
        self.assertNotIn('parallel.service',[x['name'] for x in result])
        self.assertEqual(next(x['duration_ms'] for x in result if x['name']=='b.service'),1000.)
    def test_missing_chain_is_not_silently_labeled_unknown_time(self):
        r={'critical_chain':'','summary':{'stages':[{}, {}, {'start_s':1.,'end_s':5.}], 'units':[]}}
        with self.assertRaisesRegex(ValueError,'critical chain'):m.critical_path(r)
    def test_missing_slice_keeps_prefix_as_gap(self):
        r={'critical_chain':'slot-rg353v.service @4s\n a.service @2s\n -.slice @0s',
           'summary':{'stages':[{}, {}, {'start_s':1.,'end_s':5.}],
                      'units':[{'Id':'a.service','start_s':2.,'end_s':4.}]}}
        rows=m.critical_path(r)
        self.assertEqual([x['duration_ms'] for x in rows],[1000.,2000.,1000.])
        self.assertEqual(rows[0]['kind'],'unattributed')
    def test_missing_service_timestamp_is_rejected(self):
        r={'critical_chain':'slot-rg353v.service @4s\n a.service @2s',
           'summary':{'stages':[{}, {}, {'start_s':1.,'end_s':5.}],
                      'units':[{'Id':'a.service','start_s':2.,'end_s':None}]}}
        with self.assertRaisesRegex(ValueError,'ready timestamp'):m.critical_path(r)

if __name__=='__main__':unittest.main()
