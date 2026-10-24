# Setup menu icons

`setup-menu-icons.ttf` is a build-only subset of the Nerd Fonts Symbols Mono
font used for the installer feature menu, storage selection and setup actions. It contains only the
28 distinct characters (32 named icons) in `../slot-setup-menu-icons.json`. The font source is
https://github.com/ryanoasis/nerd-fonts/blob/master/patched-fonts/NerdFontsSymbolsOnly/SymbolsNerdFontMono-Regular.ttf
and the retained copyright is Copyright (c) 2016, Ryan McIntyre.

`scripts/generate-rg353v-setup-font.py` bakes these icons at 24 pixels into
`slot-setup-font.json.gz`. Neither this TTF nor a font service is needed on
the installed device. See the accompanying MIT license.

`setup-scroll-symbols.ttf` contains the two Nerd Font caret glyphs used for
Up/Down scrolling in setup. It shares the same source and MIT license. Existing
button symbols retain their original glyphs. This subset is also build-only.
