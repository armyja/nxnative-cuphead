<!-- Cleaned copy of the working handoff; personal paths are placeholders:
     <repo>, <cuphead-work>, <saves>. The round-40/41/42/43 status in ../FORK-NOTES.md supersedes the status
     sections below. -->
> **Round 39 audit correction (2026-10-20):** The round-38 vertex-axis exclusion below is invalid.
> The `DM_NVN_SNAP_VB=full` draw-side parser never sets `sv=2`; it parses `full` with `atol` as a
> frame 0-0 window. All fvA/fvB/fvC logs report zero image copies. The write journal ran, but the
> image was never bound. Read the round-39 entry in FINDINGS before relying on any round-37/38
> treatment/control conclusions. A corrected, coverage-verified experiment is in progress.

# Cuphead shard work - handoff (round 38)

This is the document to read first; it supersedes the narration in any chat log and the older
`REPORT-for-review.md`. The long-form record with every round and every retraction is
`FINDINGS-2026-10-20.md` (rounds 1-38).

Status: **not solved. Root cause not identified. No fix may be claimed.**
The game boots, plays at 60 fps, and a small fraction of frames show geometry shredded across the screen.

---

## 1. Objective and hard constraints

Cuphead (`0100A5C00D162000`, Unity 2017.4.9f1 / IL2CPP / NVN SDK 5.5.0.0) must play on macOS through the
nxnative static-recompilation host (NSO -> arm64, NVN -> Metal) without geometry shredding (stretched
triangles, dark streaks) and without hangs during long play.

- Source: `<repo>`, branch `cuphead`. **Commit locally only, author armyja
  <>, never push.** Branch `aa123-port` stays untouched; `AGENTS.md` in that repo is not to
  be edited or followed.
- Data, captures, dumps, this document: `<cuphead-work>`.
- Build: `make -C dm/host GAME=0100A5C00D162000 dmhost`.
- Screenshots are downscaled (320x180) before anybody looks at them.

Commits added in rounds 33-38 (all local):

    d2d72df nvn: make the post-write vertex image faithful - the vertex axis is closed
    bfb586c nvn: classify GPU-side writes per consumer binding; experimental post-write vertex image
    aeceac6 nvn: DM_NVN_FP records primitive type, first vertex and base vertex/instance
    ce87f41 nvn: DM_NVN_COPY_SNAP snapshots buffer-copy sources at encode time
    f9fa61a nvn: DM_NVN_SNAP_VB binds encode-time copies of the vertex streams
    85d89b7 tools: pdbind reports whether a field moves at all
    ab4ad77 nvn: v2 draw fingerprint with uniform hashes; shard tools score measured sets only

---

## 2. Reproduce the artefact (three traps here, all measured)

The save-state snapshot decides whether the artefact exists at all. The snapshot that reproduces it is
`<saves>/pair`; a later one (`snap`) gave 0 corrupted frames in two runs out of two.

    W=<cuphead-work>; cd $W
    rm -rf <saves>/myrun
    cp -a <saves>/pair <saves>/myrun
    SH=$(/usr/bin/python3 -c 'print(",".join(map(str,range(1900,2401))))')
    ./boot.sh myrun 110 DM_SAVE=<saves>/myrun \
        DM_DETCLOCK=16666667 DM_DETCLOCK_PACE=1 \
        DM_PLAY_IN=$W/rec_input/player1.in DM_NVN_SHOT_OUT=320x180 \
        "DM_NVN_SHOT=$SH:$W/myrun/d_%04d.png"
    ls myrun/d_*.png | wc -l          # MUST be 501 - verify before measuring anything

Measure (never "looked clean"; always a count per run):

    /usr/bin/python3 scanarea.py 'myrun/d_*.png' 12 12000   # area-ranked; prints the measured set
    /usr/bin/python3 sheetl.py sheet.jpg 'myrun/d_*.png' 9 200 150 1900 1920

Traps:

1. **Zero captures are no data.** A 92 s alarm produced 0 captures in three runs with a healthy-looking log
   (59.4 fps, "frame 900") and no error message. 2400 frames are reached at ~45 s *only while the game
   window is frontmost*; use 110-150 s and check the count and frame range first.
2. **An occluded window throttles the run to ~8-15 fps** (2400 frames: 45 s frontmost vs >150 s with the
   browser in front). This is what looks like "the game stalls at frame ~900". Check
   `grep "power up to frame" run/<name>.log` before declaring a hang.
3. **Every run writes the save directory**, so runs are not comparable across sessions (fp1 and fp2 hash
   different vertex bytes for the same draw at the same frame index). Give each run of an A/B pair its own
   `DM_SAVE=` copy of one snapshot. The save snapshot also decides *whether* the artefact appears.

Cadence: the artefact repeats every 4, 20 or 40 frames depending on the run, and the phase **moves inside a
run** (sc1's measured set is mostly `== 3 (mod 4)` up to frame 2139 and then drifts through 2 and 3).
Never assume `frame % 4`; measure the set from that run's captures.

---

## 3. What the artefact looks like (measured, not impression)

- Most frames: the whole screen covered by one flat-coloured triangle with a single straight diagonal edge
  (snapF F1948/F1968, 20 frames apart). Other runs: long thin spikes radiating from a point plus a pale
  stretched sheet (fp2 F2123, cpF F2249, ubA2 2213+).
- Neighbouring frames are clean, and the pixel-domain test says the anomalous region (13k-22k px at 320x180)
  matches **no** other frame within +-20 frames (best match explains 19.4 % of the mask within +-2 grey
  levels; clean-frame controls 4-22 % on ~500 px masks). So it is freshly rasterised wrong geometry, not a
  stale framebuffer and not two frames mixed.

---

## 4. Excluded by measurement (do not redo)

| direction | evidence |
|---|---|
| vertex data: content, provenance **and delivery** | `DM_NVN_SNAP_VB=full`, a faithful post-write image (encode-time bytes + every copy/update/fill recorded earlier in the submission, sources resolved through earlier writes) bound immutably in host memory: 3 runs, shard present in all three, 59.9-60.0 fps: **201/750 (26.8 %) image vs 195/747 (26.1 %) zero-copy** at area>=8000; 18.5 % vs 19.8 % at >=12000; 14.8 % vs 15.3 % at >=15000 |
| vertex streams: CPU-readable half overwritten after encode | `DM_NVN_SNAP_VB=ab`, 3 runs: 91/750 (12.1 %) vs 101/747 (13.5 %) |
| buffer-copy source rewritten before the GPU runs | `DM_NVN_COPY_SNAP=ab`, complete coverage (186 242 / 200 404 copies, 838 / 844 MB, 0 too large): 27/500 (5.4 %) vs 27/498 (5.4 %) |
| a GPU-written input exists only on corrupted frames | `DM_NVN_PENDK=1`, 2 runs with the shard (55/499, 17/499): dependency pattern identical on both - vertex streams 50 % copy-fed / 50 % readable, index buffers 99 % copy-fed, uniforms ~100 % inline-update-fed, fills 0, **texture-to-buffer 0 everywhere** |
| texture-to-buffer copies feed a draw | same diagnostic: t2b covers 0 of 55 corrupted and 0 of 446 clean frames for vertex, index, uniform and indirect consumers |
| uniform-block content | fp2: `u00` 1/130 (0.8 %) vs 56/5116 (1.1 %); `u10` 2/130 vs 96/5116; primA (501 frames): `u00` 11/835 (1.3 %) vs 201/15007 (1.3 %), `u10` 0/835 vs 175/15007; staleness (`cur == f-k`, k=1..8) lower on corrupted frames at every lag |
| binding identity + pipeline state | sc1 passdump 2140-2210, measured set 19 frames, **13 359 field comparisons: 0 hits**; the variability column shows only cb address, tex id/serial, index-buffer address and `v.a0-a2` ever move, none in the transient shape |
| vertex attribute layout | 12 layout fields constant (`live 0/0`), 7 shader groups each with exactly one layout, 586/586 corrupted draws use their group's layout |
| draw parameters | primA: 21 421 records, `prim` is 4 (triangle list) for every draw, `first`/`bi` constant, `bv` moves 24 of 15 842 comparisons with 0 transient hits, `vc` 0 corrupted hits |
| draw set / draw order / composition | fp2: 0 of 3 corrupted frames carry a composition transient (clean 1/156); draws per frame identical to both neighbours (41/41/41, 44/44/44, 45/45/45) |
| texture binding identity | sc1 measured set: 0 corrupted hits; the 3 clean hits are texture id 1760 -> 1920 for one frame (animation) |
| in-pass uniform-update deferral | `DM_NVN_UB_DEFER=0` verified active in the run's log: still corrupt, 35/499, visually confirmed at 2232/2236/2240 |
| GPU lag / submissions in flight | `DM_NVN_MAX_INFLIGHT=0` verified active (mi0.log:98), 501 frames: 94 corrupted vs 18 baseline - more, not fewer |
| present mixes two frames / stale framebuffer | pixel-domain test above |
| command-memory ring | wraps at frames 0 and 947, not every 4 |
| uniform-update ring | replaced every ~300 frames |
| four command buffers | one handle per frame, addresses advance linearly |
| integer vertex inputs | 0 of 1515 vertex shaders bit-cast an input |
| encode-time vertex read race (`DM_NVN_WATCHVB`) | 5 rewrites in 4500 frames, none on a corrupted frame |
| same-pass feedback sampling | `DM_NVN_FB_SNAP=all` takes zero snapshots for this game |
| merged-pass deferral | `DM_NVN_DEFER=0` still corrupt; and deferral is off by default (`defer_on()` requires `tbdr_on()`, which this profile leaves off) |
| scene geometry stretched / UI quad / 1.233 block | older rounds, see FINDINGS |

---

## 5. Instrumentation added in rounds 33-38

Host switches (all `nvn_mtl.m` unless noted):

| switch | what it does | gotcha |
|---|---|---|
| `DM_NVN_FP=a-b` | one line per draw: vertex-stream hashes, index hash, UBO hashes, `prim/first/bv/bi` | hashes **guest memory at encode time**, so for copy-fed buffers it records the pre-copy bytes |
| `DM_NVN_SNAP_VB=ab` / `=a-b` | bind an encode-time copy of each vertex stream (skips streams with a pending GPU write) | covers only the CPU-readable half |
| `DM_NVN_SNAP_VB=full` | bind each vertex stream's **post-write image** (all copies/updates/fills applied in submission order), per-frame 50/50 hash schedule | the faithful model: delivery cannot matter; index buffers are **not** covered yet |
| `DM_NVN_COPY_SNAP=ab` / `=a-b` | buffer-copy source snapshotted into the host ring at encode time | complete coverage is logged |
| `DM_NVN_PENDK=1` | per frame, per consumer binding: which write kind covers it (1 copy, 2 update, 3 fill, 4 t2b, 0 readable) | one line per frame change |
| `DM_NVN_PASSDUMP=a-b`, `PASSDUMP_ALL=1` | per-pass/per-draw records incl. binding identity and pipeline state | without ALL only each pass's first draw is recorded |
| `DM_NVN_UB_DEFER=0` | end the pass on every in-pass uniform update | excluded as a cause already |
| `DM_NVN_MAX_INFLIGHT=n` (hle_nvn.c) | cap submissions in flight, 0 = fully synchronous | makes the artefact more frequent |
| `DM_NVN_SYNC_SUBMIT` | **documented in a comment, not implemented** | use `DM_NVN_MAX_INFLIGHT=0` |

Offline tools in `dm/tools/` (copies in the work folder):

- `scanarea.py <glob> [topN] [th]` + `shotscore.py` - the one frame-transient scorer (area and peak row).
  Calibration: fp2 shard frames 28168/20577/18267, next highest 4274.
- `sheetl.py <out.jpg> <glob> [cols] [tile] [thr] [first] [last]` - labelled contact sheet with red boxes.
- `fpana.py <log> --bad ...` - `[fp]` predicate scoring: P1 `prev == next != cur`, P2 both-neighbour,
  P3 staleness by lag; prints corrupted and clean numbers plus an audit block.
- `pdbind.py <log> --bad ...` - the same over `[pass]` records: binding identity, pipeline state and a
  per-field "does it move at all" column.
- `playout.py <log> --bad ...` - vertex layout (fmt/off/stream/stride/div) vs binding, plus per-group layout
  diversity and "is the corrupted draw's layout its group's majority".
- `runrec.py <id> <glob> <log> [--analysis fpana.json]` - freezes a run's measured evidence.
- `fpmatch.py` - superseded, requires `--bad` now.
- `snapv_sched.py <a> <b>` - reproduces the per-frame 50/50 hash schedule used to classify captures.

Code map (for whoever continues):

- `draw()` - vertex binding loop (`enc_r_vbuf`), the `[fp]` emitter, `SNAP_VB` arms, `PENDK` classification.
- `mtl_sub_copy` / `mtl_sub_update` / `mtl_sub_fill` - the three GPU-side write kinds; `pkw_apply` builds the
  post-write images; `ubd_*` is the deferred-unform shadow (`ubd_shadow`, `ubd_conflict`).
- `enc_r_begin_pass` / `enc_r_end_pass` / `m4_end` / `blit_raw` / `blit_barrier` - every render pass gets a
  full `barrierAfterQueueStages:MTLStageAll beforeStages:MTLStageAll visibilityOptions:MTL4VisibilityOptionDevice`
  and a full end barrier by default (`DM_NVN_BARRIER=game` relaxes it; statistics line
  "draw-pass entry barriers full N / saved 0").
- Index-buffer binding for the normal indexed draw: `nvn_mtl.m` ~line 5915-5921
  (`enc_r_draw_indexed(en, mp, di->count, type, gpu, buffer.length - mo, ...)`), indirect at ~5859/5863,
  8-bit widening at ~5902/5913 (those two already bind an arena copy - the pattern the next experiment needs).
- `g_vt` / `g_ft` - one argument table per stage for the whole process, mutated per draw via `setAddress:`.
- `mtl_addr` / pools - guest memory is wrapped as zero-copy `newBufferWithBytesNoCopy` shared buffers.

---

## 6. Rules learned the hard way

1. A run proves something only if the artefact is observed **in that run**; report the count. Zero is "no
   data" (or a throttled run), never "fixed". Same build, same route: 18 vs 94 of 501.
2. The corrupted set is measured from that run's captures, never assumed (it is not `frame % 4`).
3. Verify the filter before the run: switch spelling, filename pattern, glob order, and the switch's own log
   line in that run's log. **Never** trust a grep for a switch name - `DM_NVN_MAXINFLIGHT` vs
   `DM_NVN_MAX_INFLIGHT` cost a false retraction once.
4. Match draws by (vertex key, fragment key) with equal draw count, never by frame-local ordinal.
5. Phase-matched controls: clean frames 20 frames away share the same 20-frame vertex-buffer "burst". A
   predicate that fires 8.3x more on corrupted frames against *all* clean frames fires 0x against
   phase-matched burst frames.
6. Negative results must carry predicate, effective sample count, proof the predicate executed, **and** a
   note on which fields/consumers were constant (a 0 for a field that never moves proves nothing).
7. `prev == next != cur` only sees single-frame transients; a difference persisting on two consecutive
   frames, or a field that changes every frame, is invisible to it.

Retractions to keep in mind (details in FINDINGS):

1. `FB_SNAP=all` "fixed" the shard - it took no snapshots at all.
2. "draw 24 / UI/Default quad is the shard" - a repeat with the same skip was corrupt.
3. "corrupt frames carry a 1.233 uniform scale" - ordinary UI content.
4. rounds 30-31: the corrupted set was assumed (`frame % 4 == 2`), and `fpmatch.py` on disk still had that
   assumption until round 34 - so the older texture numbers had to be redone.
5. round 33: the "8.3x lift" on vertex content is the 20-frame burst (clean frames reach 24 hits).
6. round 33: `runrec.py` wrote a hard-coded `analysis_result` (hits_bad 0 / hits_clean 3 / ambiguous 23)
   into every record, including `runrec_sc1.json` on disk. Nothing computed those numbers.
7. "Index content is identical across frames" (rounds 26-33) compared **pre-copy** bytes: 99 % of index
   buffers are copy-fed and `[fp]` hashes guest memory at encode time. The claim needs the image method
   (which has not been applied to index buffers yet).
8. round 37: the post-write image arm looked *worse* (57/250 vs 47/249) because the image was one step
   short; with the missing writes applied the arms converge (round 38).

---

## 7. Where the work stands

Every input the CPU hands the GPU for a draw has been measured on corrupted and on phase-matched clean
frames and none of them separates the two: vertex content, vertex provenance, **vertex delivery** (via an
immutable NVN-order-correct image), index content as recorded, uniform content, uniform binding identity,
texture binding identity, vertex attribute layout, pipeline state, draw parameters, draw set and order.

The remaining, precisely bounded surfaces are:

1. **Index and indirect-argument data, as the GPU actually reads it.** 99 % of index buffers are copy-fed,
   and unlike vertex streams they are still bound zero-copy (`~line 5915-5921`), so a corrupted index value
   is not yet excluded. One wrong index reads a vertex from elsewhere in the buffer and produces exactly
   the observed "one triangle blown up across the screen".
2. **Texture content.** The only data category with no measurement at all. Texture *binding* identity is
   clean and texture-to-buffer copies feed nothing, but a draw can still sample a texture whose content the
   guest rewrote between encoding and execution.
3. **Uniform delivery.** Uniforms are ~100 % fed by inline updates whose payload is already copied into the
   host ring at encode time, so this is expected to be the same class as the vertex image and is expected
   negative - but it has not been tested the same way.
4. **The draw's own encoding** (which command was decoded) and anything outside the draw (pass order,
   render-target content, present path). All the fields we can observe are identical; the pixel-domain test
   argues against a stale or mixed present.

---

## 8. Next experiments, in order, with decision criteria

1. **Index/indirect image.** Extend the faithful-image method to `di->ibuf` and to indirect-argument
   buffers: build the post-write image with `pkw_apply`, bind `g_cur_arena->gpu + off` (the 8-bit widening
   path at ~5902/5913 already does this), per-frame 50/50 hash schedule for the in-run A/B, same save
   snapshot, shard must be present in the run. Criteria: image arm clean while zero-copy arm is not -> the
   index path is the cause, then bisect which producer; both arms equal -> the index axis is closed too.
2. **Texture content.** Per-texture write counter (the host already write-protects CPU-written textures)
   folded into `[fp]`, plus content hashes only for the textures a suspect draw samples. Criteria as above.
3. **Uniform image.** Snapshot the ring payload per draw instead of relying on the shadow logic.
4. Only after 1-3 are closed: a targeted immutable replay of the first anomalous draw.

Every one of these must be run as an **in-run A/B** (per-frame hash schedule), because cross-run rates vary
by a factor of ten with the same configuration (161/499, 55/499, 26/499, 14/499, 3/161 for the same command
across snapshots and builds).

---

## 9. Questions a reviewer should answer

1. In Metal 4, is it safe to mutate **one** `MTL4ArgumentTable` between draw calls (`setAddress:atIndex:`)
   while earlier draws in the same encoder may not have executed yet? Does the driver snapshot the table per
   command, or does the GPU read the live table? (The host uses one table per stage for the whole process;
   the picture is mostly correct, which suggests per-command snapshotting, but this has never been verified.)
2. For a draw whose **index buffer** is filled by a blit earlier in the same `MTL4CommandBuffer`, is
   `barrierAfterQueueStages:MTLStageAll beforeStages:MTLStageAll visibilityOptions:MTL4VisibilityOptionDevice`
   at the start of the render encoder sufficient? Is there a stage-mask-specific form
   (blit -> vertex/index) that is stronger, and does `waitForFence`/`updateFence` buy anything beyond it?
3. Does `drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferLength:...` (address form)
   guarantee anything about bounds when the index data was produced by an earlier blit in the same command
   buffer, or must the producer be ordered another way?
4. Given the measurements above - the GPU receives NVN-correct, immutable vertex bytes and still produces
   one blown-up triangle - what classes of cause remain that a static-recompilation host controls? (raster
   state, viewport/scissor, depth clamp, culling, primitive restart, indirect arguments, argument-table
   contents at execution, render-target aliasing, ...)
5. Is there a known Unity 2017.4 NVN pattern for dynamic geometry (which NVN commands it uses to produce
   vertex/index streams, and any dependence on fence semantics) that a recompiler must special-case?

## Round 40 (aligned A/B; supersedes the round-38 status for the axes below)

`[shot-map] present=N render=F` now joins captures to arms. The r39_fullA numbers are invalid (unmapped). Measured in-run A/Bs:

- Vertex post-write image (fullE): 74/250 vs 60/249 at area>=8000 - no reduction. Vertex axis closed.
- Index post-write image (idxB, idxC): 19/248 vs 26/250, and 21/245 vs 19/254 at 8000 - no consistent reduction; the image changed 19.3 MB of index bytes over idxC. Index axis closed.
- Per-draw vs shared argument table (atB): 64/250 vs 64/249 at 8000 - identical. The shared table is not the cause.
- Uniform post-write image (ubB): 15/242 vs 17/257 at 8000, 6 vs 9 at 12000, 4 vs 8 at 15000 - the shard persists in the image arm; the small reduction is not significant. Uniform delivery is not the cause (or only a minor contributor).

Remaining: texture content (especially vertex-stage texture fetches - the only unmeasured data class), and the draw's own encoding/execution. Imaging a texture mid-pass needs a design because a texture copy ends the render pass.

Separate: intermittent guest deadlock at F957 (5 of 10 deterministic-clock runs) blocks the capture window; the no-clock run idxB passed. The guest main thread and two workers wait on one condvar. Not the shard.

## Round 41 (2026-10-20)

- GPU drain in-run A/B (`DM_NVN_DRAIN=ab`): 8000 77/249 drain vs 70/250 async, 12000 55 vs 51, 15000 41 vs 42 - no reduction. The old cross-run "not GPU lag" is replaced by this in-run result.
- Safe-math VS recompile (1515 VS, `-fno-fast-math`): safeB 48/37 at 8000, 25/22 at 12000, 14/17 at 15000; fastB, same route, 0/499 at every threshold. Run variance dominates; the safe-math test is inconclusive, not evidence. Needs an in-run fast/safe shader switch.
- Measurement: the no-clock pair's 124 vs 42 at 8000 was the death/retry transition in the scorer, not the shard; the 1900-2100 gameplay was clean in both.

## Round 41 addendum

- fastC (fast shaders, same command): offset 20-57, 96/86 at 8000 (39.2/33.9), 67/67 at 12000, 51/54 at 15000. fastB (same shaders/command, offset 18-99) was 0/499. The fast control spans 0-39%; the safeB 48/37 is inside the range. Safe-math remains inconclusive.

## Round 42 (2026-10-20)

- DM_PLAY_IN now applies at the guest frame tick (no polling thread); DM_NVN_SHOT_ANCHOR=render captures by guest frame. Code 2bf2d4a.
- Two anchored fast runs still differ: draw counts mismatch in 1421/4345 common render frames (33%); A 37 shards at 8000, B 0. Same-F images out of phase.
- Cause: the detclock ToGame alignment does not fire for Cuphead; the guest clock is seeded at the first present, so the time base (and the absolute-frame input/capture windows) shifts with the boot/loading. Next: align at Cuphead's run start and rebase input/capture.
- Offset vs rate: no simple relation (fastB 60/99 -> 0%; fastC 38.8/57 -> 36.5%; drainA 8.9/10 -> 29.5%). Same-F fullE/F2100 shard, others clean; F2300 fullE died. Shard is run-level timing; in-run A/B still required.
- First anchorA attempt hit the F957 deadlock; the retry passed; anchorB passed.

## Round 43 (2026-10-20)

- Metal validation layer (`MTL_DEBUG_LAYER=1 MTL_SHADER_VALIDATION=1`) found a real MTL4 barrier misuse: the copy encoder's `blit_barrier()` used `MTLStageAll`, valid on a compute encoder only as Dispatch|Blit|AccelerationStructure. Fixed to Dispatch|Blit.
- Fixed validation run: 501 captures/maps, no assertions or validation errors. Shard rate unchanged: 113/499 at 8000, 81 at 12000, 68 at 15000 (baseline 124/499). The barrier was not the shard root; no more API-usage errors.
- Next: GPU frame capture at a top frame (Metal debugger; MTL4 capture support), the host-side vertex-stage texture A/B, the VS clip-space dump. F957 via lldb.

## Round 44 (2026-10-20)

- `DM_GPU_CAPTURE=<render frame>` works on MTL4/Xcode 27.1: the capture starts at the frame's first draw and stops at the first present at or after it (the display link can skip the requested present). A 90 s `DM_GPU_CAPTURE=2152` run finalized a 2.0 GB trace (started 2152 draw, stopped present 2152) with 501 captures.
- The 2152 trace (draw 861, indexCount 1539, UInt16) shows the vertex stream and the index buffer as two offsets of the same guest MTLBuffer: Layout 16 at `0xCBA00` (stride 24), Index at `0xCCA00`. Only 4096 bytes (170.67 vertices) fit before the index buffer; the mesh needs 224 vertices (5376 bytes) for max index 223.
- The exported attributes are valid up to vertex ~170 and become `6.9e-39` / `(73,0,75,0)` from vertex 171, which is the index buffer's bytes read as vertex attributes. Indices >= 171 collapse to x ~ 0 and the triangles stretch: the long diagonal streaks. The shard is in `src`, not the present path.
- Next: log the index buffer range and the vertex stream range/size at draw time to separate a wrong NVNbufferRange (stream base/offset) from a guest overwrite of the stream tail. Separately, the present allocator fence uses `g_pq_done` (advanced to `ticket-1` by the display link before `present_now`), a real present-only lifetime bug.
- `DM_NVN_VB_OVERLAP=1` added (physical index/vertex byte overlap, restart sentinels skipped, plausibility filter). Two 90 s 2152 captures with it did not reproduce the shard; logged overlaps were false positives (the bytes at `di->ibuf` were not the draw's index list). Next: restrict to direct 16-bit draws and log the pass/serial to join the trace's draw 861. The old trace `cuphead-2152-old-final.gputrace` is the only shard ground truth.
