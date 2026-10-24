#!/usr/bin/env python3
"""Silent framebuffer/evdev installer UI. No compositor or audio services."""
import array
import base64
import fcntl
import gzip
import json
import mmap
import os
from pathlib import Path
import select
import struct
import time
import threading

W,H=640,480
BG=(14,16,22); FG=(244,245,249); DIM=(169,177,189); CYAN=(83,224,249)


def size(n):
    return f'{n/1024**3:.1f} GiB'


class Canvas:
    def __init__(self,font):
        data=json.loads(gzip.decompress(Path(font).read_bytes()))
        self.fonts=data['fonts'];self.symbols=data['symbols'];self.menu_icons=data['menu_icons']
        for font in self.fonts.values():
            for glyph in font['glyphs'].values(): glyph['mask']=base64.b64decode(glyph['mask'])
        self.rasters={};self.blends={}
        for font in self.fonts.values():
            for glyph in font['glyphs'].values():
                l,t,r,b=glyph['box'];width=r-l;runs=[]
                for row in range(b-t):
                    mask=glyph['mask'][row*max(1,width):(row+1)*max(1,width)]
                    col=0
                    while col<width:
                        if not mask[col]:col+=1;continue
                        start=col
                        while col<width and mask[col]:col+=1
                        runs.append((row,start,mask[start:col]))
                glyph['runs']=runs
        self.clear()

    def clear(self): self.pixels=bytearray(bytes((*BG,255))*(W*H))

    def rect(self,x,y,w,h,color):
        left=max(0,x);right=min(W,x+w)
        if right<=left:return
        data=bytes((*color,255))*(right-left)
        for row in range(max(0,y),min(H,y+h)):
            self.pixels[(row*W+left)*4:(row*W+right)*4]=data

    def text(self,text,x,y,font='body',color=FG):
        for c in text:
            g=self.fonts[font]['glyphs'].get(c,self.fonts[font]['glyphs']['?'])
            l,t,_,_=g['box']
            for row,col,mask in g['runs']:
                px,py=x+l+col,y+t+row
                if py<0 or py>=H or px>=W or px+len(mask)<=0:continue
                if px<0:mask=mask[-px:];px=0
                mask=mask[:W-px];i=(py*W+px)*4;j=i+len(mask)*4
                under=self.pixels[i:j];bg=tuple(under[:3])
                if under==bytes((*bg,255))*len(mask):
                    key=(mask,color,bg);pixels=self.rasters.get(key)
                    if pixels is None:
                        style=(color,bg);tables=self.blends.get(style)
                        if tables is None:
                            tables=tuple(bytes((bg[n]*(255-a)+color[n]*a)//255 for a in range(256)) for n in range(3))
                            self.blends[style]=tables
                        pixels=bytearray(len(mask)*4)
                        for n in range(3):pixels[n::4]=mask.translate(tables[n])
                        pixels[3::4]=b'\xff'*len(mask);pixels=bytes(pixels)
                        if len(self.rasters)>=16384:self.rasters.clear()
                        self.rasters[key]=pixels
                    self.pixels[i:j]=pixels
                else:
                    # Preserve alpha compositing where glyphs overlap artwork.
                    for col,alpha in enumerate(mask):
                        for n in range(3):
                            at=i+col*4+n
                            self.pixels[at]=(self.pixels[at]*(255-alpha)+color[n]*alpha)//255
            x+=g['advance']
        return x

    def measure(self,text,font='body'):
        glyphs=self.fonts[font]['glyphs']
        return sum(glyphs.get(c,glyphs['?'])['advance'] for c in text)

    def centered_text(self,text,x,center_y,font='small',color=FG):
        glyphs=self.fonts[font]['glyphs']
        boxes=[glyphs.get(char,glyphs['?'])['box'] for char in text if not char.isspace()]
        top=min((b[1] for b in boxes),default=0);bottom=max((b[3] for b in boxes),default=0)
        return self.text(text,x,round(center_y-(top+bottom)/2),font,color)

    def wrap(self,text,width,font='body'):
        lines=[];line=''
        for word in text.split():
            joined=(line+' '+word).strip()
            if line and self.measure(joined,font)>width:
                lines.append(line);line=word
            else:line=joined
        if line:lines.append(line)
        return lines

    def dim(self):
        table=bytes(n*2//5 for n in range(256))
        for channel in range(3):self.pixels[channel::4]=self.pixels[channel::4].translate(table)

    def symbol(self,name,x,y,width=23,height=21,color=FG):
        char=self.symbols[name];g=self.fonts['symbols']['glyphs'][char]
        l,t,r,b=g['box']
        # Centre actual ink, as Slot's normal white button caps do.
        self.text(char,x+(width-(r-l))//2-l,y+(height-(b-t))//2-t,'symbols',color)

    def menu_icon(self,name,x,y,color=FG):
        char=self.menu_icons.get(name)
        if char is None:return
        l,t,r,b=self.fonts['menu-icons']['glyphs'][char]['box']
        self.text(char,x+(26-(r-l))//2-l,y+(24-(b-t))//2-t,'menu-icons',color)

    def badge(self,key,label,x,y):
        self.rect(x,y+2,23,21,FG)
        if key in self.symbols:self.symbol(key,x,y+2,color=BG)
        else:self.text(key,x+5,y+1,'small',BG)
        self.text(label,x+29,y,'small')

    def toggle(self,enabled,x,y,font='small',color=FG):
        value='ON' if enabled else 'OFF';width=self.measure('OFF',font)
        self.symbol('left',x-24,y+2,16,20,color)
        self.text(value,x+(width-self.measure(value,font))//2,y,font,color)
        self.symbol('right',x+width+9,y+2,16,20,color)

    def ppm(self,path):
        rgb=bytearray(W*H*3)
        for c in range(3):rgb[c::3]=self.pixels[c::4]
        Path(path).write_bytes(b'P6\n640 480\n255\n'+rgb)


PRESETS = (
    ('minimal','Minimal','preset-minimal',
     'mGBA for GB, GBC and GBA. Just the essentials; no optional connections or game effects.',
     frozenset({'emulator-mgba'})),
    ('recommended','Recommended','preset-recommended',
     'mGBA, USB Storage, TF1 / TF2 games, shaders, overlays and rewind.',
     frozenset({'emulator-mgba','usb-storage','external-sd','filters','overlays','rewind'})),
    ('full','Full','review',
     'All emulators and every available feature, including networking and developer tools.', None),
    ('custom','Custom','preset-custom',
     'Choose your emulators and optional features. Keeps your current selection.', None),
)

def preset_index(name):
    return next(index for index,preset in enumerate(PRESETS) if preset[0]==name)


class Model:
    def __init__(self,source,target,debug=None,modules=None,sd_test=False):
        self.source,self.target=source,target
        self.sd_test=sd_test;self.text_first=0;self.document_length=0;self.document_limit=0
        self.page='choose';self.selected=0;self.action=None
        self.status='';self.percent=0;self.install_started=None;self.elapsed=0;self.activity_frame=0
        self.preset='custom';self.preset_cursor=preset_index('full' if debug else 'minimal')
        self.debug=debug
        self.debug_status=''
        self.modules=modules
        self.features={'emulator-mgba'} if modules and any(m['id']=='emulator-mgba' for m in modules['modules']) else set()
        self.module_first=0
        self.help_open=False
        self.message=''
        if modules and debug:
            self.features={m['id'] for m in modules['modules']} - {'sharing','network-time'}
        self.warning=None
        self.options={'wifi':bool(debug and debug['wifi']),'usb':bool(debug),'ssh':bool(debug and debug['authorized_keys'])}

    def key(self,key):
        if self.help_open:
            if key=='b':self.help_open=False
            return None
        if self.page=='choose':
            if key in ('up','down'):self.selected=1-self.selected
            if key=='b':return 'poweroff'
            allowed=self.source.get('content_bytes') is not None if self.selected==0 else self.target is not None
            if key=='a' and allowed:
                self.action='sd' if self.selected==0 else 'emmc'
                self.page='presets' if self.modules else ('debug' if self.debug else 'confirm')
                self.selected=self.preset_cursor if self.modules else 0
        elif self.page=='presets':
            row,col=divmod(self.selected,2)
            if key in ('left','right'):self.selected=row*2+(col+1)%2
            if key in ('up','down'):self.selected=((row+1)%2)*2+col
            if key=='b':self.page='choose';self.selected=int(self.action=='emmc')
            elif key=='a':
                name,_,_,_,features=PRESETS[self.selected]
                self.preset=name;self.preset_cursor=self.selected;self.message=''
                if name=='custom':
                    self.page='modules';self.selected=0;self.scroll_features()
                else:
                    available={m['id'] for m in self.modules['modules']}
                    # Full follows the supplied catalog, including future modules.
                    self.features=available if name=='full' else set(features)&available
                    self.prepare_options();self.go_review()
        elif self.page=='modules':
            count=len(self.modules['modules'])+1
            if key=='y' and self.selected<count-1:
                self.help_open=True;return None
            if key in ('up','down'):self.message=''
            if key=='up':self.selected=(self.selected-1)%count
            if key=='down':self.selected=(self.selected+1)%count
            if key=='b':self.page='presets';self.selected=preset_index('custom')
            elif key=='a' and self.selected==count-1:
                if any(m['id'].startswith('emulator-') for m in self.modules['modules']) and not self.features & {'emulator-mgba','emulator-gpsp'}:
                    self.message='Select at least one emulator';return None
                self.message=''
                self.preset='custom';self.prepare_options()
                self.access()
            elif key in ('a','left','right') and self.selected<count-1:
                self.change_feature(self.modules['modules'][self.selected])
            self.scroll_features()
        elif self.page=='access':
            if key in ('up','down'):self.selected=1-self.selected
            if key=='b' or (key=='a' and self.selected==0):self.page='modules';self.selected=0
            elif key=='a' and self.selected==1:self.go_review()
        elif self.page=='debug':
            if key=='up':self.selected=(self.selected-1)%4
            if key=='down':self.selected=(self.selected+1)%4
            if key=='b':self.page='modules' if self.modules else 'choose';self.selected=0
            elif key=='a' and self.selected==3:self.access()
            elif key in ('a','left','right') and self.selected<3:
                name=('wifi','usb','ssh')[self.selected]
                feature={'wifi':'wifi','usb':'usb-network','ssh':'ssh'}[name]
                if self.modules and (feature not in self.features or 'developer' not in self.features):return None
                if name!='wifi' or self.debug['wifi']:
                    if name!='ssh' or self.debug['authorized_keys']:self.options[name]=not self.options[name]
                if not self.options['wifi'] and not self.options['usb']:self.options['ssh']=False
        elif self.page=='review':
            if key=='up':self.text_first=max(0,self.text_first-1)
            if key=='down':self.text_first=min(self.document_limit,self.text_first+1)
            if key=='b':
                if self.preset=='custom':
                    self.page='modules';self.selected=len(self.modules['modules']);self.scroll_features()
                else:self.page='presets';self.selected=self.preset_cursor
            if key=='a':self.page='confirm';self.selected=0
        elif self.page=='confirm':
            if key in ('up','down'):self.selected=1-self.selected
            if key=='b' or (key=='a' and self.selected==0):
                if self.modules:self.go_review()
                else:self.page='choose';self.selected=0
            elif key=='a' and self.selected==1:
                self.page='progress';return self.action
        elif self.page=='done':
            if key=='up':self.text_first=max(0,self.text_first-1)
            if key=='down':self.text_first=min(self.document_limit,self.text_first+1)
            if key=='a':return 'reboot'
            if key=='b':return 'poweroff'
        elif self.page=='error' and key=='b':self.page='choose';self.selected=0
        return None

    def prepare_options(self):
        profile=self.debug or {}
        available={'wifi':bool(profile.get('wifi')),'usb':bool(self.debug),'ssh':bool(profile.get('authorized_keys'))}
        self.options={k:available[k] and feature in self.features and 'developer' in self.features
                      for k,feature in [('wifi','wifi'),('usb','usb-network'),('ssh','ssh')]}

    def tick_progress(self,now):
        if self.install_started is None:self.install_started=now
        duration=max(0,now-self.install_started)
        self.elapsed=int(duration);self.activity_frame=int(duration*2)%3

    def feature_entries(self):
        entries=[];group=None
        for index,feature in enumerate(self.modules['modules']):
            label=feature.get('group','Features')
            if label!=group:
                entries.append(('group',label,None));group=label
            entries.append(('feature',feature['label'],index))
        entries.append(('continue','REVIEW INSTALLATION',len(self.modules['modules'])))
        return entries

    def scroll_features(self):
        entries=self.feature_entries();at=next(i for i,e in enumerate(entries) if e[2]==self.selected)
        self.module_first=max(0,min(self.module_first,max(0,len(entries)-9)))
        if at<self.module_first:self.module_first=at
        if at>=self.module_first+9:self.module_first=at-8
        header=next((i for i in range(at,-1,-1) if entries[i][0]=='group'),None)
        if header is not None and at-header<9 and header<self.module_first:self.module_first=header

    def unavailable(self,feature):
        missing=set(feature.get('available_with',[]))-self.features
        return 'Requires mGBA; choose it under Emulators.' if missing else None

    def change_feature(self,feature):
        blocked=self.unavailable(feature)
        if blocked and feature['id'] not in self.features:self.message=blocked;return
        before=set(self.features);name=feature['id']
        if name in self.features:
            self.features.remove(name)
            for item in self.modules['modules']:
                if item['id'] not in self.features:continue
                required=set(item.get('requires',[]))|set(item.get('available_with',[]))
                alternatives=item.get('requires_any',[])
                if not required<=self.features or any(not self.features.intersection(g) for g in alternatives):
                    self.features.discard(item['id'])
            if 'ssh' not in self.features or not self.features & {'wifi','usb-network'}:
                self.features.discard('developer')
        else:
            self.features.add(name)
            self.features.update(feature.get('requires',[]))
            for group in feature.get('requires_any',[]):
                if not self.features.intersection(group):self.features.add(group[0])
            if name=='developer':
                self.features.add('ssh')
                if not self.features & {'wifi','usb-network'}:self.features.add('usb-network')
        labels={v['id']:v['label'] for v in self.modules['modules']}
        added=(self.features-before)-{name};removed=(before-self.features)-{name}
        if added:self.message='Also added: '+', '.join(labels[n] for n in sorted(added))+'.'
        elif removed:self.message='Also turned off: '+', '.join(labels[n] for n in sorted(removed))+'.'
        elif name=='network-time' and name in self.features and 'wifi' not in self.features:
            self.message='Network Time will use Internet via USB.'
        else:self.message=''

    def feature_hint(self):
        if self.message:return self.message
        if self.selected>=len(self.modules['modules']):return 'Check your choices before installing.'
        feature=self.modules['modules'][self.selected]
        if self.unavailable(feature):return self.unavailable(feature)
        if feature['id'] in ('ssh','sharing') and not self.features & {'wifi','usb-network'}:
            return 'Needs Wi-Fi or USB Networking to connect.'
        if feature['id']=='network-time' and 'wifi' not in self.features and 'usb-network' in self.features:
            return 'Needs Internet via USB, shared by the computer.'
        return ''

    def transfer_routes(self):
        routes=[];features=self.features
        if 'usb-storage' in features:routes.append(('USB Storage','In Settings > Connections > USB, turn on USB Storage. Connect the DC USB-C port; safely eject after copying.'))
        transport='Wi-Fi or USB Networking' if {'wifi','usb-network'}<=features else 'Wi-Fi' if 'wifi' in features else 'USB Networking' if 'usb-network' in features else None
        if transport and 'sharing' in features:
            routes.append(('File Sharing (SMB)','Turn on '+transport+', then File Sharing. Use the SMB address shown.'))
        if transport and 'ssh' in features:
            routes.append(('SSH / SFTP','Turn on '+transport+', then SSH. Use SFTP to copy games into /storage/slotcontent/Games.'))
        if 'external-sd' in features:routes.append(('Games from TF1 / TF2','Use an exFAT card with Games folders. Insert on the shelf to discover games automatically.'))
        if self.action=='sd':routes.append(('Computer card reader','Power off before removing this SD. Open its SLOT partition on your computer.'))
        return routes

    def choice_warnings(self):
        warnings=[];transport=bool(self.features & {'wifi','usb-network'})
        if not transport and self.features & {'ssh','sharing'}:
            names='SSH and File Sharing' if {'ssh','sharing'}<=self.features else 'SSH' if 'ssh' in self.features else 'File Sharing'
            warnings.append(names+' cannot connect without Wi-Fi or USB Networking.')
        if not transport and 'updates' in self.features:
            warnings.append('OTA downloads need Wi-Fi or Internet via USB.')
        if self.action=='emmc' and not self.transfer_routes():
            warnings.append('No way to add games is selected. Internal storage cannot be removed; reinstall may be needed.')
        return warnings

    def go_review(self):
        self.page='review' if self.modules else 'confirm';self.selected=0;self.text_first=0

    def access(self):
        self.warning=self.choice_warnings() if self.modules else []
        if self.warning:self.page='access';self.selected=0
        else:self.go_review()

    def supported_systems(self):
        if not self.modules or not any(m['id'].startswith('emulator-') for m in self.modules['modules']) or 'emulator-mgba' in self.features:return ['GB','GBC','GBA']
        return ['GBA'] if 'emulator-gpsp' in self.features else []

    def review_blocks(self):
        info=self.target if self.action=='emmc' else self.source
        blocks=[('Destination',('Internal storage' if self.action=='emmc' else 'This SD card')+' / '+size(info['bytes']),'install-emmc' if self.action=='emmc' else 'install-sd'),
                ('Supported consoles',' / '.join(self.supported_systems()),'emulator-mgba')]
        blocks.append(('Setup preset',self.preset.title(),'preset-'+self.preset))
        groups={}
        for feature in self.modules['modules']:
            if feature['id'] in self.features:groups.setdefault(feature.get('group','Features'),[]).append(feature)
        for group,features in groups.items():
            blocks.append((group,', '.join(v['label'] for v in features),features[0]['id']))
        routes=self.transfer_routes()
        blocks.append(('Adding games',', '.join(name for name,_ in routes) if routes else 'No game-transfer route selected.','external-sd'))
        for warning in self.choice_warnings():blocks.append(('Check this choice',warning,'warning'))
        startup='No network features installed.'
        if 'developer' in self.features:startup='Developer Mode keeps selected debug services available.'
        elif self.features & {'wifi','usb-network','ssh','sharing','network-time'}:startup='Connections and network services stay off until you enable them.'
        blocks.append(('At startup',startup,'developer'))
        return blocks

    def completion_blocks(self):
        blocks=[('Installation complete','Your selected features are installed.','done')]
        systems=self.supported_systems()
        blocks.append(('Game folders',' / '.join('Games/'+s for s in systems),'emulator-mgba'))
        routes=self.transfer_routes() if self.modules else [('Adding games','Use File Sharing or USB Storage in Settings > Connections to copy games.')]
        blocks.extend((name,text,'usb-storage' if name=='USB Storage' else 'external-sd' if name in ('Computer card reader','Games from TF1 / TF2') else 'sharing' if name=='File Sharing (SMB)' else 'ssh') for name,text in routes)
        if not routes:blocks.append(('Adding games','No transfer method was selected. Reinstall with a transfer feature to add games.','warning'))
        if not self.modules or ('developer' not in self.features and self.features & {'wifi','usb-network','ssh','sharing'}):
            blocks.append(('Connections','Installed network features start off. Enable them in Settings when needed.','usb-network'))
        return blocks

    def text_lines(self,c,blocks):
        lines=[]
        for title,body,icon in blocks:
            lines.append((title,'heading',icon))
            lines.extend((line,'body',None) for line in c.wrap(body,532,'body'))
        return lines

    @staticmethod
    def document_window(lines,first):
        rows=[];y=93
        for at in range(first,len(lines)):
            text,kind,icon=lines[at]
            if at>first and kind=='heading':y+=12
            # Keep a category label with at least its first content line.
            needed=46 if kind=='heading' and at+1<len(lines) else 24
            if y+needed>370:break
            rows.append((at,text,kind,icon,y));y+=22 if kind=='heading' else 31
        return rows

    def draw_document(self,c,title,blocks):
        c.menu_icon('done' if self.page=='done' else 'review',32,32);c.text(title,72,30,'title')
        lines=self.text_lines(c,blocks);self.document_length=len(lines)
        limit=max(0,len(lines)-1)
        while limit>0:
            previous=self.document_window(lines,limit-1)
            if not previous or previous[-1][0]!=len(lines)-1:break
            limit-=1
        self.document_limit=limit;self.text_first=max(0,min(self.text_first,limit))
        rows=self.document_window(lines,self.text_first)
        for at,text,kind,icon,y in rows:
            if kind=='heading':
                c.menu_icon(icon,32,y-2,CYAN);c.centered_text(text,68,y+10,'small',CYAN)
            else:c.text(text,68,y,'body')
        if limit and rows:c.text(str(self.text_first+1)+'-'+str(rows[-1][0]+1)+' / '+str(len(lines)),542,376,'small',DIM)
        if self.page=='done':
            if self.action=='sd' and self.sd_test:
                x=c.text('Hold ',32,396,'small',CYAN)
                c.badge('F','',x,396);x+=29
                x=c.text('while pressing ',x,396,'small',CYAN)
                c.badge('A','',x,396);x+=29
                c.text('to boot this SD.',x,396,'small',CYAN)
            elif self.action=='emmc':
                x=c.text('Restart normally. Hold ',32,396,'small',DIM)
                c.badge('F','',x,396)
                c.text('at power-on for TF1.',x+29,396,'small',DIM)
            else:c.text('Power off before removing the SD card.',32,396,'small',DIM)
            c.badge('B','POWER OFF',32,428);c.badge('A','RESTART',470,428)
            if limit:c.badge('up','',246,428);c.badge('down','SCROLL',273,428)
        else:
            c.text('Review only. Press B to change your selection.',32,396,'small',DIM)
            c.badge('B','CHANGE',32,428);c.badge('A','NEXT',500,428)
            if limit:c.badge('up','',246,428);c.badge('down','SCROLL',273,428)

    def draw(self,c):
        c.clear()
        if self.page=='choose':
            c.text('slot.',32,24,'logo');c.text('CHOOSE WHERE TO INSTALL',32,110,'title')
            rows=[('SET UP THIS SD CARD',self.source,'install-sd'),('INSTALL TO INTERNAL STORAGE',self.target,'install-emmc')]
            for i,(label,info,icon) in enumerate(rows):
                y=185+i*88
                if self.selected==i:c.rect(24,y-6,592,77,(48,60,75))
                enabled=info is not None and info.get('content_bytes') is not None
                color=FG if enabled else DIM
                c.menu_icon(icon,36,y,color)
                c.text(label,76,y,'body',color)
                detail=size(info['bytes']) if info else 'Not available'
                if info and not enabled:detail+=' / SD setup needs 8 GiB usable'
                c.text(detail,76,y+32,'small',DIM)
            c.badge('B','POWER OFF',176,428);c.badge('A','SELECT',358,428)
        elif self.page=='presets':
            c.text('CHOOSE YOUR SETUP',32,30,'title')
            c.text('Pick a preset or choose your own features.',32,74,'small',DIM)
            for index,(_,label,icon,description,_) in enumerate(PRESETS):
                x=24+(index%2)*304;y=112+(index//2)*156
                selected=index==self.selected
                c.rect(x,y,288,140,CYAN if selected else (42,49,61))
                c.rect(x+1,y+1,286,138,(48,60,75) if selected else (22,26,35))
                c.menu_icon(icon,x+16,y+14,CYAN if selected else FG)
                c.centered_text(label,x+56,y+26,'title')
                for row,line in enumerate(c.wrap(description,256,'small')):
                    c.text(line,x+16,y+52+row*18,'small',FG if selected else DIM)
            c.badge('B','BACK',32,428);c.badge('A','SELECT',500,428)
            for index,key in enumerate(('up','down','left','right')):
                c.badge(key,'CHOOSE' if key=='right' else '',218+index*27,428)
        elif self.page=='modules':
            c.text('CHOOSE YOUR FEATURES',32,24,'title')
            c.text(self.debug_status or ('Private test: debug access is enabled.' if self.debug else 'Choose what to install. Services start off.'),32,67,'small',CYAN if self.debug_status else DIM)
            self.scroll_features()
            entries=self.feature_entries()
            for row,(kind,label,index) in enumerate(entries[self.module_first:self.module_first+9]):
                y=103+row*30
                if kind=='group':
                    c.text(label.upper(),32,y+3,'small',CYAN)
                    width=c.measure(label.upper(),'small');c.rect(48+width,y+14,568-width,1,(42,49,61));continue
                if index==self.selected:c.rect(24,y-3,592,29,(48,60,75))
                feature=self.modules['modules'][index] if kind=='feature' else None
                color=DIM if feature and self.unavailable(feature) else FG
                c.menu_icon(feature['id'] if feature else 'continue',36,y,color)
                c.text(label,76,y,'body',color)
                if feature:c.toggle(feature['id'] in self.features,550,y,color=color)
            hint=self.feature_hint()
            for row,line in enumerate(c.wrap(hint,576,'small')[:2]):c.text(line,32,379+row*18,'small',CYAN)
            if not hint:c.text(str(self.selected+1)+' / '+str(len(self.modules['modules'])+1),32,392,'small',DIM)
            if self.selected<len(self.modules['modules']):
                c.badge('B','BACK',32,428);c.badge('A','CHANGE',164,428)
                c.badge('left','',324,428);c.badge('right','CHANGE',351,428)
                c.badge('Y','INFO',520,428)
            else:c.badge('B','BACK',176,428);c.badge('A','REVIEW',350,428)
        elif self.page=='access':
            c.menu_icon('warning',32,32);c.text('CHECK YOUR CHOICES',72,30,'title')
            y=96
            for warning in self.warning:
                for line in c.wrap(warning,576,'small'):
                    c.text(line,32,y,'small',DIM);y+=26
                y+=10
            for i,(label,icon) in enumerate((('GO BACK','back'),('CONTINUE ANYWAY','continue'))):
                y=308+i*46
                if i==self.selected:c.rect(24,y-4,592,38,(48,60,75))
                c.menu_icon(icon,36,y);c.text(label,76,y)
            c.badge('B','BACK',176,428);c.badge('A','SELECT',350,428)
        elif self.page=='review':self.draw_document(c,'REVIEW INSTALLATION',self.review_blocks())
        elif self.page=='debug':
            c.text('DEVELOPER ACCESS',32,30,'title')
            c.text('Private test-image configuration',32,82,'small',DIM)
            for i,(label,name,icon) in enumerate((('SAVED WI-FI','wifi','wifi'),('USB NETWORKING','usb','usb-network'),('SSH / PUBLIC KEY','ssh','ssh'),('CONTINUE',None,'continue'))):
                y=144+i*52
                if i==self.selected:c.rect(24,y-5,592,42,(48,60,75))
                c.menu_icon(icon,36,y)
                c.text(label,76,y)
                if name:c.toggle(self.options[name],522,y,'body')
            c.text('Your private SSH key stays on your computer.',32,368,'small',DIM)
            c.badge('B','BACK',185,428);c.badge('A','SELECT',344,428)
        elif self.page=='confirm':
            internal=self.action=='emmc';info=self.target if internal else self.source
            c.text('INSTALL TO INTERNAL' if internal else 'SET UP THIS SD CARD',32,30,'title')
            c.text(('INTERNAL STORAGE' if internal else 'SD CARD')+'  /  '+size(info['bytes']),32,82)
            layout=info.get('layout',{'boot_mib':512,'storage_mib':512})
            allocation=lambda mib: str(mib//1024)+' GiB' if mib%1024==0 else str(mib)+' MiB'
            c.text('BOOT',32,127,'small',DIM);c.text(allocation(layout['boot_mib']),204,127,'small')
            c.text('SYSTEM',32,154,'small',DIM);c.text(allocation(layout['storage_mib']),204,154,'small')
            c.text('SLOT',32,181,'small',DIM);c.text(size(info['content_bytes']),204,181,'small')
            c.text('All internal data will be erased.' if internal else 'Use the remaining space for your games.',32,230,'body')
            if self.modules and not internal and not (self.features & {'usb-storage','external-sd'} or self.features & {'wifi','usb-network'} and self.features & {'ssh','sharing'}):
                c.text('Add games later using a computer card reader.',32,265,'small',DIM)
            actions=(('CANCEL','cancel'),('ERASE AND INSTALL','erase') if internal else ('SET UP SD CARD','install-sd'))
            for i,(label,icon) in enumerate(actions):
                y=298+i*48
                if i==self.selected:c.rect(24,y-5,592,40,(48,60,75))
                c.menu_icon(icon,36,y)
                c.text(label,76,y)
            c.badge('B','BACK',210,428);c.badge('A','SELECT',340,428)
        elif self.page=='progress':
            c.text('slot.',32,40,'logo');c.text('SETTING UP YOUR DEVICE',32,138,'title')
            for row,line in enumerate(c.wrap(self.status,576,'body')[:2]):c.text(line,32,208+row*28,'body')
            c.rect(32,286,576,7,(40,48,60));c.rect(32,286,int(576*self.percent/100),7,CYAN)
            c.text(str(self.percent)+'%',32,310,'small',DIM)
            c.text('Working'+'.'*(self.activity_frame+1),32,348,'small',CYAN)
            elapsed=str(self.elapsed//60).zfill(2)+':'+str(self.elapsed%60).zfill(2)
            c.text('Elapsed '+elapsed,470,348,'small',DIM)
            c.text('Do not power off during setup.',32,399,'small',DIM)
        elif self.page=='done':self.draw_document(c,'READY TO PLAY',self.completion_blocks())
        elif self.page=='error':
            c.text('SETUP STOPPED',32,48,'title')
            c.text('The installation has not completed.',32,121)
            # Fixed-length wrapped technical detail is useful here to recover a
            # failed install; credentials are never passed to this UI.
            message=self.status[:200]
            for i in range(0,len(message),54):c.text(message[i:i+54],32,180+i//54*30,'small',DIM)
            c.badge('B','BACK',275,428)

        if self.debug_status and self.page in ('choose','presets','debug'):
            c.text(self.debug_status[:34],250,392,'small',CYAN)

        if self.help_open:
            feature=self.modules['modules'][self.selected]
            c.dim()
            c.rect(38,118,576,260,(0,0,0))
            c.rect(32,112,576,260,(67,88,109))
            c.rect(34,114,572,256,BG)
            c.menu_icon(feature['id'],56,139)
            c.text(feature['label'],96,134,'title')
            description=feature.get('description','Choose whether to include this feature.')
            for row,line in enumerate(c.wrap(description,528)):
                c.text(line,56,190+row*32)
            c.rect(0,416,W,64,BG)
            c.badge('B','CLOSE',268,428)


class Framebuffer:
    def __init__(self):
        self.fd=os.open('/dev/fb0',os.O_RDWR|os.O_CLOEXEC)
        v=array.array('B',bytes(160));f=array.array('B',bytes(80))
        fcntl.ioctl(self.fd,0x4600,v,True);fcntl.ioctl(self.fd,0x4602,f,True)
        self.x,self.y,_,_,self.xoff,self.yoff,self.bits=struct.unpack_from('7I',v)
        self.channels=[struct.unpack_from('III',v,n) for n in (32,44,56)]
        self.length=struct.unpack_from('I',f,24)[0];self.stride=struct.unpack_from('I',f,48)[0]
        if ((self.x,self.y,self.bits)!=(W,H,32) or any(c[1:]!=(8,0) for c in self.channels)
                or len({c[0] for c in self.channels})!=3 or any(c[0] not in (0,8,16,24) for c in self.channels)
                or self.stride<(self.xoff+W)*4 or self.length<(self.yoff+H)*self.stride):
            os.close(self.fd);raise ValueError('Unsupported RG353V framebuffer layout')
        self.fb=mmap.mmap(self.fd,self.length)
        tty=os.open('/dev/tty0',os.O_RDWR|os.O_CLOEXEC)
        try:fcntl.ioctl(tty,0x4b3a,1) # KD_GRAPHICS
        finally:os.close(tty)

    @staticmethod
    def pack(pixels,shifts):
        data=bytearray(len(pixels))
        for channel,shift in enumerate(shifts):data[shift//8::4]=pixels[channel::4]
        return data

    def show(self,c):
        data=self.pack(c.pixels,[p[0] for p in self.channels])
        for y in range(H):
            p=(y+self.yoff)*self.stride+self.xoff*4
            self.fb[p:p+W*4]=data[y*W*4:(y+1)*W*4]

    def close(self):self.fb.close();os.close(self.fd)


class Input:
    EVENT=struct.Struct('llHHi')
    def __init__(self):
        self.fds=[];self.hats={}
        for _ in range(50):
            for path in Path('/dev/input').glob('event*'):
                fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC)
                name=array.array('B',bytes(256))
                try:fcntl.ioctl(fd,0x81004506,name,True)
                except OSError:os.close(fd);continue
                if b'joypad' in name.tobytes().lower():self.fds.append(fd)
                else:os.close(fd)
            if self.fds:break
            time.sleep(.1)
        if not self.fds:raise ValueError('RG353V controller is unavailable')

    @staticmethod
    def decode(kind,code,value):
        if kind==1 and value==1:return {0x220:'up',0x221:'down',0x222:'left',0x223:'right',0x131:'a',0x130:'b',0x134:'y'}.get(code)
        if kind==3 and code==0x11 and value:return 'up' if value<0 else 'down'
        return None

    def feed(self,fd,kind,code,value):
        directional=(kind==1 and code in (0x220,0x221) and value in (0,1)) or (kind==3 and code==0x11)
        if directional:
            before={v for k,v in self.hats.items() if k[0]==fd and v}
            key=self.decode(kind,code,value)
            self.hats[fd,kind,code]=key
            return key if key and key not in before else None
        return self.decode(kind,code,value)

    def keys(self):
        ready,_,_=select.select(self.fds,[],[],.5)
        for fd in ready:
            data=os.read(fd,self.EVENT.size*64)
            for i in range(0,len(data),self.EVENT.size):
                _,_,kind,code,value=self.EVENT.unpack_from(data,i)
                key=self.feed(fd,kind,code,value)
                if key:yield key

    def close(self):
        for fd in self.fds:os.close(fd)

    def drain(self):
        for fd in self.fds:
            while True:
                try:
                    if not os.read(fd,self.EVENT.size*64):break
                except BlockingIOError:break
        self.hats.clear()


class Screen:
    def __init__(self,font,source,target,debug=None,modules=None,sd_test=False):
        self.canvas=Canvas(font);self.model=Model(source,target,debug,modules,sd_test)
        self.lock=threading.RLock();self.activity_stop=None;self.activity_thread=None
        self.fb=Framebuffer();self.inputs=Input();self.draw()
    def draw(self):
        with self.lock:
            if self.model.page=='progress':self.model.tick_progress(time.monotonic())
            else:
                try:
                    status=json.loads(Path('/run/slot-setup-access/status.json').read_text())
                    address=status.get('wifi') or status.get('usb')
                    self.model.debug_status='SSH: '+address if address else 'Starting setup debug access'
                except (OSError,ValueError):self.model.debug_status=''
            self.model.draw(self.canvas);self.fb.show(self.canvas)
    def choose(self):
        while True:
            before=self.model.debug_status
            try:
                status=json.loads(Path('/run/slot-setup-access/status.json').read_text())
                address=status.get('wifi') or status.get('usb')
                now='SSH: '+address if address else 'Starting setup debug access'
            except (OSError,ValueError):now=''
            if now!=before:self.draw()
            for key in self.inputs.keys():
                result=self.model.key(key);self.draw()
                if result:return result
    def animate_progress(self,stop):
        while not stop.wait(.5):
            with self.lock:
                if self.model.page!='progress':return
                self.draw()
    def stop_activity(self):
        thread,stop=self.activity_thread,self.activity_stop
        if stop:stop.set()
        if thread:thread.join()
        self.activity_thread=None;self.activity_stop=None
    def progress(self,text,percent):
        with self.lock:
            self.model.page='progress';self.model.status=text;self.model.percent=percent;self.draw()
            if self.activity_thread is None:
                self.activity_stop=threading.Event()
                self.activity_thread=threading.Thread(target=self.animate_progress,args=(self.activity_stop,),daemon=True)
                self.activity_thread.start()
    def done(self):
        self.stop_activity()
        with self.lock:
            self.inputs.drain();self.model.page='done';self.model.text_first=0;self.model.install_started=None;self.draw()
    def error(self,message):
        self.stop_activity()
        with self.lock:
            self.inputs.drain();self.model.page='error';self.model.status=message;self.model.install_started=None;self.draw()
    def close(self):
        self.stop_activity()
        with self.lock:self.inputs.close();self.fb.close()
