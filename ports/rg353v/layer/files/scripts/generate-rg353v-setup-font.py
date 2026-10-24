#!/usr/bin/env python3
"""Bake Slot text and Nerd Font symbols for a dependency-free first-boot UI."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import sys
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[1]
source = root/'ports/rg353v/image/assets/label.ttf'
output = Path(sys.argv[1]) if len(sys.argv)>1 else root/'ports/rg353v/image/slot-setup-font.json.gz'
symbols_source=root/'ports/rg353v/image/assets/SymbolsNerdFontMono-Regular.ttf'
scroll_source=root/'ports/rg353v/image/assets/setup-scroll-symbols.ttf'
symbols=json.loads((root/'ports/rg353v/image/slot-setup-symbols.json').read_text())
menu_source=root/'ports/rg353v/image/assets/setup-menu-icons.ttf'
menu_icons=json.loads((root/'ports/rg353v/image/slot-setup-menu-icons.json').read_text())
result = {'schema':1,'font_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'symbols_font_sha256':hashlib.sha256(symbols_source.read_bytes()).hexdigest(),
          'scroll_font_sha256':hashlib.sha256(scroll_source.read_bytes()).hexdigest(),
          'symbols_copyright':'Copyright (c) 2016, Ryan McIntyre',
          'symbols':symbols,'menu_icons':menu_icons,
          'menu_icons_font_sha256':hashlib.sha256(menu_source.read_bytes()).hexdigest(),
          'fonts':{}}

def glyph(font,c):
    box=font.getbbox(c);w,h=box[2]-box[0],box[3]-box[1]
    image=Image.new('L',(max(1,w),max(1,h)))
    ImageDraw.Draw(image).text((-box[0],-box[1]),c,font=font,fill=255)
    return {'advance':round(font.getlength(c)),'box':box,'mask':base64.b64encode(image.tobytes()).decode()}

for name,size in [('logo',52),('title',24),('body',20),('small',15)]:
    font = ImageFont.truetype(str(source),size)
    glyphs = {}
    for code in range(32,127):
        c=chr(code);glyphs[c]=glyph(font,c)
    result['fonts'][name]={'size':size,'glyphs':glyphs}
font=ImageFont.truetype(str(symbols_source),14)
# Keep the normal renderer's question-mark fallback available in every style.
glyphs={'?':result['fonts']['small']['glyphs']['?']}
scroll_font=ImageFont.truetype(str(scroll_source),14)
for char in sorted(set(symbols.values())):
    glyphs[char]=glyph(scroll_font if char in (symbols['up'],symbols['down']) else font,char)
result['fonts']['symbols']={'size':14,'glyphs':glyphs}

font=ImageFont.truetype(str(menu_source),24)
glyphs={'?':result['fonts']['small']['glyphs']['?']}
for char in sorted(set(menu_icons.values())):glyphs[char]=glyph(font,char)
result['fonts']['menu-icons']={'size':24,'glyphs':glyphs}

with output.open('wb') as stream:
    with gzip.GzipFile(fileobj=stream,mode='wb',mtime=0,filename='') as compressed:
        compressed.write(json.dumps(result,separators=(',',':')).encode())
print(output,output.stat().st_size)
