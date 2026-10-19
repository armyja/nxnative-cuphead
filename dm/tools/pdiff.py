#!/usr/bin/env python3
"""Compare two frames' DM_NVN_PASSDUMP record sequences positionally: addresses normalised, the
numbers that identify resources (ser / tid / sid / fmt / viewport) kept, so a binding that changed
between the frames stands out. Usage: pdiff.py <log> <frameA> <frameB>"""
import sys, re
log, fa, fb = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
def lines(f):
    return [l.rstrip('\n') for l in open(log, errors='ignore') if l.startswith(f'[pass] F{f} ')]
def norm(l):
    l = re.sub(r'\[pass\] F\d+ ', '', l)
    l = re.sub(r'mtl=0x[0-9a-f]+', 'mtl=H', l)
    l = re.sub(r'0x[0-9a-f]+', 'H', l)
    return l
def rel(f):
    pm, out = {}, []
    for l in lines(f):
        m = re.match(r'\[pass\] F(\d+) (\S) (\d+)', l)
        if m:
            k = m.group(3)
            if k not in pm: pm[k] = len(pm)
            l = l.replace(f' {k} ', f' p{pm[k]:02d} ', 1) if f' {k} ' in l else l
        out.append(l)
    return out
a, b = rel(fa), rel(fb)
print(f'F{fa}: {len(a)} lines   F{fb}: {len(b)} lines')
if len(a) != len(b):
    print('line counts differ, positional compare limited to the common prefix')
n = 0
for i, (x, y) in enumerate(zip(a, b)):
    nx, ny = norm(x), norm(y)
    if nx != ny:
        n += 1
        if n <= 30:
            print(f'  [{i}] F{fa}: {nx[:130]}')
            print(f'      F{fb}: {ny[:130]}')
print(f'{n} of {min(len(a),len(b))} lines differ')
