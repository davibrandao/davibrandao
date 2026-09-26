#!/usr/bin/env python3
"""Beat grid for a song, with numpy only.

Finds the tempo, every beat, which beat is the downbeat, and the best downbeat to
start an N-bar loop on. Prints a summary and writes beats.json, which
new_project.py and mix_audio.py read.

usage: analyze_beats.py SONG [--bars 7] [--bpm-hint 120] [--start auto|SECONDS|bar:N]
                             [--downbeat-shift 0..3] [--out beats.json]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from common import decode_audio

SR = 22050
NFFT = 1024
HOP = 256
FPS = SR / HOP
# Spectral-flux onsets peak a little before the transient (the window sees it coming).
# Measured on synthetic tracks with a known grid; added back so visuals land on the hit.
ONSET_BIAS = 0.0083


# ----------------------------------------------------------------------------- features
def spectrogram(x):
    pad = np.concatenate([np.zeros(NFFT // 2, np.float32), x, np.zeros(NFFT, np.float32)])
    n = 1 + (len(pad) - NFFT) // HOP
    frames = np.lib.stride_tricks.as_strided(pad, shape=(n, NFFT), strides=(pad.strides[0] * HOP, pad.strides[0]))
    win = np.hanning(NFFT).astype(np.float32)
    out = np.empty((n, NFFT // 2 + 1), np.float32)
    for i in range(0, n, 4096):
        out[i:i + 4096] = np.abs(np.fft.rfft(frames[i:i + 4096] * win, axis=1))
    return out


def band_matrix(nbands=48, fmin=30.0, fmax=10000.0):
    freqs = np.fft.rfftfreq(NFFT, 1 / SR)
    edges = np.geomspace(fmin, fmax, nbands + 2)
    fb = np.zeros((len(freqs), nbands), np.float32)
    for b in range(nbands):
        lo, mid, hi = edges[b], edges[b + 1], edges[b + 2]
        up = (freqs - lo) / (mid - lo)
        down = (hi - freqs) / (hi - mid)
        fb[:, b] = np.clip(np.minimum(up, down), 0, None)
    fb /= np.maximum(fb.sum(0, keepdims=True), 1e-9)
    return fb, edges[1:-1]


def chroma_matrix():
    freqs = np.fft.rfftfreq(NFFT, 1 / SR)
    m = np.zeros((len(freqs), 12), np.float32)
    ok = (freqs > 80) & (freqs < 4000)
    pc = np.round(12 * np.log2(freqs[ok] / 440.0) + 69).astype(int) % 12
    m[np.where(ok)[0], pc] = 1
    return m


def moving_avg(x, w):
    w = max(1, int(w))
    k = np.ones(w) / w
    return np.convolve(np.pad(x, (w // 2, w - 1 - w // 2), mode="edge"), k, mode="valid")


def normalize_env(d):
    e = d - moving_avg(d, 0.4 * FPS)
    e = np.maximum(e, 0)
    return e / (e.std() + 1e-9)


def flux(L, sel):
    d = np.maximum(0, L[1:, sel] - L[:-1, sel]).sum(1)
    return np.concatenate([[0], d])


# ----------------------------------------------------------------------------- tempo & beats
def tempo_autocorr(env, hint, lo=60, hi=200):
    e = env - env.mean()
    n = len(e)
    ac = np.fft.irfft(np.abs(np.fft.rfft(e, 2 * n)) ** 2)[:n]
    lags = np.arange(1, n)
    bpm = 60 * FPS / lags
    ok = (bpm >= lo) & (bpm <= hi)
    prior = np.exp(-0.5 * (np.log2(bpm / hint) / 0.4) ** 2)
    score = np.where(ok, ac[1:] * prior, -np.inf)
    i = int(np.argmax(score))
    lag = lags[i]
    if 0 < i < len(score) - 1 and np.isfinite(score[i - 1]) and np.isfinite(score[i + 1]):
        a, b, c = score[i - 1], score[i], score[i + 1]
        lag = lag + 0.5 * (a - c) / (a - 2 * b + c + 1e-12)
    return 60 * FPS / lag


def dp_beats(env, bpm, tightness=120):
    """Ellis (2007) dynamic-programming beat tracker."""
    period = 60 * FPS / bpm
    n = len(env)
    offs = np.arange(-int(round(2 * period)), -int(round(period / 2)) + 1)
    penalty = -tightness * np.log(-offs / period) ** 2
    score = np.zeros(n)
    back = -np.ones(n, int)
    local = env.astype(float)
    for i in range(n):
        idx = i + offs
        ok = idx >= 0
        if ok.any():
            cand = score[idx[ok]] + penalty[ok]
            j = int(np.argmax(cand))
            if cand[j] > 0:
                score[i] = local[i] + cand[j]
                back[i] = idx[ok][j]
                continue
        score[i] = local[i]
    # start from the best-scoring frame in the last period
    tail = np.arange(max(0, n - int(period) - 1), n)
    i = int(tail[np.argmax(score[tail])])
    beats = []
    while i >= 0:
        beats.append(i)
        i = back[i]
    return np.array(beats[::-1]) / FPS


def fit_grid(beats, bpm):
    """Robust linear fit t = t0 + k*P over tracked beats."""
    P = 60 / bpm
    t = np.asarray(beats)
    k = np.round((t - t[0]) / P)
    keep = np.ones(len(t), bool)
    for _ in range(4):
        A = np.stack([np.ones(keep.sum()), k[keep]], 1)
        (t0, P), *_ = np.linalg.lstsq(A, t[keep], rcond=None)
        res = t - (t0 + k * P)
        mad = np.median(np.abs(res[keep])) + 1e-4
        keep = np.abs(res) < max(0.03, 4 * mad)
        k = np.round((t - t0) / P)
    return t0, P, res[keep]


def refine_grid(env, t0, P, t_end, span=0.02, steps=41):
    """Maximize onset strength sampled on the grid (sub-frame, linear interpolation)."""
    n = len(env)
    best = (-1, t0, P)
    for dp in np.linspace(-0.002, 0.002, 21) * P:
        for dt in np.linspace(-span, span, steps):
            ts = np.arange(t0 + dt, t_end, P + dp)
            fr = ts * FPS
            fr = fr[(fr >= 0) & (fr < n - 1)]
            s = np.interp(fr, np.arange(n), env).mean()
            if s > best[0]:
                best = (s, t0 + dt, P + dp)
    return best[1], best[2]


def peak_align(env, grid, win=0.035):
    """Median offset between grid beats and the nearest onset peak (parabolic sub-frame)."""
    offs = []
    n = len(env)
    w = int(win * FPS)
    for t in grid:
        c = int(round(t * FPS))
        lo, hi = max(1, c - w), min(n - 2, c + w)
        if hi <= lo:
            continue
        i = lo + int(np.argmax(env[lo:hi + 1]))
        if env[i] < 1.0:
            continue
        a, b, cc = env[i - 1], env[i], env[i + 1]
        frac = 0.5 * (a - cc) / (a - 2 * b + cc + 1e-12)
        offs.append((i + frac) / FPS - t)
    return (float(np.median(offs)) if offs else 0.0), len(offs)


# ----------------------------------------------------------------------------- analysis
def analyze(path, bars=7, hint=120.0, start=None, shift=None):
    x = decode_audio(path, SR, 1)[:, 0]
    dur = len(x) / SR
    if dur < 10:
        sys.exit("song is shorter than 10 s")
    S = spectrogram(x)
    fb, centers = band_matrix()
    B = S @ fb
    L = np.log1p(B / (np.percentile(B, 99.5) + 1e-9) * 1000)
    env = normalize_env(flux(L, slice(None)))
    low = normalize_env(flux(L, centers < 160))
    mid = normalize_env(flux(L, (centers > 1000) & (centers < 5000)))
    chroma = (S ** 2) @ chroma_matrix()
    times = np.arange(len(env)) / FPS

    # tempo → DP beats → robust constant grid → refine on the onset envelope
    bpm0 = tempo_autocorr(env + 0.5 * low, hint)
    beats_dp = dp_beats(env + 0.5 * low, bpm0)
    t0, P, res = fit_grid(beats_dp, bpm0)
    t0 = t0 - np.floor(t0 / P) * P  # first beat at or after 0
    t0, P = refine_grid(env + 0.5 * low, t0, P, dur)
    # snap to a round tempo when that fits at least as well (DAW-made music is usually on a round BPM)
    bpm_fit = 60 / P
    for cand in (round(bpm_fit), round(bpm_fit * 2) / 2):
        if abs(cand - bpm_fit) < 0.12:
            Pc = 60 / cand
            t0c, Pc = refine_grid(env + 0.5 * low, t0, Pc, dur, span=0.01, steps=21)
            if abs(60 / Pc - cand) < 0.02:
                t0, P = t0c, 60 / cand
            break
    grid = np.arange(t0, dur - 0.05, P)
    off, npk = peak_align(env + 0.5 * low, grid)
    t0 += off + ONSET_BIAS
    grid = np.arange(t0 - np.floor(t0 / P) * P, dur - 0.05, P)
    t0 = grid[0]
    # how well do the DP beats agree with the constant grid?
    k = np.round((beats_dp + ONSET_BIAS - t0) / P)
    dev = np.abs(beats_dp + ONSET_BIAS - (t0 + k * P))
    steady = float(np.median(dev)) < 0.015

    # per-beat features for the downbeat phase
    def at_beats(sig, w=0.03):
        n = len(sig)
        v = []
        for t in grid:
            c = int(round(t * FPS)); r = int(w * FPS)
            v.append(sig[max(0, c - r):min(n, c + r + 1)].max() if c < n else 0)
        return np.array(v)

    fr = np.clip(np.round(grid * FPS).astype(int), 0, len(env) - 1)
    beat_chroma = np.array([chroma[fr[i]:fr[i + 1]].mean(0) if i + 1 < len(fr) else chroma[fr[i]:].mean(0) for i in range(len(fr))])
    bc = beat_chroma / (np.linalg.norm(beat_chroma, axis=1, keepdims=True) + 1e-9)
    nov = np.concatenate([[0], 1 - (bc[1:] * bc[:-1]).sum(1)])
    z = lambda v: (v - v.mean()) / (v.std() + 1e-9)  # noqa: E731
    f_nov, f_low, f_mid = z(nov), z(at_beats(low)), z(at_beats(mid))
    phase_scores = []
    for p in range(4):
        sel = np.arange(len(grid)) % 4 == p
        phase_scores.append(f_nov[sel].mean() + 0.4 * f_low[sel].mean() - 0.6 * f_mid[sel].mean())
    phase = int(np.argmax(phase_scores)) if shift is None else int(shift) % 4
    ps = sorted(phase_scores, reverse=True)
    confidence = float((ps[0] - ps[1]) / (np.std(phase_scores) + 1e-9))
    downbeats = grid[phase::4]

    # per-bar features for choosing where the loop starts
    rms_fr = np.sqrt(moving_avg((x[: len(x) // HOP * HOP].reshape(-1, HOP) ** 2).mean(1), 1))
    nb = len(downbeats) - 1
    bar_rms, bar_feat = [], []
    for i in range(nb):
        a, b = int(downbeats[i] * FPS), int(downbeats[i + 1] * FPS)
        bar_rms.append(rms_fr[a:b].mean() if b > a else 0)
        spec = L[a:b].mean(0)
        ch = chroma[a:b].mean(0)
        ch = ch / (np.linalg.norm(ch) + 1e-9)
        bar_feat.append(np.concatenate([spec / (np.linalg.norm(spec) + 1e-9), ch]))
    bar_rms = np.array(bar_rms)
    bar_feat = np.array(bar_feat)
    rms_n = bar_rms / (bar_rms.max() + 1e-9)
    cos = lambda a, b: float((a * b).sum() / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))  # noqa: E731

    def phrase_boundary(i):
        if i < 2 or i + 2 > nb:
            return 0.0
        before = bar_feat[max(0, i - 4):i].mean(0)
        after = bar_feat[i:min(nb, i + 4)].mean(0)
        return 1 - cos(before, after)

    bounds = np.array([phrase_boundary(i) for i in range(nb)])
    bounds_n = bounds / (bounds.max() + 1e-9)
    strongest = int(np.argmax(bounds))
    cands = []
    for i in range(1, nb - bars + 1):
        sec = rms_n[i:i + bars]
        energy = float(sec.mean())
        stability = float(1 - min(1, sec.std() / (sec.mean() + 1e-9) * 3))
        inner = max((1 - cos(bar_feat[j - 1], bar_feat[j]) for j in range(i + 1, i + bars)), default=0)
        inner_n = inner / (bounds.max() + 1e-9)
        loop_sim = cos(bar_feat[i - 1], bar_feat[i + bars - 1])
        on_phrase_grid = (i - strongest) % 4 == 0
        score = (0.35 * energy + 0.15 * stability + 0.15 * loop_sim + 0.45 * bounds_n[i]
                 - 0.3 * min(1.0, inner_n) + (0.1 if on_phrase_grid else 0))
        if i < 4:
            score -= 0.15
        cands.append({"bar": i + 1, "start": round(float(downbeats[i]), 4), "score": round(score, 4),
                      "energy": round(energy, 3), "stability": round(stability, 3), "loop_similarity": round(loop_sim, 3),
                      "phrase_boundary": round(float(bounds_n[i]), 3), "inner_change": round(float(inner_n), 3)})
    if not cands:
        sys.exit(f"song too short for a {bars}-bar loop at {60 / P:.1f} BPM")
    ranked = sorted(cands, key=lambda c: -c["score"])

    if start is None or start == "auto":
        chosen = ranked[0]
    elif str(start).startswith("bar:"):
        n = int(str(start)[4:])
        chosen = next((c for c in cands if c["bar"] == n), None) or sys.exit(f"bar {n} can't start a {bars}-bar loop")
    else:
        s = float(start)
        chosen = min(cands, key=lambda c: abs(c["start"] - s))

    s0 = chosen["start"]
    i0 = int(np.argmin(np.abs(grid - s0)))
    nbeats = bars * 4
    sec_beats = grid[i0:i0 + nbeats + 1]
    if len(sec_beats) < nbeats + 1:  # extrapolate the last beat if the song ends exactly there
        sec_beats = np.concatenate([sec_beats, sec_beats[-1] + P * np.arange(1, nbeats + 2 - len(sec_beats))])
    strength = at_beats(env + 0.5 * low)[i0:i0 + nbeats]
    strength = (strength / (strength.max() + 1e-9)).round(3)
    # the mixer crossfades the loop's last half beat with the half beat before the start:
    # how much quieter does that make the seam than the loop's own tail?
    hb = int(P / 2 * SR)
    s_i, e_i = int(sec_beats[0] * SR), int(sec_beats[-1] * SR)
    tail = x[max(0, e_i - hb):e_i]
    pre = x[max(0, s_i - hb):s_i]
    if len(pre) < len(tail):
        pre = np.concatenate([np.zeros(len(tail) - len(pre), np.float32), pre])
    u = np.linspace(0, 1, len(tail))
    xf = tail * np.cos(u * np.pi / 2) + pre[:len(tail)] * np.sin(u * np.pi / 2)
    rms = lambda v: float(np.sqrt(np.mean(np.square(v, dtype=np.float64))) + 1e-9)  # noqa: E731
    xfade_dip = round(20 * np.log10(rms(xf) / rms(tail)), 1)

    return {
        "file": str(path), "duration": round(dur, 3),
        "bpm": round(60 / P, 3), "period": round(P, 6), "first_beat": round(float(grid[0]), 4),
        "steady_tempo": steady, "grid_vs_tracked_ms": round(float(np.median(dev)) * 1000, 1),
        "peaks_aligned": npk,
        "downbeat_phase": phase, "downbeat_confidence": round(confidence, 2),
        "phase_scores": [round(float(v), 3) for v in phase_scores],
        "beats": [round(float(t), 4) for t in grid],
        "downbeats": [round(float(t), 4) for t in downbeats],
        "bar_energy": [round(float(v), 3) for v in rms_n],
        "candidates": ranked[:8],
        "section": {
            "bars": bars, "start_bar": chosen["bar"], "start": round(float(sec_beats[0]), 4),
            "end": round(float(sec_beats[-1]), 4), "duration": round(float(sec_beats[-1] - sec_beats[0]), 4),
            "beats_rel": [round(float(t - sec_beats[0]), 5) for t in sec_beats],
            "beat_strength": [float(v) for v in strength],
            "xfade_dip_db": xfade_dip,
        },
    }


def spark(v):
    ticks = "▁▂▃▄▅▆▇█"
    return "".join(ticks[min(7, int(x * 7.999))] for x in v)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("song")
    ap.add_argument("--bars", type=int, default=7)
    ap.add_argument("--bpm-hint", type=float, default=120)
    ap.add_argument("--start", default="auto", help="auto | seconds | bar:N (1-based bar of the song)")
    ap.add_argument("--downbeat-shift", type=int, default=None, help="force which beat phase is beat 1 (0-3)")
    ap.add_argument("--out", default="beats.json")
    a = ap.parse_args()

    r = analyze(a.song, a.bars, a.bpm_hint, a.start, a.downbeat_shift)
    Path(a.out).write_text(json.dumps(r, indent=1))
    s = r["section"]
    m, sec = divmod(r["duration"], 60)
    print(f"song      {Path(a.song).name}  ({int(m)}:{sec:04.1f})")
    print(f"tempo     {r['bpm']:.2f} BPM  (beat {r['period'] * 1000:.1f} ms, "
          f"{'steady' if r['steady_tempo'] else 'DRIFTING — check the grid'}; tracked beats sit "
          f"{r['grid_vs_tracked_ms']} ms from the grid)")
    print(f"downbeat  phase {r['downbeat_phase']} (confidence {r['downbeat_confidence']}; scores {r['phase_scores']})"
          f"{'  ← low confidence: confirm by ear or pass --downbeat-shift' if r['downbeat_confidence'] < 0.5 else ''}")
    print(f"bars      {spark(r['bar_energy'])}  (energy per bar)")
    print(f"loop      bar {s['start_bar']} @ {s['start']:.3f}s → {s['bars']} bars = {s['duration']:.3f}s "
          f"(ends {s['end']:.3f}s)")
    print("           beat strength: " + spark(s["beat_strength"]))
    dip = s["xfade_dip_db"]
    print(f"seam      the loop-crossfade half beat is {dip:+.1f} dB vs the loop's own tail"
          f"{'  ← audible dip: try another candidate, or mix with --xfade-beats 0.25' if dip < -6 else ' (fine)'}")
    print("candidates (bar, start, score, energy, loop-sim, boundary):")
    for c in r["candidates"][:5]:
        print(f"  bar {c['bar']:>3}  {c['start']:>8.3f}s  {c['score']:+.3f}  e={c['energy']:.2f} "
              f"loop={c['loop_similarity']:.2f} boundary={c['phrase_boundary']:.2f}")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
