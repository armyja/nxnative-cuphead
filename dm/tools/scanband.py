#!/usr/bin/env python3
"""Cheap pre-filter for the shard artefact: per frame, the darkest-band score = largest fraction of a
single row that differs from BOTH neighbouring frames. A band/fan artefact lights up one row; ordinary
animation spreads over a few rows only. Usage: scanband.py <glob> [topN] [threshold]"""
import sys, glob
from PIL import Image, ImageChops
paths = sorted(glob.glob(sys.argv[1]))
topn = int(sys.argv[2]) if len(sys.argv) > 2 else 25
th = int(sys.argv[3]) if len(sys.argv) > 3 else 40
W = 480
ims = []
for p in paths:
    im = Image.open(p).convert('L')
    ims.append(im.resize((W, max(1, im.height * W // im.width)), Image.BILINEAR))
res = []
for i in range(1, len(ims) - 1):
    a = ImageChops.difference(ims[i], ims[i-1]).point(lambda v: 255 if v > th else 0)
    b = ImageChops.difference(ims[i], ims[i+1]).point(lambda v: 255 if v > th else 0)
    d = ImageChops.darker(a, b)
    h = d.size[1]
    rows = list(d.resize((1, h), Image.BILINEAR).getdata())
    res.append((max(rows), sum(rows) * h // 255, paths[i].rsplit('_', 1)[-1].split('.')[0]))
res.sort(reverse=True)
print(f'{len(res)} frames scanned from {paths[0]}')
for r in res[:topn]:
    print(f'  band={r[0]:3d}  area={r[1]:6d}  F{r[2]}')
