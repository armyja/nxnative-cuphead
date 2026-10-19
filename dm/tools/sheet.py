#!/usr/bin/env python3
"""Contact sheet of frames: grid, each tile scaled, frame number burned in.
Usage: sheet.py <out.jpg> <glob> [cols] [tile_width]"""
import sys, glob
from PIL import Image, ImageDraw
out, pat = sys.argv[1], sys.argv[2]
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 6
tw = int(sys.argv[4]) if len(sys.argv) > 4 else 320
paths = sorted(glob.glob(pat))
if not paths: sys.exit('no frames')
th = tw * 9 // 16
rows = (len(paths) + cols - 1) // cols
sheet = Image.new('RGB', (cols * tw, rows * th), (16, 16, 16))
d = ImageDraw.Draw(sheet)
for i, p in enumerate(paths):
    im = Image.open(p).convert('RGB').resize((tw, th), Image.LANCZOS)
    x, y = (i % cols) * tw, (i // cols) * th
    sheet.paste(im, (x, y))
    lbl = p.rsplit('_', 1)[-1].split('.')[0]
    d.rectangle([x + 2, y + 2, x + 52, y + 16], fill=(0, 0, 0))
    d.text((x + 5, y + 4), lbl, fill=(255, 255, 0))
sheet.save(out, quality=82)
print(f'{out}: {len(paths)} frames, {sheet.size[0]}x{sheet.size[1]}')
