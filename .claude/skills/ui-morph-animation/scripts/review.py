#!/usr/bin/env python3
"""Review pass before the full render: one frame per beat + automatic checks.

Writes REVIEW_DIR/beat_XX.png (with a bar.beat HUD), REVIEW_DIR/sheet.png (one row
per bar), REVIEW_DIR/report.md, and PROJECT/cues.json. Then look at the sheet and
fix anything off the grid, cramped or hard to read.

Checks:
  purity    frames rendered in a different order must be pixel-identical
  seam      the step from the last frame to the first must look like any other step
            (cursor position and speed included)
  activity  UI motion per beat with the cursor hidden — flags dead beats
  events    every event on the 16th-note grid; beats with no event are listed
  audit     small text, text outside the shape, truncated text, two swap layers
            half-visible at once, shape crowding the frame edge

usage: review.py PROJECT/index.html [--out review] [--mid] [--at BEATS] [--range A:B:STEP] [--fps 60] [--tile 360] [--quick]
  --mid            also render half-beat frames (where most transitions are mid-flight)
  --at 3.5,12      render extra full-size frames at these beats (kept across runs)
  --range 5:6:0.125  filmstrip of a transition: frames from beat 5 to 6 every 1/8 beat → strip_5-6.png
  --quick          frames + sheet only, skip the checks
"""
import argparse
import base64
import io
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import SIZE, dump_json, launch_chromium, open_page, page_info, serve  # noqa: E402

TICKS = "▁▂▃▄▅▆▇█"


def spark(v, top=None):
    top = top or (max(v) or 1)
    return "".join(TICKS[min(7, int(x / top * 7.999))] for x in v)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html")
    ap.add_argument("--out", default=None)
    ap.add_argument("--mid", action="store_true")
    ap.add_argument("--at", default="")
    ap.add_argument("--range", default="", help="A:B:STEP in beats, e.g. 5:6:0.125")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--tile", type=int, default=360)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--min-text", type=float, default=22)
    a = ap.parse_args()

    from PIL import Image
    from playwright.sync_api import sync_playwright

    html = Path(a.html).resolve()
    if html.is_dir():
        html = html / "index.html"
    proj = html.parent
    out = Path(a.out).resolve() if a.out else proj / "review"
    out.mkdir(parents=True, exist_ok=True)
    for old in list(out.glob("beat_*.png")) + [out / "sheet.png"]:  # close-ups and strips are kept
        if old.exists():
            old.unlink()
    httpd, base = serve(proj)
    url = f"{base}/{html.name}"
    report = []

    def grab(cdp, scale=1.0):
        clip = {"x": 0, "y": 0, "width": SIZE, "height": SIZE, "scale": scale}
        data = cdp.send("Page.captureScreenshot", {"format": "png", "clip": clip})["data"]
        return base64.b64decode(data)

    def gray(png):
        return np.asarray(Image.open(io.BytesIO(png)).convert("L"), dtype=np.float32)

    with sync_playwright() as p:
        browser = launch_chromium(p)

        # ---------------------------------------------------------------- beat frames
        page = open_page(browser, url, render=True, hud=True)
        cdp = page.context.new_cdp_session(page)
        info = page_info(page)
        T, nB, bpb = info["T"], info["nBeats"], info["beatsPerBar"]
        dump_json(proj / "cues.json", {"T": T, "fps": a.fps, "frames": int(round(T * a.fps)), "cues": info["cues"]})
        steps = [0.0, 0.5] if a.mid else [0.0]
        tiles, audits = [], {}
        for n in range(nB):
            for s in steps:
                beat = n + s
                t = page.evaluate("b => K.b(b)", beat)
                warn = page.evaluate("([t, m]) => K.audit(t, {minText: m})", [t, a.min_text])
                if warn:
                    audits[beat] = warn
                png = grab(cdp)
                name = f"beat_{n:02d}{'_mid' if s else ''}.png"
                (out / name).write_bytes(png)
                tiles.append(Image.open(io.BytesIO(png)).convert("RGB").resize((a.tile, a.tile), Image.LANCZOS))
        for b in [float(x) for x in a.at.split(",") if x.strip()]:
            page.evaluate("b => K.seek(K.b(b))", b)
            (out / f"at_{b:g}.png").write_bytes(grab(cdp))
        if a.range:
            r0, r1, st = [float(x) for x in a.range.split(":")]
            n = int(round((r1 - r0) / st)) + 1
            strip = []
            for i in range(n):
                b = r0 + i * st
                page.evaluate("b => K.seek(K.b(b))", b)
                strip.append(Image.open(io.BytesIO(grab(cdp))).convert("RGB").resize((a.tile, a.tile), Image.LANCZOS))
            cols = min(n, 8)
            rows_ = (n + cols - 1) // cols
            sh = Image.new("RGB", (cols * a.tile + (cols + 1) * 8, rows_ * a.tile + (rows_ + 1) * 8), (255, 255, 255))
            for i, im in enumerate(strip):
                rr, cc = divmod(i, cols)
                sh.paste(im, (8 + cc * (a.tile + 8), 8 + rr * (a.tile + 8)))
            sh.save(out / f"strip_{r0:g}-{r1:g}.png")
        cols = bpb * len(steps)
        rows = (len(tiles) + cols - 1) // cols
        gap = 8
        sheet = Image.new("RGB", (cols * a.tile + (cols + 1) * gap, rows * a.tile + (rows + 1) * gap), (255, 255, 255))
        for i, im in enumerate(tiles):
            r, c = divmod(i, cols)
            sheet.paste(im, (gap + c * (a.tile + gap), gap + r * (a.tile + gap)))
        sheet.save(out / "sheet.png")
        report.append(f"# Review — {T:.3f}s loop, {info['bpm']:.2f} BPM, {info['bars']} bars\n")
        report.append(f"frames: {out}/beat_XX.png · contact sheet: {out}/sheet.png (one row per bar)\n")
        page.context.close()

        if not a.quick:
            page = open_page(browser, url, render=True)
            cdp = page.context.new_cdp_session(page)

            def frame(t, scale=0.25):
                page.evaluate("t => K.seek(t)", t)
                return gray(grab(cdp, scale))

            # ------------------------------------------------------------ purity
            rng = np.random.default_rng(7)
            times = sorted(rng.uniform(0, T, 10).round(4))
            first = {t: frame(t) for t in times}
            worst = 0.0
            bad = []
            for t in reversed(times):
                frame(float(rng.uniform(0, T)))  # something else in between
                d = float(np.abs(frame(t) - first[t]).max())
                worst = max(worst, d)
                if d > 0:
                    bad.append(t)
            report.append("## purity\n" + ("ok — any frame renders the same in any order\n" if not bad else
                          f"**FAIL** — frames at {bad} differ when rendered out of order (max Δ {worst:.0f}). "
                          "Something in seek() depends on the previous frame: a style set only in some branches, "
                          "a variable updated per frame, or Math.random().\n"))

            # ------------------------------------------------------------ seam
            f = a.fps
            ts = [T - 3 / f, T - 2 / f, T - 1 / f, 0.0, 1 / f, 2 / f]
            frames = [frame(t) for t in ts]
            diffs = [float(np.abs(frames[i + 1] - frames[i]).mean()) for i in range(len(frames) - 1)]
            seam = diffs[2]
            others = diffs[:2] + diffs[3:]
            cur = page.evaluate("ts => ts.map(t => { const c = K.cursorAt(t); return c ? [c.x, c.y] : null })", ts)
            seam_ok = seam <= 2.5 * max(others) + 0.05
            line = f"frame-to-frame change around the loop point: {' '.join(f'{d:.2f}' for d in diffs)} (seam = 3rd)"
            if cur and cur[0] is not None:
                sp = [float(np.hypot(cur[i + 1][0] - cur[i][0], cur[i + 1][1] - cur[i][1])) for i in range(len(cur) - 1)]
                cur_ok = sp[2] <= 2.5 * max(sp[:2] + sp[3:]) + 0.5
                seam_ok = seam_ok and cur_ok
                line += f"\ncursor px/frame around the seam: {' '.join(f'{s:.1f}' for s in sp)}"
            report.append("## seam\n" + ("ok — " if seam_ok else "**FAIL** — the loop stutters. ") + line + "\n")

            # ------------------------------------------------------------ activity per beat (cursor hidden)
            page.evaluate("() => { window.__NO_CURSOR__ = true; }")
            k = 6
            act = []
            for n in range(nB):
                bt = page.evaluate("n => [K.b(n), K.b(n + 1)]", n)
                fr = [frame(bt[0] + (bt[1] - bt[0]) * i / k, 0.125) for i in range(k + 1)]
                act.append(max(float(np.abs(fr[i + 1] - fr[i]).mean()) for i in range(k)))
            page.evaluate("() => { window.__NO_CURSOR__ = false; }")
            med = float(np.median(act)) or 1e-6
            dead = [n for n, v in enumerate(act) if v < 0.08]
            quiet = [n for n, v in enumerate(act) if v >= 0.08 and v < 0.2 * med]
            lab = lambda n: f"{n // bpb + 1}.{n % bpb + 1}"  # noqa: E731
            bars_line = " ".join(spark(act[i:i + bpb], max(act)) for i in range(0, nB, bpb))
            txt = f"UI motion per beat (cursor hidden), one group per bar: {bars_line}\n"
            if dead:
                txt += f"**dead beats** (nothing but the cursor moves): {', '.join(lab(n) for n in dead)}\n"
            if quiet:
                txt += f"quiet beats (<20% of median motion): {', '.join(lab(n) for n in quiet)}\n"
            report.append("## activity\n" + txt)

            # ------------------------------------------------------------ events on the grid
            ev = info["events"]
            off = [e for e in ev if abs(e["beat"] * 4 - round(e["beat"] * 4)) > 1e-6]
            per = {}
            for e in ev:
                per.setdefault(int(np.floor(e["beat"] + 1e-6)) % nB, []).append(e["label"])
            empty = [lab(n) for n in range(nB) if n not in per]
            txt = "\n".join(f"- {lab(n)}  {' · '.join(per[n])}" for n in sorted(per))
            if off:
                txt += "\n**off the 16th grid:** " + ", ".join(f"{e['label']} @ beat {e['beat']}" for e in off)
            if empty:
                txt += f"\nbeats with no event: {', '.join(empty)}"
            cues = info["cues"]
            txt += f"\nsound cues: {len(cues)} ({', '.join(sorted({c['sound'] for c in cues}))})"
            report.append("## events\n" + txt + "\n")
            page.context.close()

        # ---------------------------------------------------------------- audits
        if audits:
            lines = []
            for beat, w in sorted(audits.items()):
                n = int(beat)
                for x in dict.fromkeys(w):
                    lines.append(f"- {n // bpb + 1}.{n % bpb + 1}{'+½' if beat % 1 else ''}  {x}")
            report.append("## audit\n" + "\n".join(lines) + "\n")
        else:
            report.append("## audit\nno text, overlap or framing warnings\n")
        errs = getattr(page, "_mk_errors", [])
        if errs:
            report.append("## page errors\n" + "\n".join(f"- {e}" for e in errs) + "\n")
        browser.close()
    httpd.shutdown()
    text = "\n".join(report)
    (out / "report.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
