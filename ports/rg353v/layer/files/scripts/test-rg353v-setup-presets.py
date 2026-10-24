#!/usr/bin/env python3
"""Preset navigation and live installation indicator, without hardware or writes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
ui=load('presets_ui','ports/rg353v/image/slot-setup-ui.py')
modules=load('presets_modules','ports/rg353v/image/slot-modules.py')
CATALOG=json.loads((ROOT/'ports/rg353v/modules/catalog-v1.json').read_text())
FONT=ROOT/'ports/rg353v/image/slot-setup-font.json.gz'
SOURCE={'bytes':60492349440,'content_bytes':54000000000}

class Presets(unittest.TestCase):
    def model(self,debug=None):
        model=ui.Model(SOURCE,None,debug,CATALOG,sd_test=True)
        self.assertIsNone(model.key('a'));self.assertEqual(model.page,'presets')
        return model

    def test_minimal_and_recommended_skip_modules_and_match_valid_composition(self):
        expected=[{'emulator-mgba'}, {'emulator-mgba','usb-storage','external-sd','filters','overlays','rewind'}]
        for index,wanted in enumerate(expected):
            model=self.model();model.selected=index
            self.assertIsNone(model.key('a'));self.assertEqual(model.page,'review')
            self.assertEqual(model.features,wanted)
            self.assertEqual(set(modules.selection(CATALOG,model.features)),wanted)
            self.assertFalse(any(model.options.values()))
            self.assertEqual(model.preset,ui.PRESETS[index][0])
            self.assertTrue(any(title=='Setup preset' and body==model.preset.title() for title,body,_ in model.review_blocks()))
            model.key('b');self.assertEqual(model.page,'presets');self.assertEqual(model.selected,index)

    def test_custom_edits_the_previous_preset_and_returns_to_its_selector(self):
        model=self.model();model.selected=1;model.key('a');before=model.features.copy()
        model.key('b');model.key('down');model.key('a')
        self.assertEqual(model.page,'modules');self.assertEqual(model.features,before)
        self.assertEqual(model.preset,'custom')
        model.key('a');self.assertNotIn('emulator-mgba',model.features)
        model.key('b');self.assertEqual(model.page,'presets')
        model.key('a');self.assertEqual(model.page,'modules');self.assertNotIn('emulator-mgba',model.features)

    def test_presets_never_start_installation_without_final_confirmation(self):
        model=self.model();model.key('a')
        for key in ('up','down','left','right'):self.assertIsNone(model.key(key))
        self.assertEqual(model.page,'review')
        self.assertIsNone(model.key('a'));self.assertEqual(model.page,'confirm')
        self.assertIsNone(model.key('a'));self.assertEqual(model.page,'review')
        model.key('a');model.key('down');self.assertEqual(model.key('a'),'sd')
        self.assertEqual(model.page,'progress')

    def test_minimal_internal_review_keeps_the_missing_game_transfer_warning(self):
        model=ui.Model(SOURCE,SOURCE,modules=CATALOG);model.key('down');model.key('a');model.key('a')
        self.assertEqual(model.page,'review');self.assertEqual(model.action,'emmc')
        self.assertTrue(any('No way to add games' in body for _,body,_ in model.review_blocks()))

    def test_private_debug_never_leaks_into_minimal_or_recommended_and_custom_can_restore_it(self):
        debug={'wifi':[1],'authorized_keys':['public fixture']}
        model=self.model(debug);self.assertEqual(model.selected,ui.preset_index('full'))
        for index in (0,1):
            model.selected=index;model.key('a');self.assertFalse(any(model.options.values()))
            self.assertNotIn('developer',model.features);model.key('b')
        model.selected=ui.preset_index('custom');model.key('a')
        for name in ('wifi','usb-network','developer'):
            model.selected=next(i for i,v in enumerate(CATALOG['modules']) if v['id']==name);model.key('a')
        model.selected=len(CATALOG['modules']);model.key('a')
        self.assertEqual(model.page,'review');self.assertTrue(all(model.options.values()))

    def test_preset_descriptions_and_all_new_screens_fit(self):
        canvas=ui.Canvas(FONT);original=canvas.text
        def checked(text,x,y,font='body',color=ui.FG):
            self.assertGreaterEqual(x,0);self.assertLessEqual(x+canvas.measure(text,font),640,text)
            self.assertLess(y,464,(text,y));return original(text,x,y,font,color)
        canvas.text=checked;model=self.model()
        for index,(_,_,_,description,_) in enumerate(ui.PRESETS):
            self.assertLessEqual(len(canvas.wrap(description,256,'small')),4)
            model.selected=index;model.draw(canvas)
        model.page='progress';model.status='Checking the selected system';model.percent=96
        model.tick_progress(100);model.tick_progress(171.5);model.draw(canvas)
        self.assertEqual(model.elapsed,71);self.assertEqual(model.percent,96)

    def test_full_uses_every_catalog_module_including_future_additions(self):
        catalog=json.loads(json.dumps(CATALOG))
        catalog['modules'].append({'id':'future-feature','label':'Future feature','requires':[]})
        for current in (CATALOG,catalog):
            model=ui.Model(SOURCE,None,modules=current);model.key('a')
            model.selected=ui.preset_index('full');self.assertIsNone(model.key('a'))
            wanted={feature['id'] for feature in current['modules']}
            self.assertEqual(model.features,wanted)
            self.assertEqual(set(modules.selection(current,model.features)),wanted)
            self.assertEqual(model.page,'review');self.assertEqual(model.preset,'full')
            self.assertFalse(any(model.options.values()))
            self.assertTrue(any(title=='Setup preset' and body=='Full' for title,body,_ in model.review_blocks()))
            model.key('b');self.assertEqual(model.selected,ui.preset_index('full'))

    def test_full_private_preset_prepares_debug_access_and_does_not_install_yet(self):
        model=self.model({'wifi':[1],'authorized_keys':['public fixture']})
        self.assertEqual(ui.PRESETS[model.selected][0],'full')
        self.assertIsNone(model.key('a'));self.assertEqual(model.page,'review')
        self.assertTrue(all(model.options.values()))
        self.assertEqual(model.features,{feature['id'] for feature in CATALOG['modules']})
        model.key('a');self.assertEqual(model.page,'confirm')
        self.assertIsNone(model.key('a'));self.assertEqual(model.page,'review')

    def test_grid_navigation_uses_rows_and_columns_with_wrapping(self):
        expected={0:{'left':1,'right':1,'up':2,'down':2},
                  1:{'left':0,'right':0,'up':3,'down':3},
                  2:{'left':3,'right':3,'up':0,'down':0},
                  3:{'left':2,'right':2,'up':1,'down':1}}
        self.assertEqual([preset[0] for preset in ui.PRESETS],['minimal','recommended','full','custom'])
        model=self.model()
        for start,moves in expected.items():
            for key,end in moves.items():
                model.selected=start;self.assertIsNone(model.key(key))
                self.assertEqual(model.selected,end);self.assertEqual(model.page,'presets')

class Activity(unittest.TestCase):
    def test_indicator_moves_between_real_progress_callbacks_and_stops_on_all_exit_paths(self):
        class Framebuffer:
            def __init__(self):self.condition=threading.Condition();self.frames=[];self.closed=False
            def show(self,canvas):
                with self.condition:
                    if self.closed:raise AssertionError('draw after close')
                    self.frames.append(hashlib.sha256(canvas.pixels).hexdigest());self.condition.notify_all()
            def close(self):self.closed=True
        class Input:
            def drain(self):pass
            def close(self):pass
        for ending in ('done','error','close'):
            with self.subTest(ending=ending),patch.object(ui,'Framebuffer',Framebuffer),patch.object(ui,'Input',Input):
                screen=ui.Screen(FONT,SOURCE,None,modules=CATALOG)
                try:
                    screen.progress('Building your selected system',88);thread=screen.activity_thread
                    with screen.fb.condition:
                        screen.fb.condition.wait_for(lambda:len(screen.fb.frames)>=4,timeout=3)
                    self.assertGreaterEqual(len(set(screen.fb.frames[1:])),3)
                    self.assertEqual(screen.model.percent,88)
                    screen.progress('Checking the selected system',96)
                    self.assertIs(screen.activity_thread,thread);self.assertEqual(screen.model.percent,96)
                    self.assertGreaterEqual(screen.model.elapsed,1)
                    if ending=='error':screen.error('fixture failure')
                    else:getattr(screen,ending)()
                    self.assertFalse(thread.is_alive());self.assertIsNone(screen.activity_thread)
                    if ending!='close':self.assertEqual(screen.model.page,ending)
                    if ending=='error':
                        screen.progress('Retrying',5);self.assertLess(screen.model.elapsed,1)
                finally:screen.close()

if __name__=='__main__':unittest.main()
