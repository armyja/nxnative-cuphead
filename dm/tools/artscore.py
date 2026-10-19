#!/usr/bin/env python3
"""Score frames for the shard artefact: the largest connected region that differs from the previous
frame more than a threshold. Normal animation moves bounded sprites (small regions); the artefact is a
band / fan / stretched quad that replaces a large contiguous area.
Usage: artscore.py <glob> [threshold]  ->  prints score per frame, highest first."""
import sys, glob
from PIL import Image, ImageChops
TH = int(sys.argv[2]) if len(sys.argv) > 2 else 40
W = 480
paths = sorted(glob.glob(sys.argv[1]))
ims = []
for p in paths:
    im = Image.open(p).convert('L')
    ims.append(im.resize((W, max(1, im.height * W // im.width)), Image.BILINEAR))
scores = {}
for idx in range(1, len(ims) - 1):
    p = paths[idx]
    im = ims[idx]
    if True:
        # a pixel counts when it differs from BOTH neighbours: content that persists (animation, a scene
        # transition) cancels out, a defect that only this frame has does not
        a = ImageChops.difference(im, ims[idx-1]).point(lambda v: 255 if v > TH else 0)
        b = ImageChops.difference(im, ims[idx+1]).point(lambda v: 255 if v > TH else 0)
        d = ImageChops.darker(a, b)
        px = d.load(); w, h = d.size
        seen = bytearray(w * h); best = 0
        for y in range(h):
            for x in range(w):
                i = y * w + x
                if not px[x, y] or seen[i]: continue
                stack = [i]; seen[i] = 1; area = 0
                while stack:
                    j = stack.pop(); area += 1
                    jy, jx = divmod(j, w)
                    for k in ((jx-1, jy), (jx+1, jy), (jx, jy-1), (jx, jy+1)):
                        if 0 <= k[0] < w and 0 <= k[1] < h:
                            m = k[1] * w + k[0]
                            if px[k[0], k[1]] and not seen[m]: seen[m] = 1; stack.append(m)
                if area > best: best = area
        scores[p.rsplit('_', 1)[-1].split('.')[0]] = best
for k, v in sorted(scores.items(), key=lambda kv: -kv[1])[:12]:
    print(f'{v:7d}  F{k}')
print(f'{len(scores)} frames scored, threshold {TH}')
