#!/usr/bin/env python3
"""The one frame-transient scorer, shared by every tool that needs "which frames of this run are corrupt".

score(paths) -> [(area, band, frame), ...] sorted by area descending.
  band: largest fraction of a single row whose grey level differs from BOTH neighbours by > TH grey levels
  area: the same mask summed over all rows (a shard covers a large region; ordinary animation does not)

detect(paths, th_area) -> [(frame, area, band), ...] for frames with area >= th_area, ascending by frame.

Calibration (fp2, 161 captured frames at 320x180, 480-wide rescale): shard 28168/20577/18267, next highest
4274 - the 8000 default sits in that 4.3x gap. Do not reuse a threshold from another resolution without
rechecking the gap; print the ranking first (scanarea.py does).
"""
import glob
from PIL import Image, ImageChops

TH = 40     # grey-level difference that counts as "changed"
W = 480     # rescale width, so the score is resolution-independent


def score(paths):
    ims = []
    for p in paths:
        im = Image.open(p).convert('L')
        ims.append(im.resize((W, max(1, im.height * W // im.width)), Image.BILINEAR))
    out = []
    for i in range(1, len(ims) - 1):
        a = ImageChops.difference(ims[i], ims[i - 1]).point(lambda v: 255 if v > TH else 0)
        b = ImageChops.difference(ims[i], ims[i + 1]).point(lambda v: 255 if v > TH else 0)
        d = ImageChops.darker(a, b)
        h = d.size[1]
        rows = list(d.resize((1, h), Image.BILINEAR).getdata())
        out.append((sum(rows) * h // 255, max(rows), int(paths[i].rsplit('_', 1)[-1][:-4])))
    out.sort(reverse=True)
    return out


def paths_of(pattern):
    return sorted(glob.glob(pattern))


def detect(paths, th_area=8000):
    return sorted((f, ar, bd) for ar, bd, f in score(paths) if ar >= th_area)
