#!/usr/bin/env python3
"""Rank a run's captured frames by frame-transient area (see shotscore.py), and print the measured
corrupted set. This is the pre-filter the work uses instead of eyeballing sheets.

Usage: scanarea.py <glob> [topN] [threshold]      (threshold on area, default 8000)
"""
import sys
import shotscore

paths = shotscore.paths_of(sys.argv[1])
topn = int(sys.argv[2]) if len(sys.argv) > 2 else 15
th = int(sys.argv[3]) if len(sys.argv) > 3 else 8000
res = shotscore.score(paths)
print('%d frames scored from %s' % (len(res), paths[0]))
for ar, bd, f in res[:topn]:
    print('  area=%-6d band=%-4d F%d' % (ar, bd, f))
hot = [f for ar, bd, f in res if ar >= th]
print('CORRUPTED (area>=%d): %d of %d frames: %s' % (th, len(hot), len(res), sorted(hot)))
