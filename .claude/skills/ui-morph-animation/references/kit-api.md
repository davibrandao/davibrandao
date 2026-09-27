# morph-kit.js API

Load it with `<script src="morph-kit.js">` (`bundle.py` inlines it later). It exposes
`window.MorphKit`. After `K.mount()`, `window.K` and `window.seek` are what the review and
render scripts call.

## Contents
1. Create and time
2. Springs
3. Tracks (sum of springs)
4. Edges (liquid indicators)
5. Presence and swaps (blur content swaps)
6. Camera
7. Cursor and drags
8. Writing styles
9. Frame loop, mount, flags
10. Helpers
11. Audit
12. Page skeleton

## 1. Create and time

```js
const K = MorphKit.create({ bpm: 120, bars: 7, beatsPerBar: 4, beats: null, loop: true, size: 1440, cursorSize: 64 });
// a Reel: const K = MorphKit.create({ ..., width: 1080, height: 1920, safe: [220, 140, 420, 60], cursorSize: 60 });
```
- `width`/`height` (or `size` for a square) set the frame. `K.W`, `K.H`, and `K.size` (the
  shorter side) read it back.
- `safe: [top, right, bottom, left]` insets mark where platform UI covers the frame (a Reel's
  header, caption and action buttons). `K.safe` is `{ l, t, r, b }`. States stay centred on
  `K.focus` (the frame centre unless you pass `focus: [x, y]`), so the video looks centred in
  any player. The safe area limits their size instead: `K.fit` sizes to the largest box
  around the focus that stays inside it, and the audit measures the shape's margin against it
  (12 px minimum, since the insets are already a margin).
- `beats`: optional measured beat times (s, relative to the loop start, `bars*4+1` of
  them). `new_project.py` passes them only when the song's tempo drifts. Otherwise the grid
  is exact from `bpm`.
- `K.b(n)` converts beats to seconds (fractional beats allowed). `K.toBeat(t)` is the inverse.
- `K.bb(bar, beat, frac)` converts a 1-based bar.beat to a beat index.
- `K.T` is the loop length in seconds, and `K.beat` is one beat in seconds.
- `K.label(t)` returns a "bar.beat" string.
- `K.since(t, beat, fromBeat?)` returns loop-aware seconds since `beat`. t is read inside a
  one-loop window starting at `fromBeat` (default: half a loop before the event). Pass the
  beat the element appears. A toast visible from beat 26 whose icon draws at 27 uses
  `K.since(t, 27, 26)`, and it stays drawn across the seam.
- `K.event(beat, label)` registers the beat sheet (review.py lists it and checks the grid).
- `K.cue(beat, sound, gain = 1)` registers a UI sound. The mixer lines the sound's peak up
  on the cue.

## 2. Springs

```js
const s = MorphKit.spring(duration = 0.5, bounce = 0);
```
This uses SwiftUI's parameterization: `duration` is the perceptual duration, and
`bounce` 0 means critically damped, while 0.2 overshoots about 1.5 %. Keep bounce ≤ 0.2.
It's closed form, so there is no integration and no state:
- `s.step(t)` goes 0 → 1, starting at rest at t = 0 (0 before). `s.stepVel(t)` is its velocity.
- `s.free(x0, v0, t)` is the displacement from the target, starting at x0 with velocity v0.
  This is what a released drag uses.
- `s.settle` is the time after which the residual is below 1e-6 (the value snaps to exact).

Starting presets at 120 BPM (scale durations with the beat):

| name | spring | use |
|---|---|---|
| morph | (0.55, 0.12) | shape size, radius |
| big | (0.62, 0.1) | large expansions |
| snap | (0.3, 0.1) | small quick things, steps |
| press | (0.16, 0) | press squish |
| color | (0.45, 0) | colors (never overshoot) |
| cam / camOut | (0.95, 0) / (0.5, 0) | camera in / out |
| lead / trail | (0.3, 0.14) / (0.62, 0.04) | liquid edges |
| release | (0.5, 0.16) | drag release |

## 3. Tracks (sum of springs)

```js
const W = K.track([[0, 204], [2, 56], [6, 220, SP.big]], SP.morph, { from, delay });
W(t); W.vel(t);
```
- Keys are `[beat, value, spring?]`. Each change adds `Δ × spring.step(t - t_key)`, so a
  change that interrupts another stays smooth, and each key can use its own spring.
- **Values can be functions of t.** The spring then blends from the previous target to a
  moving target (a dragged value, a playing progress). Continuity is automatic.
- In loop mode, the value before the first key is the last key's value, and a spring
  started near the end keeps settling after the wrap. The loop closes by construction.
- To park a hidden element, add a key at a beat where it's invisible (often `[0, …]`)
  holding where it will next appear.
- `K.trackN(keys, sp)` takes vector values (`[beat, [x, y, w]]`), each component a track.
- `K.colorTrack(keys, sp)` takes `'#hex'`, `'#rrggbbaa'`, `'rgb()'` or `'rgba()'` keys. It springs
  them in OKLab, alpha included, and `f(t, alphaMul)` returns a CSS color.

## 4. Edges (liquid indicators)

```js
const ind = K.edges([[18, 84, 168], [19, -84, 0]], { lead: SP.lead, trail: SP.trail });
const [L, R] = ind(t);
```
For each change, the edge moving in the direction of travel rides `lead` and the other
rides `trail`, so the pill stretches ahead of itself and the tail catches up. For a pure
resize, both edges ride `lead` when growing and `trail` when shrinking. Pass `k[3] = { l, r }`
to override one key. For elements that also change T/B/radius, build explicit tracks per
edge, as the reference's `BLOB` table does, choosing `lt` / `rt` per key.

## 5. Presence and swaps (blur content swaps)

```js
const v = K.presence(t, inBeat, outBeat, { delay: 0.06, outDelay: 0, enter, exit });
K.css(el, { ...K.swap(v, { blur: 14, scale: 0.94, dy: 0 }), left: x, top: y });
```
- The exit is fast (spring 0.2) and starts on `outBeat`. The enter starts `delay` seconds
  after `inBeat` and settles slower (0.38). Two labels in the same spot never read at once.
  Stagger siblings by adding 0.03–0.05 s per item.
- `null` for inBeat means "always entered", and `null` for outBeat means "never exits".
  Windows that cross the loop seam work (`[26, 28]` exits after the wrap).
- `{ instant: true }` appears exactly on the beat with no fade, for keystrokes, a caret
  or a badge count. The exit is still the quick blur.
- `K.swap` returns `opacity`, `filter: blur()`, `transform: translate/scale`, and
  `visibility`. Blur is specified in **screen** px and divided by the camera zoom, so it
  looks the same at every zoom.
  If you add your own `transform` to the same element, compose it yourself (the swap's
  transform comes first).
- `K.layer(el, group, vFn)` registers layers that share a spot, so the audit can flag two
  of them visible at once.
- `K.textAt(el, x, y, size, anchor, v, extra, swapOpts)` positions text in world px. The
  anchor is `'l'` (left edge at x), `'r'` (right edge at x) or `'c'` (centered), y is the
  vertical center, and the blur swap for `v` is applied. `extra` overrides anything
  (color, weight, clipPath…).
- `K.iconAt(el, x, y, size, v, color, extra)` places a size×size box centered at (x, y), with
  `color` feeding `currentColor`.
- `K.photoAt(img, left, top, w, h, { fx, fy, zoom, r }, extra)` fills a world-px box with an
  `<img>` like `object-fit: cover`, cropped around the focus point (fx, fy in 0..1 of the
  image), with an optional `zoom` (drive it from time for a slow drift) and corner radius.
  `extra` goes last: pass opacity, visibility and a blur filter for the swap, and leave the
  filter off (`'none'`) once it's fully visible, since a filter on a large photo is slow to
  render. `K.ready` waits for every `<img>` to decode, so frames never show a half-loaded
  photo. `bundle.py` inlines local photos.
- `K.splitClip(boxLeft, boxWidth, L, R, boxHeight?)` returns `{ inside, outside }`
  clip-path strings for a label whose box starts at `boxLeft` (world px), given a fill
  spanning [L, R]. Put `outside` on the base copy and `inside` on the inverted copy. No
  glyph is drawn twice, so there is no halo, even white over ink on an accent fill.

## 6. Camera

```js
K.camera([[0, 3.7], [2, 6.2], [24, 3.05, 0, 108, SP.camOut]], SP.cam);  // [beat, zoom, cx, cy, spring?]
K.css(world, { transform: K.worldTransform() });                          // inside frame(t)
```
- Zoom springs in log space, because equal ratios feel like equal steps.
  `K.fit(w, h, fill)` returns the zoom that makes a w×h box fill `fill` of the largest box
  centred on `K.focus` inside the safe area (the frame, unless `safe` was set).
- `K.cam` is the current camera `{z, cx, cy}` during a frame. `K.project(t, [x, y])` and
  `K.unproject(t, [sx, sy])` convert world ↔ screen. The camera centre lands on `K.focus`.
- `K.bleed(t, m = 80)` returns the world rect `{ cx, cy, w, h }` that covers the whole frame
  plus `m` screen px past each edge at time t. Key a state's w/h/cx/cy to functions of it to
  go full-bleed: `w: (t) => K.bleed(t).w`. It follows the camera, so a slow push-in keeps it
  full-bleed. While the shape covers the frame, set `shape.toggleAttribute('data-bleed', on)`
  so the audit skips the margin check.
- The world origin is the shape's resting center, and everything is laid out in world px.

## 7. Cursor and drags

```js
K.cursor(keys, presses, { warp: 0.85 });
// keys:    [[beat, anchor, { arc = 0.08, drag = false }], ...]   anchor = [x, y] or (t) => [x, y]
// presses: [[downBeat, upBeat], ...]
K.cursorAt(t)  // → { x, y (screen), world: [x, y], press (0..1 spring), down (0|1) }
```
- The cursor stops at each key (minimum-jerk, peak speed a little early, and a slight arc
  unless `drag`). Two keys with the same anchor mean "hold". The segment from the last key
  to the first wraps across the loop.
- It's drawn in screen space at a constant size, with a squish while pressed. The arrow's
  tip sits exactly on the anchor (`K.cursorTip`, a fraction of the box; set `cursorTip`
  in `create()` if you pass your own `cursorSvg`). `window.__NO_CURSOR__` hides it (review
  uses this).

```js
const vol = K.drag({ press: 13, release: 15, map: (p, t) => clamp(v0 + (p[0] - x0) / 300),
                     before: (t) => v0, rest: (vRelease) => 1, spring: SP.release });
```
- Before `press`, the value comes from `before(t)`. While held, it's `map(cursorWorld(t), t)`
  (direct manipulation). After `release`, it springs from the release value, with the release
  velocity, to `rest(vRelease)`.
- Define the cursor before the drags, because a drag reads the cursor path.
- The cursor anchor at the press should be where the value's handle is, so the grab is
  continuous. For a moving handle, use a function anchor.
- Rubber band past limits: `MorphKit.rubber(x, lo, hi, dim, c = 0.55)`, or compute the
  overshoot in px and feed it to a stretch value (see the reference's volume slider).

```js
const keys = K.steps((t) => cellAt(K.cursorAt(t).world), 7, 9, { grid: 0.25, label: (c) => `cell ${c}`, sound: 'tick' });
```
- `K.steps(fn, fromBeat, toBeat, o)` samples a continuous value on every grid point (16ths
  by default) and returns `[[beat, value], …]` only where it changes. It registers an event
  and a sound cue per change when `label` or `sound` is given. Use it for drags over
  discrete things (calendar cells, detents, stepper values), so each step lands on the grid
  instead of wherever the cursor happens to cross. Feed the keys into your tracks.

## 8. Writing styles

- `K.css(el, props)` rewrites `el.style.cssText` entirely. camelCase or kebab-case keys both
  work. Numbers get `px`, except unitless properties (opacity, z-index, font-weight,
  line-height, flex, scale…). `null`, `undefined`, and `false` are skipped. Static styles
  belong in the stylesheet, and dynamic ones are written every frame.
- `K.attr(el, name, v)` sets SVG attributes (numbers go to 3 decimals). `K.text(el, s)` sets
  text content.
- `K.box(cx, cy, w, h, r)` returns absolute left/top/width/height/borderRadius for a
  centered box.

## 9. Frame loop, mount, flags

```js
K.onFrame((t) => { /* write every dynamic style from t */ });
K.mount(stageEl, { audio: 'mix.wav', fonts: ['400 16px Geist', '500 16px Geist', '600 16px Geist'], cursorSvg });
```
- `K.seek(t)` wraps t into [0, T), sets `K.t` and `K.cam`, calls your frame function, then
  draws the cursor and HUD. `window.seek === K.seek`.
- `K.ready` resolves after the fonts load and frame 0 is drawn. The scripts wait for it.
- Opening the page directly gives a dev player (space, ←/→, shift+←/→, and a scrubber), and
  the stage scales to fit the window. `?render` or `window.__RENDER__` hides the player.
  `?hud` or `window.__HUD__` shows the bar.beat HUD, which review frames use.

## 10. Helpers (`MorphKit.*`)

`clamp`, `lerp`, `invLerp`, `remap(x, a, b, c, d)`, `mod`, `minjerk(u)`, `hash(n)` (a
deterministic 0..1 value), `rubber(...)`, `oklab(hex)`, `oklabToCss(lab, a)`,
`mixHex(a, b, u, alpha)` (a static OKLab mix that returns a CSS color),
`smoothPath(points, tension)` (Catmull-Rom → Bézier `d`), `playPause(u, size)` (a
▶ ↔ ❚❚ morph path), `icon(name, px, stroke, color)` (SVG markup from `ICONS`: arrowDown,
check, search, volume, volumeLow, prev, next, download, share, copy, trash, image, file,
bell, close, plus, chevronRight, command, enter, sparkle, heart, user, calendar, home,
settings).

## 11. Audit

`K.audit(t, { minText: 22, minPad: 10, minMargin: 48, shape })` seeks t and returns
warnings. It flags on-screen text under `minText` px, text outside the shape or within
`minPad` of its edge (measured on the glyphs), truncated text, two registered layers of
one group visible together, and the `[data-shape]` element within `minMargin` of the frame
edge. `review.py` calls it on every sampled beat.

## 12. Page skeleton

```html
<div id="stage">                         <!-- 1440×1440, warm gray, Geist -->
  <div id="world">                       <!-- camera transform; NO will-change -->
    <div id="shape" data-shape>          <!-- the one shape: overflow hidden, box + radius + bg -->
      <div id="origin">                  <!-- at the world origin: left = w/2 - cx, top = h/2 - cy -->
        … content, absolutely positioned in world px …
```
Positioning content in world coordinates under `#origin` lets it stay put while the shape
grows around it. The shape's overflow clips it, so content is revealed as the shape grows.
