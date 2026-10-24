#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('exporter',Path(__file__).with_name('export-rg353v-wiki.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class WikiExport(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.wiki=self.root/'wiki';self.wiki.mkdir()
        for name in ['Home.md','Other-Page.md','_Sidebar.md','_Footer.md']:(self.wiki/name).write_text('# Guide\n')
        (self.root/'CREDITS.md').write_text('credits')
        (self.wiki/'image.png').write_bytes(b'fixture')
    def render(self,text):return m.rewrite(text,self.wiki/'Home.md',self.wiki,'owner/repo','v1.2.3')
    def test_page_links_keep_anchors_and_use_wiki_urls(self):
        self.assertEqual(self.render('[Next](Other-Page.md#one)'), '[Next](https://github.com/owner/repo/wiki/Other-Page#one)')
    def test_credit_links_target_the_matching_source_ref(self):
        self.assertEqual(self.render('[Credits](../CREDITS.md)'), '[Credits](https://github.com/owner/repo/blob/v1.2.3/CREDITS.md)')
    def test_images_embed_from_the_versioned_source(self):
        self.assertEqual(self.render('![UI](image.png)'), '![UI](https://raw.githubusercontent.com/owner/repo/v1.2.3/wiki/image.png)')
    def test_external_links_anchors_and_code_examples_remain_unchanged(self):
        text='[Source](https://example.org/path) [Here](#here)\n```md\n[Next](Other-Page.md)\n```'
        self.assertEqual(self.render(text),text)
    def test_missing_and_escaping_links_fail_without_an_export(self):
        for text in ['[Missing](Missing.md)','[Outside](../../file.md)']:
            with self.assertRaises(ValueError):self.render(text)
        self.assertFalse((self.root/'export').exists())
    def test_export_is_local_and_refuses_overwriting_a_reviewed_copy(self):
        out=self.root/'export';report=m.export(self.wiki,out,'owner/repo','v1')
        self.assertEqual(report['pages'],4);self.assertIn('Local export only',report['publication'])
        with self.assertRaises(ValueError):m.export(self.wiki,out,'owner/repo','v1')
    def test_video_download_links_are_rejected(self):
        (self.wiki/'boot.mp4').write_bytes(b'fixture')
        with self.assertRaises(ValueError):self.render('[Download](boot.mp4)')
if __name__=='__main__':unittest.main()
