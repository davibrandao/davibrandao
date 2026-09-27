# Choreography: from a list of states to a beat sheet

## Contents
1. The grid (1b: default and alternative chains)
2. Rules for the beat sheet
3. The cursor
4. The camera
5. Transitions between states
6. The plan you show the user (format)
7. Worked example: the reference loop

## 1. The grid

- `t = 0` is the analyzed downbeat. The loop is `bars × 4` beats long. At 120 BPM, a beat is
  0.5 s and 7 bars is 14 s.
- Write every time in **beats** (0-based). `K.b(n)` converts to seconds, and `K.bb(bar, beat)`
  converts a DAW-style bar.beat into a beat index (`K.bb(3, 2) = 9`).
- Events sit on beats, eighths (x.5), or sixteenths (x.25, x.75). Nothing lands in
  between. The review flags anything off the 16th grid.
- Budget by interactions. A morph takes about 1 beat. Each click, drag step, hover move or
  typing burst takes about 1 beat. A multi-step drag (a date range, a long scrub) takes 3–5.
  Sum the plan, then round up to whole bars. States usually average 2–2.5 beats, but a
  rich state (player, chart, palette, date picker) can take 3–5 if a small one gets 1.
- Default chain when the user asks for "the usual": button → loader → check → dynamic
  island → music player → volume slider → toggle → tabs → chart → ⌘K pill → command
  palette → toast (12 states, 28 beats, 7 bars; section 7).
- Other tempos: scale the motion with the beat. A good morph duration is about 1.1 × beat
  (0.55 s at 120 BPM, 0.45 s at 140, 0.7 s at 90). At slow tempos, put interactions on
  eighths so there is still something every half second.

## 1b. Default and alternative chains

Offer these when the user hasn't named states. Each has been checked for continuity
(a carried part links most neighbors) and for alternating scale. The first two have been
built end to end.

- **Default (12 states, 7 bars):** button → loader → check → dynamic island → music player →
  volume slider → toggle → tabs → chart → ⌘K pill → command palette → toast. This is the
  reference build.
- **Trip planner (8 states, 6 bars):** search bar → dropdown → date picker (range drag) →
  stepper (guests) → like → notification → avatar stack → toast. Carried parts: the
  dropdown highlight → calendar hover dot → range pill; the bell badge → unread dot; the
  card avatars → the stack. This is `examples/trip-planner.html`.
- **Travel Reel (9 states, 8 bars, 1080×1920, photos):** search → suggestion (with a photo
  thumbnail) → photo card (swipe ×2) → calendar (range drag) → travellers stepper →
  checklist → full-bleed photo (the drop) → WhatsApp chat → brand sign-off (segmented motto
  with a liquid indicator). Carried parts: the thumbnail opens into the card; the hover dot
  stretches into the date range; the WhatsApp button becomes the sent message; the typing
  bubble becomes the reply. This is `examples/travel-reel/`. Swap the destination, photos,
  palette and copy for another place or brand.
- **Sign-up (8 states, 5–6 bars):** button → dropdown (plan) → pricing switch (price rolls) →
  stepper (seats) → text field (email) → OTP code → check → toast.
- **Publish a shot (8 states, 5–6 bars):** button → upload (progress) → check → like →
  notification → avatar stack → chart → toast.

## 2. Rules for the beat sheet

1. **Something happens on every beat.** That can be a morph, a click, a drag step, a value
   change, a tooltip moving, a keystroke, a draw-on, or a counter. A beat with only the
   cursor drifting is dead time. Loaders count as long as they visibly step on beats.
2. **Each change has a cause** the viewer can see: the cursor clicks, drags, or types. The
   only automatic changes are consequences, like a loader finishing into a check or a
   success state resolving.
3. **Continuity over novelty.** When deciding the order, prefer neighbors that share a
   part: a progress bar becomes a slider, a slider becomes a toggle (the fill becomes the
   knob), and a knob becomes a tab indicator. Name the carried part in the plan.
4. **Alternate scale.** Small → big → small keeps the camera breathing. Avoid three big
   states in a row.
5. **Alternate color at most a few times.** Black states with one or two white moments
   (an inverted check, a white palette) read as punctuation. With an accent, spend it on
   two to four moments.
6. **The seam lands on 1.1.** The last state morphs back into the first on the downbeat of
   the next loop. The first state is mid-morph at t = 0, and that's correct.
7. **Leave the story readable.** Short labels ("Download", "Chart exported"), real-seeming
   data, and one idea per state.

## 3. The cursor

- **Clicks:** arrive about 1/8 beat or more before the press. Press a 16th before the beat
  and release on the beat. The UI reacts on release, so the change and its sound land on
  the beat. `K.cursor(keys, [[1.75, 2], …])`.
- **Drags:** hold for a beat or two. Keep a drag as one keyframe segment
  (`{ drag: true }`), because several keys would make the cursor stop at each one.
  The value comes from the cursor (`K.drag`), never the other way round.
- **Discrete drags snap on the grid:** when a drag walks over cells or detents, the cursor
  crosses them at arbitrary times. Sample what's under the cursor on 16ths with
  `K.steps(...)` and drive the UI, events and ticks from those keys. The cursor stays smooth
  and the steps stay on the beat.
- **Anchors are functions** when the target moves (a playing progress thumb):
  `[9, (t) => thumbAt(t)]`.
- **Get out of the way.** After a click, drift to a spot that doesn't cover the next
  state's content (below-right is usually free). Park outside the shape while typing.
- **Paths:** minimum-jerk with a slight arc and an early peak speed, like a real flick.
  Consecutive keys with the same anchor mean "hold".
- **The cursor is in screen space**, at a constant 64 px that is never scaled by the
  camera. Its position follows world anchors, so it rides along when the camera zooms.
- **Seam:** the cursor's last key flows into its first key across the loop. Plan the final
  move so it arrives on the first state's click target.

## 4. The camera

- **Vertical formats.** In a 1080×1920 Reel, a 300-wide state at zoom 2.2–2.6 fills the
  width, and most states end up at similar zooms. Vary the state widths (280–320) and let
  small states (a stepper, a pill) zoom in to 3+ so the camera still breathes. Pass the safe
  area to `create()` and every state centres clear of the platform's UI. A full-bleed photo
  is the one state allowed past it (`K.bleed`), and it makes the natural drop.
- Set one zoom per state so it fills the frame: 55–85 % of the width for wide states and
  25–40 % for tiny ones (loader, toggle). Use `K.fit(w, h, fill)` or set the values by eye.
  In the reference, zooms range from 3.05 (palette) to 6.2 (loader).
- **Zooming out uses a fast spring (0.5 s), and zooming in uses a slow one (0.95 s).** A
  growing shape must never overfill the frame, and a shrinking one should feel like the
  camera settling in.
- Move the camera center only when the shape's center moves. For example, a palette that
  grows downward from a pill needs `cy` to follow.
- Never shake, never rotate, and never punch in on the beat. The beat belongs to the UI.

## 5. Transitions between states

| from → to | what carries over | how |
|---|---|---|
| button → loader | the shape shrinks to a circle | label exits fast, ring enters, progress steps on beats |
| loader → check | ring completes | shape inverts (black → white, or → accent), check draws on |
| check → island | circle stretches into a pill | art and equalizer pinned to the growing edges |
| island → player | the island expands | art and equalizer glide to their player spots, rows blur in staggered by ~30 ms |
| player → slider | progress fill → volume fill | the fill rect's edges spring to the slider's |
| slider → toggle | fill → knob | fill shrinks to a circle, and the track turns "off" gray |
| toggle → tabs | knob → indicator | the knob stretches (leading edge first) into the pill under a tab |
| tabs → chart | tab row → card header | the shape grows downward, the row springs up, the line draws |
| chart → ⌘K pill | indicator → keycap | card collapses to a white pill, and the indicator becomes the `⌘K` keycap |
| pill → palette | keycap → highlighted row | palette grows downward from the pill (top-anchored), and rows enter staggered |
| palette → toast | — | enter flashes the row, and the card collapses into a dark pill |
| toast → button | — | label swap, width change (the seam) |

When nothing carries over, the shape still morphs, and only the content swaps.

## 6. The plan you show the user (format)

Show it before writing any code. Keep it scannable in a terminal:

```
Song: "Night Drive" — 120.0 BPM, loop = bars 17–23 (0:32.4 → 0:46.4), 14.0 s
Palette: black & white on warm gray · font Geist · cursor drives every change

bar.beat  t      state        on the beat                         cursor                 sound
1.1       0.00   button       toast → "Download" (seam)           glides in              pop
1.2       0.50   ·            hover: fill lightens                on the button          —
1.3       1.00   loader       click → shrinks to a ring           press 1.2+¾, release   click
…
7.4      13.50   ·            toast check draws                   drifts back to button  pop

States
- button   204×56 pill, black, "↓ Download"
- loader   56 circle, black, white progress ring (46 → 82 → 100%)
- player   372×196 r40, black, art · title · progress · controls; the island's art+EQ carry over
…
Camera: zooms 3.0–6.2 (fills each state); pulls back fast when the UI grows.
Anything to change before I build it?
```

## 7. Worked example: the reference loop (7 bars, 120 BPM)

| bar.beat | beat | state | on the beat | cursor | sound |
|---|---|---|---|---|---|
| 1.1 | 0 | button | toast → "Download" (seam) | glides in from the toast | pop |
| 1.2 | 1 | · | hover: fill lightens | arrives (0.75) | — |
| 1.3 | 2 | loader | click → shrinks into a ring | press 1.75, release 2 | click |
| 1.4 | 3 | · | progress steps to 46 % | drifts aside | tick |
| 2.1 | 4 | · | progress 82 % | — | tick |
| 2.2 | 5 | check | ring completes → circle inverts, check draws | — | success |
| 2.3 | 6 | island | circle stretches into the island (art + EQ dots) | moves onto it | pop |
| 2.4 | 7 | player | click → island expands into the player | press 6.75 | click + whoosh |
| 3.1 | 8 | · | click play → play/pause morph, EQ starts bouncing | press 7.75 | click |
| 3.2 | 9 | · | hover the thumb → it grows | follows the moving thumb | — |
| 3.3 | 10 | · | grab → track thickens | press 10 | tap |
| 3.4 | 11 | · | scrub to 62 %, time labels run; release 11.5 | drag | tick |
| 4.1 | 12 | slider | player → volume slider (fill carries over) | moves to the fill edge | pop_down |
| 4.2 | 13 | · | drag volume up | press 13 | tap |
| 4.3 | 14 | · | past max → slider stretches (rubber band) | keeps dragging | tick |
| 4.4 | 15 | · | release → springs back | release 15 | thud |
| 5.1 | 16 | toggle | slider → toggle (fill → knob, gray track) | moves onto it | pop_down |
| 5.2 | 17 | · | click → toggle on; knob stretches across | press 16.75 | toggle |
| 5.3 | 18 | tabs | knob → liquid indicator under "Year" | steps aside | pop |
| 5.4 | 19 | · | click "Week" → indicator slides, leading edge first | press 18.75 | click |
| 6.1 | 20 | chart | tabs open into a card; line draws; value counts up | moves into the plot | whoosh |
| 6.2 | 21 | · | hover → tooltip "Wed · 340" | on Wed | tick |
| 6.3 | 22 | · | tooltip slides to the peak "Fri · 612" | on Fri | tick |
| 6.4 | 23 | ⌘K pill | click → card collapses into "Search… ⌘K" | press 22.75 | click |
| 7.1 | 24 | palette | click → palette opens downward, rows stagger in | press 23.75, then parks outside | click + pop |
| 7.2 | 25 | · | type "exp" on 16ths → list filters, rows reorder | parked | key ×3 |
| 7.3 | 26 | toast | enter → palette collapses into a toast | parked | enter |
| 7.4 | 27 | · | toast check draws | heads back to the button | pop |

Carried parts: the progress fill → volume fill → toggle knob → tab indicator → ⌘K keycap →
highlighted palette row (one element, from 3.1 to 7.3), and the island art and equalizer →
player art and equalizer.
