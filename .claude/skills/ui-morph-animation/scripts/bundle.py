#!/usr/bin/env python3
"""Bundle the project into ONE self-contained HTML file: kit, font and soundtrack inlined.

Open the result in any browser: space plays with sound, ←/→ step by beat, shift+←/→ by frame.

usage: bundle.py PROJECT [--out PROJECT/dist/loop.html] [--no-audio]
"""
import argparse
import base64
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ffmpeg_bin  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--out")
    ap.add_argument("--no-audio", action="store_true")
    a = ap.parse_args()
    d = Path(a.project).resolve()
    if d.is_file():
        d = d.parent
    html = (d / "index.html").read_text()
    kit = (d / "morph-kit.js").read_text()
    html = html.replace('<script src="morph-kit.js"></script>', "<script>\n" + kit + "\n</script>")
    font = base64.b64encode((d / "Geist-Variable.woff2").read_bytes()).decode()
    html = html.replace("url('Geist-Variable.woff2')", f"url(data:font/woff2;base64,{font})")
    # photos referenced by relative path become data URIs, so the file stays self-contained
    mimes = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".avif": "image/avif"}

    def inline(m):
        p = d / m.group(2)
        if not p.exists() or p.suffix.lower() not in mimes:
            return m.group(0)
        return f'{m.group(1)}data:{mimes[p.suffix.lower()]};base64,{base64.b64encode(p.read_bytes()).decode()}{m.group(3)}'

    html = re.sub(r'(src=")(?!data:|https?:)([^"]+)(")', inline, html)
    mix = d / "mix.wav"
    if mix.exists() and not a.no_audio:
        with tempfile.TemporaryDirectory() as tmp:
            m4a = Path(tmp) / "a.m4a"
            subprocess.run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(mix), "-c:a", "aac", "-b:a", "192k", str(m4a)],
                           check=True)
            audio = "data:audio/mp4;base64," + base64.b64encode(m4a.read_bytes()).decode()
        html, n = re.subn(r'("audio":\s*)"[^"]*"', lambda m: m.group(1) + '"' + audio + '"', html, count=1)
        if n != 1:
            print("warning: CONFIG.audio not found; bundle has no sound", file=sys.stderr)
    out = Path(a.out) if a.out else d / "dist" / "loop.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, self-contained)")


if __name__ == "__main__":
    main()
