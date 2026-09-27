#!/usr/bin/env python3
"""Compose an original, loop-perfect soundtrack scored to the beat sheet.

Everything is synthesized here from scratch (no samples, no loops from anywhere), so the
track belongs to whoever runs this: royalty-free, nothing for Content ID to match.
Style: warm tropical house with a Nordeste accent. It has a soft four-on-the-floor kick,
finger snaps, a ganzá shaker, a forró triangle, a plucked tresillo bass, a sidechained
pad, a marimba hook with a dotted-eighth echo, and a pan-flute lead on the drop. A riser
and a snare roll build into the drop, an impact lands on it, and a tom fill leads back
into the seam.

The loop is rendered on a circle. Every tail (reverb, echo, decays) that rings past the
end folds back onto the start, so the loop continues into itself sample for sample.
OUT.wav holds --loops copies, and OUT.beats.json points render.py at the second one:

  compose.py music.wav --bars 8          # drop on the first bar with energy 4
  render.py PROJECT --song music.wav --beats music.beats.json

usage: compose.py OUT.wav [--bpm 120] [--bars 8] [--key F] [--chords "vi IV I V"]
                          [--energy 2,2,3,3,3,4,4,3] [--drop auto|none|BEAT] [--build 4]
                          [--no-fill] [--loops 3] [--stems DIR] [--seed 0]
--energy, one per bar: 1 = marimba, pad, shaker, snaps · 2 = + kick, offbeat bass ·
  3 = + forró triangle, tresillo bass · 4 = + pan-flute lead, open hats, claps (the drop).
--chords: roman numerals in the key (vi IV I V) or chord names (Dm Bb F C), one per bar,
  cycled. "IV|V" splits a bar. The default is vi IV I V, with IV|V before the drop so the
  drop lands on vi, and an I|V turnaround in the last bar.
--drop: the beat of the impact (auto = the first bar with energy 4). The riser and roll
  fill the --build beats before it, and the kick and bass sit out its last 2 beats.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import write_wav  # noqa: E402

SR = 48000
LETTER = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
ACC = {"": 0, "#": 1, "b": -1}
MAJOR = [0, 2, 4, 5, 7, 9, 11]
MINOR = [0, 2, 3, 5, 7, 8, 10]
ROMAN = ["i", "ii", "iii", "iv", "v", "vi", "vii"]

# per stem: level (dBFS RMS while it plays), reverb send, echo send, how deep the kick ducks it
MIX = {
    "kick": (-14.0, 0.03, 0.0, 0.0),
    "bass": (-16.5, 0.0, 0.0, 0.55),
    "pad": (-22.5, 0.25, 0.0, 0.7),
    "marimba": (-22.5, 0.22, 0.25, 0.15),
    "lead": (-19.0, 0.35, 0.2, 0.15),
    "snap": (-20.0, 0.45, 0.0, 0.0),
    "clap": (-23.5, 0.4, 0.0, 0.0),
    "roll": (-24.0, 0.35, 0.0, 0.0),
    "shaker": (-35.5, 0.08, 0.0, 0.0),
    "triangle": (-32.0, 0.22, 0.0, 0.0),
    "openhat": (-35.0, 0.1, 0.0, 0.0),
    "toms": (-20.0, 0.3, 0.0, 0.0),
    "riser": (-26.0, 0.3, 0.0, 0.0),
    "impact": (-18.0, 0.4, 0.0, 0.0),
    "crash": (-33.0, 0.15, 0.0, 0.0),
}

HOOK_STEPS = [0, 3, 6, 8, 11, 14]  # 16ths: 3-3-2-3-3-2, the tresillo twice
HOOK_A = [1, 0, 1, 2, 1, 0]  # chord-tone ladder steps above the bar's base note
HOOK_B = [1, 0, 1, 2, 3, 2]  # second bar of each pair lifts at the end
HOOK_VEL = [1.0, 0.78, 0.86, 0.95, 0.8, 0.84]
LEAD_A = [(0, 0.5, 0), (0.75, 0.5, 1), (1.5, 1.0, 2), (2.5, 0.5, None), (3.0, 0.75, 1)]  # None = passing tone
LEAD_B = [(0, 0.5, 0), (0.75, 0.5, 1), (1.5, 1.0, 2), (2.5, 0.5, None), (3.0, 1.0, 0)]
BASS_OFF = [(2, 2, 0), (6, 2, 0), (10, 2, 0), (14, 2, 12)]  # (16th, length in 16ths, interval)
BASS_TRES = [(0, 3, 0), (3, 3, 0), (6, 2, 12), (8, 3, 0), (11, 3, 7), (14, 2, 12)]
SHAKE_ACC = [0.55, 0.38, 1.0, 0.45]
TRI_ACC = [0.8, 0.45, 1.0, 0.5]  # forró triangle: closed, closed, OPEN, closed
PAD_CUT = {1: 1300, 2: 1700, 3: 2300, 4: 3200}


# ---------------------------------------------------------------- helpers

def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def taxis(dur):
    return np.arange(int(round(dur * SR))) / SR


def noise(n, seed):
    return np.random.default_rng(seed).standard_normal(n)


def lp(fc, order=2):
    return lambda f: 1 / np.sqrt(1 + (f / fc) ** (2 * order))


def hp(fc, order=2):
    return lambda f: 1 / np.sqrt(1 + (fc / np.maximum(f, 1e-3)) ** (2 * order))


def bp(lo, hi, order=2):
    return lambda f: lp(hi, order)(f) * hp(lo, order)(f)


def filt(x, resp):
    """Zero-phase FFT filter. It is circular, which is exactly right for a whole loop.
    One-shots filter their noise source before the envelope, so nothing wraps."""
    h = resp(np.fft.rfftfreq(len(x), 1 / SR))
    return np.fft.irfft(np.fft.rfft(x, axis=0) * (h[:, None] if x.ndim == 2 else h), len(x), axis=0)


def fade_end(x, dur=0.015):
    x = np.array(x, dtype=float)
    n = min(len(x), int(dur * SR))
    w = np.cos(np.linspace(0, np.pi / 2, n))
    x[len(x) - n:] *= w[:, None] if x.ndim == 2 else w
    return x


def pan(x, p):
    """Constant-power pan of a mono signal (p in -1..1), unity in each channel at center."""
    a = (p + 1) * np.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)], 1) * np.sqrt(2)


def active_rms_db(x):
    """RMS over the 50 ms blocks where the stem is actually playing (within 30 dB of its peak)."""
    p = (x ** 2).mean(1)
    blk = int(0.05 * SR)
    nb = len(p) // blk
    b = p[: nb * blk].reshape(nb, blk).mean(1)
    act = b[b >= b.max() * 1e-3]
    return 10 * np.log10(act.mean() + 1e-20)


# ---------------------------------------------------------------- harmony

def parse_key(s):
    m = re.fullmatch(r"([A-G])([#b]?)(m|min|minor|maj|major)?", s.strip())
    if not m:
        sys.exit(f"can't read key '{s}' (try F, Dm, Bb, F#m)")
    tonic = (LETTER[m.group(1)] + ACC[m.group(2)]) % 12
    minor = m.group(3) in ("m", "min", "minor")
    return tonic, minor, [(tonic + i) % 12 for i in (MINOR if minor else MAJOR)]


def parse_chord(tok, scale):
    m = re.fullmatch(r"([b#]?)(VII|VI|IV|V|III|II|I|vii|vi|iv|v|iii|ii|i)(°|o|dim|\+|aug)?(7|maj7|sus2|sus4)?", tok)
    if m:
        acc, rn, q, ext = m.groups()
        root = (scale[ROMAN.index(rn.lower())] + ACC[acc]) % 12
        minor = rn.islower()
    else:
        m = re.fullmatch(r"([A-G])([#b]?)(m(?!aj)|min)?(°|dim|\+|aug)?(7|maj7|sus2|sus4)?", tok)
        if not m:
            sys.exit(f"can't read chord '{tok}' (use roman numerals like vi IV I V, or names like Dm Bb F C)")
        root = (LETTER[m.group(1)] + ACC[m.group(2)]) % 12
        minor, q, ext = bool(m.group(3)), m.group(4), m.group(5)
    ivs = [0, 3 if minor else 4, 7]
    if q in ("°", "o", "dim"):
        ivs = [0, 3, 6]
    elif q in ("+", "aug"):
        ivs = [0, 4, 8]
    if ext == "sus2":
        ivs = [0, 2, 7]
    elif ext == "sus4":
        ivs = [0, 5, 7]
    elif ext == "7":
        ivs.append(9 if q in ("°", "o", "dim") else 10)
    elif ext == "maj7":
        ivs.append(11)
    return {"name": tok, "root": root, "pcs": [(root + i) % 12 for i in ivs]}


def chord_name(ch):
    r, ivs = ch["pcs"][0], [(p - ch["pcs"][0]) % 12 for p in ch["pcs"]]
    q = {(0, 4, 7): "", (0, 3, 7): "m", (0, 3, 6): "dim", (0, 4, 8): "aug", (0, 2, 7): "sus2", (0, 5, 7): "sus4"}
    base = q.get(tuple(ivs[:3]), "?") + {10: "7", 9: "7", 11: "maj7"}.get(ivs[3] if len(ivs) > 3 else -1, "")
    return ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"][r] + base


def default_chords(bars, minor, drop_bar):
    cyc = ["i", "VI", "III", "VII"] if minor else ["vi", "IV", "I", "V"]
    out = [cyc[i % 4] for i in range(bars)]
    if drop_bar is not None and drop_bar >= 1:
        out[drop_bar - 1] = f"{cyc[1]}|{cyc[3]}"  # IV|V lifts into the drop
        for k, i in enumerate(range(drop_bar, bars)):
            out[i] = cyc[k % 4]  # the drop restarts the progression on vi
    if bars >= 3 and (drop_bar is None or drop_bar < bars - 1) and cyc[3] not in out[-1]:
        out[-1] = f"{cyc[2]}|{cyc[3]}"  # I|V turns around into the seam
    return out


def default_energy(bars):
    d = max(1, round(0.6 * bars))
    return [2 if i < 2 else 3 if i < d else 4 if i < bars - 1 else 3 for i in range(bars)]


def ladder(pcs, lo=28, hi=100):
    return [m for m in range(lo, hi) if m % 12 in pcs]


def pick(lad, anchor, prev):
    """Index of the chord tone near the register anchor, pulled toward the previous base."""
    return min(range(len(lad)), key=lambda i: abs(lad[i] - anchor) + 0.5 * abs(lad[i] - prev))


def step_below(m, scale):
    m -= 1
    while m % 12 not in scale:
        m -= 1
    return m


# ---------------------------------------------------------------- instruments

def kick():
    t = taxis(0.5)
    f = 50 + 95 * np.exp(-t / 0.03) + 150 * np.exp(-t / 0.0035)
    env = (1 - np.exp(-t / 0.0008)) * np.exp(-t / 0.16)
    body = np.tanh(1.8 * np.sin(2 * np.pi * np.cumsum(f) / SR) * env) / np.tanh(1.8)
    click = 0.22 * filt(noise(len(t), 11), bp(1500, 7000)) * np.exp(-t / 0.0012)
    return fade_end(body + click)


def snap(seed=0):
    t = taxis(0.3)
    crack = filt(noise(len(t), 30 + seed), bp(1200, 5000)) * np.exp(-t / 0.007)
    body = 0.3 * np.sin(2 * np.pi * (1050 + 60 * seed) * t) * np.exp(-t / 0.012)
    skin = 0.1 * filt(noise(len(t), 40 + seed), bp(2000, 7000)) * np.exp(-t / 0.035)
    return fade_end((crack + body + skin) * (1 - np.exp(-t / 0.0004)))


def clap(seed=0):
    t = taxis(0.35)
    src = filt(noise(len(t), 50 + seed), bp(900, 5500))
    x = np.zeros(len(t))
    for k, d in enumerate((0.0, 0.009, 0.019, 0.027)):
        i = int(d * SR)
        x[i:] += src[i:] * np.exp(-t[: len(t) - i] / (0.004 if k < 3 else 0.055)) * (0.8 if k < 3 else 1.0)
    return fade_end(x)


def snare(seed=0):
    t = taxis(0.3)
    body = 0.5 * np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.05) + 0.25 * np.sin(2 * np.pi * 330 * t) * np.exp(-t / 0.03)
    wires = filt(noise(len(t), 120 + seed), bp(1200, 6500)) * np.exp(-t / 0.07)
    return fade_end((body + wires) * (1 - np.exp(-t / 0.0006)))


def shaker(seed=0):
    t = taxis(0.12)
    src = filt(noise(len(t), 60 + seed), bp(3000, 8000))
    env = np.where(t < 0.012, np.sin(np.pi / 2 * t / 0.012) ** 2, np.exp(-(t - 0.012) / 0.028))
    return fade_end(src * env)


def triangle(open_, seed=0):
    """A struck steel triangle: inharmonic partials over a bright strike. Closed = muted by the hand."""
    t = taxis(0.9 if open_ else 0.07)
    rng = np.random.default_rng(70 + seed)
    x = np.zeros(len(t))
    for k, (r, a) in enumerate([(1.0, 1.0), (2.49, 0.55), (2.97, 0.4), (4.12, 0.5), (5.43, 0.3),
                                (6.31, 0.25), (7.89, 0.18), (9.34, 0.12)]):
        tau = (0.55 if open_ else 0.018) / (1 + 0.3 * k)
        x += a * np.sin(2 * np.pi * 1320 * r * (1 + rng.uniform(-2e-3, 2e-3)) * t + rng.uniform(0, 2 * np.pi)) * np.exp(-t / tau)
    x *= 1 - np.exp(-t / 0.0005)
    x += 0.3 * filt(noise(len(t), 80 + seed), bp(4000, 14000)) * np.exp(-t / 0.0015)
    return fade_end(x, 0.01)


def open_hat(seed=0):
    t = taxis(0.3)
    return fade_end(filt(noise(len(t), 90 + seed), bp(7000, 15000)) * np.exp(-t / 0.07) * (1 - np.exp(-t / 0.001)))


def tom(f0, seed=0):
    t = taxis(0.4)
    f = f0 * (1 + 0.5 * np.exp(-t / 0.025))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.16) * (1 - np.exp(-t / 0.001))
    x = np.tanh(1.5 * x) / np.tanh(1.5)
    return fade_end(x + 0.25 * filt(noise(len(t), 95 + seed), bp(300, 4000)) * np.exp(-t / 0.008))


def crash(seed=0, dur=2.2, tau=0.6):
    t = taxis(dur)
    x = np.stack([filt(noise(len(t), 500 + seed + c), bp(3000, 12000, 1)) for c in range(2)], 1)
    return fade_end(x * (np.exp(-t / tau) * (1 - np.exp(-t / 0.0015)))[:, None], 0.1)


def impact():
    t = taxis(2.0)
    f = 34 + 60 * np.exp(-t / 0.07)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.5) * (1 - np.exp(-t / 0.002))
    return fade_end(np.tanh(1.6 * boom) / np.tanh(1.6), 0.1)


def riser(dur, seed=0):
    """Noise swept up through a moving band (short-time FFT) plus a rising tone, swelling to the drop."""
    n = int(dur * SR)
    nfft, hop = 2048, 256
    src = noise(n + nfft, 400 + seed)
    out = np.zeros(n + nfft)
    win = np.hanning(nfft)
    freqs = np.fft.rfftfreq(nfft, 1 / SR)
    for i in range(0, n, hop):
        fc = 350 * (7000 / 350) ** ((i / n) ** 1.3)
        h = np.exp(-0.5 * (np.log2((freqs + 1) / fc) / 0.8) ** 2)
        out[i:i + nfft] += np.fft.irfft(np.fft.rfft(src[i:i + nfft] * win) * h, nfft) * win
    u = np.arange(n) / n
    x = out[:n] / (np.abs(out[:n]).max() + 1e-12) * u ** 2
    x += 0.25 * np.sin(2 * np.pi * np.cumsum(180 * 4 ** (u ** 1.5)) / SR) * u ** 2.5
    k = int(0.02 * SR)
    x[-k:] *= np.linspace(1, 0, k)
    return x


def marimba(m, vel=1.0):
    """Tuned bar: fundamental, the 4th partial (two octaves up) and the ~10th, over a mallet knock."""
    f = hz(m)
    t = taxis(1.4)
    tau = float(np.clip(0.5 * (440 / f) ** 0.6, 0.12, 0.9))
    x = np.sin(2 * np.pi * f * t) * np.exp(-t / tau)
    x += 0.45 * vel * np.sin(2 * np.pi * 3.98 * f * t + 0.3) * np.exp(-t / (tau * 0.16))
    if 9.8 * f < 16000:
        x += 0.09 * vel * np.sin(2 * np.pi * 9.8 * f * t + 1.1) * np.exp(-t / (tau * 0.06))
    x *= 1 - np.exp(-t / 0.0008)
    x += 0.18 * vel * filt(noise(len(t), int(m)), bp(500, 4000)) * np.exp(-t / 0.0025)
    return fade_end(x * vel, 0.05)


def bass_note(m, dur, bright=0.5):
    """Sine sub with a plucked, saturated top so it still reads on phone speakers."""
    f = hz(m)
    t = taxis(dur + 0.06)
    ph = 2 * np.pi * f * t
    x = np.sin(ph) + 0.25 * np.sin(2 * ph + 0.2)
    x += bright * 0.35 * sum(np.sin(k * ph) / k for k in range(2, 12) if k * f < 2500) * np.exp(-t / 0.12)
    x = np.tanh(1.6 * x) / np.tanh(1.6)
    amp = (1 - np.exp(-t / 0.003)) * (0.55 + 0.45 * np.exp(-t / 0.18)) * np.clip((dur + 0.06 - t) / 0.06, 0, 1)
    return x * amp


def wavetable(f, cutoff, size=4096):
    k = np.arange(1, max(2, int(min(cutoff * 3, 18000) / f)) + 1)
    g = (1 / k) / np.sqrt(1 + (k * f / cutoff) ** 4)
    return (g[:, None] * np.sin(np.outer(k, 2 * np.pi * np.arange(size) / size))).sum(0)


def pad_chord(notes, dur, cutoff, rng):
    """Three detuned band-limited saws per note, spread across the stereo field."""
    t = taxis(dur + 0.4)
    n = len(t)
    x = np.zeros((n, 2))
    for m in notes:
        tab = wavetable(hz(m), cutoff)
        for cents, p in ((-9, -0.6), (0, 0.0), (9, 0.6)):
            f = hz(m) * 2 ** (cents / 1200)
            pos = (rng.random() + f / SR * np.arange(n)) % 1 * len(tab)
            i = pos.astype(int)
            fr = pos - i
            x += pan(tab[i] * (1 - fr) + tab[(i + 1) % len(tab)] * fr, p)
    att = np.minimum(1, t / 0.08)
    env = att * att * (3 - 2 * att) * np.clip((dur + 0.4 - t) / 0.4, 0, 1) ** 2
    return x * env[:, None]


def flute_line(notes, spb, n_total, seed=0):
    """One breathy pan-flute voice: slides into legato notes, a chiff on fresh attacks, late vibrato."""
    f = np.full(n_total, np.nan)
    a = np.zeros(n_total)
    rel, att, glide = int(0.08 * SR), int(0.03 * SR), int(0.05 * SR)
    prev_end, prev_f, chiffs = -10 ** 9, None, []
    for beat, dur, m in sorted(notes):
        s, e = int(round(beat * spb)), int(round((beat + dur) * spb))
        F, idx = hz(m), np.arange(e - s)
        legato = prev_f is not None and s - prev_end < int(0.06 * SR)
        if legato:
            g = np.minimum(1, idx / glide)
            fr = prev_f * (F / prev_f) ** (g * g * (3 - 2 * g))
            env = 1 - 0.18 * np.exp(-idx / (0.02 * SR))
        else:
            g = np.minimum(1, idx / (0.04 * SR))
            fr = F * 2 ** (-0.6 / 12 * (1 - g))  # breathy scoop up from 60 cents flat
            env = np.minimum(1, idx / att) ** 1.5
            chiffs.append(s)
        tv = idx / SR
        fr = fr * (1 + 0.0045 * np.clip((tv - 0.18) / 0.25, 0, 1) * np.sin(2 * np.pi * 5.4 * tv))
        f[s:e], a[s:e] = fr, env
        r = min(rel, n_total - e)
        a[e:e + r] = np.cos(np.pi / 2 * np.arange(r) / rel)
        f[e:e + r] = F
        prev_end, prev_f = e, F
    ph = 2 * np.pi * np.cumsum(np.nan_to_num(f, nan=440.0)) / SR
    tone = np.sin(ph) + 0.24 * np.sin(2 * ph + 0.5) + 0.07 * np.sin(3 * ph + 1.3)
    breath = filt(noise(n_total, 300 + seed), bp(1200, 7000)) * (0.1 + 0.05 * np.sin(ph))
    x = (tone + breath) * a
    for s in chiffs:
        n = min(int(0.035 * SR), n_total - s)
        x[s:s + n] += 0.35 * filt(noise(n, s % 997), bp(1500, 8000)) * np.exp(-np.arange(n) / (0.008 * SR))
    return np.tanh(1.3 * x) / np.tanh(1.3)


# ---------------------------------------------------------------- effects (all periodic)

def echo(x, d, fb=0.36, taps=7, lpf=3500):
    """Ping-pong echo on the circle: taps alternate left and right and get darker."""
    m = x.mean(1)
    y = np.zeros_like(x)
    for k in range(1, taps + 1):
        y[:, (k - 1) % 2] += fb ** (k - 1) * np.roll(m, k * d)
    return filt(y, lp(lpf))


def reverb_ir(seed=7, rt60=1.7, pre=0.014):
    n = int(rt60 * 1.2 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    ir = np.zeros((n, 2))
    for c in range(2):
        z = rng.standard_normal(n)
        dec = [np.exp(-6.91 * t / (rt60 * k)) for k in (1.15, 1.0, 0.45)]  # highs die first
        ir[:, c] = filt(z, lp(500)) * dec[0] + filt(z, bp(500, 4000)) * dec[1] + 0.7 * filt(z, hp(4000)) * dec[2]
    ir *= (1 - np.exp(-t / 0.015))[:, None]
    ir = np.concatenate([np.zeros((int(pre * SR), 2)), ir])
    return ir / np.sqrt((ir ** 2).sum(0).mean())


def convolve_loop(x, ir):
    """Circular convolution: the loop's reverb with its tail folded onto the start."""
    N = len(x)
    if len(ir) > N:
        ir = np.stack([np.bincount(np.arange(len(ir)) % N, weights=ir[:, c], minlength=N) for c in range(2)], 1)
    return np.fft.irfft(np.fft.rfft(x, axis=0) * np.fft.rfft(ir, n=N, axis=0), N, axis=0)


def duck_shape(N, starts, release):
    """0..1 envelope that dips on every kick (3 ms lead-in, 8 ms hold, cosine recovery)."""
    pre, hold, r = int(0.003 * SR), int(0.008 * SR), int(release * SR)
    curve = np.concatenate([np.sin(np.linspace(0, np.pi / 2, pre, endpoint=False)) ** 2, np.ones(hold),
                            0.5 * (1 + np.cos(np.linspace(0, np.pi, r)))])
    env = np.zeros(N)
    for s in starts:
        idx = (s - pre + np.arange(len(curve))) % N
        env[idx] = np.maximum(env[idx], curve)
    return env


def glue(x, thr_db=-16.0, ratio=2.0, att=0.012, rel=0.18):
    """Gentle bus compression. The smoother runs two laps so its state wraps around the loop."""
    N = len(x)
    nb = max(1, N // 240)
    p = (x ** 2).mean(1)
    lv = 10 * np.log10(np.array([c.mean() for c in np.array_split(p, nb)]) + 1e-12)
    want = np.maximum(0.0, lv - thr_db) * (1 - 1 / ratio)
    dt = N / nb / SR
    aa, ar = np.exp(-dt / att), np.exp(-dt / rel)
    g, out = 0.0, np.zeros(nb)
    for _ in range(2):
        for i in range(nb):
            c = aa if want[i] > g else ar
            g = c * g + (1 - c) * want[i]
            out[i] = g
    gr = np.interp(np.arange(N), (np.arange(nb) + 0.5) * N / nb, out, period=N)
    return x * (10 ** (-gr / 20))[:, None]


# ---------------------------------------------------------------- arrangement

class Loop:
    def __init__(self, bpm, bars):
        self.spb = 60.0 / bpm * SR
        self.N = int(round(bars * 4 * self.spb))
        self.stems = {}

    def add(self, stem, x, beat, gain=1.0, p=0.0):
        """Place a sound at a beat. Whatever runs past the end wraps onto the start."""
        buf = self.stems.setdefault(stem, np.zeros((self.N, 2)))
        x = np.asarray(x, dtype=float)
        x = (pan(x, p) if x.ndim == 1 else x) * gain
        s, i = int(round(beat * self.spb)) % self.N, 0
        while i < len(x):
            m = min(len(x) - i, self.N - s)
            buf[s:s + m] += x[i:i + m]
            i, s = i + m, 0


def compose(bpm, bars, key, tokens, energy, drop, build, fill, seed):
    tonic, minor, scale = key
    L = Loop(bpm, bars)
    rng = np.random.default_rng(seed)
    nb = bars * 4
    last = nb - 1
    spans = []
    for i in range(bars):
        parts = tokens[i % len(tokens)].split("|")
        w = 4 / len(parts)
        spans += [(4 * i + j * w, 4 * i + (j + 1) * w, parse_chord(p, scale)) for j, p in enumerate(parts)]

    def span_of(beat):
        return next(k for k, s in enumerate(spans) if s[0] <= beat % nb < s[1])

    def E(beat):
        return energy[int(beat // 4) % bars]

    def in_gap(beat):
        return drop is not None and drop - min(2, build) <= beat < drop

    def in_build(beat):
        return drop is not None and drop - build <= beat < drop

    # drums
    K, SN, CL = kick(), [snap(i) for i in range(3)], [clap(i) for i in range(2)]
    SH, TO, TC, OH = [shaker(i) for i in range(4)], triangle(True), triangle(False), open_hat()
    kicks = []
    for b in range(nb):
        e = E(b)
        fill_beat = fill and b == last
        if e >= 2 and not in_gap(b) and not fill_beat:
            L.add("kick", K, b)
            kicks.append(b)
        if b % 4 in (1, 3) and not in_build(b) and not fill_beat:
            L.add("snap", SN[b % 3], b, 0.94 + 0.06 * rng.random(), p=0.05)
            if e >= 4:
                L.add("clap", CL[b % 2], b)
        for k in range(4):
            pos = b + k / 4 + (0.025 if k % 2 else 0)  # a touch of swing on the off-16ths
            L.add("shaker", SH[(4 * b + k) % 4], pos, SHAKE_ACC[k] * (0.65 if e == 1 else 1) * (0.9 + 0.1 * rng.random()), p=0.35)
            if e >= 3 and not fill_beat:
                L.add("triangle", TO if k == 2 else TC, pos, TRI_ACC[k] * (0.9 + 0.1 * rng.random()), p=-0.3)
        if e >= 4:
            L.add("openhat", OH, b + 0.5, p=0.15)

    # build, drop, fill
    if drop is not None:
        if build > 0:
            b0, t = drop - build, drop - build
            SR_ = [snare(i) for i in range(2)]
            while t < drop - 1e-9:
                L.add("roll", SR_[int(t * 4) % 2], t, 0.2 + 0.8 * ((t - b0) / build) ** 1.6, p=0.1)
                t += 0.5 if t < drop - build / 2 else 0.25
            L.add("riser", riser(build * L.spb / SR, seed), b0)
        L.add("impact", impact(), drop)
        L.add("crash", crash(seed), drop)
    if fill:
        root = 41 + (tonic - 41) % 12  # tonic in octave 2
        for k, iv in enumerate((19, 12 + (3 if minor else 4), 12, 7)):  # 5th, 3rd, root, 5th below
            L.add("toms", tom(hz(root + iv), k), last + k / 4, 0.8 + 0.07 * k, p=0.4 - 0.25 * k)
        L.add("crash", crash(seed + 1) * 0.5, 0)

    # marimba hook on chord tones, voice-led around A4
    bases, prev = [], 69
    for s0, s1, ch in spans:
        lad = ladder(ch["pcs"])
        k = pick(lad, 69, prev)
        bases.append((lad, k))
        prev = lad[k]
    for b in range(bars):
        tpl = HOOK_A if b % 2 == 0 else HOOK_B
        for step, rel, vel in zip(HOOK_STEPS, tpl, HOOK_VEL):
            beat = 4 * b + step / 4
            lad, k = bases[span_of(beat)]
            v = vel * (0.85 if E(beat) == 1 else 0.93 if E(beat) == 2 else 1.0)
            L.add("marimba", marimba(lad[k + rel], v), beat, p=-0.1)

    # bass
    for b in range(bars):
        if energy[b] < 2:
            continue
        for step, dur, iv in (BASS_TRES if energy[b] >= 3 else BASS_OFF):
            beat = 4 * b + step / 4
            if in_gap(beat):
                continue
            root = 34 + (spans[span_of(beat)][2]["root"] - 34) % 12  # Bb1..A2
            L.add("bass", bass_note(root + iv, dur / 4 * L.spb / SR * 0.92, 0.35 + 0.1 * energy[b]), beat)

    # pad: close voicings, each chord moving as little as possible
    prev_v = [57, 60, 64]
    for s0, s1, ch in spans:
        lad = ladder(ch["pcs"], 48, 84)
        v = min((lad[i:i + 3] for i in range(len(lad) - 2) if 52 <= lad[i] <= 64),
                key=lambda c: sum(abs(x - y) for x, y in zip(c, prev_v)))
        prev_v = v
        e = E(s0)
        L.add("pad", pad_chord(v + ([v[0] + 12] if e >= 4 else []), (s1 - s0) * L.spb / SR, PAD_CUT[e], rng), s0,
              1.0 if e == 1 else 0.85)

    # pan-flute lead on the energy-4 bars, voice-led around D5
    lead, n_lead, prev = [], 0, 74
    lbases = []
    for s0, s1, ch in spans:
        lad = ladder(ch["pcs"])
        k = pick(lad, 74, prev)
        lbases.append((lad, k))
        prev = lad[k]
    for b in range(bars):
        if energy[b] < 4:
            n_lead = 0
            continue
        tpl = LEAD_A if n_lead % 2 == 0 else LEAD_B
        n_lead += 1
        m = None
        for off, dur, rel in tpl:
            beat = 4 * b + off
            lad, k = lbases[span_of(beat)]
            m = step_below(m, scale) if rel is None else lad[k + rel]
            lead.append((beat, dur, m))
    if lead:
        L.add("lead", flute_line(lead, L.spb, L.N + int(0.5 * SR), seed), 0)

    duck_at = kicks + ([drop] if drop is not None and drop not in kicks else [])
    return L, spans, [int(round(b * L.spb)) for b in duck_at]


def mixdown(L, kick_samples, bpm):
    N = L.N
    duck = duck_shape(N, kick_samples, release=0.55 * 60 / bpm)
    bus, rev_in, echo_in = np.zeros((N, 2)), np.zeros((N, 2)), np.zeros((N, 2))
    levels = {}
    for name, x in L.stems.items():
        level, rs, es, dk = MIX[name]
        x = x * 10 ** ((level - active_rms_db(x)) / 20)
        if dk:
            x = x * (1 - dk * duck)[:, None]
        L.stems[name] = x
        levels[name] = level
        bus += x
        rev_in += rs * x
        echo_in += es * x
    ech = echo(echo_in, int(round(0.75 * L.spb)))
    wet = convolve_loop(filt(rev_in + 0.35 * ech, bp(250, 9000)), reverb_ir()) * (1 - 0.35 * duck)[:, None]
    L.stems["fx_echo"], L.stems["fx_reverb"] = ech, 0.55 * wet
    bus += ech + 0.55 * wet
    bus = glue(filt(bus, hp(38)))
    bus /= np.abs(bus).max()
    bus = np.tanh(1.4 * bus) / np.tanh(1.4)
    return bus * 10 ** (-1 / 20) / np.abs(bus).max(), levels


def band_report(x):
    X = np.abs(np.fft.rfft(x.mean(1))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    edges = [20, 60, 150, 400, 1000, 2500, 6000, 16000]
    tot = X.sum()
    return [(lo, hi, 10 * np.log10(X[(f >= lo) & (f < hi)].sum() / tot + 1e-20)) for lo, hi in zip(edges, edges[1:])]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--bpm", type=float, default=120)
    ap.add_argument("--bars", type=int, default=8)
    ap.add_argument("--key", default="F")
    ap.add_argument("--chords", default=None)
    ap.add_argument("--energy", default=None, help="comma list, one per bar (1-4)")
    ap.add_argument("--drop", default="auto", help="auto, none, or the beat of the impact")
    ap.add_argument("--build", type=float, default=4, help="beats of riser and roll before the drop")
    ap.add_argument("--no-fill", action="store_true", help="no tom fill into the seam")
    ap.add_argument("--loops", type=int, default=3, help="copies in OUT.wav (render uses the second)")
    ap.add_argument("--stems", default=None, help="also write each stem (one loop) to this folder")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    key = parse_key(a.key)
    energy = [int(v) for v in a.energy.split(",")] if a.energy else default_energy(a.bars)
    if any(e not in (1, 2, 3, 4) for e in energy):
        sys.exit("--energy values are 1-4")
    energy = (energy + [energy[-1]] * a.bars)[: a.bars]
    if a.drop == "none":
        drop = None
    elif a.drop == "auto":
        drop = next((4 * i for i in range(1, a.bars) if energy[i] == 4 and energy[i - 1] < 4), None)
    else:
        drop = float(a.drop)
        if not 0 <= drop < a.bars * 4 or drop * 4 != int(drop * 4):
            sys.exit("--drop must be a beat inside the loop, on a 16th")
    build = max(0.0, min(a.build, drop)) if drop is not None else 0.0
    tokens = a.chords.replace(",", " ").split() if a.chords else default_chords(
        a.bars, key[1], int(drop // 4) if drop is not None else None)

    L, spans, kick_samples = compose(a.bpm, a.bars, key, tokens, energy, drop, build, not a.no_fill, a.seed)
    loop, levels = mixdown(L, kick_samples, a.bpm)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_wav(out, np.tile(loop, (max(1, a.loops), 1)), SR)
    if a.stems:
        d = Path(a.stems)
        d.mkdir(parents=True, exist_ok=True)
        for name, x in L.stems.items():
            write_wav(d / f"{name}.wav", np.clip(x, -1, 1), SR)

    T = L.N / SR
    beat = 60 / a.bpm
    nbt = a.bars * 4
    start = T if a.loops >= 2 else 0.0
    names = [tokens[i % len(tokens)] for i in range(a.bars)]
    chord_names = [chord_name(ch) for _, _, ch in spans]
    info = {
        "file": str(out.resolve()), "duration": round(T * a.loops, 6), "bpm": a.bpm, "period": beat,
        "first_beat": 0.0, "steady_tempo": True, "downbeat_phase": 0, "downbeat_confidence": 1.0,
        "beats": [round(i * beat, 6) for i in range(nbt * a.loops)],
        "downbeats": [round(i * 4 * beat, 6) for i in range(a.bars * a.loops)],
        "section": {"bars": a.bars, "start_bar": a.bars + 1 if a.loops >= 2 else 1, "start": start, "end": start + T,
                    "duration": T, "beats_rel": [round(i * beat, 6) for i in range(nbt + 1)],
                    "beat_strength": [1.0 if i % 4 == 0 else 0.7 for i in range(nbt)],
                    "xfade_beats": 0, "xfade_dip_db": 0.0},
        "composed": {"key": a.key, "chords": names, "chord_names": chord_names, "energy": energy,
                     "drop_beat": drop, "build_beats": build, "fill": not a.no_fill, "seed": a.seed,
                     "note": "original synthesized music, loop-perfect: section.start is a loop boundary"},
    }
    bj = out.with_suffix(".beats.json")
    bj.write_text(json.dumps(info, indent=1))

    rms = 10 * np.log10((loop ** 2).mean() + 1e-20)
    print(f"wrote {out} ({a.loops} × {T:.3f}s, {a.bpm:g} BPM, key {a.key}) and {bj.name}")
    print("  bars    " + " ".join(f"{i + 1:>6}" for i in range(a.bars)))
    print("  chords  " + " ".join(f"{c:>6}" for c in names))
    print("  energy  " + " ".join(f"{e:>6}" for e in energy))
    if drop is not None:
        print(f"  drop on beat {drop:g} (bar {int(drop // 4) + 1}.{int(drop % 4) + 1}), {build:g}-beat build before it")
    print(f"  master: peak -1.0 dBFS, RMS {rms:.1f} dBFS, crest {-1 - rms:.1f} dB")
    print("  spectrum: " + "  ".join(f"{lo}-{hi}Hz {db:.0f}dB" for lo, hi, db in band_report(loop)))
    print(f"  render: render.py PROJECT --song {out} --beats {bj}")


if __name__ == "__main__":
    main()
