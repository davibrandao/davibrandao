#!/usr/bin/env python3
"""Render the loop to MP4: Playwright screenshots of seek(t), 4 subframes per frame,
blended with ffmpeg tmix for motion blur, 60 fps, soundtrack muxed in.

Subframes are spread across a 180° shutter centred on each frame's time, so fast
morphs get a film-like smear while held states stay razor sharp. Workers render
contiguous frame ranges in parallel into lossless chunks, then one final encode.

usage: render.py PROJECT/index.html [--out loop.mp4]
                 [--song SONG --beats beats.json | --audio mix.wav]
                 [--fps 60] [--subframes 4] [--shutter 180] [--workers N] [--loops 1]
                 [--crf 14] [--scale 1.0] [--gif] [--preview]
--preview = 30 fps, 1 subframe, half size: a fast draft to check timing with sound.
"""
import argparse
import base64
import json
import multiprocessing as mp
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import SIZE, dump_json, ffmpeg_bin, launch_chromium, open_page, page_info, serve  # noqa: E402


def subframe_times(m, fps, S, shutter):
    if S == 1:
        return [m / fps]
    span = (shutter / 360.0) / fps
    return [m / fps + ((j + 0.5) / S - 0.5) * span for j in range(S)]


def render_chunk(job):
    from playwright.sync_api import sync_playwright

    url, f0, f1, fps, S, shutter, out, scale, wid = job
    ff = ffmpeg_bin()
    vf = f"tmix=frames={S},select='eq(mod(n\\,{S})\\,{S - 1})',setpts=N/({fps}*TB)" if S > 1 else "null"
    cmd = [ff, "-y", "-v", "error", "-f", "image2pipe", "-c:v", "png", "-framerate", str(fps * S), "-i", "-",
           "-vf", vf, "-r", str(fps), "-c:v", "libx264rgb", "-qp", "0", "-preset", "ultrafast", out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    clip = {"x": 0, "y": 0, "width": SIZE, "height": SIZE, "scale": scale}
    t_start = time.time()
    with sync_playwright() as p:
        browser = launch_chromium(p)
        page = open_page(browser, url, render=True)
        cdp = page.context.new_cdp_session(page)
        for m in range(f0, f1):
            for t in subframe_times(m, fps, S, shutter):
                page.evaluate("t => window.seek(t)", t)
                shot = cdp.send("Page.captureScreenshot", {"format": "png", "optimizeForSpeed": True, "clip": clip})
                proc.stdin.write(base64.b64decode(shot["data"]))
            done = m - f0 + 1
            if done % 60 == 0 or m == f1 - 1:
                rate = done / (time.time() - t_start)
                print(f"  worker {wid}: {done}/{f1 - f0} frames ({rate:.1f} fps)", flush=True)
        errors = getattr(page, "_mk_errors", [])
        browser.close()
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for chunk {wid}")
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html")
    ap.add_argument("--out", default=None)
    ap.add_argument("--song")
    ap.add_argument("--beats")
    ap.add_argument("--audio", help="pre-mixed WAV (skips mixing)")
    ap.add_argument("--sounds", help="UI sound folder (default PROJECT/sounds, generated if missing)")
    ap.add_argument("--ui-db", type=float, default=-8.0)
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--subframes", type=int, default=4)
    ap.add_argument("--shutter", type=float, default=180)
    ap.add_argument("--workers", type=int, default=max(1, min(6, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--loops", type=int, default=1, help="repeat the loop N times in the file")
    ap.add_argument("--crf", type=int, default=14)
    ap.add_argument("--scale", type=float, default=1.0, help="output scale (0.5 → 720px)")
    ap.add_argument("--gif", action="store_true", help="also write a 720px GIF")
    ap.add_argument("--preview", action="store_true", help="30 fps, no motion blur, half size")
    a = ap.parse_args()
    if a.preview:
        a.fps, a.subframes, a.scale = 30, 1, 0.5

    html = Path(a.html).resolve()
    if html.is_dir():
        html = html / "index.html"
    proj = html.parent
    out = Path(a.out).resolve() if a.out else proj / ("preview.mp4" if a.preview else "loop.mp4")
    httpd, base = serve(proj)
    url = f"{base}/{html.name}"

    # page info + cues (one throwaway browser)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = launch_chromium(p)
        info = page_info(open_page(b, url, render=True))
        b.close()
    T = info["T"]
    N = int(round(T * a.fps))
    cues_path = proj / "cues.json"
    dump_json(cues_path, {"T": T, "fps": a.fps, "frames": N, "cues": info["cues"]})
    print(f"loop {T:.3f}s @ {info['bpm']:.2f} BPM → {N} frames × {a.subframes} subframes, {a.workers} workers")

    # soundtrack
    audio = Path(a.audio).resolve() if a.audio else None
    if not audio and a.song and a.beats:
        import mix_audio

        sounds = Path(a.sounds) if a.sounds else proj / "sounds"
        if not (sounds / "click.wav").exists() and not a.sounds:
            subprocess.run([sys.executable, str(Path(__file__).parent / "ui_sounds.py"), str(sounds)], check=True)
        beats = json.loads(Path(a.beats).read_text())
        audio = proj / "mix.wav"
        placed, _ = mix_audio.mix(a.song, beats["section"], info["cues"], audio, int(round(N / a.fps * 48000)),
                                  str(sounds), a.ui_db)
        print(f"mixed {audio.name}: song from {beats['section']['start']:.3f}s + {len(placed)} UI sounds")

    # frames
    t0 = time.time()
    W = max(1, min(a.workers, N // 8 or 1))
    bounds = [round(i * N / W) for i in range(W + 1)]
    tmp = Path(tempfile.mkdtemp(prefix="mk_render_", dir=str(proj)))
    jobs = [(url, bounds[i], bounds[i + 1], a.fps, a.subframes, a.shutter, str(tmp / f"chunk{i:02d}.mkv"), a.scale, i)
            for i in range(W)]
    ctx = mp.get_context("spawn")
    with ctx.Pool(W) as pool:
        errs = pool.map(render_chunk, jobs)
    page_errors = sorted({e for chunk in errs for e in chunk})
    print(f"frames rendered in {time.time() - t0:.0f}s")

    # final encode
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{j[6]}'\n" for _ in range(a.loops) for j in jobs))
    ff = ffmpeg_bin()
    cmd = [ff, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if audio:
        cmd += ["-stream_loop", str(a.loops - 1), "-i", str(audio)]
    cmd += ["-map", "0:v"] + (["-map", "1:a"] if audio else [])
    cmd += ["-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
            "-c:v", "libx264", "-preset", "slow", "-crf", str(a.crf), "-tune", "animation"] + ([] if a.crf == 0 else ["-profile:v", "high"]) + [
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv",
            "-r", str(a.fps), "-movflags", "+faststart"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "256k", "-shortest"]
    subprocess.run(cmd + [str(out)], check=True)
    if a.gif:
        gif = out.with_suffix(".gif")
        subprocess.run([ff, "-y", "-v", "error", "-i", str(out), "-vf",
                        "fps=30,scale=720:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];"
                        "[b][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle", str(gif)], check=True)
        print(f"wrote {gif}")
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    httpd.shutdown()
    if page_errors:
        print("page errors during render:\n  " + "\n  ".join(page_errors), file=sys.stderr)
    size = out.stat().st_size / 1e6
    print(f"wrote {out} ({size:.1f} MB, {N * a.loops / a.fps:.2f}s, {a.fps} fps{', with audio' if audio else ''})")


if __name__ == "__main__":
    main()
