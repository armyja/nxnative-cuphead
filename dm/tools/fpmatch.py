#!/usr/bin/env python3
"""SUPERSEDED by pdbind.py (richer fields: binding identity, pipeline state) and fpana.py (DM_NVN_FP v2).
Kept only for reading old [pass] K/B records; it now REFUSES to run without a measured bad set.

This tool used to assume the corrupted-frame set (`frame % 4 == 2`), which broke the rule that the set must
be measured from the same run - and it was wrong for the runs it was applied to (sc1's measured set is
mostly == 3 (mod 4), drifting to 2 later). Every number it produced before that fix is mislabelled.

Usage: fpmatch.py <log> --bad 2103,2107,... [field ...]   (default field: tex)
"""
import re, sys, collections

argv = sys.argv[1:]
if not argv:
    sys.exit(__doc__)
log, bad, want = argv[0], set(), ['tex']
i = 1
while i < len(argv):
    if argv[i] == '--bad':
        bad = {int(x) for x in argv[i + 1].split(',') if x.strip()}; i += 2
    else:
        want = argv[i:]; break
if not bad:
    sys.exit('--bad is required: the corrupted set must be measured from this run, never assumed')

K = collections.defaultdict(dict)
B = collections.defaultdict(lambda: collections.defaultdict(list))
nk = nb = 0
for l in open(log, errors='ignore'):
    m = re.match(r'\[pass\] F(\d+) K (\d+) st(\d+) key=(\S+)', l)
    if m:
        nk += 1
        K[int(m.group(1))].setdefault(int(m.group(2)), {})[int(m.group(3))] = m.group(4)
        continue
    m = re.match(r'\[pass\] F(\d+) B (\d+) st(\d+) (\S+) reg(\d+) (.*)', l)
    if m:
        nb += 1
        r = re.search(r'tid=(\d+)', m.group(6)) or re.search(r'sid=(\d+)', m.group(6)) or re.search(r'addr=(\S+)', m.group(6))
        B[int(m.group(1))][int(m.group(2))].append((m.group(4), m.group(5), r.group(1) if r else '?'))


def draws(fr):
    out = collections.defaultdict(list)
    for passn, binds in B.get(fr, {}).items():
        keys = K.get(fr, {}).get(passn, {})
        gk = (keys.get(0, '?'), keys.get(1, '?'))
        out[gk].append(tuple(sorted((s, r, i) for s, r, i in binds if any(w in s for w in want))))
    return {k: sorted(v) for k, v in out.items()}


frames = sorted(B)
tri = amb = ok = 0
stat, statc = collections.Counter(), collections.Counter()
samples = []
for f in frames:
    if f - 1 not in B or f + 1 not in B:
        continue
    tri += 1
    A, C, D = draws(f - 1), draws(f), draws(f + 1)
    for gk in set(A) | set(C) | set(D):
        a, c, d = A.get(gk, []), C.get(gk, []), D.get(gk, [])
        if not (len(a) == len(c) == len(d)):
            amb += 1
            continue
        ok += 1
        for i in range(len(c)):
            if a[i] == d[i] and c[i] != a[i]:
                (stat if f in bad else statc)[gk[0][:8]] += 1
                if len(samples) < 3:
                    samples.append((f, gk[0][:8], a[i][:2], c[i][:2]))
print('AUDIT: K lines %d, B lines %d, frames %d, triples %d, groups matched %d, groups ambiguous %d'
      % (nk, nb, len(frames), tri, ok, amb))
print('AUDIT: corrupted frames present in this log %d of %d' % (len([f for f in frames if f in bad]), len(frames)))
for s in samples:
    print('AUDIT sample:', s)
print('hits (prev == next != cur) by vertex key: corrupted / clean')
for k, v in stat.most_common(8):
    print('  %s %6d / %d' % (k, v, statc.get(k, 0)))
if not stat:
    print('  (no hits)')
