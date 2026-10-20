<!-- Cleaned copy of the working log; personal paths are placeholders:
     <repo>, <cuphead-work>, <saves>. This is not the summary: several claims were retracted later,
     and the current state is ../FORK-NOTES.md. -->
# Cuphead shard analysis, 2026-10-20

## What is established

Boot path is complete: title -> menu -> world map -> forest level, 60.0 fps
(p50 16.67 ms, p95 16.80 ms), no hangs, no crashes in 60 s replay runs.

Three host gaps were found and fixed to get there (all committed on branch `cuphead`):
1. `hid::GetKeyboardStates` (plural) was not taken over, so the SDK body read the keyboard shared
   memory the host never fills and aborted with an empty-string assertion (main+0x1396E04).
2. `device_api` must be 53.x with minor > 208; the host default 55.15 trapped right after WindowCrop.
3. Command memory accounting: the modules are 76 MB, more than the 64 MB reported as used, so the
   game's own 0xC9400000 heap request failed the pool check and Unity's dlmalloc asserted.

## The picture has two distinct defect classes

### Class A - whole view wrong (big blue triangles, another part of the map on screen)
Seen on the world map every ~4th frame at K=0 (unbounded submissions).
**Disappears when `nvn_hostseg_only` is off** (records go into the game's own command memory).
Cause: the host-lent command segments were reclaimed 8 frames after their recording, but the game
keeps CALLing recorded command handles, so the replay read overwritten commands. This is the failure
the rewriter's own comments warn about ("the old reclaim-8-frames-after-lending rewrote the segment
while the game still CALLed it").

### Class B - thin horizontal light-black streaks and stretched geometry (the user's "shards")
Still present with `nvn_hostseg_only` off. In the forest level the corrupted frames are 1910, 1914,
1918 - **all == 2 (mod 4)**, and the phase is stable within a run but shifts between runs
(another run corrupted 1143/1147/1151 == 3 (mod 4)).

Eliminated so far for class B:
- GPU lag / submissions in flight: `DM_NVN_MAX_INFLIGHT` 0 (fully synchronous), 1, 2, unbounded -
  the corrupted phase stays. So it is not "the GPU reads memory the CPU already rewrote".
- The game's command-memory ring: `DM_NVN_WRAPLOG` shows the ring wraps at frames 0 and 947
  (~950 frames apart), not every 4 frames. So the 4-frame cadence is not that ring.
- Integer vertex inputs: 0 of Cuphead's 1515 vertex shaders bit-cast an input, and none declares
  uint inputs, so the documented "stretched into streaks" cause (`int_inputs`) does not apply here.

## Open leads
- A 4-frame cadence with a phase that is stable within a run points at a ring of 4 on one side.
  The host's own 4-slot rings are: `g_vis_ring[4]` (visibility buffers, fenced) and the submission
  arena ring (fenced by `g_done`). Neither is obviously wrong, but neither has been cleared either.
- On the corrupted frame `DM_NVN_PASSDUMP` shows 2 extra `Y` lines; `Y` is `copy_b2b` / `signal_event`.
  So the bad frame performs two more buffer copies or event signals than its neighbours.
- `DM_NVN_MAX_INFLIGHT=0` with `nvn_hostseg_only` off hit
  `FATAL buffer copy address is in no memory pool src=0x714d24a600 dst=0x714d2d6b00 n=0x1e0` at frame
  1200: the host dies instead of reporting when a copy names memory outside every pool. Separate
  robustness bug, worth fixing on its own.

## Tools left behind (work folder)
- `boot.sh <log> <secs> [VAR=value ...]` - one run, log in `run/`.
- `shot.sh <name>` - screen grab, downscaled JPEG.
- `imgdiff.py <glob>` - mean pixel difference between consecutive frames (PIL, no numpy).
- `sheet.py <out.jpg> <glob> [cols] [tile]` - contact sheet; the way these findings were made.
- `rec_input/player1.in` - 141 recorded console inputs to the forest level (frame-numbered).
- `DM_RECORD_IN` / `DM_PLAY_IN` for new recordings, `DM_NVN_SHOT=<frames>:<path>` for frames,
  `DM_NVN_MAX_INFLIGHT`, `DM_NVN_HOSTSEG_ONLY`, `DM_NVN_HOSTSEG_AGE`, `DM_NVN_WRAPLOG`.

## Round 2 additions

### The shard shape, at full resolution
The top of a corrupted level frame holds a **horizontally smeared band**: the whole scene squeezed
into the top ~15 % of the picture, the rest normal. That is the shape of a full-screen quad with one
vertex at the wrong place, so the corruption sits in a *full-screen pass*, not in the world geometry.

### FXAA (the game's own AA pass) is involved but is not the whole story
48 consecutive frames from 1900, FXAA on: corrupted frames are **1913, 1917, 1929, 1937 - all
== 1 (mod 4)**, the phase stable over the whole run. With `DM_NVN_NOFXAA=1` those frames are clean,
but the run corrupts later instead (**1936 fully black**, 1941 and 1945-1946 smeared). So skipping
FXAA moves the symptom rather than removing it.

### The cadence is stable within a run and shifts between runs
Observed phases: == 1 (mod 4), == 2 (mod 4), == 3 (mod 4) in different runs. Whatever has the
period of four is seeded per run, which is what a ring picked by an initial index looks like.

### A black frame argues for the presentation path, not the draw data
One frame of the FXAA-off run is entirely black. Geometry cannot turn a whole frame black that way;
a swapchain texture that is presented before the frame's rendering finished (or one that was only
cleared) can. The user's own description of the residual artifact - "horizontal, light black" -
matches tearing rather than a wrong mesh.

### Where that leaves the work
Not established yet: whether the present blit can read the game's swapchain texture while the next
frame is already rendering into it (the game cycles 3 textures and it is the host that decides which
one the drawable gets), and whether the host honours the acquired index. That is the next thing to
read, before any more experiments.

## Round 2 result

Shipped: `nvn_hostseg_only off` in the profile (the whole-view corruption class), verified with a
60 s replay - frame 3900, p50 16.67 ms, the only "CRASH" line is the alarm's sig=14.

Eliminated this round:
- Present-path tearing: `present_main` waits on the GPU event value of the frame before it presents
  (`ext_wait(it.ev_val)` then `present_now`), and the present blit is encoded on the same ordered
  queue, so the drawable cannot read a half-rendered swapchain texture.
- Buffer copies as the signature: `DM_NVN_COPYLOG` shows the bad frame is not distinguished by its
  copy count (52 against 54 and 58 on its neighbours).

Still open, in the order I would attack them:
1. What has a period of four and a phase fixed per run. Candidates left: the host's submission arena
   ring (fenced by `g_done`) and the argument-block reuse rule ("reused only within the same pass").
2. Whether the smeared band is one full-screen pass (FXAA is full-screen and skipping it moved the
   symptom rather than removing it) reading a vertex/uniform source that another of the four slots owns.

## Round 3: eliminated list (do not redo these)

| Tried | Result |
|---|---|
| `nvn_hostseg_only on` (records in host segments) | whole-view corruption every ~4th frame - class A. Off now. |
| submissions in flight 0/1/2/unbounded (`DM_NVN_MAX_INFLIGHT`) | corrupted phase unchanged: not GPU lag. |
| `DM_NVN_NOFXAA=1` | the corrupted frames move, they do not go away. |
| `DM_NVN_DEFER=0` (merged-pass deferral off) | still corrupt (1907, 1913). |
| buffer copies as the signature (`DM_NVN_COPYLOG`) | bad frame is not distinguished by copy count (52 vs 54/58). |
| command-memory ring (`DM_NVN_WRAPLOG`) | wraps at frame 0 and 947, ~950 apart: not a 4-frame ring. |
| four command buffers | each frame submits exactly one handle, addresses advance linearly ~0x8600/frame: no ring of four. |
| integer vertex inputs (`int_inputs`) | 0 of 1515 vertex shaders bit-cast an input; the documented streak cause does not apply. |
| presentation tearing | `present_main` waits on the frame's GPU event (`ext_wait(it.ev_val)`) before `present_now`, and the blit is on the same ordered queue. |
| the "3D every other frame" extrapolation | off by default (`g_frz_on` needs `DM_NVN_TEST_FRZ`). |

## What the artifact actually looks like (for whoever picks this up)

Not thin lines only: a corrupted frame contains **large translucent quads with wrong vertices** - a
grey-white fan covering the top half (1907), a full-width band across the bottom (1913), the whole
scene squeezed into the top 15 % (earlier crop). A frame with a wrong full-screen quad. That is why
per-draw localisation kept failing: the offending draw is not stable enough to follow, but the
*shape* says a quad's vertices were read while something else owned that memory.

Strongest remaining hypothesis: the host reads vertex / uniform memory **at encode time**, whereas
the GPU reads it later. Anything the guest writes between our read and the "real" read shows up as a
wrong vertex. The 4-frame cadence is then the game's own buffer cycle, whose phase depends on where
startup left it. Testing it needs a way to make the read and the write exclusive - copy the ranges a
submission reads at record time into fenced host memory, or stall the guest's writes into ranges a
pending replay has read (the host already tracks those with `pend_hits`).

## Round 4: the encode-time-read hypothesis is dead

Built `DM_NVN_WATCHVB=1`: snapshot each vertex range on first use in a submission, compare it again
just before the commit, and print the frame when the guest rewrote it.

Result: the guest does rewrite ranges the host already read (e.g. `1 of 19` on the first run), but
only at F1020, F1021, F1950, F1951 and F2197 - **five times in 4500 frames, none of them a corrupted
frame** (the corrupted ones were ~1909 and ~1913). So "the host reads vertex data too early" is not
what produces the every-fourth-frame corruption. Do not redo it.

Also eliminated: `vconv_bind` (the CPU conversion of integer attributes into the frame arena). Its
cache is keyed by `g_sub_serial`, so it cannot leak across submissions, and it only runs when a
vertex input is used as raw bits - which no Cuphead shader does.

## Next target (round 5)

The uniform-buffer shadow path, `nvnCommandBufferUpdateUniformBuffer` -> `ubd_*`: a deferred update is
used in place when it covers the range, otherwise updates are laid into the arena "in order". A shadow
that misses or reorders one update in a cycle gives exactly what is seen - a large translucent quad
(an effect drawn from a handful of vertices) placed with the previous draw's or the previous frame's
transform, one frame in four, shifting phase per run. Read that path next; do not start another
rendering-wide experiment before it is read.

## Round 5: the uniform paths are guarded, and the copy drop is rare

- `ubd_*` (deferred inline uniform updates): reading the whole path, the shadow is only used when
  `ubd_covers` holds, `ubd_conflict` ends the pass when a vertex / index / indirect buffer would read
  deferred data, and a partial cover falls back to the pre-update content with `RED 92`. No red lines
  of that kind appear in any run, so the guard is doing its job.
- The 1 MB uniform-update ring is replaced at F0, 350, 658, 956, 1167 - every ~300 frames, not every
  four. (`DM_NVN_UBWRAP=1`.) Not the cadence.
- `ui_mat_patch` (which overwrites the UI matrix in stage 0 / cb0) only runs when `g_ui_moff != 0`,
  i.e. iPad fullscreen positioning; zero on the Mac.

Fixed along the way: a buffer copy whose address is in no memory pool used to `abort()` the whole
session (`FATAL buffer copy address is in no memory pool`). It now reports one red line and drops that
copy (`[dropcopy]` logs each one with its frame). The address in the observed case
(`dst=0x71000df600`) is inside the guest heap, which the host does not register as an NVN pool - the
game copies into plain heap memory, which is legal on hardware and unresolvable here. In one 80 s run
it did not happen at all, so it is rare and does not explain the every-fourth-frame corruption.

## Where this stands

Ten directions are now eliminated by measurement (see the table above plus this round). The artifact
is still there. What has NOT been tried, and is the next thing I would do:

- **Diff two runs of the same frames and look at where they first differ.** The phase shifts between
  runs, so something in the first frames differs. If the vertex data handed to one draw differs
  between two runs whose guest input is identical, that draw's source is not deterministic and the
  question becomes "what does the host read that varies".
- `DM_NVN_CBDUMP` gives byte-exact uniform blocks per draw; two runs' dumps of the same frame can be
  compared directly, which is the same idea for uniforms and needs no new code.

## Round 6: what a differential comparison can and cannot do here

Tried the "compare the same frame across two runs" method with `DM_NVN_CBDUMP` (byte-exact uniform
blocks per draw, no new code).

What blocks it: **the guest itself drifts between runs.** The same frame index produces 32 uniform
dumps in one run and 33 in the other, and the pass numbers differ, so the runs are not at the same
state and a byte diff is meaningless. Frame-based input replay fixes *when input arrives*, not the
guest simulation. Any cross-run comparison therefore needs a state anchor first (e.g. compare only
after both runs reach a state identified by something stable, or drive the guest with a deterministic
clock - `DM_DETCLOCK` exists in the host and has not been tried).

Within one run, frames 1908/1909/1910 each dump exactly **35** uniform blocks, so the draw set is
stable frame to frame there; comparing those is legitimate and is what to do next.

Also learned: `st0_cb0` contains **6-7 non-finite values out of 40 in every frame** (20/24/23 blocks
per frame across the three frames). That is normal data (unused slots), not the corruption - do not
mistake it for a smoking gun.

## The single most useful next tool

The corrupted frame is a full-screen effect reading the scene with a wrong transform (the whole
picture squeezed into a band is what a self-referential full-screen draw looks like when its UV or
MV matrix is wrong). To pin that draw without guessing: record, per draw, the *texture it samples*
and the transform it ends up with, and flag draws whose source is the current frame's own colour
buffer. There should be exactly one or two such draws per frame, and their uniforms can then be
compared with the game's intent frame by frame.

## Round 7: same-pass feedback sampling is one real cause (half of it)

The host has `fb_prepare`: when a draw samples a colour attachment of the render pass it is itself
writing, Metal's behaviour is undefined, so the host copies the attachment first and the draw reads
the copy. It only does this for fragment shaders the profile lists in `feedback_snap`, and **Cuphead's
list is empty**. `DM_NVN_FB_SNAP=all` applies it to every shader.

Result over 48 consecutive level frames (1900-1947): the big artefacts are gone - no smeared band, no
whole-view jump, no stretched quad. Before this, roughly one frame in four had one of those.
A second 48-frame range (2040-2087) was captured for confirmation.

Residual (reported by the user, and visible in 1903): **long thin dark diagonal lines / triangles**
across the grass, and they can appear on two consecutive frames. So this is a **third** class, not the
same one:

| class | symptom | status |
|---|---|---|
| A | whole view jumps to another camera, large blue triangles | fixed by `nvn_hostseg_only off` |
| B | whole picture smeared into a band, one frame in four | fixed by same-pass feedback snapshots (`DM_NVN_FB_SNAP=all`) |
| C | long thin dark diagonal lines/triangles, can be consecutive | open |

## Next steps
1. Replace `DM_NVN_FB_SNAP=all` with the minimal shader key list in the profile's `feedback_snap`
   (the "all" form splits a pass for every draw, which is only acceptable as a diagnostic). Finding
   the keys: log the fragment key whenever `fb_prepare` actually takes a snapshot, run once, and keep
   the keys that appeared - those are the only draws that need it.
2. Attack class C on its own: dark and elongated points at a shadow / outline mesh rather than the
   colour chain, so look at what samples or writes the shadow attachment.

## RETRACTION of the round-7 conclusion

Round 7 claimed that `DM_NVN_FB_SNAP=all` removed the every-fourth-frame corruption. **That is wrong.**

Instrumented `fb_prepare` to print the fragment key whenever it actually takes a snapshot, then ran
with `DM_NVN_FB_SNAP=all`: **zero snapshots were taken** in the whole run, and the same is true of the
earlier `fball` run that looked clean. So the switch did nothing at all; the 48 clean frames were the
intermittency, not a fix. Cuphead genuinely has no draw that samples an attachment of its own render
pass, which is why its profile's `feedback_snap` is empty and should stay empty.

Lesson to carry: a single clean 48-frame window proves nothing here. Any claimed fix needs the
mechanism to be *observed working* (a counter that is non-zero), not just a quiet picture.

Class table from round 7 is therefore also wrong; the corrected state is:

| class | symptom | status |
|---|---|---|
| A | whole view jumps to another camera, large blue triangles | fixed by `nvn_hostseg_only off` (counter-verified: 24/24 frames stable) |
| B | whole picture smeared into a band / stretched quads, often one frame in four | **open** |
| C | long thin dark diagonal lines, can be consecutive | **open** (may be the same defect as B seen differently) |

## Known-good baseline (measured 2026-10-20, round 8)

Profile `dm/games/0100A5C00D162000/game.tsv` on branch `cuphead`:

    device_api 53.313          # major 53 and minor > 208, otherwise the game traps after WindowCrop
    mem_used 0x4D00000         # modules are 76 MB; with 64 MB the game's own heap request fails the pool check
    nvn_hostseg_only off       # on = whole-view corruption every ~4th frame (reclaim of live recordings)
    app_pool 0xCD500000, mem_reserve 0x180000000, mem_alias 0x80000000, mem_stack 0x10000000

Host on that branch, rebuilt with `make -C dm/host GAME=0100A5C00D162000 dmhost`, run with:

    <cuphead-work>/boot.sh <log> <secs> \
        DM_PLAY_IN=<cuphead-work>/rec_input/player1.in

Measured: replay reaches the forest level, frame 2400 in 70 s, frame time p50 16.67 / p95 16.79 ms,
zero `FATAL`, zero `[RED]`. Boot -> title -> menu -> world map -> forest level all work; the only
remaining defect is the intermittent geometry corruption (classes B/C above).

Recording `rec_input/player1.in` (141 rows, frames 647-3025) is the reference route: title, menu,
storybook, world map, forest level, death screen. `DM_RECORD_IN` / `DM_PLAY_IN` capture new routes.

## Round 9: an automatic artefact scorer (the instrument this work was missing)

`artscore.py <glob> [threshold]`: for each frame, take the pixels that differ from **both** the
previous and the next frame by more than a threshold (so an animation or a scene transition, which
persists, cancels out), then report the area of the largest 4-connected region. Prints per-frame
scores, highest first.

Calibration on `shots/fa_19*.png` (the 48 frames whose corrupted ones are known from the contact
sheet): the top two scores are exactly the two corrupted frames, by a wide margin:

    16935  F1917      <- corrupted
    16138  F1913      <- corrupted
     8983  F1941
     4942  F1925
     2833  F1929      <- corrupted
     2801  F1909      <- corrupted

So "how many frames score above N" is now a usable, comparable number for any experiment, instead of
"this 48-frame window looked clean" - the mistake that forced a retraction in round 7.

## Round 9 addendum: the scorer's recall is not 100 %

On that same 48-frame set the corrupted frames known from the contact sheet are 1913, 1917, 1929 and
1937. The scorer ranks 1913 (2nd), 1917 (1st) and 1929 (5th) - but **1937 does not reach the top 12**.
So its recall on this set is 3 of 4.

Use it as a *comparative* number (same tool, same route, different build), never as proof that a build
is clean: a run scoring 0 above threshold may still show artefacts to the eye. That is the same trap
that caused the round-7 retraction, one level down.

## Round 10: the bug is now reproducible on demand (deterministic clock + pacing)

Every earlier round looked for the corruption inside a run that had to be watched in real time, and the
phase moved between runs. Two host switches, which exist but had never been used here, fix that:

    DM_DETCLOCK=16666667          # guest clock advances one fixed step per present (hle_os.c)
    DM_DETCLOCK_PACE=1            # ...and each frame's wall time is at least one step (hle_nvn.c, WindowAcquireTexture)

Command:

    ./boot.sh detA2 55 DM_DETCLOCK=16666667 DM_DETCLOCK_PACE=1 \
        DM_PLAY_IN=<cuphead-work>/rec_input/player1.in \
        DM_NVN_SHOT_OUT=640x360 "DM_NVN_SHOT=<frames>:<dir>/d_%04d.png"

Result: 598 scored frames of the forest level (1900-2499) contained **90 corrupted frames, all == 1
(mod 4)**. A second identical run corrupted on a different phase (mostly == 3), i.e. the per-run phase
is still seeded by something outside these switches - but *within* a run the cadence is hard and
stable, so a single run is now a usable fixture: the artifact can be asked for, at a known frame, as
often as needed.

Two identical runs are **not byte-identical** (pixel mean difference 10-60 between the same frame
index), so cross-run diffing is still off the table; the guest simulation itself drifts. Within-run
comparison remains legitimate (frames 1900-1990 share an identical draw set).

### What the artifact is, at 640x360

Not a black band: the corrupted frame is uniformly darker and carries **several long, thin, dark
ribbons with straight edges across the upper third** - stretched triangles, shaded dark (shadow-like),
over the trees. Same family as the user's "light black streaks". Nothing is missing from the frame.

### The pass structure of a corrupted frame is identical to its neighbours'

`DM_NVN_PASSDUMP=1940-1990` on the corrupted run: the corrupt frame F1943 has the same 31 passes, 28
draws, 56 shader keys, 92 bindings and 23 pass ends as its clean neighbours (F1942, F1944). So no draw
is dropped, added or re-bound - the defect is in the *data* one of those draws reads, not in the
sequence. (The earlier "2 extra Y lines" observation was positional, not a count difference.)

### Tools added this round (work folder)

- `scanband.py <glob> [topN]` - fast pre-filter: per frame, the largest fraction of a single row that
  differs from BOTH neighbours. ~4 s for 600 frames; ranks the corrupted frames far above clean ones.
- `sheetl.py <out.jpg> <glob> [cols] [tile] [thr] [first] [last]` - labelled contact sheet: grid, frame
  number + score burned in, red label and a red box drawn around the detected shard on suspects.
  `sheet_detA2_1941_2020.jpg` shows 17 of 80 frames flagged, every 4th frame exactly.
- `pdiff.py <log> <frameA> <frameB>` - positional / multiset comparison of two frames' passdump records.

### Next (round 11)

The suspect is one draw whose *input* is wrong on the corrupted frame. Plan: at encode time, compute the
clip-space bounds of the position attribute of every draw (the data is already read by `attr_read` for
the cover path) and log the draws whose extent is impossible (> 1e3 in x/y, or w <= 0). Join the flagged
draw with the passdump line and then dump that draw's vertex range and index buffer for the corrupt
frame and its two clean neighbours, compare byte for byte.

## Round 11: a draw-level bisection tool, and why group skipping does not work yet

Added `DM_NVN_SKIP_DRAW=a-b[,c-d]` (host, `nvn_mtl.m`, draw path): drops draws by their index **within
the frame**, everything else untouched. The index has to be frame-local - `g_stat_draw` is cumulative,
so the first version (which used it directly) skipped nothing at all after the first frame of the
process, and the run looked unchanged. Verified fixed by the log line and by the picture.

Two groups tried on the reproducible window (frames 1900-2060, `DM_DETCLOCK=16666667
DM_DETCLOCK_PACE=1`, replay route, 480x270 captures):

| skipped | result |
|---|---|
| draws 0-13 | max band score 30 (baseline 150-250, i.e. the artefact is gone) - **but the scene is gone too**: the frame is a near-blank bright field. The first 14 draws carry the visible scene. |
| draws 14-27 | the run slows to ~20 fps and never reaches the level inside 45 s (frame 900 at the alarm), no captures, no FATAL / RED line. Unexplained; dropping the post passes seems to change the game's frame pacing. |

So the artefact lives in the same 14 draws that produce the visible picture, and dropping a group
cannot separate "the draw that is wrong" from "the draws that are the picture". Bisection therefore
needs to keep the frame intact: recolour a draw (or a small set) instead of dropping it, and look for
the ribbon in that colour. `DM_NVN_HILITE` already does this per *fragment shader key*, but every scene
draw shares one key (`ae73c1bfb1ed6a60`), so the next host change is the same override keyed on the
frame-local **draw index** (six draws per run, one colour each), i.e. 5 runs cover the 28 draws of a
frame.

Measured on the F1943 passdump: the frame is 28 draws / 31 passes; draws 0-26 are one mesh each into
`c0 ser=1010` + `d ser=1011` (1920x1080), then p27-p30 are four 6-vertex full-screen passes with
distinct keys (post chain). The 24 scene draws all share vertex key `8d06257195b04c7a` and fragment key
`ae73c1bfb1ed6a60`, so per-key diagnostics cannot tell them apart.

## Round 12: the shard is one UI draw (Unity UI/Default), and skipping it removes the artefact

Swept single draws with `DM_NVN_SKIP_DRAW=i-i`, one run each, frames 1900-2040, 141 captures per run,
`DM_DETCLOCK=16666667 DM_DETCLOCK_PACE=1` + the replay route:

| skipped draw | worst band score | verdict |
|---|---|---|
| 14, 16, 17, 18, 19, 20, 22 | 255, 244, 246, 250, 213, 253, 219 | artefact still there |
| **24** | **64** | **artefact gone, picture intact** (scene, characters, HUD all drawn; the sheet `sheet_sw24.jpg` shows 21 consecutive coherent frames at scores 9-17) |
| 15 | run never reached the level (0 captures) | separate anomaly, see below |

Draw 24 is pass `p27`: prim=4, **vc=6**, st=1, 1920x1080 target. Its shader pair resolves through
`dm/games/0100A5C00D162000/shader_map.tsv`:

    vertex  66ffc54aa13bbfdd  -> /Data/Resources/unity_builtin_extra#UI/Default#var19.0
    fragment 27e42b719904ee7a -> /Data/Resources/unity_builtin_extra#UI/Default#var19.4

So the defect is **a full-screen Unity UI quad** (the built-in UI/Default material, six vertices = two
triangles), not world geometry and not the post chain. A UI quad whose vertex data or transform is
wrong is exactly the "whole picture smeared into a band / large translucent quad with wrong vertices"
shape recorded in the earlier rounds - one vertex out of place on a full-screen quad smears everything
it covers.

This also explains why every per-shader diagnostic failed to find it: UI/Default is one key shared by
every UI quad in the frame, and the earlier `DM_NVN_HILITE` / `DM_NVN_SKIP_FS` experiments could only
switch the whole class of UI draws, which visibly breaks the HUD and was therefore never pursued.

Open question for round 13: the UI quad's six vertices come from Unity's batched UI vertex buffer,
which the engine cycles (typically four slots - matching the 4-frame cadence). Next: dump that draw's
vertex range and its uniform block on the corrupt frame and on its two clean neighbours, in one run,
and compare byte for byte. `DM_NVN_CBDUMP_KEY` can already do the dump half of this, driven by the
vertex key `66ffc54aa13bbfdd`.

### Side finding: skipping draw 15 stops the run

`DM_NVN_SKIP_DRAW=15-15` (vc=12, the smallest mesh) never reaches the level inside 48 s - frame ~900 at
the alarm, no FATAL / RED. Same symptom as skipping 14-27 as a group in round 11. Worth its own look
after the shard: it is either a host dependency between passes or a game-side sync that the missing
draw starves.

## RETRACTION of the round-12 result (draw 24 / UI quad)

The "skipping draw 24 removes the artefact" result does **not** reproduce. Two follow-ups, same switch,
same window:

| run | frames | worst band | outcome |
|---|---|---|---|
| sw24 (first) | 141 | 64 | looked clean |
| sw24c (repeat, same window 1900-2040) | 141 | 255 (F1941) | corrupt |
| sw24b (same skip, later window 2100-2240) | 141 | 235 | corrupt |

So sw24 was a run whose corruption phase had not started inside the captured window - the same
intermittency that forced the round-7 retraction, one level down. The UI/Default identification of the
draw at frame-local index 24 is still *correct for that frame* (it is what the passdump says), but the
artefact is not that draw's, and index 24 is not even stable across the run: the frame's draw count
grows from 28 to 35+ as objects come on screen, so the same index selects a different pass at 2100
than at 1940.

Two things this proves about the method, to be applied from now on:
1. A run only counts as evidence if the artefact is **observed in that same run** - e.g. at least five
   frames above the band threshold. A clean-looking run is "no data", never "fixed" (round-7 lesson,
   now with a number).
2. Draw identity must not be a frame-local index. Use (shader key, vertex count) or the ordinal among
   draws sharing a key, both of which survive the draw count changing.

### Which sweep runs actually saw the artefact (band > 150), 141 frames each

    run     frames  >150  max
    sw14      141    28   255      skip draw 14
    sw16      141     6   244
    sw17      141    12   246
    sw18      141    11   250
    sw19      141     1   213
    sw20      141     9   253
    sw22      141    17   219
    sw24      141     0    64      <- the run that looked "fixed": it never saw the artefact
    sw24b     141    29   235      draw 24 skipped, later window
    sw24c     141     7   255      draw 24 skipped, same window as sw24

Every "still corrupt" row had the artefact observed in the same run, so those draws are excluded for
real. sw24 had zero observations, which is why it must not be read as a fix.

## Round 13: two dead ends and one host robustness bug worth fixing

- **Dropping the Unity UI/Default draw is not testable by skipping**: `DM_NVN_SKIP_FS=27e42b719904ee7a`
  never reaches the level - the run sits at frame ~900 for 92 s with a healthy 16.67 ms frame time, i.e.
  the game keeps presenting nothing / waits on something. Same symptom as skipping draw 15 and as
  skipping draws 14-27 as a group in round 11. So the UI pass is load-bearing for the game's progress in
  a way a normal cosmetic draw is not, and "skip it and look" cannot answer whether it carries the shard.
- **Per-draw vertex bbox (`DM_NVN_VBBOX=a-b`)**: the first version printed nothing at all - these draws
  have `rf.pos_attr == -1` (the position attribute index is only resolved for the cover path), so the
  guard skipped every draw. The fallback version (use attribute 0 when pos_attr is unset) reached the
  host but the run aborted before the window, on an unrelated host bug:

      FATAL uniform update target is in no memory pool dst=0x714d24a900 n=0x10

  This is the same class as the buffer-copy abort fixed in round 5 (`FATAL buffer copy address is in no
  memory pool`): the game updates a uniform block that lives in plain guest heap memory, which the host
  does not register as an NVN pool. It should report one red line and drop that update, not abort the
  whole session. A real-device-like build must not die here.

### Next

1. Fix the uniform-update abort the way the copy abort was fixed (report + drop, with the frame).
2. Re-run the bbox capture; the tool is the only one so far that can name a draw without perturbing the
   picture, so it is worth the two-line fallback.

## Round 14: the abort is fixed, and CPU-side vertex inspection turns out to be impossible here

- Fixed the `FATAL uniform update target is in no memory pool` (and the same pattern in the buffer fill):
  a destination outside every registered pool is guest heap the host never registered, which is legal on
  hardware, so it now prints `[dropub]` / `[dropfill]` with frame and addresses (first 400) and drops
  that operation instead of aborting the session. Verified: the run that used to abort now completes 201
  frames. This is the same treatment the buffer copy got in round 5.
- `DM_NVN_VBBOX` then produced 7459 lines, but only 52 of them carried a bbox: **7403 were `why=10`,
  i.e. the address of the vertex buffer is in no pool the CPU can read.** Cuphead's vertex buffers are
  GPU-private storage, so `attr_read` (which needs CPU-visible memory) cannot see them. Only the
  six-vertex draws resolved. Conclusion: per-draw CPU-side vertex inspection is not a usable instrument
  for this game; the same data has to be read back on the GPU side (blit to a shared buffer) if it is
  wanted at all.
- The run also had **0 corrupted frames** in 1900-2100 (band max ~60), i.e. another phase-lottery run:
  no correlation was possible even for the 52 draws that did resolve.

### A separate lead worth its own round: dropping draws stops the game at frame ~900

Three independent cases now (skip 15, skip 14-27, skip the UI/Default fragment key) all sit at frame
~900 with a healthy 16.67 ms frame time, exactly where the level loads. A normal draw being dropped
should not stop the guest. The shape of the symptom - progress stops, frame time stays nominal - is what
a fence or event that never gets signalled looks like. That is a host-side sync defect worth finding on
its own; it may even be connected to the shard, since a fence that is signalled late is one way for a
frame to be composed from data that is not ready.

## Round 15: the "not GPU lag" exclusion re-measured with the new rule (it holds)

The round-2 elimination of "the GPU reads memory the CPU already rewrote" rested on a 48-frame window,
which the phase lottery makes unreliable. Re-measured over 501 frames each, with the artefact counted
per run (band > 150), same route, same switches:

| run | frames | corrupted frames | worst band |
|---|---|---|---|
| baseline (`uiA`) | 501 | 18 | 246 |
| `DM_NVN_MAX_INFLIGHT=0` (fully synchronous, `mi0`) | 501 | **94** | 255 |

So submissisions-in-flight is still excluded - and going fully synchronous does not merely fail to fix
it, it makes it *more* frequent. Whatever decides whether a frame is corrupted is decided per run and
per stretch of the level, not by how much work is in flight.

Also a methodological number: the same build, same route, two runs: 18 versus 94 corrupted frames out of
501. Any experiment that compares a single 48-frame window against another single window can produce a
"fix" by luck alone; every future result must be a count of corrupted frames per run, with the run's own
count as the evidence that the artefact was there at all.

## Round 16: the frame-900 stall is a guest-side spin, not a blocked host fence

Thread dump of the stalled run (`uiB`, UI/Default fragment key dropped) versus the healthy baseline
(`uiA`) at the same point:

| | stalled (uiB) | healthy (uiA) |
|---|---|---|
| last frame printed | 900 | 5100+ |
| draws per frame at frame 900 | **6** | 11 |
| guest main thread 0x1001 | `running/not waiting`, svc 108831 in 91 s | `waits:condvar` |
| worker 0x1006 | condvar, svc 178531 | 64 ms/s of work |

So the guest main thread is not blocked in the host - it is spinning with an enormous syscall count
while the frame counter stays put, and it had already dropped to six draws per frame before it stopped
(11 on the healthy run at the same frame). That is a guest-side poll loop waiting for something that
never becomes true, not a host fence that was never signalled - so the suspicion from round 14 (host
sync defect, possibly related to the shard) is not supported by this dump. It is still a real defect in
the sense that the host gives the guest a different world when those draws are missing, but it is not
evidence about the shard and should not be chased further for it.

## Round 17: how to reproduce and measure (start here)

Everything below is on branch `cuphead` (host commit as of this round), work folder
`<cuphead-work>`.

Reproduce the artefact (deterministic clock + 60 fps pacing + the replay route):

    SH=$(/usr/bin/python3 -c 'print(",".join(map(str,range(1900,2401))))')
    ./boot.sh base 92 DM_DETCLOCK=16666667 DM_DETCLOCK_PACE=1 \
        DM_PLAY_IN=$PWD/rec_input/player1.in DM_NVN_SHOT_OUT=320x180 \
        "DM_NVN_SHOT=$SH:$PWD/base/d_%04d.png"

Measure: `/usr/bin/python3 scanband.py 'base/d_*.png' 5` (band > 150 counts as corrupted). Report the
**count per run**; a run with 0 counts is "no data", never "fixed". Same build, same route: 18 and 94
corrupted frames out of 501 in two runs, so single windows prove nothing.

Look: `/usr/bin/python3 sheetl.py sheet.jpg 'base/d_*.png' 8 200 150 1940 2000` (grid, score, red box).

Useful host switches found so far: `DM_DETCLOCK` + `DM_DETCLOCK_PACE` (reproducibility), `DM_NVN_SHOT`
+ `DM_NVN_SHOT_OUT` (frames), `DM_NVN_PASSDUMP=a-b` (pass/draw structure), `DM_NVN_CBDUMP` (+
`DM_NVN_CBDUMP_KEY=<shader key>` for that shader's vertex streams and indices - note this writes from the
raw guest pointer, so it works even for buffers `mtl_addr` cannot resolve), `DM_NVN_SKIP_DRAW=a-b`
(drops draws; makes the game stop at frame ~900 in some cases), `DM_NVN_VBBOX` (only resolves shared
buffers, so nearly useless here), `DM_NVN_MAX_INFLIGHT`, `DM_NVN_SKIP_FS`, `DM_NVN_HILITE`.

Established by measurement, do not redo: submissions-in-flight (0/1/2/unbounded; 0 makes it *more*
frequent, 94/501), presentation tearing, the command-memory ring, the uniform-update ring, four command
buffers, integer vertex inputs, the encode-time vertex read race (WATCHVB: 5 hits in 4500 frames, none
on a corrupted frame), same-pass feedback sampling (FB_SNAP=all takes zero snapshots), merged-pass
deferral (DEFER=0 still corrupt), the whole-view class (fixed by `nvn_hostseg_only off`).

Still open: which draw carries the artefact. Skips are unreliable (empty passes change the guest's
world), CPU-side vertex inspection is blocked by GPU-private storage, and the frame's draw count grows
(28 -> 35+) so frame-local indices are not stable identities. Best remaining route: `DM_NVN_CBDUMP_KEY`
on individual shader keys around the corrupted frames, comparing a key's vertex/UBO bytes on corrupt
frames against its clean neighbours in the same run.

## Round 18: the per-key dump attempt, and a timing trap

Tried the route this document recommends: `DM_NVN_CBDUMP=<dir> DM_NVN_CBDUMP_KEY=66ffc54aa13bbfdd_b`
(the Unity UI/Default vertex key) with 500 frame captures. Two attempts, both useless:

- first with `..._KEY=66ffc54aa13bbfdd` (no `_b`): zero dumps - the runtime key carries a `_b` suffix
  (as every `K` line in a passdump shows), so `strcmp` never matched.
- second with the `_b` suffix: the run only reached frame 1200 in 92 s, i.e. it never got into the level,
  so the draw under study never happened. The reason the runs got slower is not established (the dump
  I/O only starts once the draw exists, so it cannot be the cause); it may be the machine under load or
  a leftover host from the killed run.

Lesson for the next attempt: do not assume the previous run's speed. Print the reached frame in the run
summary and only accept a run that reached the capture window - the same "no data, not a result" rule,
applied to the *run* rather than to the artefact.

## Round 19: why the per-key dump produced nothing (two gates, not one)

A 150 s run did reach the capture window this time (501 frames, last budget print frame 8700), so the
run itself was fine - but still **zero files** in the dump directory. Reading the code again:

    if (all) { ... PD("v ...");
        const char *cbd = getenv("DM_NVN_CBDUMP"), *cbk = getenv("DM_NVN_CBDUMP_KEY");
        if (cbd && cbk && pr->sh[0] && !strcmp(pr->sh[0]->key, cbk)) { ... dump vb / ib ... } }

The vertex / index dump sits inside the `if (all)` block, i.e. it needs **`DM_NVN_PASSDUMP_ALL` as well**;
`DM_NVN_CBDUMP_KEY` alone dumps only uniform blocks. And even the uniform-block dump did not fire, so the
key string still does not match the runtime key - `66ffc54aa13bbfdd_b` is what the passdump prints after
my own `.replace('_b','')` was applied, so the printed form may not be the stored form either. Next
attempt: log the actual `pr->sh[0]->key` bytes once, and use that exact string (or match by prefix
instead of `strcmp`).

This is the third attempt at the same idea; the lesson is to verify the *filter* before the run, not
after, by printing one matched key at startup.

## Round 20: the per-key dump works - the incantation and the data are on disk

All three switches are needed; any one of them missing gives an empty directory and a wasted run:

    DM_NVN_PASSDUMP=1900-2200        # opens the per-draw record path for those frames
    DM_NVN_PASSDUMP_ALL=1            # ...for every draw, not just each pass's first
    DM_NVN_CBDUMP=<dir>              # the dump itself
    DM_NVN_CBDUMP_KEY=66ffc54aa13bbfdd_b   # the vertex shader key, WITH the _b suffix

Result: 301 frames, 2709 files in `cbu4/`, named `F<frame>_p<pass>_vb<stream>_<guest addr>.bin`,
`..._ib<type>_...`, and `..._st<stage>_cb<slot>_...` for uniform blocks. The UI/Default draw's stream is
`vb0`, 480 bytes per frame.

That run also produced the artefact: 4 corrupted frames (2157, 2162, 2189, 2199) out of 301 captures, so
the dump and the defect are in the same run and can be compared directly - which is the property every
earlier attempt lacked.

First look was inconclusive because `vb0`'s first 24 floats are all 0.0/1.0 on every frame (it is a
constant or a different attribute's stream, not the position stream). Next: unpack the streams with the
vertex format/stride from the same passdump `v` lines (attribute index, format, offset, stream, stride),
then compare the position stream of the corrupted frames against their neighbours.

Nothing has been changed in the renderer in this round.

## Round 21: the UI/Default draw is excluded by its own vertex data

Offline analysis of `cbu4/` + `ui4.log` (301 frames, 602 UI/Default draws, position attribute unpacked
with the `v` line's offset / stride):

- the reference max |position| over all UI draws is **620.0** (the median, and the same value on the
  corrupted frames 2157 / 2162 / 2189 / 2199);
- no UI draw on a corrupted frame has an out-of-range or non-finite position;
- the only outliers are frames 1900-1905 (max 876, three NaNs), i.e. before the level, in the loading
  screen, and they are identical on every one of those frames.

So the UI quad is **not** stretched - its six-to-thirty-six vertices are exactly the same on corrupted
and clean frames. This replaces the unreliable "skip the UI shader and look" test with a direct
measurement, and closes the UI-quad hypothesis for good.

What remains for that draw is its uniforms / textures (the `st0_cb0` dumps are in the same directory),
but since its geometry is correct the artefact has to come from something outside it as well - most
likely another draw whose vertex data was never dumped because the dump was filtered to one shader key.
The next run should either drop the `CB_DUMP_KEY` filter (dump every draw's uniform blocks) or be
repeated with the key of the draw that covers the ribbons' screen area.

## Round 22: a uniform-level lead - corrupt frames carry a 1.23 scale block

Reading the `st0_cb0` dumps (uniform block per draw, 160 B) of the UI/Default draws on clean and
corrupted frames of the same run:

    2155 (clean)  0 nan 0.125 0.785 -48 288 0 nan 0.128 0.76    |  268 342 ...
    2156 (clean)  0.121 0.719 -80.5 -136 0 nan ...              |  0 nan 0.203 0.728 252 -104 0 nan
    2157 (BAD)    1.23 0 0 0 0 1.23 0 0 0 0                     |  0.0016 0 0 0 0 0.0016 0 0 0 0
    2158 (clean)  0.0498 0.647 240 -192 0 nan ...               |  5.6e-39 ...
    2162 (BAD)    2.16e-38 ...                                  |  1 0 0 0 0 1 0 0 0 0
    2189 (BAD)    1.23 0 0 0 0 1.23 0 0 0 0                     |  0.0016 0 0 0 0 0.0016 0 0 0 0
    2199 (BAD)    0.0498 0.647 240 -192 0 nan ...               |  5.6e-39 ...

Two of the four corrupted frames carry a block that is a pure **uniform scale of 1.23** (and a
0.0016 scale next to it), while the clean frames carry scattered translation/UV-like values. 2189's
block is identical to 2157's, and 2199's identical to 2158's - i.e. the *same* block content recurs,
which is what a stale or wrongly indexed uniform slot looks like.

Caveat, stated so this is not over-read: the files were paired by position in the sorted list, not by
pass number, and the per-frame addresses differ, so it is not yet established that these are the same
draw across frames. The next step is to key the comparison by the draw's pass number and shader key
(both are in the file name) instead of by list position, and to check whether the 1.23 block belongs to
the draw that covers the ribbons.

## Round 23: the 1.23-scale lead does not reproduce under a proper key - resolve before trusting it

Re-ran the comparison keyed by the draw's ordinal in the frame (pass numbers sorted, instead of list
position) with a simple predicate: first four floats of the block are (1.23, 0, 0, 0). Result: **zero
hits over 301 frames**, including on 2157 and 2189 where the pairwise print in round 22 had shown exactly
`1.23 0 0 0 0 1.23 0 0 0 0`.

Two readings, and they cannot both be right:
1. round 22's print paired files by list position while this one sorts by pass number - if the order in
   which `glob` returns files differs from pass order, the "first block" is a different file in the two
   scripts, and the round-22 table compares unrelated draws;
2. the predicate is too strict (the block starts at a different offset, or 1.23 is not the first word).

Until that is resolved, the "corrupt frames carry a 1.23 scale block" line is **not evidence** - it is a
possible artefact of my own file pairing. The next step is to print, for one corrupted frame, the full
list of (pass, first 8 floats) and check by eye which file holds 1.23, then apply exactly that key.

## Round 24: resolved - the 1.23 block is real, and it is that draw's transform

With the file pattern fixed (`F<frame>_p<pass>_st0_cb0_*` - the earlier attempt matched nothing and
once returned empty), every UI/Default uniform block of the two frames, sorted by pass:

    frame 2156 (clean)  p36274 len=144  0.1211 0.719 -80.5 -136.5 0 nan 0.1208 0.7195
                        p36275 len=144  0 nan 0.2031 0.7275 251.5 -104.5 0 nan
    frame 2157 (BAD)    p36314 len=144  1.233 0 0 0 0 1.233 0 0 ...
                        p36315 len=144  0.001604 0 0 0 0 0.001604 0 0 ...

So on the corrupted frame the UI/Default draw's uniform blocks are **pure scales (1.233 and 0.001604)**
where the clean frame has translation/UV-like values, and the vertex stream of the same draw was
*identical* on both frames (round 21). Same geometry, different transform: that is exactly the shape of
the artefact - a screen-covering quad whose matrix is not the one the game meant.

2189 showed the same 1.233 block in round 22, so this reproduces on more than one corrupted frame.
What is not yet established: whether 1.233 is *wrong* or is simply the transform of a different UI
element that happens to be drawn on those frames; that needs the value the game intended, which the
`u` lines of a passdump for the same frame provide (buffer hash and the first 64 bytes in hex).

Next: PASSDUMP=2150-2200 on one run, take the `x` (hex) lines of the corrupt frames' UI draws, and read
the matrix the guest actually wrote; compare against the block the host ended up binding.

## RETRACTION of the round-24 lead: the 1.233 block is normal UI content

Counted the pure-scale block (first word 1.2333, next three zero) over all 301 frames of the same run:

- present in **37 of 301 frames**, among them plainly clean ones (1914, 1916, 1930, 1934, 1943, 1944,
  1954, 1974, 1983, 1999, ...);
- only **2 of the 4** corrupted frames have it (2162 and 2199 do not).

So it is the transform of some ordinary UI element that is drawn on roughly one frame in eight, not a
corrupt frame's signature. Round 24's "same geometry, different matrix, that is the artefact's shape" was
reading a coincidence: the two frames happened to be at different points of a UI animation.

What survives from rounds 21-24: the dumps work, the unpacking works, the UI/Default draw's vertex data
is demonstrably identical on corrupted and clean frames, and the tooling to compare any shader key's
streams/uniforms across frames is in place. What does not survive: any claim that this draw's uniforms
are wrong.

Method note: any "signature" must be counted against the whole run before it is called a signature. The
same mistake has now happened twice (round 7's clean window, round 12's clean draw) and this time it was
caught by counting, which is the intended workflow.

## Round 25: the scene-shader dump landed - data ready for the next analysis

Run `sc1` (150 s, `PASSDUMP=2140-2210`, `PASSDUMP_ALL=1`, `CBDUMP=cbu5`,
`CBDUMP_KEY=8d06257195b04c7a_b`, 161 frame captures 2100-2260) produced **9168 files** in `cbu5/`,
covering the scene draws around the known corrupted frame 2157:

    F2140_p35611_vb0_714d2e9400.bin   F2140_p35611_vb1_714d3d7400.bin
    F2140_p35611_ib1_714d2c1000.bin   F2140_p35611_st0_cb0_714d22e100.bin

Next: for each pass ordinal, unpack the position attribute (offset / stride from the frame's `v` lines
in `run/sc1.log`), and compare the corrupted frames against their neighbours in the same run - the same
method that excluded the UI draw, now applied to the geometry that actually covers the screen.

Also note the run reached frame 3300 and kept presenting, so this dump did not perturb the game the way
the skip experiments did; the dump path is safe to use for longer captures.

## Round 26: the scene geometry is not stretched either

Run `sc1` scored: 161 captures, **40 corrupted frames**, all == 3 (mod 4) (2103, 2107, 2111, ...), and
the dump window 2140-2210 covers several of them. Comparing every scene draw's position extent (max
|coordinate| over the first attribute, up to 3000 vertices) on corrupted frames against their immediate
neighbours:

    F2146 (BAD)  p35843=949 p35844=1 p35845=6109 p35846=926 p35847=4911 p35848=5506 ...
    F2145        p35804=949 p35805=1 p35806=6109 p35807=926 p35808=4905 p35809=5506 ...
    F2147        p35882=949 p35883=0 p35884=6108 p35885=926 p35886=4918 p35887=5505 ...

The extents agree with the neighbours to within ordinary animation (hundreds of units out of thousands),
on every corrupted frame checked (2142, 2146, 2150, 2154, 2158, 2162). So the geometry is not being
stretched: whatever produces the ribbons does not do it by handing the GPU a bad vertex buffer. This
closes the "stretched triangles" reading that the artefact's *shape* suggested since round 2 - its shape
misled us; the frame is not built from a stretched mesh.

(Also visible in the data and worth remembering: several draws carry values around 1.7e38 in the first
attribute on clean and corrupted frames alike, so that is normal data for this game, not corruption.)

Where that leaves the search: not geometry (now measured twice: UI quad and scene draws), not present
path, not submission lag, not the rings. The remaining measurable difference must be in what the draws
*sample* or in the order/uniform data, and the same dump now exists for the uniform blocks and index
buffers of those draws.

## Round 27: the dumped uniform blocks do not separate corrupted frames either

Ranked every scene draw's `st0_cb0` block by "how much the corrupted frame differs from *both* its
neighbours, compared with how much the two neighbours differ from each other" (a draw that is wrong on
the corrupted frame must differ from both sides while the neighbours agree with each other).

Aggregated over the 18 corrupted frames inside the dump window (2142, 2146, ... 2206; 33 ordinals):

    ord  hits>50 / n  median
      7      4/17      -7
      8      4/17     -15
      6      4/17     -18
     13      3/17     -18
     12      3/17     -25

No ordinal is anomalous on more than 4 of 17 corrupted frames, and every median is negative, i.e. the
"neighbours agree, the bad frame does not" pattern is not there. So the uniform blocks of these draws
are not what distinguishes a corrupted frame from its neighbours - another measured negative.

At this point the following have all been measured and excluded for the shard: geometry (UI quad and
scene draws), uniform blocks of the scene/UI draws, presentation, submission in flight, the command and
uniform rings, integer vertex inputs, same-pass feedback, merged-pass deferral. What is left that has not
been measured in the same way: the *index buffers*, the *textures sampled* (which the passdump `B` lines
give as ids), and the *order* in which draws and copies are encoded.

## Round 28: agreed next instrument - per-draw effective-input fingerprint (B+)

Decision: do not build a global freeze/replay (A) first. Add a per-draw fingerprint of the bytes the GPU
is actually going to read, and use the neighbour-agreement test from round 27 on it. A is kept for the
case "inputs and state identical, output still different".

Minimal version to implement (one host switch, one log line per draw, nothing else changes):

- `DM_NVN_FP=a-b` - for frames a..b, one line per draw:
  `[fp] F f4 ordinal pass vs=.. fs=.. vc=.. idx=<type/addr/count> vrx=<hash,len>.. ubx=<hash,len>..
   tex=<id/gen>.. vp=.. sc=.. tgt=..`
- Hash of the *actual* read range, never the whole buffer:
  - vertex: from first vertex (or index values + base_vertex) through count, per stream, using that
    attribute's offset/stride/divisor;
  - index: index offset + count x index type;
  - UBO: the bound range; if the shader indexes dynamically, label it `bound` not `read`.
- status per line: `complete` / `bound_only` / `unreadable`, so a heuristic never masquerades as an
  exact range.
- Resource identity = host logical id + generation (addresses are not identities); textures keep serial.
- Cheap 64-bit hash (XXH3-64 or FNV-1a) for screening; verify suspects byte for byte.
- Enable only for the window, add no GPU waits, copy nothing, do not touch submission order. Log the CPU
  cost and compare the corrupted-frame rate with the switch off (the round-6 lesson: 18 vs 94 out of 501
  for the same build).

Analysis (offline, reuses round 27's statistic): group draws by (pipeline, pass role), not by ordinal
alone (draw counts drift), then look for the field that satisfies prev == next != cur, and require that
the same field does *not* separate clean-frame triples.

First target window: 2140-2210 (dumps for that window already exist in `cbu5/`), starting with the
texture-id difference seen at ordinals 24/34 in round 26.

Verification criterion for the round: can the data answer "which input or state first diverged from a
comparable clean frame, before the corrupted one?" If yes, the next experiment narrows from the whole
host to one resource-update or state-replay path.

## Round 29: first run of the per-draw input fingerprint (B+) - weak, not decisive

`DM_NVN_FP=2100-2260`: 7342 lines, 161 captured frames, 31 corrupted. Neighbour-agreement test over
7004 draw triples (matched by frame-local ordinal, same vertex/fragment key), counting fields where
`prev == next != cur`:

    field   bad frames   clean frames
    ib        154           375
    v0        129           330
    v1          7            27

Rates per frame (31 bad, 129 clean): ib 5.0 vs 2.9, v0 4.2 vs 2.6. So the corrupted frames produce such
events at roughly 1.5-1.7x the clean-frame rate - a bias, not a separation. Ordinary animation and the
ordinal-based matching (draw counts drift) can explain that much on their own.

Verdict: **vertex and index content are not the divergence point** as far as this instrument can see.
The run itself is fine (7342 lines, 161 frames, the game kept presenting, so hashing does not perturb
it), so this is a measurement, not a failed run.

Two known holes in this version, both already planned: the vertex range is stride x count (a superset of
what is actually read for indexed draws, so it includes bytes the GPU never touches), and neither the
uniform ranges nor the texture bindings are in the fingerprint at all. The next iteration should add
UBO bindings (address/size/hash) and texture id + generation, since the round-26 texture-id difference
at ordinals 24/34 is still unexplained and is the only state-level lead not yet measured properly.

## Round 30: the tex0 difference does not survive proper matching either

Re-ran the round-26 texture-binding observation with strict matching: draws grouped by (vertex key,
fragment key), compared only within groups whose draw count is identical on all three frames, and asked
for `prev == next != cur` on the sorted texture-binding tuple.

Result over the 18 corrupted frames of the `sc1` window: **zero events**, on corrupted and clean frames
alike. So the earlier "tex0 differs at ordinal 24/34" was an artefact of ordinal matching across frames
whose draw sets had drifted - exactly the failure mode the round-28 plan predicted.

Status of the state-level leads: none of the measured fields (vertex content, index content, uniform
block content, texture binding identity) separates corrupted frames from clean ones under neighbour
matching. What is still missing from the fingerprint: UBO binding identity/range and texture
generation/content version (as opposed to texture id), plus a matching pass that tolerates draw-count
drift instead of discarding those groups.

Rule confirmed by three separate retractions now: a difference seen without matched identities is not a
lead until it survives the match.

## Round 31: the conclusion, tightened, and the audit rule for negative results

Formal wording for the texture-binding result: under the `sc1` data and the stated matching rule
(vertex key + fragment key, equal draw count on all three frames), the transient texture-binding
anomaly hypothesis is **not supported**. Coverage was verified after the fact - 6152 `K` lines, 10154 `B`
lines, 71 frames, 69 triples, 460 equal-count groups, with sample groups printed - so the zero is a
measurement and not a filter artefact. It is still not an exclusion of every texture-related fault.

Boundary conditions to keep attached to that number: 460 groups are not 460 independent samples (same
frames, passes and resources recur), and `prev == next != cur` only catches one transient shape - it
cannot see a persistent error, an error on both neighbours, content changes under an unchanged binding
identity, or draws that share a key but differ in other state.

Rule now mandatory for every negative result in this file: report the predicate, the effective sample
count, and evidence the predicate executed (lines parsed, frames covered, groups matched, groups
discarded as ambiguous, plus a few matched samples). A bare "zero events" is not acceptable.

Next, in this order: (1) UBO binding identity/range (resource id, generation, offset, length, plus the
existing content hash) so that "bound to a different region" and "same region, different content" are
distinguishable; (2) texture serial + generation + view + content version, reusing an existing write
counter if one exists rather than hashing whole textures per draw; (3) if both still have no
discriminating power, stop adding fields of the same kind and move to uncovered state and execution
semantics: index / base-vertex interpretation, viewport and render-target state, the actual vertex
attribute read pattern, and state inheritance between recording and replay.

## Round 32: correction - the round-30/31 bad-frame set was assumed, not measured

The audit block exposed a real error in the rounds 30-31 numbers: that script used `frame % 4 == 2` as
the corrupted set (true for an older run) instead of the set measured from the captures. For `sc1` the
measured set is **40 frames, mods {2, 3}** (2103, 2107, ...), not "18 frames == 2 (mod 4)".

Redone with the measured set (same matching rule, 23 ambiguous groups discarded):

    hits (prev == next != cur) on texture bindings:  bad frames: none    clean frames: 3 (vertex key 8d06...)

So the conclusion survives - no texture-binding transient anomaly on corrupted frames - but every number
quoted in rounds 30-31 came from a mislabelled set and is superseded by this line. The three clean-frame
hits are ordinary animation (a texture switching between two ids for one frame).

Method rule, added: the corrupted-frame set must be computed from the captures in the same run, never
assumed from a cadence seen in another run. The audit block (round 31) is what caught this; it should
have been in place before the first negative result, not after.

## Round 33: the v2 fingerprint (uniform hashes included) is analysed - negative; and the phase structure is not what we thought

Data: run `fp2`, 161 captured frames 2100-2260 at 320x180, `DM_DETCLOCK=16666667 DM_DETCLOCK_PACE=1`,
`DM_NVN_FP=2100-2260`; 7199 records (0 unparsable), 40-49 draws and 35-44 passes per frame.

Measured corrupted set of that run: **2123, 2163, 2203**. Predicate: the frame differs from BOTH
neighbours by >40 grey levels over >=8000 pixels (480-wide rescale); scores 28168 / 20577 / 18267, the
next highest frame 4274 (F2140) - a 4.3x gap - and all three were confirmed by eye on the captures
(black wedge plus a pale stretched sheet over the bottom right). Tool: `scanarea.py 'fp2/d_*.png'`.

Analysis (`fpana.py`, identity-matched by (vertex key, fragment key), only groups with equal draw count:
3 corrupted triples, 156 clean triples, 62 groups discarded for draw-count drift, 130 field comparisons
on corrupted triples), predicate `prev == next != cur`:

| field | corrupted | clean | lift |
|---|---|---|---|
| v0 | 44/130 (33.8 %) | 208/5116 (4.1 %) | 8.3x |
| ib | 30/130 (23.1 %) | 192/5116 (3.8 %) | 6.2x |
| v1 | 0/130 | 2/5116 | - |
| **u00** | **1/130 (0.8 %)** | **56/5116 (1.1 %)** | **0.7x** |
| **u10** | **2/130 (1.5 %)** | **96/5116 (1.9 %)** | **0.8x** |

The handoff's next action 1 is therefore closed as a negative: **uniform-block content does not separate
corrupted frames from clean ones** - both fields fire *below* the clean rate, and the two hits are the
ordinary one-frame animation the clean set shows too. Staleness is negative as well: `cur == frame f-k`
for k = 1..8 is *lower* on corrupted frames at every lag (43.8 % vs 52.2 % at k = 1), so the corrupted
frame is not re-reading older content either.

The 8.3x on v0 is **not** a lead, and the reason is the most useful thing in this round: it is the
20-frame burst. Frames 2103, 2123, 2143, 2163, 2183, 2203, 2223, 2243 all carry 18-29 `prev == next !=
cur` hits on the scene batch's vertex and index content; the corrupted frames are only *every other*
burst (2123, 2163, 2203 == 3 (mod 40)), and the clean bursts reach the same level (F2103 24 hits, F2183
23, F2243 22, F2143 18). So the predicate identifies "this is a burst frame", not "this frame is
corrupt". Against the whole clean set the lift looks like 8.3x; against the phase-matched controls it is
zero. Another instance of the rule that a candidate filter is not a criterion - and the concrete form of
"controls must be phase-matched, not merely clean".

Two structural facts, measured, that all earlier rounds had folded together:

1. The cadence is not "4 frames, stable phase". In fp2 the visible corruption is 40 frames apart. In
   `sc1` the measured set (40 frames, band > 150, identical to runrec_sc1.json) is == 3 (mod 4) only up
   to 2139 and then drifts through 2 and 3 (2142, 2146, 2147, 2150, 2151, ...). Both the period and the
   phase move; any analysis that assumes `frame % 4` silently mislabels a large part of the set (which is
   how round 30-31 got its numbers).
2. The 20-frame burst is the level's own dynamic-vertex-buffer recycling: the same contents recur across
   bursts (e.g. one 360-byte quad buffer hashes to `8a8a87d5...` on 2122/2124 and `46fc0c66...` on
   2119/2121/2123/2125, and the whole scene batch's contents repeat at 2103/2143/2163/2183). It is not
   the defect (clean frames have it) but it is the trap that produced the 8.3x.

And a limitation of the instrument that must be attached to every fingerprint result: `DM_NVN_FP` hashes
*guest* memory at encode time. For a draw that reads a deferred in-pass uniform update, the host hands the
GPU a *shadow* (nvn_mtl.c `ubd_shadow`), so the bytes the fingerprint hashed are not the bytes the shader
reads. The fingerprint is structurally blind to that path.

## Round 34: state and binding identity measured properly - also negative; two host paths excluded; three measurement traps

**1. The [pass] state record, scored against a measured set (`pdbind.py`).** sc1's passdump covers frames
2140-2210: 71 frames, 10154 binding records, matches by (vertex key, fragment key) with equal draw counts:
18 corrupted triples, 51 clean, 22 groups discarded, **11277 field comparisons**. Fields scored: constant
buffer identity (address / size / pool), texture identity (tid, serial, format, dimensions, view levels,
view slice, target), sampler state, and per-draw pipeline state (base vertex, base instance, first index,
index buffer address and type, blend, depth/stencil, cull, colour mask). Result:

    0 hits on corrupted frames for every field (and 0 on clean frames)

with the corrupted set measured from sc1's captures (19 of the 71 frames in the window). That closes the
handoff's action 2 (binding identity) and most of action 3 (viewport/render-target/pipeline state are not
in this record beyond the fields above). Two caveats that keep this from being an exclusion of "state":
the predicate only sees a *single-frame* transient (a difference that persists on two consecutive frames
is invisible), and a field that changes every frame can never satisfy it - the next version must report,
per field, how often `prev != next` at all, or the zero means nothing.

**2. In-pass uniform-update deferral (`DM_NVN_UB_DEFER=0`) is excluded.** This was the one host path where
the GPU provably does not read the bytes the fingerprint hashes, and it had never been tested. Run `ubB`,
501 captured frames 1900-2400, the switch verified in the run's own log ("DM_NVN_UB_DEFER=0: uniform
updates inside a pass end the pass as before"), same save snapshot as its partner `ubA2`:

| run | switches | captured | corrupted (area >= 8000) |
|---|---|---|---|
| ubA2 | default (in-pass updates deferred) | 501 | 161 of 499 scored |
| ubB | `DM_NVN_UB_DEFER=0` | 501 | **35 of 499** |

The shard survives with the deferral off (visually confirmed at 2232, 2236, 2240 - a 4-frame cadence in
that run). It is not the cause. The 4.6x difference in rate between the two runs is the phase lottery, not
the switch: cross-run rates differ by that much between identical configurations (round 15: 18 vs 94).

**3. The corrupted region is freshly rasterised, not stale or mixed.** For fp2's 2123/2163/2203 and ubB's
2232/2236/2240, the transient mask (13 384 - 22 373 pixels at 320x180) was compared against every frame
within +-20 frames: the best match explains at most 19.4 % of the mask pixels within +-2 grey levels
(clean-frame controls: 4-22 % on masks of ~500 pixels). So the region is not a copy of another frame's
pixels and not a two-frame mix of the presented image; it is new geometry/texture content rendered wrong.
That excludes the "presented swapchain mixes two frames" family, which the class A symptom had suggested.

**4. Three traps that cost this round runs (all now in HANDOFF):**
- The documented reproduce command's 92 s alarm produced **0 captures** in three different runs today,
  with a healthy-looking log and no error. Zero captures are no data, not a clean run. 110-150 s, and
  print the capture count and its frame range before measuring. (Measured: 2400 frames are reached at
  ~45 s when the window is frontmost.)
- A run whose window is behind another application is throttled to ~8-15 fps (2400 frames: 45 s
  frontmost vs >150 s occluded). What looked like "the game stalls at frame ~900" was this: three runs
  killed at the alarm had 900-1200 frames and no captures, while the same command reached 2400 frames in
  45 s when the game window was frontmost. Check the frame rate before concluding a hang.
- Runs are not comparable across sessions: fp1 and fp2 hash different vertex bytes for the same draw at
  the same frame index, and sc1's and fp2's captures show different camera positions at 2100. The save
  directory `<saves>` is written by every run, so each run starts from a different save
  state. `boot.sh` accepts `DM_SAVE=`, so give A/B pairs their own copies of one snapshot (verified not to
  change the run rate by itself: 2400 frames in 45 s with a copied save).

**5. Tool defects fixed (both were in the analysis path that produced earlier "measured" claims).**
- `runrec.py` wrote a hard-coded `analysis_result` block (hits_bad 0, hits_clean 3, ambiguous_groups 23)
  into every record it produced, including `runrec_sc1.json` that is on disk. Nothing computed those
  numbers. Rewritten: it measures the capture set with `shotscore.py` and records an analysis only when
  `fpana.py` produced one.
- `fpmatch.py` hard-coded the corrupted set as `frame % 4 == 2`, and it parses only `[pass]` lines, so on
  an `[fp]` log it reports zero parsed records - which reads as "no hits". It now requires `--bad` and is
  marked superseded by `pdbind.py`/`fpana.py`. Re-run on sc1's measured set it gives 0 corrupted-frame
  hits; the three clean-frame hits are a texture id alternating 1760 -> 1920 for one frame (animation).
- `DM_NVN_MAXINFLIGHT` does not exist: the switch is `DM_NVN_MAX_INFLIGHT` (hle_nvn.c:1027) and round 15's
  run `mi0` did have it active (mi0.log:98), so round 15's exclusion stands - the handoff's tooling table
  merely dropped an underscore. Separately, the comment at hle_nvn.c:1018 documents `DM_NVN_SYNC_SUBMIT=1`
  but no code reads it; only `DM_NVN_MAX_INFLIGHT=0` implements that behaviour.

**Correction to 1. (same round, after adding the variability column to `pdbind.py`).** "0 hits for every
field" overstates it: most of those fields are *constant* in this window, so they could never fire. The
honest split, with the number of comparisons in which the field actually moved (`prev != next`):

| field | moves on corrupted triples | hits |
|---|---|---|
| `cb.st0.r0` (uniform block address/size/pool) | moves | 0 |
| `cb.st1.r0` | moves | 0 |
| `tex.st1.r0` (tid/serial/format/dims/view) | moves | 0 |
| `tex.st1.r1` | 14 of 14 | 0 |
| `d.ib` (index buffer address) | 76 of 531 | 0 |
| sampler state, depth/stencil, cull, colour mask, blend b0-b3, base vertex, base instance, first index, index type | never | - |

So the negative is: *the state that moves* never moves in the transient shape. Nine of the fields are
constant in this window and prove nothing; base vertex being always 0 also answers part of the handoff's
"index / base-vertex interpretation" item for this game (single-draw batches, no base-vertex offsets).

## Round 34 addendum: vertex layout and draw composition also do not move

Two more field categories, both from data already on disk, both negative.

**Vertex attribute layout** (`v` records: format / offset / stride / divisor / vertex-buffer address per
attribute, i.e. *how* the GPU is told to read the stream - the one thing a vertex spike could come from
without any content change). Added to `pdbind.py`; field comparisons on corrupted triples 11277 -> 13359:

| field | moves on corrupted triples | hits |
|---|---|---|
| `v.a0`, `v.a1`, `v.a2` | 75 of 531 (182 of 1267 clean) | 0 |
| `v.nattr` | never | - |

So the layout and the bound vertex address move at the same rate as the index buffer address (they advance
linearly with the dynamic ring) and never in the transient shape.

**Draw composition.** The predicate analysis discards groups whose draw count differs, which silently
removes the "a draw is missing / an extra draw appeared on the corrupted frame" hypothesis. Measured
separately on fp2 (per (vertex key, fragment key) group, the count differing from both neighbours while
the neighbours agree): corrupted frames 0 of 3 have any composition transient, clean frames 1 of 156
(F2224, an ordinary one-frame extra group). Total draws per frame are identical to both neighbours
(2123: 41/41/41, 2163: 44/44/44, 2203: 45/45/45). The corrupted frame draws the same set of draws in the
same order.

After this round the complete list of things that are *identical* on a corrupted frame and its
phase-matched neighbours: draw set, draw order, vertex-stream content, index content, uniform-block
content, uniform binding identity (address/size/pool), texture binding identity (id/serial/format/
dimensions/view), vertex attribute layout and addresses, and pipeline state. The defect is therefore not
in anything the CPU hands to the GPU; it is in what the GPU ends up reading, or in how Metal executes it.

## Round 35: immutable-snapshot binding - the covered half of the vertex reads is not the source, and the uncovered half is the first measurable blind spot

New switch `DM_NVN_SNAP_VB` in `nvn_mtl.m`: at encode time every bound vertex stream is copied into the
frame arena (StorageModeShared, already resident - no staging blit, the cost is one CPU memcpy) and the
copy is bound instead of the zero-copy guest buffer. `=a-b` is a frame window, `=ab` is a per-frame 50/50
schedule from a hash of the frame number, which cannot alias with the artefact's cadence (an every-k-frames
schedule would: a 4-frame artefact and k=4 put every corrupted frame in one class).

Three runs, same save snapshot, same 501 frames (1900-2400), the switch active for ~50 % of frames
(3021 of 6030 by frame 6000), 60.0 fps in all three - the copy costs nothing measurable:

| run | corrupted area>=8000 (snapshotted / zero-copy) | >=12000 | >=15000 |
|---|---|---|---|
| snapE | 4 / 250 vs 7 / 249 | 3 vs 5 | 3 vs 3 |
| snapF | 64 / 250 vs 66 / 249 | 35 vs 31 | 21 vs 18 |
| snapG | 23 / 250 vs 28 / 249 | 9 vs 17 | 4 vs 8 |
| **pooled** | **91/750 (12.1 %) vs 101/747 (13.5 %)** | 47 vs 53 | 28 vs 29 |

No effect. The shard occurs at the same rate on frames whose vertex streams were private copies and on
frames that kept the zero-copy binding.

What that does and does not mean, with the coverage measured rather than assumed: the same runs report
how many bindings could *not* be snapshotted - those whose bound range is covered by a GPU-side write
(copy / fill / update) earlier in the same submission, where the CPU copy would be the pre-copy content:

| run | stream copies | left zero-copy (pending GPU write) | share |
|---|---|---|---|
| snapE | 149 251 | 116 287 | 43.8 % |
| snapF | 150 209 | 123 003 | 45.0 % |
| snapG | 142 135 | 121 004 | 46.0 % |

So the experiment covers 54-56 % of vertex-stream bindings, and the conclusion is bounded accordingly:
**the streams whose bytes the CPU can read at encode time are not the source.** The remaining 44-46 % are
draws whose vertex bytes are produced by a GPU-side copy *after* the draw is encoded in wall-clock terms
but *before* it in command order - the host cannot see those bytes at encode time, and neither can
`DM_NVN_FP`, which hashes the pre-copy content there. That is the first *quantified* blind spot of every
data-level measurement in this file (rounds 26-34 all inherit it).

A second thing this round produced, from the same runs: the shard's clearest form so far. snapF frames
1948 and 1968 (20 frames apart, both in the *snapshotted* class) show the whole screen covered by a flat
dark-green triangle with a single straight diagonal edge - one triangle whose three vertices project to
the screen corners, i.e. vertex positions far outside the model. Frames 1947/1949 and 1967/1969 are clean.
That is the shape to look for: one draw's triangle blown up, not a texture-sampling artefact.

Boundary condition on the negative, per the round-34 rule: this excludes "the bytes of a CPU-readable,
non-pending vertex stream were overwritten after encoding" for the frames measured; it does not exclude a
race on the pending-write streams, on index buffers (not snapshotted), on uniforms (not snapshotted), or
a GPU-side ordering defect inside a submission.

Also re-measured in this round, because it decides whether a run is usable at all: the save snapshot
selects whether the artefact shows up. The same command, same input, same switches, two snapshots:
`pair` gave 161 of 499 corrupted frames (ubA2) and 35 of 499 (ubB), while `snap` (taken from a later save
state) gave **0 of 499 in both classes, twice** (snapA, snapB). "Zero" there meant "this run never had the
artefact", not "the change fixed it" - which is exactly why the snapshot A/B had to be repeated against
the state that produces the artefact.

## Round 36: buffer-copy sources are not the source either - and the copy path is now covered completely

`mtl_sub_copy` (nvnCommandBufferCopyBufferToBuffer) records a GPU blit that reads its *source* from guest
memory when the GPU executes it, not when the host records it. That is the same hazard the inline
uniform-update path already avoids by copying the payload into the host ring at encode time (see its
comment: command memory recycled before the GPU runs gave SMBW the next batch's coefficients). It was the
last mechanism that could feed a draw bytes the host never saw, and 44-46 % of vertex-stream bindings are
fed by exactly such copies (round 35).

New switch `DM_NVN_COPY_SNAP`: the copy source is copied into a host ring at encode time and the blit
reads the ring. `=ab` is the same per-frame 50/50 hash schedule as round 35, so both arms run inside one
run and cannot alias with the artefact's cadence. Coverage is measured, not assumed: **every** copy in the
window was snapshotted (`too large 0`), 186 242 / 200 404 copies and 838 / 844 MB per run.

| run | captures | fps | copy-snapshot arm | guest-read arm |
|---|---|---|---|---|
| cpE | 0 (never reached the window) | 56.7 | - | - |
| cpF | 501 | 60.0 | 23/250 | 24/249 |
| cpG | 501 | 59.4 | 4/250 | 3/249 |
| **pooled (area>=12000)** | | | **27/500 (5.4 %)** | **27/498 (5.4 %)** |

No effect, and the shard was confirmed by eye inside the snapshot arm (cpF F2249: stretched spikes plus the
pale sheet, between two clean frames).

So: the bytes a buffer copy delivers are not the difference. Combined with round 35, the two *CPU-side*
mechanisms by which a draw's vertex data could differ from what the host recorded at encode time are both
excluded - the CPU-readable range itself, and the copy that fills it.

What is left on that axis is narrower and now precise: the pending writes that feed vertex streams are not
all buffer copies. `mtl_sub_update` is already snapshotted; `mtl_sub_copy` is now snapshotted; what
remains is the *texture-to-buffer* path (`enc_b_copy_texture_buffer`), whose source is a texture the GPU
reads at execution time, and the texture *content* a draw samples - the one data category with no
measurement in this whole file.

## Round 37: the producer->consumer table (what the Metal-4 review asked for), and a post-write image that is not yet faithful

New diagnostic `DM_NVN_PENDK=1` classifies, per frame and per *consumer binding*, which kind of GPU-side
write covers it: 1 buffer copy, 2 inline uniform update, 3 fill, 4 texture-to-buffer copy, 0 readable. The
texture-to-buffer destinations are kept in a separate list (`g_t2b_*`, reset per submission) so the
classification can see them without changing `pend_hits` anywhere else.

Two runs against the artefact-producing save snapshot, both with the shard present (55/499 and 17/499):

| consumer | corrupted frames | clean frames |
|---|---|---|
| vertex stream | copy 50 %, update 0-2 %, fill 0 %, **t2b 0 %**, readable 50 % | copy 49-55 %, update 0-2 %, fill 0 %, **t2b 0 %**, readable 45-51 % |
| index buffer | copy 99-100 %, readable 0-1 % | copy 98-100 %, readable 0-2 % |
| uniform (vertex stage) | update 99-100 %, copy 0-1 % | update 96-97 %, copy 3-4 % |
| uniform (fragment stage) | update 100 % | update 91-96 %, copy 4-9 % |
| indirect arguments | no pending writes observed | same |

Three facts, all of them usable:

1. **The texture-to-buffer path feeds nothing.** 0 of 55 corrupted and 0 of 446 clean frames have any
   consumer covered by a t2b copy. That closes the remaining execution-time source the review listed as the
   second suspect, at least for the vertex/index/uniform/indirect consumers in this window.
2. **The dependency pattern is the same on corrupted and clean frames** (50/50 copy-vs-readable vertex
   streams, 99 % copy-fed index buffers, ~100 % update-fed uniforms). So "a dependency exists" is not the
   differentiator; the artefact is not a frame that uniquely has a GPU-written input.
3. The 44-46 % pending-write share of round 35 is now fully explained: it is buffer copies (vertex, index)
   and inline uniform updates (uniforms), not textures.

**The post-write image (`DM_NVN_SNAP_VB=full`) is the completion of the round-35/36 idea and it is not
faithful yet.** It builds, for every bound vertex stream, the bytes NVN says the draw must read - the bytes
at encode time plus every copy and fill recorded earlier in the same submission applied on the CPU - and
binds that image, so delivery (ordering, aliasing, GPU copies) cannot matter. Run against the same save
snapshot on a per-frame 50/50 schedule (one usable run, fuA; a second never reached the window, a third had
no shard):

| area >= | image arm | zero-copy arm |
|---|---|---|
| 8000 | 57/250 (22.8 %) | 47/249 (18.9 %) |
| 12000 | 42/250 | 29/249 |
| 15000 | 32/250 | 23/249 |

The image arm is *worse*, not better, and that is the informative part: changing the bytes the GPU reads
changed the artefact rate, so the vertex path is causally involved - but the image must itself be wrong for
it to be worse. Two known gaps make it wrong:

1. inline uniform updates (`mtl_sub_update`, pending kind 2) write buffers too and are not in the image
   (`g_pkw`) at all - small (0.4 % of vertex bindings) but nonzero;
2. a copy whose *source* was written by an earlier copy in the same submission gets a source snapshot of the
   pre-copy bytes, i.e. chained copies are resolved one step short.

Both are fixable by evaluating the recorded writes in order and propagating them into each copy's source
image (the same lazy-image trick `ubd_read` uses for uniforms). Until then this experiment proves only that
the vertex path matters, not which side of it is broken. Encode order is a valid stand-in for command order
here because merged-pass deferral is off for this game (`defer_on()` requires `tbdr_on()`, which the profile
leaves off), so it is not the cause of the gap.

## Round 38: the vertex axis is closed - a faithful post-write image changes nothing

Round 37's image was one step short (inline uniform updates not applied, chained copies resolved from the
pre-copy source). Both gaps are now closed: every recorded write is applied in submission order
(`pkw_apply`), a copy's source is snapshotted *through* the writes recorded before it, and inline uniform
updates are recorded as kind 2 with their payload. The image a draw binds is therefore the byte image NVN
defines for that draw, held in host memory and immutable for the GPU - ordering, aliasing, copy delivery
and the zero-copy question cannot reach it.

Three runs, same save snapshot, in-run 50/50 schedule, shard present in all three (149, 216 and 31 of 499
frames by area >= 8000), 59.9-60.0 fps:

| area >= | post-write image | zero-copy | pooled image | pooled zero-copy |
|---|---|---|---|---|
| 8000 | 73/250, 115/250, 13/250 | 76/249, 101/249, 18/249 | **201/750 (26.8 %)** | **195/747 (26.1 %)** |
| 12000 | 57, 74, 8 | 63, 73, 12 | 139/750 (18.5 %) | 148/747 (19.8 %) |
| 15000 | 51, 55, 5 | 53, 53, 8 | 111/750 (14.8 %) | 114/747 (15.3 %) |

No effect at any threshold. This is the strongest exclusion in the file, because it does not depend on any
assumption about how the GPU orders anything:

**The vertex data a draw reads - its content, its provenance (CPU-written or GPU-copied), and its delivery
to the shader - is not what differs on a corrupted frame.**

With rounds 35-38 the whole vertex axis is closed from both directions: the readable half (round 35), the
copy-fed half (round 36), and now both halves together as an immutable, NVN-order-correct image (round 38).
Round 37's "worse" result was the unfaithful image, not a property of the game: with the missing writes
applied, the arms converge.

What that leaves is now a short list, and it is no longer about vertex buffers:
1. uniform *delivery* (uniforms are ~100 % fed by inline updates; the host already copies the payload into
   its ring at encode time, so this is the same class as the vertex image and is likely excluded too - but
   it has not been tested the same way);
2. texture *content* (the one data category with no measurement at all);
3. the draw's own encoding and the pipeline state (primitive type, first vertex, base vertex, blend/depth/
   stencil, viewport/scissor, shader identity - all measured identical, with the caveat that `prim` is a
   single value for every draw in this game);
4. something outside the draw: pass order, render-target content, or the present path (pixel-domain evidence
   already argues against a stale or mixed present).


## Round 39: audit invalidates the claimed full-vertex exclusion (in progress)

Independent source/log verification found a decisive diagnostic defect: `snapvb_full()` recognizes
`full` for producer journaling, but the draw-side `sv` parser initializes only 0/1 and recognizes
`ab` or a numeric window. `full` falls through `atol` and becomes frame 0-0. The `sv == 2` branch
that builds and binds post-write images is unreachable. `run/fvA.log` explicitly says frame 0-0,
and the capture runs fvA/fvB/fvC report zero image copies. Therefore the round-38 measured pixel
rates compare two zero-copy groups, not treatment versus control. The vertex axis is OPEN.
Round 37's full-image causal interpretation is likewise unsupported by an executed intervention.

The source also never sets `g_pkw_over` on journal limits, so old gap=0 statistics do not certify
complete coverage. These two issues are being corrected before any new exclusion or fix claim.

Apple's official `MTL4RenderCommandEncoder.setArgumentTable(_:stages:)` documentation states that
resource bindings are snapshotted when encoding each draw/dispatch/execute command. Updating one
argument table between draws is supported; it is not itself evidence of an execution-time race.
Source: https://developer.apple.com/documentation/metal/mtl4rendercommandencoder/setargumenttable(_:stages:)

Status: not solved; baseline and corrected instrumentation verification are in progress.

## Round 40: mapping fixed; the vertex, index and uniform data axes and the shared argument table are all excluded (aligned in-run A/B)

The r39 capture runs had a fatal join flaw: the capture filename is the present count, while the arm is chosen from the rendered frame; with the display link these differ by a
variable offset (measured 6-54 frames), so joining by filename flips arms. `[shot-map] present->render` was added and every number below uses that join. The old r39_fullA
numbers are unmapped and invalid.

| run | switch / arms | area>=8000 | area>=12000 | area>=15000 | evidence |
|---|---|---|---|---|---|
| fullE | DM_NVN_SNAP_VB=full, image vs zero | 74/250 (29.6%) vs 60/249 (24.1%) | 64 vs 52 | 58 vs 43 | 501 captures, 501 maps; image changes the bytes; no reduction (image slightly higher) |
| idxB | DM_NVN_SNAP_IB=ab, image vs zero | 19/248 (7.7%) vs 26/250 (10.4%) | 13 vs 19 | 9 vs 10 | no deterministic clock; 501 maps; image changed bytes on many frames (diff up to 12k) |
| idxC | DM_NVN_SNAP_IB=ab, image vs zero | 21/245 (8.6%) vs 19/254 (7.5%) | 15 vs 13 | 8 vs 9 | deterministic clock; 501 maps; 19.3 MB of index bytes changed over the run |
| atB | DM_NVN_ARG_TABLE=ab, private vs shared table | 64/250 (25.6%) vs 64/249 (25.7%) | 43 vs 40 | 36 vs 37 | one run, in-run per-frame A/B; the shared table is not the cause |
| ubB | DM_NVN_SNAP_UB=ab, image vs zero | 15/242 (6.2%) vs 17/257 (6.6%) | 6 vs 9 | 4 vs 8 | uniform image changes bytes on 2043/2206 image frames; shards persist in the image arm (1965, 2233, 1985); the lower rate is not significant |

The index image is a real intervention: the journal changed up to 11797 bytes in one frame and 19.3 MB over idxC, yet the shard rate did not fall. The uniform image
also changes bytes (e.g. 4725 bytes on a shard frame) and the shard persists.

Consequences:
- Vertex content/provenance/delivery: closed (round 38's method, now with a valid switch and a valid join).
- Index content/delivery: closed by the image A/B (the image is the NVN-order bytes).
- Shared MTL4ArgumentTable mutation: closed by the private-table A/B.
- Uniform delivery: the image does not remove the shard; a small reduction is possible but unproven.

Remaining, in order:
1. Texture content, especially textures sampled by vertex shaders. It is the only data category never measured, and a wrong vertex-stage texture can displace vertices (blown-up triangles), unlike a wrong fragment texture. Imaging it mid-pass needs a design (a texture copy ends the render pass); a first step is to record, per draw, which vertex-stage textures are bound and whether their content changed in the frame.
2. The draw's own encoding/execution: which command the GPU executes, argument-table contents at execution (now excluded for the shared table), render-target aliasing, pass order.

Separate defect found: an intermittent guest deadlock at F957 (fullB, fullD, idxA, idxC, ubA; 5 of 10 deterministic-clock runs). The guest main thread and two workers wait on the same condvar; the run never reaches the capture window. fullA/fullC/fullE/atB/ubB passed. It is not the shard and not loading-clock freeze; it looks like another lost-wakeup instance in the host's process-wide key/condvar path (hle_thread.c 0x1C/0x1D already has one fixed case and t_condvar). The no-clock run idxB passed; removing DM_DETCLOCK/PACE avoided it once but not always.

## Round 41: the GPU-drain exclusion becomes an in-run A/B; safe math is inconclusive

`DM_NVN_DRAIN=ab` makes every second rendered frame wait for its own submission to complete (`mtl_wait(sub_fence)`)
before returning to the game, so the next frame's CPU writes cannot land in memory this frame's GPU still reads.
This replaces the old cross-run `DM_NVN_MAX_INFLIGHT=0` comparison (94/501 vs baseline 18/501), which violated the
in-run rule. One no-clock run, 501 captures, 501 present->render maps, 249/250 frames per arm:

| area >= | drain | async |
|---|---|---|
| 8000 | 77/249 (30.9%) | 70/250 (28.0%) |
| 12000 | 55/249 (22.1%) | 51/250 (20.4%) |
| 15000 | 41/249 (16.5%) | 42/250 (16.8%) |

No reduction; the GPU-lag / CPU-rewrite race is excluded with the same in-run discipline as the other axes.

Safe math: the 1515 vertex shaders were recompiled offline with `xcrun metal -fno-fast-math` (pixel shaders
unchanged) and the host was run on the shard-rich deterministic route (`DM_DETCLOCK=... DM_NVN_SNAP_VB=full`).
The safe run (safeB) showed 48/37 shards at area>=8000, 25/22 at 12000, 14/17 at 15000. An adjacent run with the
restored fast shaders (fastB), same route and settings, showed **0/499 at every threshold**. The fast shaders can
produce a clean run, so the difference between fullE/safeB is run-level variance, not the math mode: the cross-run
safe-math test is inconclusive. A valid test needs an in-run fast/safe vertex-shader switch. The NaN / 1.7e38
values in uniforms and attributes remain a lead, not an established cause.

Measurement trap, again: the no-clock baseline/safe pair died and the area scorer counted the death/retry
transition (diagonal wipe, menu); the 1900-2100 gameplay window was clean in both. The 42/499 vs 124/499 difference
in that pair was the death-screen timing, not the shard. Always inspect the top frames.

## Round 41 addendum: the fast control is not reproducible

A repeat of the fast control (fastC; same `DM_DETCLOCK=16666667 DM_DETCLOCK_PACE=1 DM_NVN_SNAP_VB=full` command, fast vertex shaders) had a present->render offset of 20-57 and 96/86 shards at area>=8000 (39.2 % / 33.9 %), 67/67 at 12000 and 51/54 at 15000. The first fast control (fastB) had offset 18-99 and 0/499. Same shaders, same command: 0 vs 182 hot at 8000. The fast shaders span the whole range; the safeB 48/37 is inside it. The safe-math test is confounded by run-level variance and remains inconclusive; the fastB zero was a clean route, not a fix.

## Round 42: anchoring the input and captures to the guest frame; the run start is still missing

DM_PLAY_IN was already stepped by dm_guest_frame() (the game's present frame), not by the screen present
count; the screen-present offset only shifted which game frames the captures sampled. Two real jitters
remained: the replay ran in a polling thread (usleep 2000, up to a frame late), and DM_NVN_SHOT selected
captures by the screen present count. Both are fixed: the replay steps are now applied synchronously in
dm_guest_frame_tick, and DM_NVN_SHOT_ANCHOR=render selects captures by the guest frame.

Two anchored fast runs (same save/input/detclock/shader set) still diverged: A 467 captures and 37 shards
at area>=8000, B 442 captures and 0; the same render frame draw counts differ in 1421 of 4345 common frames
(33%; F144 A=7 B=11, F189 A=11 B=7). The same-F images are out of phase (player and effect positions), not
identical. The anchoring removed the replay jitter and the capture-window shift, but not the run-level
divergence.

The logs show the next gap: the DM_DETCLOCK "on entering a run (ToGame)" alignment never fires for Cuphead
(the uimsg hook is d2r's), so the guest clock is seeded from the wall clock at the first present. The two
runs' time base differs by the boot/loading wall time; the game's time-based animations and the input/capture
windows (absolute guest frame) are phase-shifted. The fix is to align the guest clock and rebase the input and
capture at Cuphead's run start (its own uimsg, or the save/level load), not at the absolute first present.

The offset statistics across runs show no simple relation to the shard rate (fastB mean 60 / max 99 -> 0%;
fastC 38.8/57 -> 36.5%; drainA 8.9/10 -> 29.5%): the display-link offset is a marker of present lag, not the
cause. The same-F comparison of fullE/safeB/fastB/fastC shows close draw counts but different player/particle
positions; at F2100 only fullE has a shard, at F2300 only fullE has died. The shard stays run-level timing;
the in-run A/B remains the only clean comparison, and the texture-content A/B must be in-run.
