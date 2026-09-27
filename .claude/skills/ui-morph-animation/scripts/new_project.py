#!/usr/bin/env python3
"""Scaffold a morph-loop project folder.

Creates DIR/index.html (from the template, with the beat grid written into CONFIG),
DIR/morph-kit.js, DIR/Geist-Variable.woff2, DIR/sounds/ (UI kit) and, when a song and
beats.json are given, DIR/mix.wav (music only) so the dev player has sound right away.

usage: new_project.py DIR [--beats beats.json] [--song SONG] [--bars 7] [--bpm 120] [--size 1080x1920]
                          [--accent '#FF4F1A'] [--from-example [reference|trip-planner]] [--force]
--from-example starts from a finished build in examples/ instead of the minimal template —
faster when most requested states are in it. reference: button → … → toast (7 bars, B&W);
trip-planner: search → dropdown → date range → stepper → like → notification → avatars →
toast (6 bars, one accent).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir")
    ap.add_argument("--beats")
    ap.add_argument("--song")
    ap.add_argument("--bars", type=int, default=None)
    ap.add_argument("--bpm", type=float, default=None)
    ap.add_argument("--accent", default=None, help="one accent color, e.g. '#FF4F1A' (omit for pure black and white)")
    ap.add_argument("--size", default=None, help="frame WxH: 1440x1440 (default), 1080x1920 Reel/Story, 1080x1350 feed 4:5")
    ap.add_argument("--from-example", nargs="?", const="reference", default=None, metavar="NAME")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    d = Path(a.dir).resolve()
    if (d / "index.html").exists() and not a.force:
        sys.exit(f"{d}/index.html exists (use --force to overwrite)")
    d.mkdir(parents=True, exist_ok=True)

    cfg = {"bpm": 120, "bars": 7, "beats": None, "accent": a.accent, "audio": "mix.wav", "width": 1440, "height": 1440}
    beats = None
    if a.beats:
        beats = json.loads(Path(a.beats).read_text())
        sec = beats["section"]
        cfg["bars"] = sec["bars"]
        cfg["bpm"] = beats["bpm"]
        if not beats.get("steady_tempo", True):
            cfg["beats"] = sec["beats_rel"]  # follow the measured beats when the tempo drifts
    if a.size:
        w, h = (int(v) for v in a.size.lower().split("x"))
        if w % 2 or h % 2:
            sys.exit("--size needs even numbers (H.264 requires it)")
        cfg["width"], cfg["height"] = w, h
    if a.bars:
        cfg["bars"] = a.bars
    if a.bpm:
        cfg["bpm"] = a.bpm

    src = SKILL / (f"examples/{a.from_example}.html" if a.from_example else "assets/template.html")
    if not src.exists():
        names = ", ".join(p.stem for p in sorted((SKILL / "examples").glob("*.html")))
        sys.exit(f"no example named '{a.from_example}' (have: {names})")
    html = src.read_text()
    if a.from_example:
        m = re.search(r'"bars":\s*(\d+)', html)
        ex_bars = int(m.group(1)) if m else None
        if ex_bars and cfg["bars"] != ex_bars:
            print(f"note: the {a.from_example} timeline is {ex_bars} bars ({ex_bars * 4} beats) and this loop is "
                  f"{cfg['bars']} bars. Its keys past beat {cfg['bars'] * 4} wrap to the start (or it ends early), so "
                  f"re-time PLAN, CAM, the cursor keys and presence windows before the first review.", file=sys.stderr)
        if a.accent is None:
            m = re.search(r'"accent":\s*("[^"]*"|null)', html)
            cfg["accent"] = json.loads(m.group(1)) if m else None  # keep the example's palette unless told otherwise
    html, n = re.subn(r"const CONFIG = \{.*?\};", "const CONFIG = " + json.dumps(cfg) + ";", html, count=1, flags=re.S)
    if n != 1:
        sys.exit(f"CONFIG block not found in {src}")
    (d / "index.html").write_text(html)
    shutil.copy(SKILL / "assets/morph-kit.js", d / "morph-kit.js")
    shutil.copy(SKILL / "assets/fonts/Geist-Variable.woff2", d / "Geist-Variable.woff2")
    if not (d / "sounds/click.wav").exists():
        subprocess.run([sys.executable, str(HERE / "ui_sounds.py"), str(d / "sounds")], check=True, capture_output=True)

    proj = {"song": str(Path(a.song).resolve()) if a.song else None,
            "beats_json": str(Path(a.beats).resolve()) if a.beats else None,
            "bpm": cfg["bpm"], "bars": cfg["bars"], "accent": cfg["accent"]}
    (d / "project.json").write_text(json.dumps(proj, indent=1))

    if a.song and beats:
        sys.path.insert(0, str(HERE))
        import mix_audio

        if cfg["bars"] != beats["section"]["bars"]:
            print(f"note: beats.json was analyzed for {beats['section']['bars']} bars; re-run analyze_beats.py "
                  f"--bars {cfg['bars']} so the loop start is chosen for the right length", file=sys.stderr)
        T = cfg["bars"] * 4 * 60 / cfg["bpm"]
        mix_audio.mix(a.song, beats["section"], [], d / "mix.wav", n_samples=int(round(T * mix_audio.SR)),
                      sounds_dir=str(d / "sounds"))
    print(f"project ready: {d}")
    print(f"  {cfg['width']}×{cfg['height']}, {cfg['bars']} bars @ {cfg['bpm']} BPM"
          f"{' (measured beat grid)' if cfg['beats'] else ''}, accent {cfg['accent'] or 'none (black and white)'}")
    print(f"  edit {d / 'index.html'}; preview: python3 {HERE / 'serve.py'} {d}")


if __name__ == "__main__":
    main()
