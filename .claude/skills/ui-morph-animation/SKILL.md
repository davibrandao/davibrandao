---
name: ui-morph-animation
description: Make Dribbble-level looping UI motion videos where ONE shape morphs through 8–12 UI states (button, loader, check, dynamic island, music player, slider, toggle, tabs, chart, ⌘K palette, toast…) with a cursor doing real clicks and drags, cut to a song's beat grid. Builds a single 1440×1440 HTML animation in which every frame is a pure function of time (closed-form springs), analyzes the song with numpy for tempo and downbeats, places UI sounds by their measured peak, reviews one frame per beat, and renders a 60 fps motion-blurred MP4 with Playwright + ffmpeg. Use this whenever someone wants a UI animation, product motion shot, morphing-interface video, micro-interaction reel, beat-synced or music-synced UI animation, or a Dribbble/Instagram motion post, or pastes a prompt about a shape becoming different UI states on the beat, even if they never say "skill" or spell out the steps.
compatibility: Python 3.9+ with numpy, pillow and playwright; ffmpeg on PATH (or pip imageio-ffmpeg); a Chromium that Playwright can launch (the scripts also find common preinstalled paths).
---

# UI morph animation

One element, never cut, becomes a sequence of UI states on the beat of a song while a
cursor drives every change. The output is a seamless loop: an MP4 (1440×1440, 60 fps,
motion blur, soundtrack) plus the single HTML file that produced it.

The craft lives in three places, and this skill covers each:
- **Choreography**: which state lands on which beat, and what the cursor does.
- **Motion**: springs, blur swaps, liquid edges, camera. See `assets/morph-kit.js`.
- **Pipeline**: beat analysis, sound placement, per-beat review, and the render. See `scripts/`.

`examples/reference.html` is a finished 7-bar build of the default 12 states (button →
loader → check → dynamic island → music player → volume slider → toggle → tabs → chart →
⌘K pill → command palette → toast → button). Along the way it plays, scrubs, stretches the
volume past max, types, and presses enter. Read it before building. It shows every pattern
below working together, and most new states are variations of something in it.
`examples/trip-planner.html` is a second build (6 bars at 124 BPM, one accent) on different
states: search bar → dropdown → date range → stepper → like → notification → avatar stack →
toast. Read it when the requested states overlap those.

Paths: `$SKILL` below means this skill's folder. Run everything from the user's working
directory, so the song, `beats.json` and the project folder live there, never inside
`$SKILL`.

## Direction

- **One shape, never cut.** Every state is the same `#shape` element changing its size,
  radius, and color. Content inside swaps with a short blur. Inner parts that mean the same
  thing keep their identity across states: the progress fill becomes the volume fill, then
  the toggle knob, then the tab indicator. That continuity is what makes it feel designed.
- **A cursor drives every change** with real clicks (press a 16th early, release on the
  beat), real drags (direct manipulation), and typing. Automatic changes are fine only
  when they are causal, like a loader finishing.
- **Look:** a light warm-gray canvas (`#ECEAE6`), black and white components, and one clean
  UI font (Geist, bundled). Optionally use one accent color, spent on two to four moments
  (success, toggle on, chart line). Design at real 1× UI sizes (a 56 px button, 15–17 px
  text) and let the camera zoom. Authentic proportions are what keep it from looking like
  a template.
- **Motion:** springs everywhere, with a tiny overshoot at most (bounce ≤ 0.2). The camera
  zooms so each state fills the frame, pulling back fast as the UI grows and pushing in
  slowly as it shrinks.
- **Timing:** something happens on every beat, and the last frame flows into the first.
- **Banned:** bouncy easing, particle bursts, glows, gradients on UI chrome, mismatched
  icon strokes, dead time, and anything that looks like a template.

## Workflow

### 1. Ask for the inputs, and nothing else yet

Ask for three things in one message. Give each a default so "defaults" is a complete
answer:
1. **8–12 UI states** for the shape to become, in order. The default is the reference's
   12: button → loader → check → dynamic island → music player → volume slider → toggle →
   tabs → chart → ⌘K pill → command palette → toast (→ button). Scrubbing, typing and
   hovering are interactions inside states, not extra states. If the user describes the
   idea loosely ("a button that turns into a bunch of components"), offer the default
   plus the pre-checked alternative chains in `references/choreography.md` §1b.
   `references/state-recipes.md` lists every state they can mix in.
2. **Pure black and white (the default), or one accent color** as a hex value.
3. **A royalty-free song around 120 BPM**, as a local path or a URL, or by dropping the file
   into the working folder. Mixkit is a good source: its tracks are free for commercial use
   in videos, and the user should read the license on the chosen track's page. Sandboxed
   sessions often block music hosts. If `curl -sI <url>` fails, ask for the file instead.
   With no song yet, the default is `$SKILL/scripts/placeholder_track.py` (a synthetic
   groove) as a timing stand-in. Say so up front. Before the final render, ask once more
   for the real track, and re-analyze and re-time when it arrives. If none comes, deliver
   with the placeholder and label it as one.

Also mention the output format once: a 1440×1440 square MP4 at 60 fps with sound, plus a
self-contained HTML file. The loop runs roughly 1.2–1.5 s per state at 120 BPM: about 14 s
for 12 states, and 10–12 s for 8.

If the user already gave all three, skip straight to step 2. Don't write animation code
before step 3 is approved.

### 2. Analyze the song

```bash
pip install numpy pillow playwright   # plus ffmpeg on PATH (or: pip install imageio-ffmpeg)
python3 $SKILL/scripts/analyze_beats.py song.mp3 --bars 7 --bpm-hint 120 --out beats.json
```

Choose `--bars` by counting interactions, not states. A morph takes about 1 beat, and so
does each click, drag step or typing burst. A range selection or other multi-step drag
takes 3–5 beats. Round the total up to whole bars. The reference's 12 states with their
interactions come to 28 beats, which is 7 bars (14 s at 120 BPM). Eight states usually
land at 5–6 bars.

Read the summary. It reports the tempo, whether the tempo is steady, the downbeat
confidence, the chosen loop start (a downbeat at a phrase boundary, in a high-energy
stretch), and how much the loop-crossfade half beat dips. Tell the user the BPM and where
in the song the loop starts. If the downbeat confidence is low, the tempo drifts, or the
seam dips audibly, say so. Fixes are `--downbeat-shift N`, `--start 32.5`, or
`--start bar:17`. If you change the bar count after the plan, re-run the analysis, because
the best start depends on the loop length. Details are in `references/audio.md`.

### 3. Show the state list on the beat grid, and wait

Present the plan as a table with one row per beat: bar.beat, time, state, what happens on
that beat, what the cursor does, and the sound. Below the table, add one line per state
covering size, color, content, and which inner part carries over. Follow the format and the
rules in `references/choreography.md` (every beat has an event, clicks land on the beat,
drags span beats, and the loop seam lands on 1.1). Ask for approval or changes. This is the
cheapest moment to change the story.

### 4. Build

```bash
python3 $SKILL/scripts/new_project.py morph-loop --beats beats.json --song song.mp3 [--accent '#FF4F1A'] [--from-example [reference|trip-planner]]
```

This writes `index.html` (the beat grid is already in `CONFIG`), `morph-kit.js`, the
font, a UI sound kit, and a music-only `mix.wav`. Pass `--from-example` (the reference) or
`--from-example trip-planner` only when most of the chosen states are in that build. Its
timeline must be re-timed for any other length, and the script warns you. Otherwise, start
from the template and copy patterns out of the examples. Both use the same layout: content in world px under `#origin`, inside the
one `#shape`. Build in this order, because each layer depends on the one before:

1. `PLAN`: the beat sheet from step 3, registered with `K.event()`. Add sounds with `K.cue()`.
2. `GEO`: the one shape per state (w, h, r, bg, optional cx/cy), turned into tracks.
3. Driven values: playback, drags (`K.drag`), typing, draw-ons, and counters.
4. Persistent inner parts: the "blob" that carries meaning between states, art, and indicators.
5. Camera keys (zoom per state) and cursor keys plus presses.
6. `vis`: the presence windows (enter and exit) for each content layer.
7. `frame(t)`: write every dynamic style, every frame.

You can't watch a browser, so you see frames through `review.py` (step 5). Use `--at` for
single moments and `--range A:B:STEP` for a filmstrip of a transition. For the user,
`python3 $SKILL/scripts/serve.py morph-loop` serves a live preview (space plays with sound, ←/→
steps a beat, shift+←/→ steps a frame).

### 5. Review one frame per beat before the full render

```bash
python3 $SKILL/scripts/review.py morph-loop/index.html --mid   # + --at 12.5,19.25 close-ups, --range 18.75:19.75:0.125 filmstrip
```

Open `review/sheet.png` (one row per bar, beat and half-beat) with the Read tool, then
open individual `review/beat_XX.png` or `at_*.png` frames at full size, and a
`strip_A-B.png` for any transition that matters. Close-ups and strips are kept across runs.
Fix anything off the grid, cramped, or hard to read. The report also checks:
- **purity**: frames rendered out of order must be identical.
- **seam**: the loop point must look like any other frame step, cursor included.
- **activity**: flags dead beats and quiet beats.
- **events**: flags anything off the 16th grid and beats with no event.
- **audit**: flags small text, text clipped or cramped against the shape, two swap layers
  visible together, and a shape crowding the frame edge.

Iterate until the report is clean and the sheet meets `references/quality-checklist.md`.
Automated checks catch mechanical problems. Taste is on you, so look at the frames.

### 6. Render and deliver

```bash
python3 $SKILL/scripts/render.py morph-loop/index.html --song song.mp3 --beats beats.json   # → loop.mp4
python3 $SKILL/scripts/bundle.py morph-loop                                                  # → dist/loop.html
```

`render.py` takes 4 subframes per frame across a 180° shutter, blends them with ffmpeg
`tmix` to 60 fps, mixes the song section with a loop crossfade, and adds UI sounds placed
by their peak. Use `--preview` for a fast half-size draft, `--loops 3` for a longer post,
and `--gif` for a 720 px GIF. A 14 s loop renders in about 2 minutes on 4 cores. Deliver
`loop.mp4`, `dist/loop.html` (self-contained, font and audio inlined), and the review sheet.
Say what's left to tweak. The usual suspects are the UI sound level (`--ui-db`), a state's
zoom, and a label.

## Build rules, and why

1. **Everything is computed from time inside `seek(t)`.** No CSS transitions, timers,
   `requestAnimationFrame` state, `Math.random()`, or values carried between frames.
   The renderer seeks to arbitrary subframe times, often out of order across workers.
   Any hidden state shows up as flicker. Use `K.css(el, {...})`, which rewrites the whole
   inline style every frame, so a property set in one frame can't leak into the next. Use
   `MorphKit.hash(n)` for variety.
2. **Springs are closed-form step responses.** A value that changes target many times
   is the sum of one spring per change (`K.track`). It stays a pure function of time,
   interrupted motion stays smooth, and each change can use its own spring.
3. **Two edges on two springs** (`K.edges` or explicit L/R tracks). The edge moving in
   the direction of travel rides the fast spring, so tab indicators and toggle knobs
   stretch ahead of themselves and the tail catches up. That is the "liquid" look.
4. **Drags are direct manipulation.** While the cursor is held, the value is computed from
   the cursor's position. On release, it springs back from wherever it was, with the
   release velocity (`K.drag`). Past the limits, use a rubber band (`MorphKit.rubber`).
5. **Start on a downbeat.** `t = 0` is the analyzed downbeat. Every event sits on a beat or
   a 16th. Each UI sound's measured peak (not its first sample) lands on its cue.
6. **The loop closes by construction.** In the kit, a track's value before its first key
   is its last key, and springs started near the end keep settling after the wrap. For
   anything else that runs "since an event", use `K.since(t, beat, appearBeat)` so a toast
   icon drawn at beat 27 is still drawn at t = 0.1.
7. **Render one frame per beat first** (`review.py`), then the full render.

## Kit cheat sheet

```js
const K = MorphKit.create({ bpm: CONFIG.bpm, bars: CONFIG.bars, beats: CONFIG.beats });
const SP = { morph: spring(0.55, 0.12), snap: spring(0.3, 0.1), color: spring(0.45, 0), cam: spring(0.95, 0) };
K.event(2, 'click → loader'); K.cue(2, 'click', 0.9);            // beat sheet + sounds
const W = K.track([[0, 204], [2, 56], [6, 220]], SP.morph);       // [beat, value|fn(t), spring?]
const BG = K.colorTrack([[0, '#0B0B0C'], [5, '#FFFFFF']], SP.color);
const ind = K.edges([[18, 84, 168], [19, -84, 0]]);               // → [left, right], leading edge fast
const v = K.presence(t, inBeat, outBeat, { delay: 0.06 });        // 0..1 visibility, fast exit ({instant:true} for keys)
K.textAt(label, x, y, 15, 'l', v, { fontWeight: 500 });            // text at world px with a blur swap (K.iconAt for icons)
const clip = K.splitClip(boxLeft, boxW, L, R);                     // halo-free inversion under a moving fill
const cellKeys = K.steps((t) => cellUnderCursor(t), 7, 9, { sound: 'tick' }); // snap a drag's steps to 16ths
const drawn = clamp(K.since(t, 27, 26) / 0.3);                     // loop-aware "since beat 27", element appears at 26
K.camera([[0, 3.7], [2, 6.2], [24, 3.05, 0, 108]], SP.cam);       // [beat, zoom, cx, cy, spring?]
K.cursor([[0.75, [50, 12]], [2, [50, 12]], [9, (t) => thumbAt(t)]], [[1.75, 2], [10, 11.5]]);
const prog = K.drag({ press: 10, release: 11.5, map: (p) => clamp((p[0] + 124) / 248), before: playing });
K.onFrame((t) => { K.css(world, { transform: K.worldTransform() }); /* … every dynamic style … */ });
K.mount(document.querySelector('#stage'), { audio: CONFIG.audio });
```

The full API, with the reasons behind each default, is in `references/kit-api.md`.

## Gotchas

- **Never put `will-change` (or `translateZ(0)`) on anything the camera scales.** The text
  gets rasterized once and then scaled, and it turns blurry.
- **Text that swaps inside a morphing container needs its own enter and exit timing**, or
  it overlaps. `K.presence` exits fast on the beat and enters about 60 ms later and slower.
  A placeholder vanishes the instant the first key lands, with no fade.
- **Make the last frame identical to the first, cursor position and speed included**, or
  the loop stutters. `review.py` measures the step across the seam against its
  neighbors. Don't render the frame at `t = T`, because it is frame 0.
- **Park hidden elements.** An element that is hidden for part of the loop needs a key
  (while hidden) that puts it where it will next appear. Otherwise it flies in from its last
  position.
- **The camera lags on purpose, but never overfills.** Zoom out on a fast spring when the
  shape grows, and zoom in on a slow one.
- **Drags over discrete things snap on the grid.** The cursor crosses calendar cells or
  detents at arbitrary times. Sample the value on 16ths with `K.steps` and drive the UI and
  sounds from those keys.
- **Liquid edges are for one axis.** A highlight moving diagonally (a calendar hover) must
  move all edges on the same spring, or the lead/trail lag piles into a blob.
- **Inverting labels under a moving fill:** give the base copy `clip.outside` and the
  inverted copy `clip.inside` from `K.splitClip`. Stacking an unclipped copy leaves a halo.
- **If you center layers with CSS grid**, use `grid-template: minmax(0,1fr) / minmax(0,1fr)`,
  or the widest layer pushes the others off-center. World coordinates under `#origin`
  avoid the problem.
- **Keep icons in one family and one visual stroke weight.** `MorphKit.icon(name, px,
  stroke)` normalizes the stroke across sizes. Filled media glyphs get the same rounded
  join treatment.
- **Fonts need http.** Preview with `serve.py`, not `file://`. `bundle.py` inlines everything
  for the shareable single file.

## Files

- `assets/morph-kit.js`: the runtime (springs, tracks, edges, swaps, camera, cursor, drags,
  audit, dev player).
- `assets/template.html`: a minimal scaffold. `examples/reference.html` (7 bars, B&W) and
  `examples/trip-planner.html` (6 bars, accent) are full builds.
- `scripts/`: `analyze_beats.py`, `new_project.py`, `review.py`, `render.py`, `bundle.py`,
  `serve.py`, `mix_audio.py`, `ui_sounds.py`, `placeholder_track.py`, `common.py`.
- `references/choreography.md`: planning the beat grid, the plan format, cursor and camera
  direction, and the reference's beat sheet as a worked example.
- `references/state-recipes.md`: 25 states with sizes, content, continuity, interaction,
  and sound.
- `references/kit-api.md`: the kit, function by function.
- `references/audio.md`: beat analysis, picking the loop, sound design and placement, and
  mixing.
- `references/quality-checklist.md`: the by-eye review list.
