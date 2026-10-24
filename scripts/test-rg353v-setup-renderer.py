#!/usr/bin/env python3
"""Installer pixel packing, clipping and private module-flow regression checks."""
import importlib.util
from pathlib import Path
import unittest
import json
import gzip
import hashlib

ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('ui',ROOT/'ports/rg353v/image/slot-setup-ui.py');u=importlib.util.module_from_spec(s);s.loader.exec_module(u)
class Renderer(unittest.TestCase):
    def test_confirmation_displays_the_selected_layout_including_legacy_media(self):
        for layout,labels in [({'boot_mib':512,'storage_mib':512},('512 MiB','512 MiB')),
                              ({'boot_mib':1024,'storage_mib':5120},('1 GiB','5 GiB'))]:
            info={'bytes':31268536320,'content_bytes':28000000000,'layout':layout}
            model=u.Model(info,info);model.action='sd';model.page='confirm'
            canvas=u.Canvas(ROOT/'ports/rg353v/image/slot-setup-font.json.gz');seen=[]
            original=canvas.text
            def text(value,x,y,font='body',color=u.FG):
                if (x,y) in ((204,127),(204,154)):seen.append(value)
                return original(value,x,y,font,color)
            canvas.text=text;model.draw(canvas)
            self.assertEqual(tuple(seen),labels)
    def test_pack_channels_and_zero_unused_byte(self):
        pixels=bytearray([1,2,3,255,4,5,6,255])
        self.assertEqual(u.Framebuffer.pack(pixels,(16,8,0)),bytes([3,2,1,0,6,5,4,0]))
        self.assertEqual(u.Framebuffer.pack(pixels,(0,8,16)),bytes([1,2,3,0,4,5,6,0]))
        self.assertEqual(u.Framebuffer.pack(pixels,(8,16,24)),bytes([0,1,2,3,0,4,5,6]))
    def test_framebuffer_offsets_stride_and_padding(self):
        fb=u.Framebuffer.__new__(u.Framebuffer);fb.channels=[(16,8,0),(8,8,0),(0,8,0)];fb.stride=(u.W+4)*4;fb.xoff=2;fb.yoff=1
        fb.fb=bytearray(b'\x7f'*(fb.stride*(u.H+2)))
        c=type('Canvas',(),{'pixels':bytearray([1,2,3,255]*(u.W*u.H))})()
        fb.show(c)
        self.assertEqual(fb.fb[:fb.stride],b'\x7f'*fb.stride)
        for y in (1,u.H):
            row=fb.fb[y*fb.stride:(y+1)*fb.stride]
            self.assertEqual(row[:8],b'\x7f'*8);self.assertEqual(row[8:-8],bytes([3,2,1,0])*u.W);self.assertEqual(row[-8:],b'\x7f'*8)
    def test_cached_raster_clipping_and_overlapping_text_matches_scalar(self):
        c=u.Canvas(ROOT/'ports/rg353v/image/slot-setup-font.json.gz')
        # Compare one general alpha-composite reference across all glyphs,
        # clipping edges and a nonuniform backing that takes the fallback path.
        for x,y in ((-10,-8),(590,460),(40,40)):
            c.clear();c.rect(50,40,20,40,(140,70,20));expected=c.pixels.copy();text='slot. Aa123@'
            at=x
            for char in text:
                g=c.fonts['body']['glyphs'][char];l,t,r,b=g['box'];mask=g['mask'];w=r-l
                for row in range(b-t):
                    for col in range(w):
                        alpha=mask[row*max(1,w)+col];px,py=at+l+col,y+t+row
                        if alpha and 0<=px<u.W and 0<=py<u.H:
                            for n in range(3):
                                i=(py*u.W+px)*4+n;expected[i]=(expected[i]*(255-alpha)+u.FG[n]*alpha)//255
                at+=g['advance']
            self.assertEqual(c.text(text,x,y),at);self.assertEqual(c.pixels,expected)
    def test_symbols_match_bundled_nerd_font_and_fit_white_button_caps(self):
        data=json.loads(gzip.decompress((ROOT/'ports/rg353v/image/slot-setup-font.json.gz').read_bytes()))
        source=ROOT/'ports/rg353v/image/assets/SymbolsNerdFontMono-Regular.ttf'
        self.assertEqual(data['symbols_font_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(data['symbols'],json.loads((ROOT/'ports/rg353v/image/slot-setup-symbols.json').read_text()))
        canvas=u.Canvas(ROOT/'ports/rg353v/image/slot-setup-font.json.gz')
        glyphs=canvas.fonts['symbols']['glyphs']
        self.assertNotEqual(glyphs[data['symbols']['left']]['mask'],glyphs[data['symbols']['right']]['mask'])
        for name,char in data['symbols'].items():
            glyph=glyphs[char];l,t,r,b=glyph['box']
            self.assertTrue(any(glyph['mask']),name)
            self.assertLessEqual(r-l,23,name);self.assertLessEqual(b-t,21,name)
            canvas.clear();canvas.badge(name,'',20,20)
            changed=[]
            for y in range(18,46):
                for x in range(18,46):
                    at=(y*u.W+x)*4
                    if canvas.pixels[at:at+3]!=bytes(u.BG):changed.append((x,y))
            self.assertTrue(changed,name)
            self.assertTrue(all(20<=x<43 and 22<=y<43 for x,y in changed),name)

    def test_every_feature_modal_renders_bounded_text_and_native_close_hint(self):
        catalog=json.loads((ROOT/'ports/rg353v/modules/catalog-v1.json').read_text())
        model=u.Model({'content_bytes':1},None,modules=catalog);model.key('a');model.selected=u.preset_index('custom');model.key('a')
        canvas=u.Canvas(ROOT/'ports/rg353v/image/slot-setup-font.json.gz')
        for index,feature in enumerate(catalog['modules']):
            self.assertIsInstance(feature['description'],str)
            lines=canvas.wrap(feature['description'],528)
            self.assertLessEqual(len(lines),4,feature['id'])
            self.assertTrue(all(canvas.measure(line)<=528 for line in lines),feature['id'])
            self.assertLessEqual(canvas.measure(feature['label'],'title'),528,feature['id'])
            model.selected=index;model.module_first=max(0,index-6);model.key('y');model.draw(canvas)
            self.assertEqual(len(canvas.pixels),u.W*u.H*4)
            self.assertEqual(canvas.pixels[(430*u.W+270)*4:(430*u.W+270)*4+3],bytes(u.FG))
            model.key('b')
        # Older catalogs still have a usable explanation instead of crashing.
        model.modules={'modules':[{'id':'wifi','label':'Wi-Fi','requires':[]}]}
        model.selected=0;model.module_first=0;model.key('y');model.draw(canvas)

    def test_grouped_review_completion_and_warnings_fit_and_scroll(self):
        catalog=json.loads((ROOT/'ports/rg353v/modules/catalog-v1.json').read_text())
        source={'bytes':60492349440,'content_bytes':54000000000}
        canvas=u.Canvas(ROOT/'ports/rg353v/image/slot-setup-font.json.gz')
        original=canvas.text;seen=[]
        def text(value,x,y,font='body',color=u.FG):
            self.assertGreaterEqual(x,0,(value,x,y));self.assertGreaterEqual(y,0,(value,x,y))
            self.assertLessEqual(x+canvas.measure(value,font),640,(value,x,y))
            self.assertLess(y,464,(value,x,y));seen.append(value)
            return original(value,x,y,font,color)
        canvas.text=text
        for features in ({'emulator-gpsp'}, {m['id'] for m in catalog['modules']},
                         {'emulator-mgba','ssh','sharing','updates'}):
            model=u.Model(source,source,modules=catalog,sd_test=True);model.action='sd';model.features=features.copy()
            model.page='modules'
            for index in range(len(catalog['modules'])+1):model.selected=index;model.draw(canvas)
            for page in ('review','done'):
                model.page=page;model.text_first=0;model.draw(canvas)
                length=model.document_length
                for _ in range(length+2):model.key('down');model.draw(canvas)
                self.assertEqual(model.text_first,model.document_limit)
                for _ in range(length+2):model.key('up');model.draw(canvas)
                self.assertEqual(model.text_first,0)
            if model.choice_warnings():model.access();model.draw(canvas)
        self.assertIn('while pressing ',seen)
        self.assertIn('to boot this SD.',seen)
        self.assertFalse(any('test SD' in text for text in seen))
        regular=u.Model(source,None,modules=catalog);regular.action='sd';regular.page='done'
        seen.clear();regular.draw(canvas);self.assertNotIn('to boot this SD.',seen)

    def test_private_modules_have_one_feature_page_and_no_duplicate_debug_page(self):
        catalog=json.loads((ROOT/'ports/rg353v/modules/catalog-v1.json').read_text())
        m=u.Model({'bytes':60492349440,'content_bytes':54000000000},None,{'wifi':[1],'authorized_keys':['public']},catalog)
        m.key('a');self.assertEqual(m.page,'presets');m.selected=u.preset_index('custom');m.key('a');self.assertEqual(m.page,'modules');m.key('up');m.key('a')
        self.assertEqual(m.page,'review');self.assertEqual(m.options,{'wifi':True,'usb':True,'ssh':True})
        m=u.Model({'bytes':60492349440,'content_bytes':54000000000},None,{'wifi':[1],'authorized_keys':['public']},catalog)
        m.features.discard('developer');m.key('a');m.selected=u.preset_index('custom');m.key('a');m.key('up');m.key('a')
        self.assertEqual(m.options,{'wifi':False,'usb':False,'ssh':False})
if __name__=='__main__':unittest.main()
