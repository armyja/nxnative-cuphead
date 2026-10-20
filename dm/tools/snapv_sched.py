#!/usr/bin/env python3
"""The DM_NVN_SNAP_VB=ab per-frame schedule, reproduced for classification.

The host decides per frame:  h = f*0x9e3779b97f4a7c15; h ^= h>>29; h *= 0xbf58476d1ce4e5b9; h ^= h>>32; class = h&1
1 = snapshotted (private copy bound), 0 = zero-copy original.
Print the class of each frame in a range, and the counts, so an analysis can split the captures.
Usage: snapv_sched.py <first> <last> [--write file]
"""
import sys
M = (1 << 64) - 1
def cls(f):
    h = (f * 0x9e3779b97f4a7c15) & M
    h ^= h >> 29
    h = (h * 0xbf58476d1ce4e5b9) & M
    h ^= h >> 32
    return h & 1
a, b = int(sys.argv[1]), int(sys.argv[2])
rows = [(f, cls(f)) for f in range(a, b + 1)]
on = [f for f, c in rows if c]
off = [f for f, c in rows if not c]
print('frames %d..%d: snapshotted %d, zero-copy %d' % (a, b, len(on), len(off)))
print('first 24:', ' '.join('%d:%d' % r for r in rows[:24]))
if len(sys.argv) > 3 and sys.argv[3] == '--write':
    open(sys.argv[4], 'w').write('\n'.join('%d %d' % r for r in rows) + '\n')
    print('wrote', sys.argv[4])
