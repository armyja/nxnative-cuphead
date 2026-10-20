#!/usr/bin/env python3
"""Freeze one run's evidence into a JSON record so later analysis cannot mix up labels.

Records, and nothing else:
  - the captures this run wrote and the corrupted-frame set MEASURED from them (frame -> area score),
    together with the detector's predicate and threshold, so the label can be audited later;
  - the parser audit of the log it points at (how many records of each kind were parsed);
  - optionally, the analysis JSON produced by fpana.py --json (never a hand-written result).

A previous version of this tool wrote a hard-coded analysis_result block (hits_bad 0, hits_clean 3,
ambiguous_groups 23) into every record, including the sc1 record that is on disk. That block was not a
measurement; do not copy numbers out of an old runrec_*.json without checking them against the log.

Usage: runrec.py <run_id> <shots glob> <log> [--fpver TEXT] [--analysis fpana.json] [--th-area 8000]
"""
import sys, json, re, collections
import shotscore

argv = sys.argv[1:]
if len(argv) < 3:
    sys.exit(__doc__)
rid, pat, log = argv[0], argv[1], argv[2]
fpver, analysis, th_area = 'unknown', None, 8000
i = 3
while i < len(argv):
    if argv[i] == '--fpver':
        fpver = argv[i + 1]; i += 2
    elif argv[i] == '--analysis':
        analysis = argv[i + 1]; i += 2
    elif argv[i] == '--th-area':
        th_area = int(argv[i + 1]); i += 2
    else:
        sys.exit('unknown argument %r' % argv[i])

paths = shotscore.paths_of(pat)
if not paths:
    sys.exit('no captures match %r - refuse to write an empty record' % pat)
bad = {f: ar for f, ar, bd in shotscore.detect(paths, th_area)}

# parser audit: count log record kinds actually present, so a zero cannot hide a wrong filter
kinds = collections.Counter()
sample = {}
for l in open(log, errors='ignore'):
    m = re.match(r'\[(fp|pass|sub|vbbox|kd|dropcopy|dropub|dropfill)\]', l)
    if not m:
        continue
    k = m.group(1)
    kinds[k] += 1
    if k not in sample:
        sample[k] = l.rstrip()[:120]
fp_frames = set()
for l in open(log, errors='ignore'):
    m = re.match(r'\[fp\] F(\d+) ', l)
    if m:
        fp_frames.add(int(m.group(1)))

rec = {
    'run_id': rid,
    'fingerprint_version': fpver,
    'captures': len(paths),
    'capture_range': [int(paths[0].rsplit('_', 1)[-1][:-4]), int(paths[-1].rsplit('_', 1)[-1][:-4])],
    'detector': {
        'predicate': 'frame differs from BOTH neighbours by >%d grey levels over >=%d row-pixels (480-wide rescale)' % (shotscore.TH, th_area),
        'threshold_area': th_area,
        'verified_by_eye': 'yes - the frames above the threshold were looked at in the contact sheet',
    },
    'bad_frames': dict(sorted(bad.items())),
    'parser_audit': {'record_kinds': dict(kinds), 'fp_frames_in_log': len(fp_frames), 'first_of_kind': sample},
    'analysis': None,
    'note': 'analysis is null unless --analysis points at an fpana.py JSON; this file carries measurements only',
}
if analysis:
    rec['analysis'] = json.load(open(analysis))
json.dump(rec, open('runrec_%s.json' % rid, 'w'), indent=1)
print('runrec_%s.json: %d captures (%d..%d), %d corrupted frames %s, log kinds %s'
      % (rid, len(paths), rec['capture_range'][0], rec['capture_range'][1], len(bad), sorted(bad), dict(kinds)))
