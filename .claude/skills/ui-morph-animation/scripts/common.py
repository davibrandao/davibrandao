"""Shared helpers: ffmpeg discovery, a local static server, and a Chromium launcher
that survives mismatched Playwright/browser versions."""
import functools
import glob
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

SIZE = 1440


def ffmpeg_bin(name="ffmpeg"):
    """Return a path to ffmpeg/ffprobe. Falls back to imageio-ffmpeg's static build."""
    found = shutil.which(name)
    if found:
        return found
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg  # pip install imageio-ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass
    sys.exit(f"{name} not found. Install it (apt/brew install ffmpeg) or `pip install imageio-ffmpeg`.")


def decode_audio(path, sr, channels=1, start=None, duration=None):
    """Decode any audio file to float32 numpy (frames, channels) via ffmpeg."""
    import numpy as np

    cmd = [ffmpeg_bin(), "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{max(0.0, start):.6f}"]
    cmd += ["-i", str(path)]
    if duration is not None:
        cmd += ["-t", f"{duration:.6f}"]
    cmd += ["-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32).copy()
    return x.reshape(-1, channels)


def write_wav(path, x, sr):
    """Write float audio (frames, channels) in [-1, 1] as 16-bit PCM WAV."""
    import wave

    import numpy as np

    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    pcm = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def read_wav(path):
    """Read a PCM WAV (16/24/32-bit) as float (frames, channels), sr."""
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float64) / 32768
    elif sw == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        v = np.where(v >= 1 << 23, v - (1 << 24), v)
        x = v.astype(np.float64) / (1 << 23)
    elif sw == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float64) / (1 << 31)
    else:
        raise ValueError(f"unsupported sample width {sw}")
    return x.reshape(-1, ch), sr


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def serve(directory):
    """Serve `directory` on an ephemeral localhost port. Returns (server, base_url)."""
    handler = functools.partial(_QuietHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


CHROME_ARGS = [
    "--force-color-profile=srgb",
    "--font-render-hinting=none",
    "--disable-lcd-text",
    "--hide-scrollbars",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
]


def launch_chromium(p):
    """Launch Chromium via Playwright, trying known executables if the bundled one is missing."""
    tried = []
    env_path = os.environ.get("CHROMIUM_PATH") or os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    candidates = [env_path] if env_path else []
    candidates.append(None)  # Playwright's own browser
    home = str(Path.home())
    for pattern in [
        "/opt/pw-browsers/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
        "/opt/pw-browsers/chromium",
        "/opt/pw-browsers/chromium-*/chrome-linux/chrome",
        home + "/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
        home + "/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
        home + "/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
    ]:
        candidates += sorted(glob.glob(pattern), reverse=True)
    for exe in candidates:
        try:
            if exe is None:
                return p.chromium.launch(args=CHROME_ARGS)
            return p.chromium.launch(executable_path=exe, args=CHROME_ARGS)
        except Exception as e:  # noqa: BLE001 — try the next candidate
            tried.append(f"{exe or 'playwright default'}: {str(e).splitlines()[0][:120]}")
    sys.exit("Could not launch Chromium. Tried:\n  " + "\n  ".join(tried) +
             "\nInstall one with `python -m playwright install chromium` or set CHROMIUM_PATH.")


def open_page(browser, url, render=True, hud=False, scale=1.0):
    """Open the animation page and wait until fonts are loaded and seek() exists."""
    ctx = browser.new_context(viewport={"width": SIZE, "height": SIZE}, device_scale_factor=scale)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    init = []
    if render:
        init.append("window.__RENDER__ = true;")
    if hud:
        init.append("window.__HUD__ = true;")
    if init:
        page.add_init_script("\n".join(init))
    page.goto(url, wait_until="load")
    try:
        page.wait_for_function("window.K && window.K.ready", timeout=15000)
        page.evaluate("() => window.K.ready")
    except Exception:
        msg = "\n".join(errors) or "window.K.ready never appeared (did the page call K.mount?)"
        sys.exit(f"Page failed to start:\n{msg}")
    # the frame size lives in the page (K.W × K.H); match the viewport to it
    w, h = page.evaluate("() => [K.W || 1440, K.H || 1440]")
    if (w, h) != (SIZE, SIZE):
        page.set_viewport_size({"width": int(w), "height": int(h)})
        page.evaluate("() => K.seek(K.t)")
    if errors:
        print("page errors:\n  " + "\n  ".join(errors), file=sys.stderr)
    page._mk_errors = errors  # surfaced by callers after rendering
    return page


def page_info(page):
    return page.evaluate(
        """() => ({T: K.T, bpm: K.bpm, bars: K.bars, nBeats: K.nBeats, beatsPerBar: K.beatsPerBar, W: K.W, H: K.H,
                   beats: Array.from({length: K.nBeats + 1}, (_, i) => K.b(i)),
                   events: K.events, cues: K.cues})"""
    )


def dump_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2))
