# Cuphead fork notes

This is a fork of [nxnative](https://github.com/seedds/nxnative) (MIT) for **Cuphead**
(`0100A5C00D162000`, Unity 2017.4.9f1 / IL2CPP / NVN SDK 5.5.0.0) on Apple Silicon macOS.

**Status: work in progress; not playable end-to-end.** The game boots, reaches the title, menu, world map
and the forest level at 60 fps with audio and input. Two defects remain:

1. **Geometry shredding.** Some frames show large flat-coloured triangles, horizontal tears or stretched
   spikes, with clean frames on both sides. The rate is 2-30 % of frames depending on the run and the save
   snapshot; the cadence is 4, 20 or 40 frames, and the phase moves inside a run.
2. **An intermittent guest deadlock at frame ~957.** 5 of 10 deterministic-clock runs stopped there: the
   guest main thread and two worker threads wait on one condition variable forever. It is independent of
   the shredding; runs without `DM_DETCLOCK` passed.

No fix is claimed. Every direction that was measured and its result is below; the raw round-by-round log
is [docs/cuphead/FINDINGS.md](docs/cuphead/FINDINGS.md) and the working handoff is
[docs/cuphead/HANDOFF.md](docs/cuphead/HANDOFF.md).

Nothing from the game is in this repository except a few downscaled screenshots used to document the
defect: no ROM/NSP/XCI, no keys, no extracted data, no patched binaries and no save files. You need your
own legally obtained copy and your own `prod.keys`; this project does not provide or explain how to obtain
either. Not affiliated with Nintendo or Studio MDHR.

## The two questions a reviewer asks first

1. **Texture content (especially vertex-stage), in-run A/B: not done yet.** The measured texture facts are
   *binding identity* (clean) and texture-to-buffer copies (they feed no draw); the content a draw samples has
   never been imaged. A per-frame A/B needs a private copy of each vertex-stage texture at encode time. A
   texture copy ends the render pass, so the snapshot has to be taken before the pass opens (or the pass
   re-opened after it); the design is in Open problems. Nothing in the table below covers texture content.
   It must be measured in-run: the route is not deterministic across runs until the run-start anchor exists
   (Round 42).
2. **"Not GPU delay", per-frame 50/50: done.** `DM_NVN_DRAIN=ab` waits for the frame's own submission on every
   second frame: 8000 77/249 (drain) vs 70/250 (async), 12000 55 vs 51, 15000 41 vs 42. No effect. This
   replaces the old cross-run `MAX_INFLIGHT` comparison (94 vs 18 of 501).

## What it looks like

These are contact sheets of the highest-scoring frames from the runs named in each caption (320x180
captures, labelled with the present number and the transient score). The defect is not subtle: one
flat-coloured triangle with a straight edge, or the scene torn into horizontal streaks; the frames on both
sides are clean.

| | |
|:---:|:---:|
| ![Vertex-image A/B](docs/cuphead/images/r39-fullE-vertex-image.jpg) | ![Index-image A/B](docs/cuphead/images/r39-idxB-index-image.jpg) |
| **Vertex post-write image (fullE)** - top 20 frames; binding the NVN-order vertex bytes does not change the rate. | **Index post-write image (idxB)** - top 20; the index image changes the bytes but not the defect. |
| ![Argument-table A/B](docs/cuphead/images/r39-atB-argument-table.jpg) | ![Uniform image A/B](docs/cuphead/images/r39-ubB-uniform-image.jpg) |
| **Per-draw vs shared argument table (atB)** - top 16; the two arms are identical. | **Uniform post-write image (ubB)** - top 12; shards persist in the image arm. |
| ![Unmapped r39 fullA](docs/cuphead/images/r39-fullA-unmapped.jpg) | ![Not shards](docs/cuphead/images/r39-fullC-particles-not-shards.jpg) |
| **r39 fullA** - the run whose captures were joined by filename; the numbers are invalid, the picture shows the defect. | **fullC** - high transient scores but clean particle effects; the scorer alone cannot classify a shard. |

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

## Open problems and next steps

1. **Geometry shredding (main).** Every CPU-side input and its delivery is excluded; the GPU still produces
   one blown-up triangle. Two leads remain:
   - **Run-start anchor.** The guest clock and the absolute-frame input/capture windows shift with the
     boot/loading because the detclock ToGame hook does not fire for Cuphead; align at Cuphead's run start
     (its own uimsg or the save/level load) and rebase the windows. Until then cross-run comparisons remain
     invalid and texture content must be measured in-run.
   - **Texture content, especially vertex-stage texture fetches.** It is the only data class not measured;
     a wrong vertex texture displaces vertices. A texture image cannot simply be copied mid-pass (a copy
     ends the render pass), so the first step is to record, per draw, which vertex-stage textures are
     bound and whether their content changes in the frame, then design the snapshot.
   - **The draw's own encoding/execution.** Which command the GPU actually runs, argument-table contents at
     execution (excluded for the shared table), render-target aliasing and pass order. A targeted
     immutable replay of the first anomalous draw is the fallback. A Metal GPU frame capture of an
     anomalous draw (geometry viewer, VS output, sampled textures) is the next direct look; the MTL4
     capture support is to be checked.
   - **Fast-math / NaN amplification.** The cross-run safe-math test is inconclusive (Round 41); a valid test
     needs an in-run fast/safe vertex-shader switch, or a NaN/Inf sanitizer on the translated vertex position.
     The NaN values in unused uniform slots and the 1.7e38 vertex attributes are the motivation.
2. **Frame-957 deadlock.** 5 of 10 deterministic-clock runs; the guest main thread and two workers wait on
   one condition variable. The host's process-wide key path already fixes one lost wakeup; this looks like
   a second instance. Workaround for capture runs: omit `DM_DETCLOCK` / `DM_DETCLOCK_PACE`.
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
- `DM_NVN_COPY_SNAP`, `DM_NVN_PENDK`, `DM_NVN_PASSDUMP`, `DM_NVN_CBDUMP`, `DM_NVN_VBBOX`, `DM_NVN_SKIP_DRAW`.
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
