# By-eye review checklist

Run `review.py --mid`, open `review/sheet.png`, then open full-size frames for anything
doubtful. `--at 12.5,19.25` renders exact close-ups, and `--range 18.75:19.75:0.125`
renders a filmstrip of one transition. Go row by row, one bar per row, beats and
half-beats.

## Every frame
- [ ] One shape. No second container appears, and nothing is cut in or out without the
      shape morphing.
- [ ] The state fills the frame: wide states at 55–85 % of the width, tiny ones 25–40 %.
      Nothing within about 48 px of the edge, including mid-morph (half-beat) frames.
- [ ] Text is crisp at rest. If it's soft, something under `#world` is composited: look for
      `will-change`, `translateZ`, a 3D transform, or `filter` left on at rest (the swap
      sets `filter: none` at full visibility).
- [ ] Labels are short and real. Numbers are tabular. The smallest text is at least 22 px on
      screen.
- [ ] Padding inside the shape is even, and there's no text within about 10 px of an edge.
- [ ] Icons share one weight and one family. Media glyphs are filled with matching joins.
- [ ] Colors are black, white, and warm gray, plus at most one accent in two to four places.
      No gradients on chrome, no glows, and shadows only as soft depth under the shape or knob.

## Beat frames (the moment of each event)
- [ ] The event in the HUD label is visibly starting or landing in that frame. A click
      frame shows the press squish, and the release-on-the-beat starts the morph.
- [ ] Every beat changes something besides the cursor. The report's activity line has no
      dead beats.
- [ ] The cursor is on the thing it's about to click, and not covering the content that
      matters in the next beat.

## Half-beat frames (mid-flight)
- [ ] Only one label is legible at a time. Swaps overlap only while blurred.
- [ ] Carried parts (fill, knob, indicator, art) travel along a sensible path, with no
      detours or flying in from a stale position (park hidden elements).
- [ ] Liquid edges visibly lead and trail, but the stretch reads as a stretch, not a glitch.
      About 1.3–1.8× the resting width at peak is plenty.
- [ ] Overshoot is tiny. Nothing wobbles after it lands.

## Loop and sound
- [ ] The report's seam line is ok: the step across the loop point is no bigger than its
      neighbors, and the cursor speed is continuous.
- [ ] The first frame (1.1) shows the last state morphing into the first, and it reads as
      the natural next beat.
- [ ] Cue gains are sensible: at most one or two sounds per event, and ambience quieter than
      actions.
- [ ] After the render, spot-check two or three frames from the MP4
      (`ffmpeg -ss 8.62 -i loop.mp4 -frames:v 1 f.png`) for motion blur on fast edges and
      sharp text at rest.

## Vertical formats, photos and brands (Reels, Stories, 4:5)
- [ ] Every state sits inside the safe area (`K.safe`): nothing important under the header,
      the caption, or the action buttons. The audit's margin check is clean.
- [ ] Text reads on a phone: about 30 px or more of the 1080 px width, and nothing under 25.
- [ ] The first second already shows the product or the place, and the hook plays from bar 1.
- [ ] Photos are cropped on their subject (the sign, the boat's bow, the sun), with no
      sliver of the card behind a settling photo and no chip covering the subject.
- [ ] Text over a photo is legible over its darkest and lightest parts (flat tint plus a
      soft dark shadow), and it sits on the calm part of the photo.
- [ ] The brand's palette is used as the brand uses it (the main color for the big surfaces,
      the accent for the moments), and the copy is in the audience's language.
- [ ] The full-bleed moment lands on the music's drop.
