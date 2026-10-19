#!/usr/bin/env python3
"""Labelled contact sheet + automatic defect annotation, one picture.

Per frame the tool computes
  * band  - the largest fraction of a single row that differs from BOTH neighbouring frames
            (transient artefacts light up here; animation persists and cancels out)
  * shard - the largest 4-connected changed region, found on a 1/8-scale grid, and its box
Tiles are laid out in a grid with the frame number and score burned in; frames over the threshold get
a red label and the detected shard is boxed in the picture, so the sheet shows where the defect is.

Usage: sheetl.py <out.jpg> <glob> [cols] [tile_w] [threshold] [first] [last]
"""
import sys, glob
from PIL import Image, ImageChops, ImageDraw

out, pat = sys.argv[1], sys.argv[2]
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 8
tw   = int(sys.argv[4]) if len(sys.argv) > 4 else 200
TH   = int(sys.argv[5]) if len(sys.argv) > 5 else 150
lo   = int(sys.argv[6]) if len(sys.argv) > 6 else -1
hi   = int(sys.argv[7]) if len(sys.argv) > 7 else 10**9
W, CELL, CTH = 480, 8, 55
paths = sorted(glob.glob(pat))
def fn(p): return int(p.rsplit('_', 1)[-1].split('.')[0])

ims = []
for p in paths:
    im = Image.open(p).convert('L')
    ims.append(im.resize((W, max(1, im.height * W // im.width)), Image.BILINEAR))

score, boxes, csize = {}, {}, {}
for i in range(1, len(ims) - 1):
    a = ImageChops.difference(ims[i], ims[i-1]).point(lambda v: 255 if v > 40 else 0)
    b = ImageChops.difference(ims[i], ims[i+1]).point(lambda v: 255 if v > 40 else 0)
    d = ImageChops.darker(a, b)
    f = fn(paths[i])
    score[f] = max(d.resize((1, d.size[1]), Image.BILINEAR).getdata())
    # coarse grid -> largest 4-connected component
    w, h = d.size
    cw, ch = max(1, w // CELL), max(1, h // CELL)
    c = d.resize((cw, ch), Image.BILINEAR).load()
    seen = bytearray(cw * ch); best = (0, 0, 0, 0)
    for j in range(ch):
        for k in range(cw):
            i0 = j * cw + k
            if c[k, j] <= CTH or seen[i0]: continue
            st = [i0]; seen[i0] = 1; n = 0
            x0, y0, x1, y1 = k, j, k, j
            while st:
                m = st.pop(); n += 1
                my, mx = divmod(m, cw)
                x0 = min(x0, mx); x1 = max(x1, mx); y0 = min(y0, my); y1 = max(y1, my)
                for nx, ny in ((mx-1, my), (mx+1, my), (mx, my-1), (mx, my+1)):
                    if 0 <= nx < cw and 0 <= ny < ch:
                        q = ny * cw + nx
                        if c[nx, ny] > CTH and not seen[q]: seen[q] = 1; st.append(q)
            if n > best[0]: best = (n, x0, y0, x1, y1)
    csize[f] = (cw, ch)
    if best[0]: boxes[f] = best

sel = [p for p in paths if lo <= fn(p) <= hi]
if not sel: sys.exit('no frames in range')
th = tw * 9 // 16
rows = (len(sel) + cols - 1) // cols
sheet = Image.new('RGB', (cols * tw, rows * (th + 16)), (12, 12, 12))
dr = ImageDraw.Draw(sheet)
bad = 0
for i, p in enumerate(sel):
    f = fn(p); s = score.get(f, 0)
    tile = Image.open(p).convert('RGB').resize((tw, th), Image.LANCZOS)
    x, y = (i % cols) * tw, (i // cols) * (th + 16)
    sheet.paste(tile, (x, y + 16))
    hot = s > TH
    col = (255, 70, 70) if hot else (160, 160, 160)
    if hot:
        bad += 1
        b = boxes.get(f)
        if b:
            n, x0, y0, x1, y1 = b
            sx = tw / csize[f][0]
            sy = th / csize[f][1]
            dr.rectangle([x + x0 * sx, y + 16 + y0 * sy, x + (x1 + 1) * sx, y + 16 + (y1 + 1) * sy],
                         outline=(255, 40, 40), width=2)
    dr.text((x + 3, y + 3), f'F{f}  {s}', fill=col)
    dr.rectangle([x, y + 16, x + tw - 1, y + 16 + th - 1], outline=col)
sheet.save(out, quality=84)
print(f'{out}: {len(sel)} frames, {bad} suspect (band>{TH}), {sheet.size[0]}x{sheet.size[1]}')
