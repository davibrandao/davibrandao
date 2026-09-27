# Audio: beat grid, loop point, UI sounds, mix, composing

## Contents
1. Getting the song
2. analyze_beats.py
3. Sound design (ui_sounds.py)
4. Placement by measured peak (mix_audio.py)
5. Mix
6. Composing an original track (compose.py)

## Getting the song

- Take a file path, or download a URL with `curl -L -o song.mp3 URL`. Mixkit track pages
  link an MP3 on `assets.mixkit.co`. If the page URL is given, find the audio URL in the
  page. If the network blocks the host, ask the user to upload the file.
- Mixkit tracks are free for commercial use in videos. Still point the user to the specific
  track's license page, and make no other legal claims.
- No song yet? `python3 $SKILL/scripts/placeholder_track.py placeholder.wav --bpm 120` makes a
  synthetic groove with a known grid. It's a timing stand-in. Tell the user, and ask for the
  real track again before the final render. When it arrives, re-run the analysis, update
  `CONFIG` (or re-scaffold), and re-review, because the tempo and loop start will change. If
  no song ever arrives, deliver with the placeholder and label it as one.

## analyze_beats.py (numpy only)

Pipeline: ffmpeg decode (mono, 22.05 kHz) → STFT (1024/256) → 48 log bands → spectral
flux (the whole band, plus a low band for the kick and a mid band for the snare) → tempo
by autocorrelation with a log-normal prior around `--bpm-hint` → dynamic-programming
beat tracking (Ellis 2007) → robust constant-grid fit → sub-frame refinement on the onset
envelope → snap to a round BPM when it fits as well → the median offset to onset peaks,
plus a measured 8.3 ms flux bias (without it, visuals would land early).

On synthetic tracks with a known grid, it's accurate to under 1 ms, including 118 BPM with
a 1.13 s intro offset, and MP3.

Downbeat phase: of the 4 phases, beat 1 is where harmonic change (chroma novelty) and kick
energy peak and snare energy is lowest. Snares sit on 2 and 4, which is why "loudest
beat" alone gets it wrong. `downbeat_confidence` under 0.5 prints a warning. Override with
`--downbeat-shift 0-3`.

Loop start (`candidates`): each downbeat that has room for `--bars` bars is scored on
- energy (a full arrangement is better than an intro),
- stability (no breakdown inside the loop, via bar-to-bar change),
- phrase boundary (the change between the 4 bars before and after, normalized). Loops
  should start where a phrase starts, and there's a bonus on the 4-bar grid of the
  strongest boundary,
- loop similarity (the bar before the start vs the loop's last bar, which get crossfaded),
- minus a penalty for the first 4 bars.

Override with `--start SECONDS` (it snaps to the nearest downbeat) or `--start bar:N`.

The summary's `seam` line (`section.xfade_dip_db`) is the loudness of the crossfaded half
beat relative to the loop's own last half beat. Near 0 dB is seamless. Below about -6 dB,
the loop audibly ducks just before it restarts, which happens when the pre-roll is a
breakdown or silence. Pick another candidate, or mix with `--xfade-beats 0.25`.
`loop_similarity` alone doesn't decide this; the dip does.

Key fields in `beats.json`: `bpm`, `steady_tempo`, `downbeat_phase`, `downbeat_confidence`,
`beats`, `downbeats`, `bar_energy`, `candidates[]`, and
`section {start, end, duration, bars, beats_rel, beat_strength}`. `beat_strength` shows
which beats of the loop are accented. Put big moments (a chart opening, a color
inversion) on strong ones.

## Sound design (ui_sounds.py)

A soft, synthesized kit (royalty-free by construction), 48 kHz mono:
`click` (a UI click with a small body) · `tap` (press) · `tick` (detents, steps, tooltip
moves) · `key1-4` (keystrokes, each slightly different) · `enter` (a heavier key) ·
`pop` / `pop_down` (a shape arriving or collapsing) · `whoosh` (big expansions; its peak
is about 150 ms in) · `toggle` (two clicks) · `success` (a two-note chime whose second note
is the peak) · `thud` (release, landing) · `swipe`.

To use a user-supplied sound, drop `name.wav` (or any format ffmpeg reads) into
`PROJECT/sounds/` and reference it with `K.cue(beat, 'name')`.

`success` is the one pitched sound (root, then the fifth above). Over a composed track,
regenerate the kit in the track's key so it rings with the music:
`ui_sounds.py PROJECT/sounds --key F`. The default (E6 → B6) suits songs in E, A or C.

Taste:
- Give each event at most one sound, and big morphs at most two (click plus whoosh).
- Gains 0.3–0.6 for ambience (whoosh, pop) and 0.8–1.0 for direct actions (click, toggle,
  keys).
- Silence is allowed on hover beats. The music carries those.

## Placement by measured peak (mix_audio.py)

For each cue, the mixer finds the sound's peak (the argmax of a 2 ms envelope) and starts
it at `cue_time - peak`. A whoosh swells *into* the beat, and a chime's pickup note plays
just before it. Sounds that start before 0 or ring past the end **wrap around the loop**,
because the video loops.

Verified on the reference: across 30 cues, the UI-layer peaks sit at a median 0.0 ms from
the cue times (the worst was 1.4 ms).

## Mix

- The song section runs from the chosen downbeat for exactly the video's length. Its last
  half beat is crossfaded with the half beat *before* the start, so the audio flows
  seamlessly into frame 0 on every repeat. The crossfade keeps power when the two sides are
  unrelated and keeps gain when they are the same music (a song that repeats), so it never
  bumps. A composed track sets `section.xfade_beats: 0` and needs no crossfade.
- Music is normalized to -1.5 dBFS peak, and UI sounds sit at `--ui-db -8` (relative to full
  scale, with the sounds peak-normalized). Lower it to -11 for a subtler mix, and raise it to
  -6 for louder UI. It's safety-limited to -0.3 dBFS.
- The video is a whole number of frames, so it can be up to half a frame longer or shorter
  than the musical loop (3.8 ms at 124 BPM). The mix is cut to the video's length, and the
  crossfade hides the difference.
- `render.py --song --beats` does all of this (it generates the kit if missing) and writes
  `PROJECT/mix.wav` and `PROJECT/cues.json`. To remix without re-rendering, run
  `python3 $SKILL/scripts/mix_audio.py --song S --beats beats.json --cues PROJECT/cues.json --out mix.wav`
  then `render.py --audio mix.wav`, or mux it with ffmpeg.

## Composing an original track (compose.py)

`compose.py OUT.wav --bars 8 [--bpm 120] [--key F] [--chords …] [--energy …] [--drop 20]`
synthesizes a track from scratch with numpy: no samples and no loops from anywhere, so it
can be posted and monetized, and nothing matches in Content ID. It writes `OUT.wav` (three
copies of the loop) and `OUT.beats.json`, whose section points at the second copy, so
`render.py --song OUT.wav --beats OUT.beats.json` uses it like an analyzed song.

**Style.** Warm tropical house with a Nordeste accent, 4/4, one chord per bar:
- Drums: a soft four-on-the-floor kick; finger snaps on 2 and 4 (claps join on the drop); a
  ganzá shaker on swung 16ths; a forró triangle (closed, closed, OPEN, closed); open hats on
  the offbeats of the drop.
- Bass: offbeat plucks at energy 2, and a tresillo (3-3-2) figure at 3 and above. It is a
  sine with a saturated top, so it still reads on phone speakers.
- Pad: detuned band-limited saws in close voicings, each chord moving as little as possible,
  and ducked by the kick.
- Marimba hook: the tresillo rhythm on chord tones, voice-led around A4, with a
  dotted-eighth ping-pong echo.
- Lead: a breathy pan flute on energy-4 bars, voice-led around D5, with slides into legato
  notes, a chiff on fresh attacks and late vibrato.
- Arc: a noise riser and a snare roll (eighths, then sixteenths) over `--build` beats before
  `--drop`; the kick and bass sit out its last 2 beats; an impact and a crash land on it; a
  descending tom fill (on the key's arpeggio) leads into the seam.

**Scoring it to the plan.**
- `--drop` is the beat of the moment that deserves the hit: the full-bleed photo, the big
  reveal. `auto` uses the first bar with energy 4.
- `--energy` is one value per bar (1–4). Keep the hook present from bar 1, since social
  video is judged in its first second; build to 4 on the drop and ease to 3 for the last bar.
- The default harmony is vi–IV–I–V, with IV|V leading into the drop so it lands on vi, and
  an I|V turnaround in the last bar. `--chords` takes roman numerals or chord names.
- Pick a key whose success chime suits the brand, then run `ui_sounds.py --key` with it.

**Loop-perfect by construction.** Every sound is placed on a circle of exactly one loop:
tails that ring past the end fold onto the start. Reverb is a circular convolution, the
echo is a sum of rolled copies, filters are circular FFT filters, and the bus compressor's
smoother runs two laps so its state wraps. Loop N+1 continues loop N sample for sample.

**Checks it prints, and what to look for.** The chord and energy map, the master level (about
-14 dBFS RMS with a 12–13 dB crest), and the energy per band. A healthy balance for this
style is roughly -5/-4/-9/-8/-17/-17/-20 dB for 20–60/60–150/150–400/400–1k/1–2.5k/2.5–6k/
6–16k Hz. A much hotter 6–16k band means hiss; a much hotter 400–1k band sounds boxy. Levels
live in the `MIX` table (dBFS RMS while each stem plays), so rebalancing is a one-line
change. `--stems DIR` writes every stem for a closer look.

**Mixing it with the UI.** The composed track is denser than a sparse song, so UI sounds
need about 2 dB more (`render.py --ui-db -6`). Clicks should peak 3–5 dB above the music's
local RMS; `pop` and `tick` can sit near it.
