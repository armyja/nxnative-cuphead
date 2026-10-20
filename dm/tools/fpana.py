#!/usr/bin/env python3
"""Score candidate predicates over DM_NVN_FP (v2) records, always against a clean-frame control.

The record is one line per draw:
  [fp] F<frame> o<draw idx> p<pass> vc=<vertices> vs=<vertex key> fs=<fragment key>
       v<stream>=<hash>/<len> ...  ib=<itype>/<count>/<hash>  u<slot><range>=<hash>/<size> ...

Draws are identified by (vertex key, fragment key) and by their index *inside* that group, never by
frame-local ordinal: the draw count itself changes between frames (41 -> 49 in the fp2 run).

Predicates scored per (draw, field), with the opportunity count each time:
  P1  prev == next != cur          cur is the odd member of an agreeing pair
  P2  cur != prev and cur != next  cur differs from both neighbours (weak: animation does this)
  P3  cur == f-k for k in 1..8     staleness: does the corrupted frame re-read older content?

Every number is printed as hits/opportunities for the corrupted set AND for the clean set, because a
predicate that fires on 90 % of corrupted comparisons and 88 % of clean ones proves nothing.

Usage: fpana.py <log> --bad 2123,2163,2203 [--kmax 8] [--top 12] [--json out.json]
"""
import re, sys, json, collections

LINE = re.compile(r'\[fp\] F(\d+) o(\d+) p(\d+) vc=(\d+) vs=(\S+) fs=(\S+)(.*)')


def parse(path):
    frames = collections.defaultdict(list)
    bad_lines = 0
    for l in open(path, errors='ignore'):
        if not l.startswith('[fp]'):
            continue
        m = LINE.match(l)
        if not m:
            bad_lines += 1
            continue
        vals = {}
        for t in m.group(7).split():
            k, _, v = t.partition('=')
            vals[k] = tuple(v.split('/'))
        frames[int(m.group(1))].append({
            'o': int(m.group(2)), 'p': int(m.group(3)), 'vc': int(m.group(4)),
            'gk': (m.group(5), m.group(6)), 'f': vals})
    return frames, bad_lines


def groups(draws):
    g = collections.defaultdict(list)
    for d in draws:
        g[d['gk']].append(d)
    return g


def matched(ga, gc, gd):
    """(vs,fs) groups with equal draw counts in all three frames; also count what was discarded."""
    out, amb = [], 0
    for k in set(ga) & set(gc) & set(gd):
        a, c, d = ga[k], gc[k], gd[k]
        if len(a) == len(c) == len(d):
            out.append((k, a, c, d))
        else:
            amb += 1
    amb += len(set(ga) | set(gc) | set(gd)) - len(set(ga) & set(gc) & set(gd))
    return out, amb


def main():
    argv = sys.argv[1:]
    if not argv:
        sys.exit(__doc__)
    log = argv[0]
    bad, kmax, top, jout = set(), 8, 12, None
    i = 1
    while i < len(argv):
        if argv[i] == '--bad':
            bad = {int(x) for x in argv[i + 1].split(',') if x.strip()}; i += 2
        elif argv[i] == '--kmax':
            kmax = int(argv[i + 1]); i += 2
        elif argv[i] == '--top':
            top = int(argv[i + 1]); i += 2
        elif argv[i] == '--json':
            jout = argv[i + 1]; i += 2
        else:
            sys.exit('unknown argument %r' % argv[i])
    if not bad:
        sys.exit('--bad is required: the corrupted set must be measured from this run, never assumed')

    frames, bad_lines = parse(log)
    allf = sorted(frames)
    G = {f: groups(frames[f]) for f in allf}

    print('AUDIT source: %s' % log)
    print('AUDIT parsed: %d frames (%d..%d), %d fp records, %d unparsable fp lines'
          % (len(allf), allf[0], allf[-1], sum(len(v) for v in frames.values()), bad_lines))
    print('AUDIT corrupted set: %d frames %s (given by --bad, measured from this run)'
          % (len(bad), sorted(bad)))
    fld_kinds = collections.Counter()
    for f in allf:
        for d in frames[f]:
            for k in d['f']:
                fld_kinds[k] += 1
    print('AUDIT field coverage: %s' % ', '.join('%s=%d' % (k, v) for k, v in sorted(fld_kinds.items())))
    vcs = collections.Counter(len(frames[f]) for f in allf)
    print('AUDIT draws per frame: %d..%d; distinct counts %s' % (min(vcs), max(vcs), sorted(vcs)))

    stats = collections.defaultdict(lambda: [0, 0, 0, 0])
    amb_total = tri_bad = tri_clean = 0
    cand = []
    vcstat = collections.Counter()

    for f in allf:
        if f - 1 not in G or f + 1 not in G:
            continue
        isbad = f in bad
        if isbad:
            tri_bad += 1
        else:
            tri_clean += 1
        gt, amb = matched(G[f - 1], G[f], G[f + 1])
        amb_total += amb
        for gk, a, c, d in gt:
            for i in range(len(c)):
                da, dc, dd = a[i], c[i], d[i]
                if not (da['vc'] == dc['vc'] == dd['vc']):
                    vcstat['bad' if isbad else 'clean'] += 1
                for k in dc['f']:
                    if k not in da['f'] or k not in dd['f']:
                        continue
                    va, vc_, vd = da['f'][k], dc['f'][k], dd['f'][k]
                    s1, s2 = stats[('P1', k)], stats[('P2', k)]
                    j = 0 if isbad else 2
                    s1[j + 1] += 1; s2[j + 1] += 1
                    if va == vd and vc_ != va:
                        s1[j] += 1
                        if isbad and len(cand) < 400:
                            cand.append({'frame': f, 'o': dc['o'], 'pass': dc['p'], 'vc': dc['vc'],
                                         'vs': gk[0], 'fs': gk[1], 'field': k,
                                         'prev': list(va), 'cur': list(vc_), 'next': list(vd)})
                    if vc_ != va and vc_ != vd:
                        s2[j] += 1

    print('AUDIT triples: %d corrupted, %d clean; groups discarded (draw-count drift / key absent): %d'
          % (tri_bad, tri_clean, amb_total))
    print('AUDIT vertex-count drift vs neighbours: %d corrupted draws, %d clean draws'
          % (vcstat['bad'], vcstat['clean']))
    executed = sum(v[1] for k, v in stats.items() if k[0] == 'P1')
    if not executed:
        sys.exit('predicate executed on 0 comparisons - the analysis proves nothing')

    print()
    print('PREDICATE P1 (prev == next != cur) by field: hits/opportunities, corrupted vs clean')
    print('  %-6s %-22s %-22s %s' % ('field', 'corrupted', 'clean', 'lift'))
    rows = []
    for (pr, k), v in stats.items():
        if pr != 'P1':
            continue
        br = v[0] / v[1] if v[1] else 0.0
        cr = v[2] / v[3] if v[3] else 0.0
        lift = (br / cr) if cr else (float('inf') if br else 0.0)
        rows.append((br - cr, k, v, br, cr, lift))
    rows.sort(reverse=True)
    for d, k, v, br, cr, lift in rows[:top]:
        print('  %-6s %5d/%-5d (%5.1f%%) %5d/%-5d (%5.1f%%) %6.2fx'
              % (k, v[0], v[1], 100 * br, v[2], v[3], 100 * cr, lift))
    hi = [r for r in rows if r[2][0] > 0 and r[2][2] == 0]
    print('  fields with corrupted hits and ZERO clean hits: %s'
          % (', '.join('%s(%d/%d)' % (r[1], r[2][0], r[2][1]) for r in hi) or 'none'))

    print()
    print('PREDICATE P2 (cur differs from both neighbours), ranked by corrupted-minus-clean rate:')
    rows2 = []
    for (pr, k), v in stats.items():
        if pr != 'P2':
            continue
        br = v[0] / v[1] if v[1] else 0.0
        cr = v[2] / v[3] if v[3] else 0.0
        rows2.append((br - cr, k, v, br, cr))
    rows2.sort(reverse=True)
    for d, k, v, br, cr in rows2[:top]:
        print('  %-6s %5d/%-5d (%5.1f%%) %5d/%-5d (%5.1f%%)'
              % (k, v[0], v[1], 100 * br, v[2], v[3], 100 * cr))

    print()
    print('PREDICATE P3 (cur equals frame f-k, i.e. a stale read), by lag k:')
    print('  %-4s %-26s %-26s' % ('k', 'corrupted', 'clean'))
    stal = []
    for k in range(1, kmax + 1):
        bh = bo = ch = co = 0
        for f in allf:
            pf = f - k
            if pf not in G:
                continue
            isbad = f in bad
            gt, _ = matched(G[pf], G[f], G[f])
            for gk, a, c, _ in gt:
                for i in range(len(c)):
                    for fk, vc_ in c[i]['f'].items():
                        if fk not in a[i]['f']:
                            continue
                        if vc_ == a[i]['f'][fk]:
                            if isbad:
                                bh += 1
                            else:
                                ch += 1
                        if isbad:
                            bo += 1
                        else:
                            co += 1
        stal.append({'k': k, 'bad_hits': bh, 'bad_opps': bo, 'clean_hits': ch, 'clean_opps': co})
        print('  %-4d %5d/%-6d (%5.1f%%)    %5d/%-6d (%5.1f%%)'
              % (k, bh, bo, 100.0 * bh / bo if bo else 0, ch, co, 100.0 * ch / co if co else 0))

    print()
    print('CANDIDATE DRAWS (P1 on a corrupted frame):')
    by_frame = collections.Counter(c['frame'] for c in cand)
    print('  hits per corrupted frame: %s'
          % (', '.join('F%d=%d' % (f, n) for f, n in sorted(by_frame.items())) or 'none'))
    seen, shown = set(), 0
    for c in cand:
        sig = (c['field'], c['vs'], c['fs'])
        if sig in seen:
            continue
        seen.add(sig)
        print('  F%d o%-2d p%-6d vc=%-4d %s/%s %s: prev=%s cur=%s next=%s'
              % (c['frame'], c['o'], c['pass'], c['vc'], c['vs'][:6], c['fs'][:6], c['field'],
                 '/'.join(c['prev']), '/'.join(c['cur']), '/'.join(c['next'])))
        shown += 1
        if shown >= top:
            break

    if jout:
        json.dump({'predicates': {'%s/%s' % k: v for k, v in stats.items()},
                   'staleness': stal, 'candidates': cand,
                   'audit': {'frames': len(allf), 'bad': sorted(bad), 'triples_bad': tri_bad,
                             'triples_clean': tri_clean, 'groups_ambiguous': amb_total,
                             'vc_drift': dict(vcstat)}},
                  open(jout, 'w'), indent=1)
        print('\nwrote %s' % jout)


main()
