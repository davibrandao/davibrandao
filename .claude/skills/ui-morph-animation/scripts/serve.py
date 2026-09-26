#!/usr/bin/env python3
"""Serve a project folder for live preview in a browser (fonts need http, not file://).

usage: serve.py PROJECT [--port 8765]
"""
import argparse
import functools
import http.server
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    d = Path(a.project).resolve()
    if d.is_file():
        d = d.parent
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
    with http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler) as httpd:
        print(f"preview: http://127.0.0.1:{a.port}/index.html  (space = play, ←/→ = beat, shift+←/→ = frame)")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
