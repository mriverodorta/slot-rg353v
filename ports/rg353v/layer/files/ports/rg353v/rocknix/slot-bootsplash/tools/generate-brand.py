#!/usr/bin/env python3
"""Bake Open Sans Bold coverage masks for a dependency-free early boot renderer."""
import argparse, hashlib, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
p=argparse.ArgumentParser();p.add_argument('font',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
logo_font=ImageFont.truetype(str(a.font),76)
assert logo_font.getname()==('Open Sans','Bold')
def raster(text,font,spacing=0):
 boxes=[font.getbbox(c) for c in text];width=round(sum(font.getlength(c) for c in text)+spacing*(len(text)-1));top=min(b[1] for b in boxes);height=max(b[3] for b in boxes)-top
 image=Image.new('L',(width,height));draw=ImageDraw.Draw(image);x=0
 for c in text:draw.text((round(x),-top),c,font=font,fill=255);x+=font.getlength(c)+spacing
 return image
logo=raster('slot.',logo_font,-3.4)
digits_font=ImageFont.truetype(str(a.font),18)
glyphs=[raster(c,digits_font) for c in '0123456789%']
with a.output.open('w') as f:
 f.write('/* Open Sans Bold coverage masks. Source font under SIL OFL 1.1. */\n')
 for name,image in [('logo',logo)]+[('digit_'+str(i),im) for i,im in enumerate(glyphs)]:
  f.write(f'static const int {name}_w={image.width}, {name}_h={image.height};\nstatic const unsigned char {name}[]={{\n')
  values=list(image.tobytes())
  for n in range(0,len(values),32):f.write(','.join(map(str,values[n:n+32]))+',\n')
  f.write('};\n')
 f.write('static const unsigned char *digits[]={'+','.join('digit_'+str(i) for i in range(11))+'};\n')
 f.write('static const int digits_w[]={'+','.join(str(im.width) for im in glyphs)+'};\n')
 f.write('static const int digits_h[]={'+','.join(str(im.height) for im in glyphs)+'};\n')
(a.output.parent/'brand-provenance.json').write_text(json.dumps({'family':logo_font.getname(),'font_sha256':hashlib.sha256(a.font.read_bytes()).hexdigest(),'text':'slot.','source':'Official Slot crates/slot-ui/assets/label.ttf (Open Sans Bold)','tracking_px':-3.4},indent=2)+'\n')
