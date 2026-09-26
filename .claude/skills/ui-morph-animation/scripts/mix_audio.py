#!/usr/bin/env python3
"""Mix the loop's soundtrack: the song section + UI sounds placed by their measured peak.

- The song is cut on the analyzed downbeat. Its last `xfade` beat is crossfaded with the
  audio just *before* the start, so the end flows into the first frame and the loop is seamless.
- Every cue's sound is shifted so its loudest moment (not its first sample) lands on the cue
  time. Sounds that start before 0 or ring past the end wrap around the loop.

usage: mix_audio.py --song SONG --beats beats.json --cues cues.json --out mix.wav
                    [--sounds DIR] [--ui-db -8] [--music-db -1.5] [--xfade-beats 0.5] [--loops 1]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from common import decode_audio, read_wav, write_wav

SR = 48000


def peak_index(x, sr=SR, win=0.002):
    m = x if x.ndim == 1 else x.mean(1)
    w = max(1, int(win * sr))
    e = np.convolve(np.abs(m), np.ones(w) / w, "same")
    return int(np.argmax(e))


def load_sound(sounds_dir, name, cache={}):  # noqa: B006 — tiny per-process cache
    if name in cache:
        return cache[name]
    p = Path(sounds_dir) / f"{name}.wav"
    if not p.exists():
        cands = sorted(Path(sounds_dir).glob(f"{name}.*"))
        if not cands:
            sys.exit(f"sound '{name}' not found in {sounds_dir}")
        x = decode_audio(cands[0], SR, 1)[:, 0]
    else:
        x, sr = read_wav(p)
        x = x.mean(1)
        if sr != SR:
            x = decode_audio(p, SR, 1)[:, 0]
    cache[name] = x
    return x


def mix(song, section, cues, out, n_samples=None, sounds_dir=None, ui_db=-8.0, music_db=-1.5,
        xfade_beats=0.5, loops=1, music=True):
    start = float(section["start"])
    T = float(section["duration"])
    beat = T / (len(section["beats_rel"]) - 1)
    N = int(round(T * SR)) if n_samples is None else int(n_samples)
    X = int(round(xfade_beats * beat * SR))
    body = np.zeros((N, 2))
    if music:
        pre_start = start - X / SR
        seg = decode_audio(song, SR, 2, start=max(0.0, pre_start), duration=N / SR + X / SR + 0.2)
        if pre_start < 0:  # song starts right at the loop: pad silence before it
            seg = np.concatenate([np.zeros((int(round(-pre_start * SR)), 2)), seg])
        need = X + N
        if len(seg) < need:
            seg = np.concatenate([seg, np.zeros((need - len(seg), 2))])
        pre, body = seg[:X].astype(float), seg[X:X + N].astype(float).copy()
        if X > 0:
            u = np.linspace(0, 1, X)[:, None]
            body[N - X:] = body[N - X:] * np.cos(u * np.pi / 2) + pre * np.sin(u * np.pi / 2)
        pk = np.max(np.abs(body)) + 1e-12
        body *= 10 ** (music_db / 20) / pk
    ui = np.zeros(N)
    placed = []
    g_ui = 10 ** (ui_db / 20)
    for c in cues:
        x = load_sound(sounds_dir, c["sound"])
        p = peak_index(x)
        s0 = int(round(c["t"] * SR)) - p
        idx = (s0 + np.arange(len(x))) % N  # wrap around the loop seam
        np.add.at(ui, idx, x * g_ui * float(c.get("gain", 1)))
        placed.append((c["t"], c["sound"], p / SR))
    mixed = body + ui[:, None]
    pk = np.max(np.abs(mixed))
    if pk > 0.97:
        mixed *= 0.97 / pk
    if loops > 1:
        mixed = np.tile(mixed, (loops, 1))
    write_wav(out, mixed, SR)
    return placed, N


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--song", required=True)
    ap.add_argument("--beats", required=True, help="beats.json from analyze_beats.py")
    ap.add_argument("--cues", required=True, help="cues.json written by review.py / render.py")
    ap.add_argument("--sounds", default=None, help="folder of UI sounds (default: next to cues.json/sounds)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ui-db", type=float, default=-8.0)
    ap.add_argument("--music-db", type=float, default=-1.5)
    ap.add_argument("--xfade-beats", type=float, default=0.5)
    ap.add_argument("--loops", type=int, default=1)
    ap.add_argument("--no-music", action="store_true")
    a = ap.parse_args()
    beats = json.loads(Path(a.beats).read_text())
    cues = json.loads(Path(a.cues).read_text())
    sounds = a.sounds or str(Path(a.cues).parent / "sounds")
    if not Path(sounds).exists():
        sys.exit(f"no sounds folder at {sounds} — run ui_sounds.py {sounds}")
    n = int(round(cues["frames"] / cues["fps"] * SR)) if "frames" in cues else None
    placed, N = mix(a.song, beats["section"], cues["cues"], a.out, n, sounds, a.ui_db, a.music_db,
                    a.xfade_beats, a.loops, not a.no_music)
    print(f"wrote {a.out}: {N / SR:.3f}s × {a.loops}, {len(placed)} UI sounds placed by peak")


if __name__ == "__main__":
    main()
