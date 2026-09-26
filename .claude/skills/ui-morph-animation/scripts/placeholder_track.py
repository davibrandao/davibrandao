#!/usr/bin/env python3
"""Synthesize a placeholder electronic track (default 120 BPM) with numpy.

Use it to preview motion before the real song is available, or to test the
beat analysis (the true grid is written next to the audio as *.truth.json).
It is not a substitute for the song the user picks.

usage: placeholder_track.py OUT.wav [--bpm 120] [--bars 40] [--offset 0.37]
"""
import argparse
import json
from pathlib import Path

import numpy as np

from common import write_wav

SR = 44100


def env_exp(n, tau):
    return np.exp(-np.arange(n) / (tau * SR))


def kick():
    n = int(0.4 * SR)
    t = np.arange(n) / SR
    f = 46 + 120 * np.exp(-t * 32)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t * 7.5)
    click = np.random.default_rng(1).standard_normal(n) * env_exp(n, 0.0015) * 0.25
    return x + click


def lowpass_fft(x, cutoff, order=2):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(X / np.sqrt(1 + (f / cutoff) ** (2 * order)), len(x))


def bandpass_fft(x, lo, hi):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR) + 1e-9
    h = 1 / np.sqrt(1 + (lo / f) ** 4) / np.sqrt(1 + (f / hi) ** 4)
    return np.fft.irfft(X * h, len(x))


def clap():
    rng = np.random.default_rng(2)
    n = int(0.3 * SR)
    x = np.zeros(n)
    for k, d in enumerate([0, 0.011, 0.022]):
        i = int(d * SR)
        m = n - i
        x[i:] += rng.standard_normal(m) * env_exp(m, 0.006 if k < 2 else 0.07)
    return bandpass_fft(x, 900, 5000) * 0.9


def hat(open_=False):
    rng = np.random.default_rng(3 if open_ else 4)
    n = int((0.25 if open_ else 0.06) * SR)
    x = rng.standard_normal(n) * env_exp(n, 0.06 if open_ else 0.012)
    return bandpass_fft(x, 7000, 16000) * 0.55


def tone(freq, dur, harmonics=6, tau=None, detune=0.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for h in range(1, harmonics + 1):
        for d in ([0.0] if not detune else [-detune, detune]):
            x += np.sin(2 * np.pi * freq * h * (1 + d) * t) / h
    a = np.minimum(1, t / 0.005) * (env_exp(n, tau) if tau else 1)
    r = np.minimum(1, (dur - t) / 0.02)
    return x * a * r


def midi(m):
    return 440 * 2 ** ((m - 69) / 12)


CHORDS = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]  # Am F C G


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--bpm", type=float, default=120)
    ap.add_argument("--bars", type=int, default=40)
    ap.add_argument("--offset", type=float, default=0.37, help="silence before the first downbeat (s)")
    a = ap.parse_args()

    beat = 60 / a.bpm
    total = a.offset + a.bars * 4 * beat + 2
    out = np.zeros(int(total * SR) + SR)
    K, C, H, OH = kick(), clap(), hat(), hat(True)

    def put(sig, t, g=1.0):
        i = int(round(t * SR))
        out[i:i + len(sig)] += sig[: len(out) - i] * g

    for bar in range(a.bars):
        section = "intro" if bar < 4 else "break" if 24 <= bar < 28 else "A" if bar < 16 else "B"
        chord = CHORDS[bar % 4]
        t_bar = a.offset + bar * 4 * beat
        # pad: whole bar, soft
        pad = sum(tone(midi(m), 4 * beat, harmonics=3, tau=None, detune=0.003) for m in chord)
        put(lowpass_fft(pad, 1400) * 0.05, t_bar)
        if bar % 4 == 0:
            put(OH * 1.2, t_bar)  # crash-ish accent on phrase starts
        for b in range(4):
            tb = t_bar + b * beat
            if section != "intro" or b % 2 == 0:
                put(H, tb + beat / 2, 0.8)
            if section == "break":
                continue
            if section != "intro":
                put(K, tb, 0.9)
                if b in (1, 3):
                    put(C, tb, 0.6)
                put(H, tb, 0.5)
                # bass on 8ths following the chord root
                root = midi(chord[0] - 24)
                for e in range(2):
                    put(lowpass_fft(tone(root * (2 if e else 1), beat / 2 * 0.9, harmonics=8, tau=0.12), 700) * 0.22,
                        tb + e * beat / 2)
            if section == "B" and b in (1, 3):
                stab = sum(tone(midi(m + 12), beat * 0.4, harmonics=4, tau=0.08) for m in chord)
                put(lowpass_fft(stab, 3000) * 0.07, tb + beat / 2)

    out = out[: int(total * SR)]
    out /= np.max(np.abs(out)) / 0.89
    write_wav(a.out, np.stack([out, out], 1), SR)
    truth = {"bpm": a.bpm, "first_downbeat": a.offset, "bars": a.bars,
             "downbeats": [a.offset + i * 4 * beat for i in range(a.bars)],
             "sections": "bars 1-4 intro, 5-16 A, 17-24 B, 25-28 break, 29+ B"}
    Path(a.out).with_suffix(".truth.json").write_text(json.dumps(truth, indent=2))
    print(f"wrote {a.out} ({total:.1f}s, {a.bpm} BPM, first downbeat {a.offset}s)")


if __name__ == "__main__":
    main()
