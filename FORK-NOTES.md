# Cuphead fork notes

This is a fork of [nxnative](https://github.com/seedds/nxnative) (MIT) for **Cuphead**
(`0100A5C00D162000`, Unity 2017.4.9f1 / IL2CPP / NVN SDK 5.5.0.0) on Apple Silicon macOS.

**Status: work in progress; not playable end-to-end.** The game boots, reaches the title, menu, world map
and the forest level at 60 fps with audio and input. Two defects were tracked; one is fixed:

1. **Geometry shredding - fixed (Round 45).** Some frames showed large flat-coloured triangles, horizontal
   tears or stretched spikes. The cause was a buffer copy whose source the guest reuses before the GPU
   executes it: the terrain index buffer received another mesh's indices, so the draw fetched vertices past
   its stream. Small copy sources are now snapshotted at encode time (`021c612`); three consecutive runs
   after the fix had 0/499 corrupted frames. Upstream PR: seedds/nxnative#21.
2. **An intermittent guest deadlock at frame ~957 - open.** 5 of 10 deterministic-clock runs stopped there:
   the guest main thread and two worker threads wait on one condition variable forever. Runs without
   `DM_DETCLOCK` passed.

The round-by-round record is [docs/cuphead/FINDINGS.md](docs/cuphead/FINDINGS.md) (the fix is Round 45) and
the working handoff is [docs/cuphead/HANDOFF.md](docs/cuphead/HANDOFF.md). The shredding rounds below are kept
as the record of what was excluded.

Nothing from the game is in this repository except a few downscaled screenshots used to document the
defect: no ROM/NSP/XCI, no keys, no extracted data, no patched binaries and no save files. You need your
own legally obtained copy and your own `prod.keys`; this project does not provide or explain how to obtain
either. Not affiliated with Nintendo or Studio MDHR.

## The two questions a reviewer asks first

1. **Texture content (especially vertex-stage), in-run A/B: not done - and not needed (Round 45).** The
   measured texture facts are *binding identity* (clean) and texture-to-buffer copies (they feed no draw); the
   content a draw samples was never imaged. The shredding turned out to be a buffer-copy source reuse, fixed in
   Round 45, so no texture A/B was required. The question stays open only as a completeness check.
2. **"Not GPU delay", per-frame 50/50: done.** `DM_NVN_DRAIN=ab` waits for the frame's own submission on every
   second frame: 8000 77/249 (drain) vs 70/250 (async), 12000 55 vs 51, 15000 41 vs 42. No effect. This
   replaces the old cross-run `MAX_INFLIGHT` comparison (94 vs 18 of 501).

## What it looked like before the fix

The geometry shredding (fixed in Round 45) was not subtle: one flat-coloured triangle with a straight edge, the
scene torn into horizontal streaks, or stretched spikes, with clean frames on both sides. The two clearest
frames from the earlier rounds:

| | |
|:---:|:---:|
| ![cpF 2249](docs/cuphead/images/shard-cpF-2249.png) | ![fp2 2123](docs/cuphead/images/shard-fp2-2123.png) |
| **cpF present 2249**: stretched spikes and a pale sheet. | **fp2 present 2123**: horizontal tearing. |

The r39 A/B contact sheets that used to be here documented the excluded hypotheses (vertex/index/uniform
post-write images, the argument-table A/B, the run whose captures were joined by filename, the particles that
scored as shards). Their numbers and conclusions are in the rounds below and in
[docs/cuphead/FINDINGS.md](docs/cuphead/FINDINGS.md).

The clearest single frames from the earlier rounds:

| | |
|:---:|:---:|
| ![cpF 2249](docs/cuphead/images/shard-cpF-2249.png) | ![fp2 2123](docs/cuphead/images/shard-fp2-2123.png) |
| **cpF present 2249**: stretched spikes and a pale sheet. | **fp2 present 2123**: horizontal tearing. |


## What works

- Boot: title -> menu -> world map -> forest level at 60.0 fps (p50 16.67 ms, p95 16.80 ms on an M1).
- 60 s replay runs without crashes; recorded input replay (`DM_PLAY_IN`), keyboard and gamepad.
- The Cuphead profile in `dm/games/0100A5C00D162000/` (build v1.0.0).
- Diagnostic switches for frame capture, per-draw fingerprints, faithful snapshot images and pass dumps.

## Build

Prerequisites and the general flow are in the [main README](README.md) and
[docs/development.md](docs/development.md). In short, on macOS with Xcode command-line tools, .NET and the
Python packages the extraction script needs:

1. Put your own Cuphead NSPs in a folder and run `python3 scripts/build_ipa_from_nsp.py` (or the Mac-only
   extraction path) to produce the patched modules and the shader chain. The script writes its build
   directory outside the repository. **Game files, keys and extracted data stay outside this repository.**
2. Build the Mac host:
   `make -C dm/host GAME=0100A5C00D162000 dmhost`
3. Run the host with the patched modules and the game's RomFS, e.g.
   `DM_ROMFS=<build>/data/v0/RomFS DM_SAVE=<save-dir> ./dm/host/dmhost <build>/patched_v0 main sdk subsdk0`
   (the development work folder's `boot.sh` is not part of this repository; it sets these variables plus
   `DM_WINDOW=1` for a window).

The iOS/IPA path is the same as the base project; Cuphead has not been verified on iOS.

## Reproducing the defect

The save snapshot decides whether the defect appears at all. With the snapshot used during development
(the `pair` state), a 501-frame capture (present frames 1900-2400) at 60 fps showed 10-160 corrupted
frames; a later snapshot gave 0/499 in two runs. Always count the corrupted frames in that run; zero is
"no data", never "fixed".

Capture and score:

```
DM_WINDOW=1 DM_NVN_SHOT_OUT=320x180 \
  DM_NVN_SHOT=1900,1901,...,2400:<out>/d_%04d.png \
  ... dmhost ...
python3 dm/tools/scanarea.py '<out>/d_*.png' 20 8000
```

`scanarea.py` / `shotscore.py` rank frames by a frame-transient score; **the score is not a shard
classifier**: particle effects score 8k-45k too. Look at the top frames (contact sheet via `dm/tools/sheet.py`
or `sheetl.py`) and count the flat triangles/tears by eye. The `[shot-map] present=N render=F` line (added
in this fork) is required to join a capture to the per-frame diagnostics: the capture filename is the
present count, which is not the rendered frame when the display link merges frames.

## What was tried (and what it showed)

"no effect" means the corrupted-frame rate on the treated arm matched the control arm **inside the same
run** (per-frame 50/50 schedule), not a cross-run comparison. Raw numbers and retractions are in
[docs/cuphead/FINDINGS.md](docs/cuphead/FINDINGS.md).

| Direction | Result |
|---|---|
| Host-lent command segments (`nvn_hostseg_only on`) | whole-view corruption every ~4th frame; off fixes that class. |
| FXAA skip (`DM_NVN_NOFXAA`) | the symptom moves, it does not disappear. |
| Submissions in flight 0/1/2/unbounded | the old result was cross-run (fully synchronous 94 vs baseline 18 of 501); replaced by the in-run drain A/B below. |
| GPU drain, every second frame (`DM_NVN_DRAIN=ab`) | no effect: 77/249 vs 70/250 at 8000, 55 vs 51 at 12000, 41 vs 42 at 15000. The GPU-lag/CPU-rewrite race is excluded in-run. |
| Vertex shaders recompiled with `-fno-fast-math` (1515 VS) | inconclusive: safeB 48/37 at 8000; the fast control was 0/499 once (fastB) and 96/86 in a repeat (fastC, 39.2/33.9). The fast shaders span 0-39%; run variance dominates. Needs an in-run fast/safe switch. |
| Input/capture anchored to the guest frame (`DM_PLAY_IN` tick, `DM_NVN_SHOT_ANCHOR=render`) | removed the replay thread's up-to-a-frame jitter and the capture-window shift, but two anchored runs still differ in 1421/4345 draw counts (33%) and 0 vs 37 shards; the guest clock/run-start anchor is still missing (the ToGame alignment does not fire for Cuphead). |
| Metal validation layer (`MTL_DEBUG_LAYER=1 MTL_SHADER_VALIDATION=1`) | caught a real MTL4 barrier misuse in the copy encoder (`MTLStageAll` on a compute encoder; valid: Dispatch\|Blit\|AccelerationStructure); fixed. The layer then runs the whole game with no assertion or validation error; the shard rate is unchanged (113/499 at 8000 vs 124/499 baseline). Not an API-usage bug. |
| Buffer-copy source snapshotted at encode time | no effect (27/500 vs 27/498 at area >= 12000). |
| Uniform content / inline updates / deferred updates (`DM_NVN_UB_DEFER=0`) | no effect. |
| Binding identity, pipeline state, vertex layout, draw parameters, draw set/order, texture binding | identical on corrupted and phase-matched clean frames (0 transient hits). |
| Integer vertex inputs | 0 of 1515 vertex shaders bit-cast an input. |
| Encode-time vertex read race (`DM_NVN_WATCHVB`) | 5 rewrites in 4500 frames, none on a corrupted frame. |
| Same-pass feedback sampling | zero snapshots for this game. |
| Vertex stream snapshots (readable half, copy-fed half, faithful post-write image) | no effect; aligned A/B 74/250 (image) vs 60/249 (zero) at area >= 8000. |
| Index post-write image (`DM_NVN_SNAP_IB=ab`) | no effect; the image changed up to 11797 bytes in one frame and 19.3 MB over a run. 19/248 vs 26/250 and 21/245 vs 19/254 at 8000. |
| Uniform post-write image (`DM_NVN_SNAP_UB=ab`) | shards persist in the image arm (1965, 2233, 1985); 15/242 vs 17/257 at 8000, 6 vs 9 at 12000, 4 vs 8 at 15000 - a small, not significant reduction. |
| Shared `MTL4ArgumentTable` mutated per draw | per-draw private tables give the same rate: 64/250 vs 64/249 at 8000, 43 vs 40 at 12000, 36 vs 37 at 15000. |
| Present path mixing two frames / stale framebuffer | the corrupted region matches no frame within +-20 frames (best 19.4 % of the mask); it is freshly rasterised wrong geometry. |
| Command-memory ring, uniform-update ring, four command buffers | not the 4-frame cadence. |

**Conclusion so far:** the GPU receives NVN-correct, immutable vertex, index and uniform bytes and still
produces one blown-up triangle. The draw's CPU-side inputs, their provenance and their delivery are
excluded. What remains is (a) texture content, especially textures sampled by vertex shaders (the only
data class not measured; a wrong vertex-stage texture displaces vertices), and (b) the draw's own
encoding/execution (which command the GPU runs, render-target aliasing, pass order). The GPU-lag/CPU-rewrite
race is now excluded in-run; safe math is not established. The guest-frame input/capture anchor is in place
(Round 42); the run-start anchor is still missing, so cross-run comparisons remain invalid.

## Round 41: GPU drain and safe math

The old "not GPU lag" exclusion compared two runs (synchronous 94/501 vs baseline 18/501), which violates the
in-run rule. `DM_NVN_DRAIN=ab` (added in this round) waits for the frame's own submission on every second frame:
8000 77/249 (drain) vs 70/250 (async), 12000 55 vs 51, 15000 41 vs 42. No reduction, so the GPU-lag/CPU-rewrite
race is excluded in-run.

Safe math was tested by recompiling the 1515 vertex shaders offline with `xcrun metal -fno-fast-math` (pixel
shaders unchanged) and running the shard-rich deterministic route. The safe run (safeB) had 48/37 shards at 8000,
25/22 at 12000, 14/17 at 15000; an adjacent run with the restored fast shaders (fastB), same route and settings,
had **0/499 at every threshold**. A fast run can be clean, so run-level variance dominates and the safe-math test
is inconclusive, not evidence. A valid test needs an in-run fast/safe vertex-shader switch; the NaN / 1.7e38
values remain a lead, not an established cause.

A repeat of the fast control (fastC, same command, offset 20-57) had 96/86 at 8000 (39.2/33.9 %), 67/67 at
12000 and 51/54 at 15000 - higher than fullE. The fast shaders thus span 0-39 % across runs; the safeB rate is
inside that range. The difference is run-level variance, not the math mode.

The no-clock pair also repeated the scorer trap: the 124 vs 42 difference at 8000 was the death/retry transition
(diagonal wipe and menu), not the shard; the 1900-2100 gameplay was clean in both.

| | |
|:---:|:---:|
| ![GPU drain A/B](docs/cuphead/images/r41-drain-ab.jpg) | ![Safe-math VS shards](docs/cuphead/images/r41-safeB-shards.jpg) |
| **GPU drain A/B** - top frames; both the drain and async arms still show the shard. | **Safe-math VS (safeB)** - shards persist (2145/2148, 2271/2274). |
| ![Fast VS clean](docs/cuphead/images/r41-fastB-clean.jpg) | ![Death transition](docs/cuphead/images/r41-safeA-death-screen.jpg) |
| **Fast VS (fastB)** - zero shards in the same route; the safe-math comparison is confounded by run variance. | **safeA no-clock** - the scorer counts the death/retry wipe; the 1900-2100 gameplay is clean. |
| ![Fast VS repeat (fastC)](docs/cuphead/images/r41-fastC-shards.jpg) | |
| **Fast VS repeat (fastC)** - same fast shaders and command, offset 20-57: 96/86 shards at 8000; the fastB zero was not reproducible. | |

## Round 42: the guest frame is anchored; the run start is not

The replay was already stepped by `dm_guest_frame()` (the game's present frame), not the screen present count;
the screen offset only changed which game frames the captures sampled. The real jitters were the replay's
polling thread (up to a frame late) and `DM_NVN_SHOT` selecting by the screen present. Both are fixed:
`DM_PLAY_IN` applies its steps in `dm_guest_frame_tick`, and `DM_NVN_SHOT_ANCHOR=render` captures by guest
frame.

Two anchored fast runs still diverged: A had 467 captures and 37 shards at 8000, B 442 captures and 0; the
same render-frame draw counts differ in 1421 of 4345 common frames (33%; F144 A=7 B=11, F189 A=11 B=7), and
the same-F images are out of phase. The replay/capture anchoring removed its own jitter, not the run-level
divergence.

The missing anchor is the run start. The `DM_DETCLOCK` "on entering a run (ToGame)" alignment never fires for
Cuphead (the uimsg hook is d2r's), so the guest clock is seeded from the wall clock at the first present: the
two runs' time base differs by the boot/loading wall time, and the time-based animations plus the absolute-
frame input/capture windows are phase-shifted. Align the guest clock and rebase the input/capture at Cuphead's
own run start (its uimsg, or the save/level load), not at the first present.

The display-link offset across runs does not explain the rate:

| run | offset mean / max | shards >=8000 |
|---|---|---|
| fullE | 35.5 / 54 | 134/499 |
| safeB | 30.5 / 50 | 85/499 |
| fastB | 60.1 / 99 | 0/499 |
| fastC | 38.8 / 57 | 182/499 |
| atB | 20.7 / 33 | 128/499 |
| idxB | 9.3 / 13 | 45/499 |
| idxC | 28.0 / 40 | 40/499 |
| ubB | 33.7 / 50 | 32/499 |
| drainA | 8.9 / 10 | 147/499 |

It is a marker of present lag, not the cause. The same-F comparison of four earlier runs shows close draw
counts but different player/particle positions; at F2100 only fullE has a shard, at F2300 only fullE has
died. The shard is run-level timing; the in-run A/B remains the only clean comparison, and the texture-content
A/B must be in-run too.

| | |
|:---:|:---:|
| ![anchored same-F](docs/cuphead/images/r42-anchor-same-f.jpg) | ![same-F four runs](docs/cuphead/images/r42-same-render-4runs.jpg) |
| **Two anchored fast runs at the same render frame** - the player/effect phase differs; 1421/4345 draw counts differ, 37 vs 0 shards. | **Four earlier runs at the same render frame** - similar scenes; F2100 only fullE shards, F2300 only fullE has died. |

## Round 43: the Metal validation layer found a real barrier bug, not the shard

`MTL_DEBUG_LAYER=1 MTL_SHADER_VALIDATION=1` aborted at startup on the copy encoder's intra-encoder barrier:
`blit_barrier()` used `MTLStageAll` for `barrierAfterEncoderStages:beforeEncoderStages:` on an MTL4 compute
encoder, whose valid encoder stages are Dispatch, Blit and AccelerationStructure. This was a real API misuse
in the copy ordering (the encoder that serializes the guest's buffer/upload/copy work; `DM_NVN_BLIT_ORDER=0`
is known to bring back the fountain stripes). The barrier is now `Dispatch|Blit`.

The fixed host runs the full validation run: 501 captures, 501 maps, no assertion and no further validation
error. The shard rate is unchanged: 113/499 at 8000 (22.7 %), 81 at 12000, 68 at 15000, against the no-clock
baseline's 124/499. The invalid barrier was not the shard's root cause; after the fix the validation layer
reports nothing more, which places the remaining cause in data/execution rather than API usage.

| | |
|:---:|:---:|
| ![validation run top](docs/cuphead/images/r43-valid-top.jpg) | |
| **Validation run (fixed barrier)** - 113/499 shards at 8000; after the copy-encoder fix the layer reports no API error. | |

## Round 45: the shredding is fixed - a buffer-copy source reused before execution

`mtl_sub_copy` encoded `enc_b_copy_buffer` straight from guest memory. The GPU reads the source when the copy
executes; Cuphead uploads each mesh's index buffer from a staging buffer and recycles that staging buffer for
the next mesh before the copy runs, so the copy wrote the next mesh's bytes into the destination. On frame
2102 the terrain index buffer held another mesh's list (max index 495 against a 423-vertex stream); the
terrain draw fetched vertices past its stream and the ground disappeared.

`DM_NVN_DUMP` (per-draw index/vertex dump) showed the index buffer's tail changing between otherwise identical
frames, with `pend 1` on every draw's index buffer: a GPU copy had not executed yet when the CPU read the
buffer, so the earlier "index buffer overwritten" reading was the stale CPU view, not what the GPU saw. The
failure was the copy's source.

The fix snapshots sources of copies <= 8 MiB into a host ring at encode time and encodes the copy from there,
so the GPU copies the bytes as of the copy's position in the command stream; this is what the inline uniform
update already did. Default on, `DM_NVN_COPY_SNAP=0` restores the old path.

Verification: `DM_NVN_COPY_SNAP=1900-2400` gave 2/499 at 8000, 0 at 12000/15000; with the default on, three
consecutive 90 s runs gave 0/499 at all three thresholds, against the historical 20-40 %.

Provenance: `mtl_sub_copy` is upstream (seedds f739638/50a9c65); the snapshot mechanism and its default are
this fork's (ce87f41/bfb586c/021c612). The fix is generic and is upstream PR seedds/nxnative#21 (f3057ac,
branch armyja:copysnap).

## Open problems and next steps

1. **Geometry shredding - resolved (Round 45).** Root cause: `mtl_sub_copy` encoded a GPU copy from guest
   memory; Cuphead recycles the staging buffer for the next mesh before the GPU executes the copy, so the
   terrain index buffer got another mesh's indices (max 495 against a 423-vertex stream) and the ground
   disappeared. Fix: snapshot sources of copies <= 8 MiB at encode time and copy from the host ring
   (`021c612`, `DM_NVN_COPY_SNAP=0` disables). Verified 0/499 at 8000/12000/15000 in three consecutive runs
   (baseline 20-40 %). Generic fix, upstream PR seedds/nxnative#21.
   The leads below were the pre-fix hypotheses and are kept for the record; none of them was needed.
   - **Historical: run-start anchor.** The guest clock and the absolute-frame input/capture windows shift
     with the boot/loading because the detclock ToGame hook does not fire for Cuphead; align at Cuphead's run
     start and rebase the windows. Cross-run comparisons are still invalid without it.
   - **Historical: texture content, especially vertex-stage texture fetches.** Not the shredding's cause.
   - **Historical: the draw's own encoding/execution and the Metal GPU frame capture.** The capture was built
     and used in Round 44; the cause was found in Round 45 without a draw-level answer.
   - **Historical: fast-math / NaN amplification.** The cross-run safe-math test stayed inconclusive; not the
     shredding's cause.
2. **Frame-957 deadlock - open.** 5 of 10 deterministic-clock runs; the guest main thread and two workers
   wait on one condition variable. The host's process-wide key path already fixes one lost wakeup; this looks
   like a second instance. Workaround for capture runs: omit `DM_DETCLOCK` / `DM_DETCLOCK_PACE`.
3. **Do not repeat the excluded directions** in the table above; they were measured with in-run A/Bs.


## The frame-957 deadlock

In 5 of 10 runs with the deterministic clock (`DM_DETCLOCK=16666667 DM_DETCLOCK_PACE=1`) the game stops
rendering at frame 957: the guest main thread and two worker threads wait on the same condition variable
and never wake. The display link is still alive; the log ends at `[snapvb-frame] F957`. Runs without
`DM_DETCLOCK` (real clock) passed, and so did 5 of the 10 deterministic runs; it is intermittent and
correlates with host load. The host already fixes one lost-wakeup case in `svcWaitProcessWideKey`
(`dm/host/hle_thread.c`, `dm/host/tests/t_condvar.c`); this looks like another instance. It is independent
of the shredding and is recorded here because it blocks long capture runs.

## Diagnostics added by this fork

- `DM_NVN_SHOT` / `DM_NVN_SHOT_OUT`: capture selected present frames to PNG (downscaled).
- `DM_NVN_FP`: one line per draw with vertex/index/uniform hashes and `prim/first/bv/bi`.
- `DM_NVN_SNAP_VB=full`: bind the NVN-order post-write image of every vertex stream, per-frame 50/50.
- `DM_NVN_SNAP_IB=ab`: the same for index buffers, with `[snapib-frame]` coverage (`copied`, `diff`).
- `DM_NVN_SNAP_UB=ab`: the same for uniform blocks.
- `DM_NVN_ARG_TABLE=ab`: shared vs one private `MTL4ArgumentTable` per draw, per-frame A/B.
- `DM_NVN_DRAIN=ab`: every second frame waits for its own submission before returning to the game.
- `DM_NVN_SHOT_ANCHOR=render`: select captures by the guest frame instead of the screen present.
- `MTL_DEBUG_LAYER=1 MTL_SHADER_VALIDATION=1`: the Metal validation layer; aborts on API misuse (it found the copy-encoder barrier).
- `DM_GPU_CAPTURE=<render frame>` (+ `MTL_CAPTURE_ENABLED=1`): a single-frame `.gputrace` (starts at the frame's first draw, stops at the first present at or after it). Keep it on APFS; the exFAT 2 TB volume and the frame-list variant produced traces Xcode could not open.
- `DM_NVN_DUMP=<render frame>:<dir>`: per-draw index buffer and vertex streams (past the declared range up to the largest index) as small `.bin` files, with a `_meta.txt` (shader, addresses, counts, `pend`).
- `DM_NVN_VB_OVERLAP=1`: log indexed draws whose index bytes physically overlap the bytes their vertices occupy.
- `DM_CAPTURE_CLICK=1`: a left click in the floating window arms a capture at the next full frame.
- `DM_NVN_COPY_SNAP=0`: disable the encode-time snapshot of small copy sources (the Round 45 fix; default on).
- `DM_NVN_PENDK`, `DM_NVN_PASSDUMP`, `DM_NVN_CBDUMP`, `DM_NVN_VBBOX`, `DM_NVN_SKIP_DRAW`.
- `[shot-map] present=N render=F`: joins a capture to the draw-side frame.
- `DM_WINDOW_SMALL` / `DM_WINDOW_FLOAT`: a 480x270 floating capture window that does not take key focus.

The Python tools are in `dm/tools/` (`scanarea.py`, `shotscore.py`, `sheet.py`, `sheetl.py`, `fpana.py`,
`pdbind.py`, `playout.py`, `runrec.py`, `snapv_sched.py`). The development work folder's copies are not part
of this repository.

## Credits

This is a fork of [nxnative](https://github.com/seedds/nxnative), which is built on d2r-mobile, Ryujinx,
Atmosphère, yuzu, LibHac, SPIRV-Cross and others; see the main README's acknowledgements and
`dm/third_party/README.md`. The Cuphead profile and the diagnostics in this fork are additions on top.
The base project and this fork are MIT; no game code or assets are included.
