#!/usr/bin/env python3
"""Build the Markdown visual index from the current catalog and guide images."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WIKI=ROOT/'wiki'
catalog=json.loads((ROOT/'ports/rg353v/modules/catalog-v1.json').read_text())
lines=['# Screens and videos','',
       'All images are native 640×480 renders of the installer or frontend. Games and cartridge artwork come from the owner’s collection; capacities, network addresses and service readings are illustrative. No ROMs or saves are bundled. See [media provenance](Media-Production.md).','',
       '## Animations','',
       '![Setup walkthrough](media/setup-walkthrough.gif)','',
       'Setup interface demonstration with condensed installation progress.','',
       '![Boot to shelf](media/boot-to-shelf.gif)','',
       'Boot replay using captured percentage changes and presentation timing. [Timing and recovery](Boot-and-Recovery.md).','',
       '![Feature tour](media/feature-tour.gif)','',
       'Real games/art rendered by the frontend, plus connection and Gallery examples. GBA uses Perfect + Shimmerless.','',
       '## Installation steps','',
       'Follow the [installation walkthrough](Installation.md) for the sequence and safety checks. These cover both destinations and the alternate warnings.','']
for path in sorted((WIKI/'images/setup').glob('[0-9][0-9]-*.png')):
    label=path.stem[3:].replace('-',' ').capitalize()
    lines += [f'<details><summary>{label}</summary>','',f'![{label}](images/setup/{path.name})','','</details>','']
lines += ['## Feature explanations','',
          'In Custom setup, highlight a feature and press Y to open its explanation; B closes it. These descriptions and labels come from the same module catalog as the installer.','']
for module in catalog['modules']:
    name=module['id']; label=module['label']; description=module['description']
    lines += [f'<details><summary>{label}</summary>','',description,'',
              f'![{label} explanation](images/setup/info-{name}.png)','','</details>','']
lines += ['## Installed settings and features','',
          'The reference uses all modules. Your installation hides omitted capabilities; [the menu map](Menus.md) explains where they belong. Expand a screen to view it at native resolution.','']
labels={
    'power-menu-game':'Power menu while a game remains inserted',
    'storage-top':'Storage: removable cards and progress policy',
    'storage-system':'Save location: System', 'storage-game':'Save location: Game',
    'clock-setup':'First-run date and time','shelf':'Cartridge shelf','favorites':'Favorites shelf',
    'settings':'Settings, first page','settings-gallery':'Settings, Gallery and Help',
    'system-bottom':'System, lower entries','features-in-game':'Feature restrictions, in-game changes',
    'screen-gba':'GBA screen preferences','screen-gbc':'GBC screen preferences','screen-gb':'GB screen preferences',
    'game':'Gameplay preferences','game-slot-overlay':'Zelda with Perfect overlay and Shimmerless',
    'game-zelda':'Zelda: A Link to the Past','game-metroid-fusion':'Metroid Fusion',
    'game-golden-sun-battle':'Golden Sun: The Lost Age battle','game-zelda-gb':'Zelda: Link’s Awakening',
    'game-zelda-gbc':'Zelda: Link’s Awakening DX',
    'states':'Manual state browser','states-delete':'State deletion confirmation',
    'gallery-grid-date':'Gallery sorted by date','gallery-grid-platform':'Gallery sorted by platform',
    'gallery-grid-game':'Gallery sorted by game','gallery-image':'Full-screen image with legends',
    'gallery-image-hidden':'Full-screen image after legends fade','gallery-delete':'Screenshot deletion confirmation',
    'usb-storage-connected':'USB Storage, shared with computer','usb-storage-waiting':'USB Storage, waiting for computer',
}
for path in sorted((WIKI/'images/features').glob('*.png')):
    label=labels.get(path.stem,path.stem.replace('-',' ').capitalize())
    lines += [f'<details><summary>{label}</summary>','',f'![{label}](images/features/{path.name})','','</details>','']
lines += ['## Setup selection and progress reference','',
          'The remaining captures show each feature group, selection example, preset review, scrolled review/completion and progress stage. The working-dot phases are animation frames, not separate user actions.','']
for path in sorted((WIKI/'images/setup').glob('*.png')):
    if path.stem[:2].isdigit() or path.stem.startswith('info-'):continue
    if path.stem.startswith('progress-') and not path.stem.endswith('-1'):continue
    label=path.stem.replace('-',' ').capitalize()
    lines += [f'- [{label}](images/setup/{path.name})']
lines += ['', '[Guide home](Home.md) · [Reproduce the media](Media-Production.md)', '']
(WIKI/'Screens-and-Media.md').write_text('\n'.join(lines))
print('Wrote wiki/Screens-and-Media.md')
