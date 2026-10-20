#!/usr/bin/env python3
"""Match draws across (prev, cur, next) by (vertex key, fragment key) and score EVERY recorded state field,
binding identity included, against a *measured* corrupted-frame set with a clean-frame control.

This is the [pass] record from DM_NVN_PASSDUMP/PASSDUMP_ALL: unlike the DM_NVN_FP fingerprint (content
hashes only) it carries the identity of each binding: cb addr/size/pool, tex tid/serial/format/dimensions/
view levels, sampler state, and the per-draw pipeline state (base vertex, index buffer, blend, stencil...).

Usage: pdbind.py <log> --bad 2103,2107,... [--top 12] [--min-cmp 30]
"""
import re, sys, collections

B = re.compile(r'\[pass\] F(\d+) B (\d+) st(\d+) (\w+) reg(\d+) (.*)')
D = re.compile(r'\[pass\] F(\d+) d (\d+) (.*)')
KV = re.compile(r'(\w+)=(\S+)')


def parse(path):
    frames = collections.defaultdict(dict)      # frame -> pass -> record
    nbind = 0
    for l in open(path, errors='ignore'):
        m = D.match(l)
        if m:
            f, p = int(m.group(1)), int(m.group(2))
            kv = dict(KV.findall(m.group(3)))
            frames[f].setdefault(p, {'vs': kv.get('vs', '?'), 'fs': kv.get('fs', '?'),
                                     'vc': kv.get('vc', '?'), 'bind': {}})
            rec = frames[f][p]
            for k in ('bv', 'bi', 'first', 'blend', 'dt', 'dw', 'df', 'cull', 'st',
                      'ib', 'it', 'cmask', 'b0', 'b1', 'b2', 'b3', 'po', 'dc'):
                if k in kv:
                    rec['d.' + k] = kv[k]
            continue
        m = B.match(l)
        if m:
            f, p, st, kind, reg, rest = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4), int(m.group(5)), m.group(6)
            kv = dict(KV.findall(rest))
            if kind == 'cb':
                val = 'addr=%s/size=%s/pool=%s' % (kv.get('addr'), kv.get('size'), kv.get('pool'))
            elif kind == 'tex':
                val = 'tid=%s/ser=%s/fmt=%s/size=%s/vlv=%s/vsl=%s/tgt=%s' % (
                    kv.get('tid'), kv.get('ser'), kv.get('fmt'), kv.get('size'),
                    kv.get('view_lv'), kv.get('view_sl'), kv.get('target'))
            elif kind == 'samp':
                val = 'sid=%s/mag=%s/min=%s/wrap=%s/border=%s/lod=%s/bias=%s/aniso=%s/cmp=%s' % (
                    kv.get('sid'), kv.get('mag'), kv.get('min'), kv.get('wrap'), kv.get('border'),
                    kv.get('lod'), kv.get('bias'), kv.get('aniso'), kv.get('cmp'))
            else:
                val = rest
            frames[f].setdefault(p, {'vs': '?', 'fs': '?', 'vc': '?', 'bind': {}})
            frames[f][p]['bind']['%s.st%d.r%d' % (kind, st, reg)] = val
            nbind += 1
    return frames, nbind


def groups(frame):
    g = collections.defaultdict(list)
    for p in sorted(frame):
        r = frame[p]
        g[(r['vs'], r['fs'])].append(r)
    return g


def main():
    argv = sys.argv[1:]
    log = argv[0]
    bad, top = set(), 12
    i = 1
    while i < len(argv):
        if argv[i] == '--bad':
            bad = {int(x) for x in argv[i + 1].split(',') if x.strip()}; i += 2
        elif argv[i] == '--top':
            top = int(argv[i + 1]); i += 2
        else:
            sys.exit('unknown argument %r' % argv[i])
    if not bad:
        sys.exit('--bad is required: measured corrupted frames of THIS run')

    F, nbind = parse(log)
    fs = sorted(F)
    G = {f: groups(F[f]) for f in fs}
    stats = collections.defaultdict(lambda: [0, 0, 0, 0])
    amb = tri_bad = tri_clean = 0
    cand = []
    for f in fs:
        if f - 1 not in G or f + 1 not in G:
            continue
        j = 0 if f in bad else 2
        if f in bad:
            tri_bad += 1
        else:
            tri_clean += 1
        for k in set(G[f - 1]) & set(G[f]) & set(G[f + 1]):
            a, c, d = G[f - 1][k], G[f][k], G[f + 1][k]
            if not (len(a) == len(c) == len(d)):
                amb += 1
                continue
            for n in range(len(c)):
                da, dc, dd = a[n], c[n], d[n]
                fields = set(dc.get('bind', {})) | set(k2 for k2 in dc if k2.startswith('d.'))
                for fld in fields:
                    if not fld.startswith('d.') and not (fld in da.get('bind', {}) and fld in dd.get('bind', {})):
                        continue
                    if fld.startswith('d.'):
                        if fld not in da or fld not in dd:
                            continue
                        va, vc, vd = da[fld], dc[fld], dd[fld]
                    else:
                        va, vc, vd = da['bind'][fld], dc['bind'][fld], dd['bind'][fld]
                    s = stats[fld]
                    s[j + 1] += 1
                    if va == vd and vc != va:
                        s[j] += 1
                        if f in bad and len(cand) < 300:
                            cand.append((f, dc.get('d.ib', '?'), k[0], k[1], fld, va, vc, vd))
    print('AUDIT log %s' % log)
    print('AUDIT %d frames (%d..%d), %d binding records; corrupted set %d; triples %d corrupted / %d clean; groups discarded %d'
          % (len(fs), fs[0], fs[-1], nbind, len(bad), tri_bad, tri_clean, amb))
    cmp_total = sum(v[1] for v in stats.values())
    if not cmp_total:
        sys.exit('predicate executed on 0 comparisons')
    print('AUDIT field comparisons on corrupted triples: %d' % cmp_total)
    rows = []
    for fld, v in stats.items():
        br = v[0] / v[1] if v[1] else 0.0
        cr = v[2] / v[3] if v[3] else 0.0
        rows.append((br - cr, fld, v, br, cr))
    rows.sort(reverse=True)
    print('\nPREDICATE prev == next != cur, by field (corrupted vs clean):')
    for dlt, fld, v, br, cr in rows[:top]:
        print('  %-16s %5d/%-5d (%5.1f%%)  %5d/%-5d (%5.1f%%)' % (fld, v[0], v[1], 100 * br, v[2], v[3], 100 * cr))
    zero = [r[1] for r in rows if r[2][0] > 0 and r[2][2] == 0]
    print('  fields with corrupted hits and zero clean hits: %s' % (', '.join(zero) or 'none'))
    print('\nfirst 12 candidate draws on corrupted frames:')
    for c in cand[:12]:
        print('  F%d %s/%s %s: prev=%s cur=%s next=%s' % (c[0], c[2][:6], c[3][:6], c[4], c[5], c[6], c[7]))


main()
