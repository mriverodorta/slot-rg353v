#!/usr/bin/env python3
"""Module selection, archive confinement and real filesystem composition tests."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
def load(name,file):
    s=importlib.util.spec_from_file_location(name,ROOT/file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=load('modules','ports/rg353v/image/slot-modules.py')
ui=load('ui','ports/rg353v/image/slot-setup-ui.py')
spec=json.loads((ROOT/'ports/rg353v/modules/catalog-v1.json').read_text())

def enter_custom(model):
    model.key('a');model.selected=ui.preset_index('custom');model.key('a')

class Selection(unittest.TestCase):
    def test_schedutil_is_optional_and_full_includes_it_without_preset_arrays(self):
        model=ui.Model({'content_bytes':1},None,modules=spec);enter_custom(model)
        self.assertNotIn('schedutil-governor',model.features)
        self.at(model,'schedutil-governor');model.key('a')
        self.assertEqual(m.selection(spec,model.features),['emulator-mgba','schedutil-governor'])
        for name,_label,_icon,_description,selected in ui.PRESETS:
            if selected is not None:self.assertNotIn('schedutil-governor',selected)
        model.page='presets';model.selected=ui.preset_index('full');model.key('a')
        self.assertIn('schedutil-governor',model.features)
        self.assertEqual(model.features,{v['id'] for v in spec['modules']})

    def test_enhanced_audio_is_an_explicit_independent_install_choice(self):
        model=ui.Model({'content_bytes':1},None,modules=spec);enter_custom(model)
        self.assertNotIn('enhanced-audio',model.features)
        self.at(model,'enhanced-audio');model.key('a')
        self.assertEqual(model.features,{'emulator-mgba','enhanced-audio'})
        self.assertEqual(m.selection(spec,model.features),['emulator-mgba','enhanced-audio'])
        model.key('a');self.assertEqual(model.features,{'emulator-mgba'})
        for _name,_label,_icon,_description,selected in ui.PRESETS:
            if selected is not None:self.assertNotIn('enhanced-audio',selected)

    def test_capture_and_gallery_are_separate_optional_modules(self):
        for capture,gallery in ((False,False),(True,False),(False,True),(True,True)):
            selected={'emulator-mgba'}
            model=ui.Model({'content_bytes':1},None,modules=spec);enter_custom(model)
            for feature,enabled in (('screenshots',capture),('gallery',gallery)):
                if enabled:
                    selected.add(feature);self.at(model,feature);model.key('a')
            self.assertEqual(model.features,selected)
            self.assertEqual(m.selection(spec,selected),sorted(selected))
        for _name,_label,_icon,_description,selected in ui.PRESETS:
            if selected is not None:
                self.assertNotIn('screenshots',selected)
                self.assertNotIn('gallery',selected)

    def test_dependency_and_developer_transport_requirements(self):
        self.assertEqual(m.selection(spec,['network-time','emulator-mgba']),['emulator-mgba','network-time','wifi'])
        for selected in (['developer','emulator-mgba'],['developer','ssh','emulator-mgba'],['developer','wifi','emulator-mgba']):
            with self.assertRaises(ValueError):m.selection(spec,selected)
        self.assertEqual(m.selection(spec,['developer','usb-network','ssh','emulator-mgba']),['developer','emulator-mgba','ssh','usb-network'])
        with self.assertRaises(ValueError):m.selection(spec,['unknown'])

    def test_diagnostics_and_development_profilers_are_independent_choices(self):
        for feature,other in [('diagnostics','profilers'),('profilers','diagnostics')]:
            self.assertEqual(m.selection(spec,[feature,'emulator-mgba']),sorted([feature,'emulator-mgba']))
            model=ui.Model({'content_bytes':1},None,modules=spec);enter_custom(model)
            model.selected=next(i for i,x in enumerate(spec['modules']) if x['id']==feature)
            model.key('a');self.assertEqual(model.features,{feature,'emulator-mgba'})
            self.assertNotIn(other,model.features)
            self.assertNotIn('developer',model.features)
            model.key('a');self.assertEqual(model.features,{'emulator-mgba'})

    def test_feature_help_blocks_changes_and_closes_without_moving_selection(self):
        model=ui.Model({'content_bytes':1},None,modules=spec);enter_custom(model)
        for index,_feature in enumerate(spec['modules']):
            model.selected=index;model.module_first=max(0,index-6)
            before=(set(model.features),model.selected,model.module_first,model.page)
            self.assertIsNone(model.key('y'));self.assertTrue(model.help_open)
            for key in ('a','left','right','up','down','y'):
                self.assertIsNone(model.key(key))
                self.assertEqual((model.features,model.selected,model.module_first,model.page),before)
            self.assertIsNone(model.key('b'));self.assertFalse(model.help_open)
            self.assertEqual((model.features,model.selected,model.module_first,model.page),before)
        model.selected=len(spec['modules']);model.key('y');self.assertFalse(model.help_open)
        model.key('a');self.assertEqual(model.page,'review')

    def test_a_and_both_horizontal_directions_keep_toggling(self):
        for key in ('a','left','right'):
            model=ui.Model({'content_bytes':1},None,modules=spec);enter_custom(model)
            model.selected=next(i for i,x in enumerate(spec['modules']) if x['id']=='wifi')
            model.key(key);self.assertEqual(model.features,{'wifi','emulator-mgba'})
            model.key(key);self.assertEqual(model.features,{'emulator-mgba'})
            self.assertFalse(model.help_open)

    def test_setup_requires_a_core_but_keeps_optional_emulators_independent(self):
        for bad in ([],['wifi'],['ssh','usb-network']):
            with self.assertRaisesRegex(ValueError,'at least one emulator'):m.selection(spec,bad)
        for selection in (['emulator-mgba'],['emulator-gpsp'],['emulator-mgba','emulator-gpsp']):
            self.assertEqual(m.selection(spec,selection),sorted(selection))
        model=ui.Model({'content_bytes':1},None,modules=spec);enter_custom(model)
        self.assertEqual(model.features,{'emulator-mgba'})
        model.key('a');self.assertEqual(model.features,set())
        model.key('up');model.key('a');self.assertEqual(model.page,'modules')
        self.assertIn('emulator',model.message)
        model.key('down');model.key('down');model.key('a')
        self.assertEqual(model.features,{'emulator-gpsp'})
        model.key('up');model.key('up');model.key('a')
        self.assertEqual(model.page,'review')

    def at(self,model,name):
        model.selected=next(i for i,v in enumerate(spec['modules']) if v['id']==name)

    def test_runahead_unavailable_without_mgba_and_removed_when_mgba_is_omitted(self):
        model=ui.Model({'content_bytes':1},None,modules=spec);enter_custom(model)
        model.features={'emulator-gpsp'};self.at(model,'runahead')
        for key in ('a','left','right'):
            model.key(key);self.assertEqual(model.features,{'emulator-gpsp'})
            self.assertIn('Requires mGBA',model.message)
        model.key('y');self.assertTrue(model.help_open);model.key('b')
        with self.assertRaisesRegex(ValueError,'requires mGBA'):
            m.selection(spec,['emulator-gpsp','runahead'])
        self.at(model,'emulator-mgba');model.key('a')
        self.at(model,'runahead');model.key('a');self.assertIn('runahead',model.features)
        self.at(model,'emulator-mgba');model.key('a')
        self.assertNotIn('runahead',model.features);self.assertIn('Run-Ahead',model.message)

    def test_network_time_reuses_usb_and_reports_fallback_and_removal(self):
        self.assertEqual(m.selection(spec,['emulator-mgba','usb-network','network-time']),
                         ['emulator-mgba','network-time','usb-network'])
        model=ui.Model({'content_bytes':1},None,modules=spec);enter_custom(model)
        self.at(model,'network-time');model.key('a')
        self.assertIn('wifi',model.features);self.assertIn('Also added: Wi-Fi',model.message)
        self.at(model,'usb-network');model.key('a')
        self.at(model,'wifi');model.key('a')
        self.assertIn('network-time',model.features)
        self.at(model,'usb-network');model.key('a')
        self.assertNotIn('network-time',model.features);self.assertIn('Network Time',model.message)
        self.at(model,'usb-network');model.key('a')
        self.at(model,'network-time');model.key('a')
        self.assertNotIn('wifi',model.features);self.assertIn('Internet via USB',model.message)

    def test_network_and_transfer_warnings_allow_return_or_review(self):
        model=ui.Model({'bytes':64*1024**3,'content_bytes':55*1024**3},None,modules=spec);enter_custom(model)
        model.features={'emulator-mgba','ssh','sharing','updates'}
        model.selected=len(spec['modules']);self.assertIsNone(model.key('a'))
        self.assertEqual(model.page,'access');self.assertEqual(len(model.warning),2)
        before=model.features.copy();model.key('b');self.assertEqual(model.page,'modules')
        self.assertEqual(model.features,before)
        model.selected=len(spec['modules']);model.key('a');model.key('down');model.key('a')
        self.assertEqual(model.page,'review')
        self.assertTrue(any('cannot connect' in body for _,body,_ in model.review_blocks()))

    def test_review_never_installs_and_requires_final_confirmation(self):
        source={'bytes':64*1024**3,'content_bytes':55*1024**3}
        model=ui.Model(source,None,modules=spec);enter_custom(model);model.key('up')
        self.assertIsNone(model.key('a'));self.assertEqual(model.page,'review')
        before=model.features.copy();self.assertIsNone(model.key('a'))
        self.assertEqual(model.page,'confirm');self.assertIsNone(model.key('a'))
        self.assertEqual(model.page,'review');model.key('b');self.assertEqual(model.page,'modules')
        self.assertEqual(model.features,before)
        model.key('a');model.key('a');model.key('down')
        self.assertEqual(model.key('a'),'sd');self.assertEqual(model.page,'progress')

    def test_group_headers_are_not_selectable_and_feature_controls_stay_the_same(self):
        model=ui.Model({'content_bytes':1},None,modules=spec);enter_custom(model)
        headers=[e for e in model.feature_entries() if e[0]=='group']
        self.assertEqual(len(headers),4)
        visited=[]
        for _ in range(len(spec['modules'])+1):
            visited.append(model.selected);model.key('down')
        self.assertEqual(visited,list(range(len(spec['modules'])+1)))
        self.at(model,'developer');model.key('a')
        self.assertTrue({'developer','ssh','usb-network'}<=model.features)
        self.assertIn('Also added:',model.message)

    def test_completion_only_explains_selected_routes_and_supported_folders(self):
        source={'bytes':64*1024**3,'content_bytes':55*1024**3}
        model=ui.Model(source,None,modules=spec,sd_test=True);model.action='sd'
        model.features={'emulator-gpsp'};text=str(model.completion_blocks())
        self.assertIn('Games/GBA',text);self.assertNotIn('Games/GB /',text)
        self.assertIn('Computer card reader',text);self.assertNotIn('SFTP',text)
        self.assertNotIn('File Sharing',text);self.assertNotIn('Connections',text)
        model.features.update({'usb-network','ssh','sharing','usb-storage','external-sd'})
        text=str(model.completion_blocks())
        for expected in ('SFTP','/storage/slotcontent/Games','File Sharing','safely eject','exFAT'):self.assertIn(expected,text)
        model.page='done';self.assertEqual(model.key('b'),'poweroff');self.assertEqual(model.key('a'),'reboot')

    def test_content_routes(self):
        for selected in (['external-sd'],['usb-storage'],['usb-network','ssh'],['wifi','sharing']):
            self.assertIsNone(m.transfer_warning(selected,'emmc'))
        self.assertIn('reader',m.transfer_warning([],'sd'))
        self.assertIn('No game-transfer',m.transfer_warning(['wifi'],'emmc'))

    def test_scroll_and_dependency_navigation(self):
        source={'bytes':64*1024**3,'content_bytes':55*1024**3}
        model=ui.Model(source,None,modules=spec);enter_custom(model)
        self.assertEqual(model.page,'modules')
        last=len(spec['modules'])
        for _ in range(last):model.key('down')
        self.assertEqual(model.selected,last);self.assertGreater(model.module_first,0)
        model.key('a');self.assertEqual(model.page,'review')
        self.assertEqual(model.features,{'emulator-mgba'})
        model=ui.Model(source,source,modules=spec);model.key('down');model.key('a');model.selected=ui.preset_index('custom');model.key('a')
        model.selected=last;model.key('a');self.assertEqual(model.page,'access')
        model.key('a');self.assertEqual(model.page,'modules')

    def test_private_default_omits_smb_and_network_time(self):
        model=ui.Model({'content_bytes':1},None,{'wifi':[1],'authorized_keys':['pub']},spec)
        self.assertNotIn('sharing',model.features);self.assertNotIn('network-time',model.features)
        self.assertTrue({'wifi','ssh','usb-network','developer'}<=model.features)

    def test_unsafe_archive_does_not_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=root/'root';target.mkdir();archive=root/'bad.tar.gz'
            for name in ('../outside','/outside','a/../../outside'):
                with tarfile.open(archive,'w:gz') as t:
                    item=tarfile.TarInfo(name);item.size=1;t.addfile(item,io.BytesIO(b'x'))
                with self.assertRaises(ValueError):m.unpack(archive,target,{name:{}})
            self.assertFalse((root/'outside').exists())

    def test_archive_cannot_follow_symlink_or_overwrite_core(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=root/'root';target.mkdir();outside=root/'outside';outside.mkdir()
            (target/'link').symlink_to(outside);(target/'core').write_text('core')
            for name in ('link/payload','core'):
                archive=root/'bad.tar.gz'
                with tarfile.open(archive,'w:gz') as t:
                    item=tarfile.TarInfo(name);item.size=1;t.addfile(item,io.BytesIO(b'x'))
                with self.assertRaises(ValueError):m.unpack(archive,target,{name:{}})
            self.assertFalse((outside/'payload').exists());self.assertEqual((target/'core').read_text(),'core')

@unittest.skipUnless(os.environ.get('SLOT_MODULE_KIT'),'requires a Linux module kit')
class Native(unittest.TestCase):
    def test_core_private_and_full_are_disjoint_and_verify(self):
        kit=Path(os.environ['SLOT_MODULE_KIT']);catalog=m.load(kit)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for label,selected in [('core',['emulator-mgba']),('gpsp',['emulator-gpsp']),('both',['emulator-mgba','emulator-gpsp']),('usb-time',['emulator-mgba','usb-network','network-time']),('diagnostics',['diagnostics','emulator-mgba']),('profilers',['profilers','emulator-mgba']),('private',[v['id'] for v in catalog['modules'] if v['id'] not in ('sharing','network-time')]),('full',[v['id'] for v in catalog['modules']])]:
                result=m.compose(kit,selected,root/(label+'-work'),root/(label+'.sfs'))
                self.assertFalse((root/(label+'-work/root')).exists())
                self.assertFalse((root/(label+'-work/verify')).exists())
                tree=root/(label+'-independent-check')
                subprocess.run([str(kit/'tools/unsquashfs'),'-processors','2','-no-progress','-no-xattrs','-d',str(tree),str(root/(label+'.sfs'))],check=True,stdout=subprocess.DEVNULL)
                self.assertEqual(result['selected'],sorted(selected))
                cores={filename for feature,filename in m.EMULATORS.items() if feature in selected}
                system=tree/'usr/share/slot/System'
                self.assertEqual(set(m.EMULATORS.values()) & {p.name for p in system.iterdir()},cores)
                self.assertEqual(set(json.loads((system/'update-contract.json').read_text())['cores']),cores)
                profile=json.loads((tree/'usr/share/slot/os-profile.json').read_text())
                self.assertEqual(set(profile['factory_binaries']),{'slot'}|cores)
                for core in cores:self.assertEqual(profile['factory_binaries'][core],m.digest(system/core))
                for feature,filename in m.EMULATORS.items():
                    evidence=[p for p in (system/'licenses/core-sources').rglob('*') if p.is_file()
                              and p.relative_to(system/'licenses/core-sources').parts[0].startswith(filename.split('_')[0])]
                    self.assertEqual(bool(evidence),feature in selected,(label,'source/license',filename))
                    self.assertEqual(any((system/'licenses').glob(filename.split('_')[0]+'-*')),feature in selected,(label,'license',filename))
                for feature,name in [('diagnostics','slot-diagnostics-ui'),('profilers','slot-boot-profile'),('profilers','btop')]:
                    self.assertEqual(any(p.is_file() for p in tree.rglob(name)),feature in selected,(label,name))
                for name in ('slot-ota-ui','slot-update','slot-os-update'):
                    self.assertEqual((system/name).is_file(),'updates' in selected,(label,'OTA companion',name))
                for feature,path in [('wifi','usr/sbin/NetworkManager'),('ssh','usr/sbin/sshd'),('sharing','usr/sbin/ksmbd.mountd'),('network-time','usr/lib/systemd/systemd-timesyncd')]:
                    # Locate by basename, accounting for distro bin aliases.
                    matches=[p for p in tree.rglob(Path(path).name) if p.is_file()]
                    self.assertEqual(bool(matches),feature in selected,(label,path))
                for name in ('smbd', 'nmbd', 'smbclient', 'wsdd2'):
                    self.assertFalse(any(p.is_file() for p in tree.rglob(name)), (label, 'legacy backend', name))
                for name in ('ksmbd.ko', 'nls_ucs2_utils.ko', 'cifs_md4.ko'):
                    self.assertEqual(any(p.is_file() for p in tree.rglob(name)), 'sharing' in selected, (label, name))
                self.assertEqual([n for n in (tree/'usr/share/slot/features-v1').read_text().splitlines()[1:] if n],sorted(selected))
                absent={u for u in catalog['optional_units'] if not (tree/'usr/lib/systemd/system'/u).exists()}
                for p in (tree/'usr/lib/systemd/system').rglob('*'):
                    if p.is_symlink() or not p.is_file():continue
                    for line in p.read_text().splitlines():
                        key,sep,value=line.partition('=')
                        if sep and key in {'Wants','Requires','After','Before','Requisite','BindsTo','PartOf'}:self.assertFalse(absent & set(value.split()),(label,str(p),line))
            bad=root/'bad-kit';bad.symlink_to(kit,target_is_directory=True)

if __name__=='__main__':unittest.main()
