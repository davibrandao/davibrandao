#!/usr/bin/env python3
"""Synthesize a small, soft UI sound kit with numpy (royalty-free by construction).

Sounds: click tap tick key1-4 enter pop pop_down whoosh toggle success thud swipe
Each is written as a 48 kHz mono WAV; mix_audio.py lines up each sound's *measured
peak* with its cue time, so a whoosh peaks on the beat instead of starting on it.

usage: ui_sounds.py OUT_DIR [--key F]
--key tunes the one pitched sound (success: root, then the fifth above) to the song's key,
so it rings with the music instead of against it. Default: E (E6 → B6).
"""
import argparse
import json
from pathlib import Path

import numpy as np

from common import write_wav

SR = 48000


def t_axis(dur):
    return np.arange(int(dur * SR)) / SR


def decay(t, tau):
    return np.exp(-t / tau)


def attack(t, a):
    return np.minimum(1, t / a) if a > 0 else 1


def sweep(t, f0, f1, curve=0.03):
    f = f1 + (f0 - f1) * np.exp(-t / curve)
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def band(x, lo, hi):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR) + 1e-9
    h = 1 / np.sqrt(1 + (lo / f) ** 4) / np.sqrt(1 + (f / hi) ** 4)
    return np.fft.irfft(X * h, len(x))


def noise(n, seed):
    return np.random.default_rng(seed).standard_normal(n)


def finish(x, fade=0.004):
    x = np.asarray(x, float)
    n = int(fade * SR)
    if n and len(x) > n:
        x[-n:] *= np.linspace(1, 0, n) ** 2
    return x / (np.max(np.abs(x)) + 1e-12) * 0.9


def click(seed=0, body=1150, low=240):
    t = t_axis(0.06)
    x = 0.55 * band(noise(len(t), seed), 2000, 7000) * decay(t, 0.0012)
    x += 0.8 * sweep(t, body * 1.15, body, 0.004) * decay(t, 0.009)
    x += 0.35 * np.sin(2 * np.pi * low * t) * decay(t, 0.014)
    return finish(x)


def tap():
    t = t_axis(0.08)
    x = 0.9 * sweep(t, 420, 300, 0.01) * decay(t, 0.016) * attack(t, 0.0008)
    x += 0.25 * band(noise(len(t), 11), 1500, 6000) * decay(t, 0.0015)
    return finish(x)


def tick():
    t = t_axis(0.025)
    x = np.sin(2 * np.pi * 3200 * t) * decay(t, 0.0025) + 0.4 * band(noise(len(t), 21), 4000, 12000) * decay(t, 0.0008)
    return finish(x)


def key(seed):
    rng = np.random.default_rng(100 + seed)
    t = t_axis(0.09)
    body = rng.uniform(165, 215)
    x = 0.8 * band(noise(len(t), 200 + seed), 1500, 5500) * decay(t, 0.006)
    x += 0.7 * np.sin(2 * np.pi * body * t) * decay(t, 0.015) * attack(t, 0.0005)
    d = int(rng.uniform(0.010, 0.016) * SR)  # the key bottoming out
    y = np.zeros_like(x)
    y[d:] = 0.3 * band(noise(len(t) - d, 300 + seed), 2500, 8000) * decay(t[: len(t) - d], 0.003)
    return finish(x + y)


def enter():
    t = t_axis(0.12)
    x = 0.8 * band(noise(len(t), 400), 1200, 5000) * decay(t, 0.009)
    x += 0.9 * np.sin(2 * np.pi * 140 * t) * decay(t, 0.026) * attack(t, 0.0006)
    d = int(0.018 * SR)
    x[d:] += 0.35 * band(noise(len(t) - d, 401), 2500, 8000) * decay(t[: len(t) - d], 0.004)
    return finish(x)


def pop(up=True):
    t = t_axis(0.16)
    f0, f1 = (380, 820) if up else (820, 380)
    x = sweep(t, f0, f1, 0.025) * decay(t, 0.045) * attack(t, 0.004)
    x += 0.15 * sweep(t, f0 * 2, f1 * 2, 0.025) * decay(t, 0.03) * attack(t, 0.004)
    return finish(x)


def whoosh():
    dur, n_fft, hop = 0.42, 1024, 256
    t = t_axis(dur)
    x = noise(len(t) + n_fft, 500)
    out = np.zeros(len(x))
    win = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1 / SR)
    for i in range(0, len(t), hop):
        u = i / len(t)
        fc = 600 * (2400 / 600) ** u
        h = np.exp(-0.5 * (np.log2((freqs + 1) / fc) / 0.6) ** 2)
        seg = np.fft.irfft(np.fft.rfft(x[i:i + n_fft] * win) * h, n_fft)
        out[i:i + n_fft] += seg * win
    out = out[: len(t)]
    env = np.where(t < 0.15, (t / 0.15) ** 2, np.exp(-(t - 0.15) / 0.07))
    return finish(out * env, fade=0.02)


def toggle():
    t = t_axis(0.09)
    x = 0.7 * sweep(t, 1500, 1400, 0.003) * decay(t, 0.006) + 0.3 * band(noise(len(t), 600), 2500, 8000) * decay(t, 0.001)
    d = int(0.032 * SR)
    x[d:] += 0.8 * sweep(t[: len(t) - d], 2300, 2100, 0.003) * decay(t[: len(t) - d], 0.008)
    return finish(x)


def success(root=1318.5):
    t = t_axis(0.6)
    x = np.zeros_like(t)
    for delay, f in ((0.0, root), (0.075, root * 2 ** (7 / 12))):
        d = int(delay * SR)
        tt = t[: len(t) - d]
        tone = np.sin(2 * np.pi * f * tt) + 0.12 * np.sin(2 * np.pi * 2 * f * tt)
        x[d:] += tone * decay(tt, 0.16) * attack(tt, 0.003)
    return finish(x, fade=0.05)


def thud():
    t = t_axis(0.2)
    x = np.sin(2 * np.pi * 95 * t) * decay(t, 0.055) * attack(t, 0.001)
    x += 0.3 * band(noise(len(t), 700), 80, 900) * decay(t, 0.01)
    return finish(x, fade=0.02)


def swipe():
    t = t_axis(0.09)
    env = np.where(t < 0.03, t / 0.03, np.exp(-(t - 0.03) / 0.015))
    return finish(band(noise(len(t), 800), 1800, 9000) * env)


KIT = {
    "click": lambda: click(), "tap": tap, "tick": tick,
    "key1": lambda: key(1), "key2": lambda: key(2), "key3": lambda: key(3), "key4": lambda: key(4),
    "enter": enter, "pop": lambda: pop(True), "pop_down": lambda: pop(False), "whoosh": whoosh,
    "toggle": toggle, "success": success, "thud": thud, "swipe": swipe,
}


def peak_time(x, sr=SR, win=0.002):
    e = np.convolve(np.abs(x if x.ndim == 1 else x.mean(1)), np.ones(max(1, int(win * sr))) / max(1, int(win * sr)), "same")
    return int(np.argmax(e)) / sr


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir")
    ap.add_argument("--key", default=None, help="song key (e.g. F, Dm, Bb) for the success chime")
    a = ap.parse_args()
    if a.key:
        pc = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[a.key[0].upper()]
        pc = (pc + {"#": 1, "b": -1}.get(a.key[1:2], 0)) % 12
        root = 440 * 2 ** ((pc - 9) / 12)
        while root < 960:  # the octave that sits between 960 and 1920 Hz
            root *= 2
        KIT["success"] = lambda: success(root)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name, fn in KIT.items():
        x = fn()
        write_wav(out / f"{name}.wav", x, SR)
        meta[name] = {"duration": round(len(x) / SR, 4), "peak": round(peak_time(x), 4)}
    (out / "sounds.json").write_text(json.dumps(meta, indent=1))
    print("wrote " + ", ".join(f"{k} (peak {v['peak'] * 1000:.0f} ms)" for k, v in meta.items()))


if __name__ == "__main__":
    main()
