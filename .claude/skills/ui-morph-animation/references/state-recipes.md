# State recipes

Sizes are world px at real 1× UI scale, and the camera zooms them. "Carries" names the part
that should survive into or out of the state. Code for the reference's 12 states, plus the
scrub interaction inside the player, lives in `examples/reference.html`. The rest follow the
same patterns.

## Contents
- Built in the reference: button · loader · check · dynamic island · music player ·
  scrub · volume slider · toggle · tabs · chart · ⌘K pill · command palette · toast
- More: dropdown · stepper · text field · OTP code · like button · rating · notification ·
  avatar stack · date picker · upload · pagination dots · accordion · pricing switch
- Numbers, text and icons

---

## Built in the reference

**Button**: 204×56, r 28, black. The label is an 18 px arrow icon plus "Download" at 17/500.
Hover lightens the fill about 13 % toward white. The press squishes the whole shape to 0.965,
and the release on the beat triggers the next state. Sound: click. Zoom ≈ 3.7.

**Loader (progress ring)**: a 56 circle. The ring has r 11, a 2.4 stroke, a 22 % white
track, and a white arc from the top. Progress *steps on beats* (26 → 46 → 82 → 100 %), each
step a snappy spring, so every beat does something. Ticks on the steps are optional.
Zoom ≈ 6.

**Check / success**: at 100 % the circle inverts (black → white, or → accent), and the check
draws on in about 0.3 s (stroke-dash, minimum-jerk). This is the loop's first color accent.
Sound: success (two-note, and the second note's peak lands on the beat).

**Dynamic island**: a 220×56 black pill. A 30 px album art sits at the left and an
equalizer at the right, both *pinned to the growing edges* (`x = ±SW(t)/2 ∓ inset`). The
equalizer shows paused dots until something plays. Click to expand. Zoom ≈ 4.4.

**Music player**: 372×196, r 40. Art 52 at the top-left, title 17/600, artist 15/400
at 56 % white, and the equalizer at the top-right (carried over from the island).
A progress row (12 px tabular time labels plus a 6 px track) and filled media glyphs
(prev, play/pause 30, next). The play/pause is two 4-point polygons morphing point for
point (`MorphKit.playPause(u)`). Clicking play morphs ▶ → ❚❚ and starts the equalizer
bouncing on the beat.

**Scrub**: hovering the thumb grows it. Grabbing thickens the track from 6 to 10. The drag
runs the time labels live, and the value comes straight from the cursor. The playback
progress creeps before the grab, and the cursor anchor follows it as a function.

**Volume slider (stretch past max)**: a 300×56 pill. The fill is the progress fill carried
over, and it covers the full height. Speaker icons: ink on the fill, gray on the track.
A covered icon flips to ink. Drag relative to the grab point. Past 100 %, the extra becomes
a rubber-band stretch: the width grows to the right (anchored left), and the height thins
by about 10 % of the stretch. Release springs back with the release velocity. Sounds: tap
on grab, tick at the max, thud on release.

**Toggle**: a 92×56 track, gray off (`#B5B2AC`) and black or accent on. The knob is 48
with a 4 px inset and a small shadow, and it is the slider fill shrunk. Pressing stretches
the knob toward the on side by 12. The release on the beat moves it with the leading edge
on a fast spring and the trailing edge on a slow one. The track color springs over.
Sound: toggle.

**Tabs (segmented, liquid indicator)**: a 344×56 black pill with four 84-wide segments. The
indicator is the knob stretched into a white pill under a tab. The labels are 15/500 gray
outside the indicator and ink inside it: two copies with **complementary clips** from
`K.splitClip`, so the inversion follows the liquid edges pixel for pixel. Clicking another
tab sends the leading edge first.

**Chart (draws itself, tooltip on hover)**: a 380×300 r 32 black card. The tab row springs up
into the header over a faint track pill. The value is 30/600 tabular and counts up with
the draw, plus a caption (13/400) and a delta. The plot is 344×104: a smooth line
(Catmull-Rom), a flat 10 % area revealed by a clip rect as the line draws (`stroke-dashoffset`
from a spring), three hairlines, and 11 px day labels centered on the points. The tooltip
is a white pill (12/600 tabular), a dashed guide, and a dot *on the curve* (y sampled from
the path once, at startup). It slides point to point on a spring. Text inside the bubble
swaps with a short blur.

**⌘K pill**: a 300×52 white pill with a search icon, "Search…" at 16/400 40 %, and a
keycap at the right (the indicator carried over, now `ink 7 %`) holding `⌘K`. The label
waits about 0.2 s for the keycap to arrive.

**Command palette (type to filter, enter)**: 400 wide, *top-anchored* at the pill's top,
so it grows downward, and the camera follows `cy`. Input row 52, 1 px divider, 40 px rows
(18 px icon, 15/500 label, 13/500 shortcut hint at 40 %). The highlight is the keycap
carried over. Keys land on 16ths. Each keystroke filters: non-matches exit, matches
spring to new slots, and the palette height springs. The placeholder disappears
instantly on the first key. Enter flashes the row and collapses the palette.
Sounds: key ×n, enter.

**Toast**: a 300×56 black pill with a circle-check icon (the circle draws, then the check),
"Chart exported" at 15/500, and "Undo" at 56 %. It morphs back into the first state on the
downbeat.

## More states

**Dropdown / select**: a 200×48 pill with the value and a chevron. Clicking grows it into a
menu (200 × n·40, r 16, top-anchored), and the chevron rotates 180° on a spring. Hovering
rows moves a highlight (edge springs). Selecting collapses it back to a pill with the new
value, with the value text swapping by blur. Sounds: click, tick per hover step, pop_down.

**Stepper / quantity**: a 160×52 pill with − · value · +. Each click on + rolls the digit up.
Each digit is a vertical strip of 0–9 in an `overflow: hidden` cell, and its `translateY`
springs to `-digit × lineHeight`. The audit ignores the clipped digits. Tabular numbers.
The + button squishes. Clicks on consecutive beats make a nice beat run.

**Text field**: a 320×52 white field with a 1.5 px border (ink 12 % → ink 60 % on focus, no
glow). The caret stays solid while typing. Characters appear instantly on 16ths.
Validation draws an inline check at the right. Continuity: a button can open into it.

**OTP / code**: six 44×52 cells in a 320 pill. Digits type in on 16ths, with the active cell
border moving as an edge-spring highlight. On the last digit the whole row flashes
success (accent or inversion) and collapses into a check.

**Like / heart**: a 64 circle with a heart outline. Clicking fills the heart (clip reveal
from the bottom, or a scale 0 → 1 fill on a snappy spring). The count to its right rolls
+1. No particles. Sound: pop.

**Rating**: five 24 px stars in a 200×52 pill. Hovering fills stars up to the cursor, and
each newly filled star is its own event on a 16th. Clicking locks the rating and fades a
"Thanks" label in.

**Notification**: a 56 circle with a bell, and a badge (18 px, red only if that's the
accent) popping in with a count. Clicking grows it into a 320×88 card (avatar, title,
body line, time). Dismissing swipes the content left and collapses the card.

**Avatar stack**: three 40 px circles overlapping by 12 inside a 136×52 pill. Hovering
spreads them apart (gaps spring open) and the pill widens. A "+3" chip rolls in.

**Date picker**: the pill grows into a 280×300 card with a month label and a 7×5 grid of
32 px day cells. The hover dot moves between cells with *all edges on one spring*. Liquid
lead/trail edges only work along one axis, and on a diagonal path they pile up into a
blob. Clicking sets a start. Dragging extends a range pill along the row (lead/trail is
fine here), with each cell step snapped to 16ths via `K.steps` and a tick per step. Numbers
under the pill invert with `K.splitClip`. Releasing confirms. The card collapses into a
"May 12 – 16" pill.

**Upload / drop zone**: a 300×160 card with a dashed 1.5 px border (a dash is fine, but no
gradients). A file chip drops in, a progress bar fills on beats, and it resolves into a
check. Continuity: the progress bar can become a slider next.

**Pagination dots**: five 8 px dots in a pill. The active dot is a 24×8 pill that travels
with edge springs. Each click or beat advances it. It works well as a small interlude
state.

**Accordion**: a 320-wide card with three 48 px rows. Clicking a row grows the card (row
content blurs in, the chevron rotates). Opening another row closes the first on the same
beat, so the heights trade and the card height is their sum.

**Pricing switch**: "Monthly · Yearly" as a 220×48 segmented pill (a tabs recipe with two
segments). Clicking flips the indicator, and the price below rolls digits (`$24 → $19`).
The shape can grow to include the price.

## Numbers, text and icons

- **Tabular numbers** (`font-variant-numeric: tabular-nums`) for anything that changes: times,
  counts, prices, and percentages. Otherwise widths jitter every frame.
- **Counters:** `Math.round(target * progress)`, or digit rolls for small integers.
  Format with `toLocaleString('en-US')`.
- **Sizes that survive the camera:** body 15–17, captions 12–13, and nothing under 11. The
  audit flags anything under 22 px on screen.
- **Weights:** 400 for secondary, 500 for labels, and 600 for titles and values. Use
  letter-spacing -0.01em (-0.02em at 28+).
- **Icons:** `MorphKit.icon(name, px, stroke)` with 18–20 px and stroke 1.8–2 within a
  state. Media controls are filled glyphs with the same rounded joins. Add to `ICONS` in
  the 24-grid style (round caps and joins, no fills) rather than mixing icon sets.
