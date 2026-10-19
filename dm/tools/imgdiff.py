#!/usr/bin/env python3
"""Mean absolute pixel difference between consecutive frames of a set (pure PIL): a static scene with
correct rendering changes only where things animate; a renderer reading memory the CPU is rewriting
changes everywhere, every frame.  Usage: imgdiff.py <glob>"""
import sys, glob
from PIL import Image, ImageChops, ImageStat
paths = sorted(glob.glob(sys.argv[1]))
if len(paths) < 2: sys.exit(f'{len(paths)} frames: need at least 2')
prev = None; rows = []
for p in paths:
    a = Image.open(p).convert('L')
    if prev is not None:
        d = ImageChops.difference(a, prev)
        mad = ImageStat.Stat(d).mean[0]
        hot = ImageStat.Stat(d.point(lambda v: 255 if v > 24 else 0)).mean[0] / 255.0 * 100.0
        rows.append((mad, hot, p.rsplit('/', 1)[-1]))
    prev = a
for mad, hot, n in rows: print(f'{mad:6.2f}  {hot:5.2f}%  {n}')
print(f'mean MAD {sum(r[0] for r in rows)/len(rows):.2f}, mean >24 {sum(r[1] for r in rows)/len(rows):.2f}%')
