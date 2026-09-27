/* morph-kit.js — a pure-function motion kit for beat-synced UI morph loops.
 *
 * The one rule: everything visible is a function of time. `seek(t)` rewrites every
 * dynamic style from scratch, so any frame can be rendered in any order and the
 * result is identical. There are no CSS transitions, no timers, and nothing is
 * remembered between frames. Precomputing lookup tables at startup is fine
 * (it is deterministic); mutating anything inside seek other than the DOM is not.
 *
 * Time is written in beats (0-based, fractional allowed) and converted with K.b().
 * The loop is closed by construction: a track's value before its first key is its
 * last key, and each spring started near the end of the loop keeps settling
 * after the wrap, so frame T and frame 0 match — position and velocity.
 */
(function (global) {
  'use strict';

  // ------------------------------------------------------------------ math
  const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
  const lerp = (a, b, u) => a + (b - a) * u;
  const invLerp = (a, b, x) => (b === a ? 0 : (x - a) / (b - a));
  const remap = (x, a, b, c, d) => lerp(c, d, clamp(invLerp(a, b, x)));
  // Exact for x already in [0, m): ((x % m) + m) % m would shift it by one ulp, and a frame
  // seeked exactly on a beat would then show the state just before that beat.
  const mod = (x, m) => { const r = x % m; return r < 0 ? r + m : r; };
  // Minimum-jerk 0→1: zero velocity and acceleration at both ends (how hands move).
  const minjerk = (u) => { u = clamp(u); return u * u * u * (10 + u * (-15 + 6 * u)); };
  // Deterministic hash noise in [0,1) — use instead of Math.random().
  const hash = (n) => { const s = Math.sin(n * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); };

  // iOS-style rubber band: past [lo, hi] the value keeps moving but with growing
  // resistance. `dim` is the size of the thing being stretched.
  function rubber(x, lo, hi, dim, c = 0.55) {
    if (x > hi) return hi + (1 - 1 / (((x - hi) * c) / dim + 1)) * dim;
    if (x < lo) return lo - (1 - 1 / (((lo - x) * c) / dim + 1)) * dim;
    return x;
  }

  // ---------------------------------------------------------------- springs
  // Closed-form damped harmonic oscillator. Parameterised like SwiftUI:
  //   duration = perceptual duration (s), bounce = 0 (no overshoot) … 0.2 (≈1.5 %).
  // Keep bounce ≤ 0.2 — "a tiny overshoot at most".
  function spring(duration = 0.5, bounce = 0) {
    const w0 = (2 * Math.PI) / duration;
    const z = bounce >= 0 ? 1 - bounce : 1 / (1 + bounce); // damping ratio
    let pos, vel, decay;
    if (Math.abs(z - 1) < 1e-6) {
      pos = (x0, v0, t) => Math.exp(-w0 * t) * (x0 + (v0 + w0 * x0) * t);
      vel = (x0, v0, t) => Math.exp(-w0 * t) * (v0 - w0 * (v0 + w0 * x0) * t);
      decay = w0;
    } else if (z < 1) {
      const wd = w0 * Math.sqrt(1 - z * z), a = z * w0;
      pos = (x0, v0, t) => {
        const B = (v0 + a * x0) / wd;
        return Math.exp(-a * t) * (x0 * Math.cos(wd * t) + B * Math.sin(wd * t));
      };
      vel = (x0, v0, t) => {
        const B = (v0 + a * x0) / wd;
        return Math.exp(-a * t) * ((B * wd - a * x0) * Math.cos(wd * t) - (x0 * wd + a * B) * Math.sin(wd * t));
      };
      decay = a;
    } else {
      const s = w0 * Math.sqrt(z * z - 1), r1 = -z * w0 + s, r2 = -z * w0 - s;
      pos = (x0, v0, t) => { const c2 = (v0 - r1 * x0) / (r2 - r1); return (x0 - c2) * Math.exp(r1 * t) + c2 * Math.exp(r2 * t); };
      vel = (x0, v0, t) => { const c2 = (v0 - r1 * x0) / (r2 - r1); return (x0 - c2) * r1 * Math.exp(r1 * t) + c2 * r2 * Math.exp(r2 * t); };
      decay = -r1;
    }
    const settle = 16 / decay; // residual < 1e-6 of the change after this
    return {
      duration, bounce, zeta: z, omega: w0, settle,
      // Step response 0 → 1, starting at rest at t = 0.
      step: (t) => (t <= 0 ? 0 : t >= settle ? 1 : 1 - pos(1, 0, t)),
      stepVel: (t) => (t <= 0 || t >= settle ? 0 : -vel(1, 0, t)),
      // Free response: displacement x0 from the target with velocity v0 → 0.
      free: (x0, v0, t) => (t <= 0 ? x0 : t >= settle ? 0 : pos(x0, v0, t)),
      freeVel: (x0, v0, t) => (t <= 0 ? v0 : t >= settle ? 0 : vel(x0, v0, t)),
    };
  }

  // ----------------------------------------------------------------- colors
  // Color springs run in OKLab so black→accent never passes through mud.
  // '#rgb', '#rrggbb', '#rrggbbaa', 'rgb(…)', 'rgba(…)' → [r, g, b, a] in 0..1
  function parseColor(c) {
    const s = String(c).trim();
    const m = /^rgba?\(([^)]+)\)/.exec(s);
    if (m) {
      const p = m[1].split(/[\s,/]+/).filter(Boolean);
      const num = (v, i) => (v.endsWith('%') ? (parseFloat(v) / 100) * (i < 3 ? 255 : 1) : parseFloat(v));
      return [num(p[0], 0) / 255, num(p[1], 1) / 255, num(p[2], 2) / 255, p.length > 3 ? num(p[3], 3) : 1];
    }
    let h = s.replace('#', '');
    if (h.length === 3 || h.length === 4) h = h.split('').map((ch) => ch + ch).join('');
    const n = parseInt(h.slice(0, 6), 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255, h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1];
  }
  const hexToRgb = (c) => parseColor(c).slice(0, 3);
  const toLin = (c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  const toGamma = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055);
  function oklab(hex) {
    const [r, g, b] = hexToRgb(hex).map(toLin);
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [
      0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
      1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
      0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
    ];
  }
  function oklabToCss([L, a, b], alpha = 1) {
    const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
    const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
    const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
    const rgb = [
      4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
      -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
      -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
    ].map((v) => Math.round(clamp(toGamma(clamp(v))) * 255));
    return alpha >= 1 ? `rgb(${rgb[0]},${rgb[1]},${rgb[2]})` : `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${+clamp(alpha).toFixed(4)})`;
  }
  // Static mix of two hex colors (u = 0 → a, 1 → b), for derived tints.
  function mixHex(a, b, u, alpha = 1) {
    const A = oklab(a), B = oklab(b);
    return oklabToCss([lerp(A[0], B[0], u), lerp(A[1], B[1], u), lerp(A[2], B[2], u)], alpha);
  }

  // ------------------------------------------------------------ geometry
  // Smooth line through points (Catmull-Rom → cubic Bézier), for charts.
  function smoothPath(pts, tension = 1) {
    if (pts.length < 2) return '';
    let d = `M${pts[0][0]},${pts[0][1]}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      const k = tension / 6;
      d += ` C${p1[0] + (p2[0] - p0[0]) * k},${p1[1] + (p2[1] - p0[1]) * k} ${p2[0] - (p3[0] - p1[0]) * k},${p2[1] - (p3[1] - p1[1]) * k} ${p2[0]},${p2[1]}`;
    }
    return d;
  }
  // Play ▶ ↔ pause ❚❚ as two 4-point polygons that morph point-for-point.
  // u = 0 → play, 1 → pause. Size is the icon box (square). Returns an SVG path.
  function playPause(u, size = 24) {
    const s = size, g = s * 0.14; // gap between pause bars
    const bw = (s * 0.62 - g) / 2, x0 = s * 0.19, y0 = s * 0.12, y1 = s * 0.88, ym = s / 2;
    // play triangle split into two quads (left half, right half); apex at x = 0.86 s
    const px0 = s * 0.22, px1 = s * 0.86, pm = (px0 + px1) / 2, slope = (ym - y0) / (px1 - px0);
    const play = [
      [[px0, y0], [pm, y0 + slope * (pm - px0)], [pm, y1 - slope * (pm - px0)], [px0, y1]],
      [[pm, y0 + slope * (pm - px0)], [px1, ym], [px1, ym], [pm, y1 - slope * (pm - px0)]],
    ];
    const pause = [
      [[x0, y0], [x0 + bw, y0], [x0 + bw, y1], [x0, y1]],
      [[x0 + bw + g, y0], [x0 + 2 * bw + g, y0], [x0 + 2 * bw + g, y1], [x0 + bw + g, y1]],
    ];
    return play.map((quad, q) => 'M' + quad.map((p, i) => {
      const x = lerp(p[0], pause[q][i][0], u), y = lerp(p[1], pause[q][i][1], u);
      return `${x.toFixed(3)},${y.toFixed(3)}`;
    }).join(' L') + ' Z').join(' ');
  }

  // Icons: one family, 24-unit grid, drawn with a single stroke width.
  // Render with K.icon(name, px, strokePx) so every icon in a state matches.
  const ICONS = {
    arrowDown: 'M12 4v14M6 12l6 6 6-6',
    check: 'M5 12.5l4.5 4.5L19 7.5',
    search: 'M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM20 20l-4.8-4.8',
    volume: 'M4 9.5h3.5L12 5.5v13l-4.5-4H4zM16 9a4 4 0 0 1 0 6M18.5 6.5a7.5 7.5 0 0 1 0 11',
    volumeLow: 'M4 9.5h3.5L12 5.5v13l-4.5-4H4zM16 9a4 4 0 0 1 0 6',
    prev: 'M18 6v12l-8.5-6zM6 6v12',
    next: 'M6 6v12l8.5-6zM18 6v12',
    download: 'M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14',
    share: 'M12 15V4M8 7.5L12 3.5l4 4M6 11v8.5h12V11',
    copy: 'M9 9h10v10H9zM5 15V5h10',
    trash: 'M5 7h14M10 7V4.5h4V7M7 7l1 12.5h8L17 7',
    image: 'M4.5 5h15v14h-15zM4.5 15.5l4-4 4 4 2.5-2.5 4 4M15 9.5h.01',
    file: 'M7 3.5h7l4 4v13H7zM14 3.5v4h4',
    bell: 'M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15zM10 20.5h4',
    close: 'M6 6l12 12M18 6L6 18',
    plus: 'M12 5v14M5 12h14',
    chevronRight: 'M9.5 6l6 6-6 6',
    command: 'M9 9V6.5A2.5 2.5 0 1 0 6.5 9H9zm0 0v6m0-6h6m-6 6H6.5A2.5 2.5 0 1 0 9 17.5V15zm0 0h6m0 0v2.5a2.5 2.5 0 1 0 2.5-2.5H15zm0 0V9m0 0h2.5A2.5 2.5 0 1 0 15 6.5V9z',
    enter: 'M19 5v7.5a2 2 0 0 1-2 2H6M9.5 11l-3.5 3.5 3.5 3.5',
    sparkle: 'M12 3.5l1.8 5.2 5.2 1.8-5.2 1.8-1.8 5.2-1.8-5.2L5 10.5l5.2-1.8z',
    heart: 'M12 19.5s-7-4.3-7-9.2A3.8 3.8 0 0 1 12 8a3.8 3.8 0 0 1 7 2.3c0 4.9-7 9.2-7 9.2z',
    user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 20a7.5 7.5 0 0 1 15 0',
    calendar: 'M5 6h14v14H5zM5 10h14M9 3.5V7M15 3.5V7',
    home: 'M4.5 11L12 4.5l7.5 6.5V20h-15z',
    settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM12 2.5v3M12 18.5v3M21.5 12h-3M5.5 12h-3M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1M18.7 18.7l-2.1-2.1M7.4 7.4L5.3 5.3',
  };
  function icon(name, px = 24, stroke = 2, color = 'currentColor') {
    const d = ICONS[name];
    if (!d) throw new Error('unknown icon ' + name);
    // stroke is in *icon px*; convert to the 24-grid so every icon gets the same visual weight
    const sw = (stroke * 24) / px;
    return `<svg width="${px}" height="${px}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" style="display:block"><path d="${d}"/></svg>`;
  }

  // ------------------------------------------------------------------- kit
  const UNITLESS = new Set(['opacity', 'z-index', 'font-weight', 'flex', 'flex-grow', 'flex-shrink', 'order', 'scale', 'line-height', 'fill-opacity', 'stroke-opacity', 'zoom']);
  const kebab = (k) => k.replace(/[A-Z]/g, (m) => '-' + m.toLowerCase());

  function create(opts = {}) {
    const K = {};
    // Frame size in px. Square 1440 by default; e.g. { width: 1080, height: 1920 } for a Reel,
    // 1080×1350 for a 4:5 feed post. K.size is the shorter side (handy for proportions).
    K.W = opts.width ?? opts.size ?? 1440;
    K.H = opts.height ?? opts.size ?? 1440;
    K.size = Math.min(K.W, K.H);
    // Safe area: insets [top, right, bottom, left] the UI must stay out of (a Reel's header,
    // caption and action buttons: about [220, 140, 420, 60] at 1080×1920). The camera centres
    // states in it, K.fit sizes to it, and the audit measures the shape's margin against it.
    const ins = opts.safe ?? [0, 0, 0, 0];
    K.safe = { l: ins[3], t: ins[0], r: K.W - ins[1], b: K.H - ins[2] };
    K.focus = opts.focus ?? [(K.safe.l + K.safe.r) / 2, (K.safe.t + K.safe.b) / 2];
    K.bpm = opts.bpm ?? 120;
    K.beatsPerBar = opts.beatsPerBar ?? 4;
    K.bars = opts.bars ?? 7;
    K.nBeats = K.bars * K.beatsPerBar;
    K.beat = 60 / K.bpm;
    K.loop = opts.loop ?? true;
    K.grid = opts.beats && opts.beats.length > 1 ? opts.beats.slice() : null; // measured beat times (s, rel. to start)

    // Beat → seconds. With a measured grid, fractional beats interpolate between measured beats.
    K.b = (n) => {
      if (!K.grid) return n * K.beat;
      const g = K.grid, last = g.length - 1;
      if (n <= 0) return g[0] + n * (g[1] - g[0]);
      if (n >= last) return g[last] + (n - last) * ((g[last] - g[0]) / last);
      const i = Math.floor(n);
      return g[i] + (n - i) * (g[i + 1] - g[i]);
    };
    // Seconds → beats (inverse of K.b)
    K.toBeat = (t) => {
      if (!K.grid) return t / K.beat;
      const g = K.grid;
      if (t <= g[0]) return (t - g[0]) / (g[1] - g[0]);
      for (let i = 0; i < g.length - 1; i++) if (t < g[i + 1]) return i + (t - g[i]) / (g[i + 1] - g[i]);
      return g.length - 1 + (t - g[g.length - 1]) / ((g[g.length - 1] - g[0]) / (g.length - 1));
    };
    // Loop-aware "seconds since an event": t is read inside a one-loop window that starts at
    // fromBeat (default: half a loop before the event). Use it for anything that draws or
    // counts after an event, e.g. a toast icon drawing at beat 27 must still be drawn at
    // t = 0.1 after the wrap. Pass fromBeat = the beat the element appears, so its draw-on
    // stays drawn until it leaves, however long it stays or wherever the seam falls.
    K.since = (t, beat, fromBeat) => {
      if (!K.loop) return t - K.b(beat);
      const w0 = fromBeat === undefined ? K.b(beat) - K.T / 2 : K.b(fromBeat);
      return w0 + mod(t - w0, K.T) - K.b(beat);
    };
    // bar/beat (1-based, like a DAW) → beat index. K.bb(3, 2) = 9; K.bb(3, 2, 0.5) = 9.5
    K.bb = (bar, beat = 1, frac = 0) => (bar - 1) * K.beatsPerBar + (beat - 1) + frac;
    K.T = K.b(K.nBeats);
    K.label = (t) => { const n = K.toBeat(t), i = Math.floor(n + 1e-6); return `${Math.floor(i / K.beatsPerBar) + 1}.${(i % K.beatsPerBar) + 1}`; };

    // Registries — read by review.py and render.py.
    K.events = []; // {beat, t, label}
    K.cues = [];   // {beat, t, sound, gain}
    K.layers = []; // {el, group, v: t => visibility}
    K.event = (beat, label) => { K.events.push({ beat, t: K.b(beat), label }); return beat; };
    K.cue = (beat, sound, gain = 1) => { K.cues.push({ beat, t: K.b(beat), sound, gain }); return beat; };

    // ---- tracks: a value that changes target many times = one spring per change, summed.
    // keys: [[beat, value, spring?], ...] in time order. Each change starts its own step
    // response from wherever the value is, so interrupted motion stays smooth, and the
    // whole thing is still a pure function of t.
    // A value may be a function of t (a dragged or playing value): the spring then blends
    // from the previous target to that moving target — continuity is automatic.
    // In loop mode the value before the first key is the last key, so the loop closes.
    // An element hidden for part of the loop: add a key while it is hidden that parks it
    // where it will next appear, so it never visibly flies in from its last position.
    // In loop mode, key beats are wrapped into the loop: [28.75, v] in a 28-beat loop is 0.75.
    const wrapKeys = (keys) => (K.loop ? keys.map((k) => [mod(k[0], K.nBeats), ...k.slice(1)]) : keys.slice()).sort((a, b) => a[0] - b[0]);
    K.track = (keys, sp, o = {}) => {
      keys = wrapKeys(keys);
      const val = (v, t) => (typeof v === 'function' ? v(t) : v);
      const init = o.from !== undefined ? o.from : K.loop ? keys[keys.length - 1][1] : keys[0][1];
      const ch = [];
      let prev = init;
      for (const [beat, v, s] of keys) {
        const same = typeof v !== 'function' && typeof prev !== 'function' && v === prev;
        if (!same) ch.push({ t: K.b(beat) + (o.delay || 0), from: prev, to: v, sp: s || sp, fn: typeof v === 'function' || typeof prev === 'function', d: typeof v === 'function' || typeof prev === 'function' ? 0 : v - prev });
        prev = v;
      }
      const T = K.T, loop = K.loop;
      const f = (t) => {
        let x = val(init, t);
        for (const c of ch) {
          const w = c.sp.step(t - c.t) + (loop ? c.sp.step(t - c.t + T) - 1 : 0);
          if (w === 0) continue;
          x += (c.fn ? val(c.to, t) - val(c.from, t) : c.d) * w;
        }
        return x;
      };
      f.vel = (t) => (f(t + 1e-4) - f(t - 1e-4)) / 2e-4;
      f.keys = keys;
      f.closed = !K.loop || typeof prev === 'function' || typeof init === 'function' || Math.abs(prev - init) < 1e-9;
      return f;
    };
    // Vector track: keys [[beat, [a, b, …], spring?]] → t => [a, b, …]
    K.trackN = (keys, sp, o) => {
      const n = keys[0][1].length;
      const parts = Array.from({ length: n }, (_, i) => K.track(keys.map((k) => [k[0], k[1][i], k[2]]), sp, o));
      return (t) => parts.map((p) => p(t));
    };
    // Color track in OKLab (alpha springs too): keys [[beat, '#hex' | 'rgba(…)', spring?]] → t => css color
    K.colorTrack = (keys, sp, o) => {
      const tr = K.trackN(keys.map((k) => [k[0], [...oklab(k[1]), parseColor(k[1])[3]], k[2]]), sp, o);
      const f = (t, alpha = 1) => { const v = tr(t); return oklabToCss(v, clamp(v[3]) * alpha); };
      f.lab = tr;
      return f;
    };

    // ---- leading/trailing edges: a pill whose two edges ride different springs.
    // The edge moving in the direction of travel gets the fast spring, so the shape
    // stretches ahead of itself and the tail catches up (liquid tab indicator, toggle knob).
    // keys: [[beat, left, right], ...]
    K.edges = (keys, o = {}) => {
      const lead = o.lead || spring(0.32, 0.1), trail = o.trail || spring(0.62, 0.05);
      keys = wrapKeys(keys);
      const Lk = [], Rk = [];
      const at = (v, beat) => (typeof v === 'function' ? v(K.b(beat)) : v);
      let prev = K.loop ? keys[keys.length - 1] : keys[0];
      for (const k of keys) {
        const [l0, r0, l1, r1] = [at(prev[1], k[0]), at(prev[2], k[0]), at(k[1], k[0]), at(k[2], k[0])];
        const dir = (l1 + r1) / 2 - (l0 + r0) / 2;
        const grow = (r1 - l1) - (r0 - l0);
        // moving right → right edge leads; moving left → left edge leads; pure resize → both lead
        const lSp = Math.abs(dir) < 1e-6 ? (grow >= 0 ? lead : trail) : dir > 0 ? trail : lead;
        const rSp = Math.abs(dir) < 1e-6 ? (grow >= 0 ? lead : trail) : dir > 0 ? lead : trail;
        Lk.push([k[0], k[1], k[3]?.l || lSp]);
        Rk.push([k[0], k[2], k[3]?.r || rSp]);
        prev = k;
      }
      const L = K.track(Lk), R = K.track(Rk);
      const f = (t) => [L(t), R(t)];
      f.L = L; f.R = R;
      return f;
    };

    // ---- content swaps: short blur with separate enter and exit timing.
    // Exit is fast and starts on the beat; enter starts a hair later and settles slower,
    // so two labels are never legible on top of each other.
    const ENTER = spring(0.38, 0), EXIT = spring(0.2, 0);
    // { instant: true } appears on the beat with no fade (keystrokes, a caret, a badge count).
    K.presence = (t, inBeat, outBeat, o = {}) => {
      const tin = inBeat == null ? -1e9 : K.b(inBeat) + (o.delay ?? 0.06);
      const tout = outBeat == null ? 1e9 : K.b(outBeat) + (o.outDelay ?? 0);
      const en = o.enter || ENTER, ex = o.exit || EXIT;
      const enterAt = (tt) => (inBeat == null ? 1 : o.instant ? (tt >= K.b(inBeat) + (o.delay ?? 0) ? 1 : 0) : en.step(tt - tin));
      const one = (tt) => enterAt(tt) * (outBeat == null ? 1 : 1 - ex.step(tt - tout));
      if (!K.loop) return one(t);
      return Math.max(one(t), one(t + K.T), one(t - K.T));
    };
    // Style for a swapping layer at visibility v. Blur is specified in *screen* px and
    // divided by the camera zoom so it reads the same at every zoom level.
    K.swap = (v, o = {}) => {
      const blur = ((1 - v) * (o.blur ?? 14)) / (K.cam.z * (o.scaleCtx ?? 1));
      const s = lerp(o.scale ?? 0.94, 1, v);
      const dy = (1 - v) * (o.dy ?? 0);
      return {
        opacity: +v.toFixed(4),
        filter: v > 0.999 ? 'none' : `blur(${blur.toFixed(3)}px)`,
        transform: `translate(0px, ${dy.toFixed(3)}px) scale(${s.toFixed(5)})`,
        visibility: v < 0.002 ? 'hidden' : 'visible',
      };
    };
    // Register a swapping layer so review.py can flag overlapping half-visible labels.
    K.layer = (el, group, vFn) => { K.layers.push({ el, group, v: vFn }); return vFn; };

    // ---- camera: zoom rides a spring in log space (zoom feels linear that way).
    K.cam = { z: 1, cx: 0, cy: 0 };
    K._camera = null;
    K.camera = (keys, sp) => {
      const s = sp || spring(0.85, 0);
      const lz = K.track(keys.map((k) => [k[0], Math.log(k[1]), k[4]]), s);
      const cx = K.track(keys.map((k) => [k[0], k[2] ?? 0, k[4]]), s);
      const cy = K.track(keys.map((k) => [k[0], k[3] ?? 0, k[4]]), s);
      K._camera = (t) => ({ z: Math.exp(lz(t)), cx: cx(t), cy: cy(t) });
      return K._camera;
    };
    // Zoom that makes a w×h box fill `fill` of the safe area (the whole frame by default).
    K.fit = (w, h, fill = 0.7) => Math.min(((K.safe.r - K.safe.l) * fill) / w, ((K.safe.b - K.safe.t) * fill) / h);
    K.camAt = (t) => (K._camera ? K._camera(t) : { z: 1, cx: 0, cy: 0 });
    // the camera centre (cx, cy) lands on K.focus: the frame centre, or the safe area's
    K.project = (t, p) => { const c = K.camAt(t); return [(p[0] - c.cx) * c.z + K.focus[0], (p[1] - c.cy) * c.z + K.focus[1]]; };
    K.unproject = (t, s) => { const c = K.camAt(t); return [(s[0] - K.focus[0]) / c.z + c.cx, (s[1] - K.focus[1]) / c.z + c.cy]; };
    K.worldTransform = () => `translate(${K.focus[0]}px, ${K.focus[1]}px) scale(${K.cam.z}) translate(${-K.cam.cx}px, ${-K.cam.cy}px)`;
    // The world rect that covers the whole frame (plus `m` screen px past each edge) at time t:
    // key a shape to it to go full-bleed. It follows the camera, so it stays full-bleed while
    // the camera drifts. Returns { cx, cy, w, h } in world px. Mark the shape data-bleed while
    // it's full-bleed so the audit doesn't flag it for touching the frame edge.
    K.bleed = (t, m = 80) => {
      const c = K.camAt(t);
      return { cx: c.cx + (K.W / 2 - K.focus[0]) / c.z, cy: c.cy + (K.H / 2 - K.focus[1]) / c.z, w: (K.W + 2 * m) / c.z, h: (K.H + 2 * m) / c.z };
    };

    // ---- cursor: stops at anchors on beats, moves with minimum-jerk + a slight arc.
    // keys: [[beat, anchor, {arc}], ...]; anchor = [x, y] in world space or (t) => [x, y].
    // presses: [[beatDown, beatUp], ...]. Press on the beat, release is when the UI reacts.
    K._cursor = null;
    K.cursor = (keys, presses = [], o = {}) => {
      keys = wrapKeys(keys);
      const at = (a, t) => (typeof a === 'function' ? a(t) : a);
      const kt = keys.map((k) => K.b(k[0]));
      const warp = o.warp ?? 0.85; // <1 puts peak speed early, like a real flick
      const world = (t) => {
        const n = keys.length;
        // find segment [i, i+1] (wrapping across the loop seam)
        let i = -1;
        for (let j = 0; j < n; j++) if (kt[j] <= t) i = j;
        let t0, t1, a, b, opt;
        if (i === -1 || i === n - 1) {
          if (!K.loop) { const k = keys[i === -1 ? 0 : n - 1]; return at(k[1], t); }
          const last = n - 1;
          t0 = kt[last] - (i === -1 ? K.T : 0);
          t1 = kt[0] + (i === -1 ? 0 : K.T);
          a = keys[last][1]; b = keys[0][1]; opt = keys[0][2] || {};
        } else {
          t0 = kt[i]; t1 = kt[i + 1]; a = keys[i][1]; b = keys[i + 1][1]; opt = keys[i + 1][2] || {};
        }
        const pa = at(a, t), pb = at(b, t);
        const u = clamp((t - t0) / Math.max(1e-6, t1 - t0));
        const s = minjerk(Math.pow(u, warp));
        let x = lerp(pa[0], pb[0], s), y = lerp(pa[1], pb[1], s);
        const arc = opt.arc ?? (opt.drag ? 0 : 0.08);
        if (arc) {
          const dx = pb[0] - pa[0], dy = pb[1] - pa[1];
          const bow = Math.sin(Math.PI * s) * arc;
          x += -dy * bow; y += dx * bow;
        }
        return [x, y];
      };
      const pressKeys = [];
      for (const [d, u] of presses) { pressKeys.push([d, 1]); pressKeys.push([u, 0]); }
      const press = pressKeys.length ? K.track(pressKeys, spring(0.16, 0), { from: 0 }) : () => 0;
      const down = (t) => { let s = 0; for (const [d, u] of presses) { const td = K.b(d), tu = K.b(u); if (t >= td && t < tu) s = 1; } return s; };
      K._cursor = { world, press, down, presses };
      return K._cursor;
    };
    K.cursorAt = (t) => {
      if (!K._cursor) return null;
      const w = K._cursor.world(t);
      const s = K.project(t, w);
      return { world: w, x: s[0], y: s[1], press: K._cursor.press(t), down: K._cursor.down(t) };
    };

    // ---- drags: direct manipulation while held, spring back from wherever it was on release.
    // map(worldPoint, t) → value while held. rest(vRelease) → where it settles.
    K.drag = ({ press, release, map, before, rest = (v) => v, spring: sp = spring(0.45, 0.12) }) => {
      const tp = K.b(press), tr = K.b(release), eps = 1 / 480;
      let cache = null; // lazily computed once (deterministic): release value & velocity
      const rel = () => {
        if (!cache) {
          const v1 = map(K._cursor.world(tr), tr), v0 = map(K._cursor.world(tr - eps), tr - eps);
          cache = { v: v1, dv: (v1 - v0) / eps, target: rest(v1) };
        }
        return cache;
      };
      return (t) => {
        if (t < tp) return before ? before(t) : map(K._cursor.world(tp), tp);
        if (t <= tr) return map(K._cursor.world(t), t);
        const r = rel();
        return r.target + sp.free(r.v - r.target, r.dv, t - tr);
      };
    };

    // ---- styles: write the complete inline style every frame (never patch), so nothing
    // from a previous frame can leak into this one.
    K.css = (el, props) => {
      let s = '';
      for (const k in props) {
        const v = props[k];
        if (v === null || v === undefined || v === false) continue;
        const key = kebab(k);
        s += `${key}:${typeof v === 'number' && !UNITLESS.has(key) ? v.toFixed(3) + 'px' : v};`;
      }
      el.style.cssText = s;
    };
    K.attr = (el, name, v) => el.setAttribute(name, typeof v === 'number' ? v.toFixed(3) : v);
    K.text = (el, s) => { if (el.textContent !== s) el.textContent = s; };
    // Box helper: position a centered box (world units) — returns css props.
    K.box = (cx, cy, w, h, r) => ({ position: 'absolute', left: cx - w / 2, top: cy - h / 2, width: w, height: h, borderRadius: r });
    // Text at world (x, y) with visibility v: anchor 'l' = left edge at x, 'r' = right edge at x,
    // 'c' = centred (in a 300-wide box); y is the vertical centre. `swo` goes to K.swap.
    K.textAt = (el, x, y, size, anchor, v, extra = {}, swo) => {
      const box = { top: y - size * 0.6, height: size * 1.2, lineHeight: `${(size * 1.2).toFixed(3)}px`, fontSize: size };
      if (anchor === 'l') box.left = x;
      else if (anchor === 'r') box.right = -x;
      else { box.left = x - 150; box.width = 300; box.textAlign = 'center'; }
      K.css(el, { position: 'absolute', ...box, ...K.swap(v, swo), ...extra });
    };
    // A photo (<img>) filling a world-px box like CSS object-fit: cover, with a slow zoom.
    // zoom > 1 pushes in around the focus point (fx, fy in 0..1 of the image). Drive zoom from
    // time (e.g. 1 + 0.06 * K.since(t, appearBeat) / 2) for a Ken Burns drift. `extra` last.
    K.photoAt = (el, left, top, w, h, o = {}, extra = {}) => {
      const fx = o.fx ?? 0.5, fy = o.fy ?? 0.5, z = o.zoom ?? 1;
      K.css(el, { position: 'absolute', left, top, width: w, height: h, objectFit: 'cover',
        objectPosition: `${(fx * 100).toFixed(2)}% ${(fy * 100).toFixed(2)}%`, borderRadius: o.r ?? 0,
        transform: `scale(${z.toFixed(5)})`, transformOrigin: `${(fx * 100).toFixed(2)}% ${(fy * 100).toFixed(2)}%`, ...extra });
    };
    // A size×size box centred at world (x, y) — icons, glyph SVGs. `color` feeds currentColor.
    K.iconAt = (el, x, y, size, v, color, extra = {}) =>
      K.css(el, { position: 'absolute', left: x - size / 2, top: y - size / 2, width: size, height: size, color, ...K.swap(v), ...extra });
    // Complementary clips for inverting a label under a moving fill (tabs, segmented controls):
    // the base copy gets `outside`, the inverted copy gets `inside`. No glyph is drawn twice,
    // so there is no halo — even white over ink on an accent fill. All values in world px.
    K.splitClip = (boxLeft, boxWidth, L, R, boxHeight = 1000) => {
      const W = boxWidth, H = boxHeight, l = clamp(L - boxLeft, 0, W), r = clamp(R - boxLeft, l, W);
      const f = (n) => `${n.toFixed(2)}px`;
      return {
        inside: `inset(0px ${f(W - r)} 0px ${f(l)})`,
        outside: `polygon(evenodd, 0px 0px, ${f(W)} 0px, ${f(W)} ${f(H)}, 0px ${f(H)}, 0px 0px, ${f(l)} 0px, ${f(l)} ${f(H)}, ${f(r)} ${f(H)}, ${f(r)} 0px, ${f(l)} 0px)`,
      };
    };
    // Snap a continuous value to the 16th grid: sample fn(t) on every grid point between two
    // beats and return keys [[beat, value], …] only where the value changes. Use it for drags
    // over discrete things (calendar cells, detents, stepper values) so each step lands on the
    // grid instead of wherever the cursor happens to cross. Optionally registers events/cues.
    K.steps = (fn, fromBeat, toBeat, o = {}) => {
      const grid = o.grid ?? 0.25, keys = [];
      let prev;
      for (let b = fromBeat; b <= toBeat + 1e-9; b += grid) {
        const beat = Math.round(b / grid) * grid, v = fn(K.b(beat));
        if (prev === undefined || v !== prev) {
          keys.push([beat, v]);
          if (prev !== undefined) {
            if (o.label) K.event(beat, typeof o.label === 'function' ? o.label(v) : o.label);
            if (o.sound) K.cue(beat, o.sound, o.gain ?? 1);
          }
        }
        prev = v;
      }
      return keys;
    };

    // ---- frame loop
    K._frame = null;
    K.onFrame = (fn) => { K._frame = fn; };
    K.t = 0;
    K.seek = (t) => {
      const tt = K.loop ? mod(t, K.T) : clamp(t, 0, K.T);
      K.t = tt;
      K.cam = K.camAt(tt);
      if (K._frame) K._frame(tt);
      drawCursor(tt);
      drawHud(tt);
    };

    // cursor element (screen space, constant size — never scaled by the camera)
    let cursorEl = null;
    K.cursorSize = opts.cursorSize ?? 64;
    K.cursorTip = opts.cursorTip ?? [6.5 / 32, 3.8 / 32]; // tip position as a fraction of the cursor box
    function drawCursor(t) {
      if (!cursorEl || !K._cursor) return;
      if (global.__NO_CURSOR__) { cursorEl.style.cssText = 'display:none'; return; } // review.py motion check
      const c = K.cursorAt(t);
      const s = 1 - 0.14 * clamp(c.press);
      const tx = K.cursorSize * K.cursorTip[0], ty = K.cursorSize * K.cursorTip[1];
      K.css(cursorEl, {
        position: 'absolute', left: 0, top: 0, width: K.cursorSize, height: K.cursorSize, zIndex: 50,
        transform: `translate(${(c.x - tx).toFixed(2)}px, ${(c.y - ty).toFixed(2)}px) scale(${s.toFixed(4)})`,
        transformOrigin: `${tx.toFixed(2)}px ${ty.toFixed(2)}px`, pointerEvents: 'none',
      });
    }
    // debug HUD for review frames (?hud=1 or window.__HUD__)
    let hudEl = null;
    function drawHud(t) {
      if (!hudEl) return;
      const n = K.toBeat(t);
      // events that fired in the last half beat (including exactly now)
      const near = K.events.filter((e) => e.beat <= n + 1e-6 && e.beat > n - 0.5).map((e) => e.label);
      hudEl.textContent = `${K.label(t)}  ·  beat ${n.toFixed(2)}  ·  ${t.toFixed(3)}s${near.length ? '  ·  ' + near.join(' / ') : ''}`;
    }

    // ---- mount: builds stage/world/cursor, dev player, and exposes window.seek
    K.mount = (stage, o = {}) => {
      K.stage = stage;
      stage.style.width = `${K.W}px`; stage.style.height = `${K.H}px`;
      const q = new URLSearchParams(location.search);
      const render = !!global.__RENDER__ || q.has('render');
      const hud = !!global.__HUD__ || q.has('hud');
      cursorEl = document.createElement('div');
      cursorEl.className = 'mk-cursor';
      cursorEl.innerHTML = o.cursorSvg || CURSOR_SVG;
      stage.appendChild(cursorEl);
      if (hud) {
        hudEl = document.createElement('div');
        hudEl.style.cssText = 'position:absolute;left:24px;top:24px;z-index:99;font:600 30px/1.2 ui-monospace,Menlo,monospace;color:#000;background:rgba(255,255,255,.88);padding:10px 16px;border-radius:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:' + (K.W - 48) + 'px';
        stage.appendChild(hudEl);
      }
      global.seek = K.seek;
      global.K = K;
      const fonts = (o.fonts || ['400 16px Geist', '500 16px Geist', '600 16px Geist']).map((f) => document.fonts.load(f));
      // photos must be decoded before any frame is captured, or early frames render empty
      const imgs = [...stage.querySelectorAll('img')].map((img) => (img.complete && img.naturalWidth ? img.decode() : new Promise((res) => { img.onload = () => res(img.decode()); img.onerror = res; })).catch(() => {}));
      K.ready = Promise.all([...fonts, ...imgs]).then(() => document.fonts.ready).then(() => { K.seek(0); return true; });
      if (!render) K.ready.then(() => devPlayer(stage, o));
      return K;
    };

    // ---- dev player (only when you open the file in a browser; the renderer never sees it)
    function devPlayer(stage, o) {
      const fit = () => {
        const s = Math.min(innerWidth / K.W, (innerHeight - 56) / K.H);
        const x = (innerWidth - K.W * s) / 2, y = (innerHeight - 56 - K.H * s) / 2;
        stage.style.transform = `translate(${x}px, ${y}px) scale(${s})`; stage.style.transformOrigin = '0 0';
        document.body.style.height = '100vh'; document.body.style.overflow = 'hidden';
      };
      fit(); addEventListener('resize', fit);
      const bar = document.createElement('div');
      bar.style.cssText = 'position:fixed;left:0;right:0;bottom:0;height:56px;display:flex;align-items:center;gap:14px;padding:0 16px;background:#111;color:#fff;font:500 14px/1 Geist,system-ui,sans-serif;z-index:1000';
      bar.innerHTML = '<button style="all:unset;cursor:pointer;width:64px">▶ Play</button><input type="range" min="0" max="1000" value="0" style="flex:1;accent-color:#fff"><span style="width:180px;text-align:right;font-variant-numeric:tabular-nums"></span>';
      document.body.appendChild(bar);
      const [btn, range, lab] = bar.children;
      const audio = o.audio ? new Audio(o.audio) : null;
      if (audio) audio.loop = true;
      let playing = false, t0 = 0, p0 = 0, cur = 0;
      const show = (t) => { cur = t; K.seek(t); range.value = Math.round((t / K.T) * 1000); lab.textContent = `${K.label(t)}  ${t.toFixed(2)}s`; };
      const tick = () => {
        if (!playing) return;
        const t = audio && !audio.paused ? audio.currentTime % K.T : (p0 + (performance.now() - t0) / 1000) % K.T;
        show(t); requestAnimationFrame(tick);
      };
      const toggle = () => {
        playing = !playing; btn.textContent = playing ? '❚❚ Pause' : '▶ Play';
        if (playing) { t0 = performance.now(); p0 = cur; if (audio) { audio.currentTime = cur; audio.play().catch(() => {}); } requestAnimationFrame(tick); }
        else if (audio) audio.pause();
      };
      btn.onclick = toggle;
      range.oninput = () => { if (playing) toggle(); show((range.value / 1000) * K.T); };
      addEventListener('keydown', (e) => {
        if (e.code === 'Space') { e.preventDefault(); toggle(); }
        const step = e.shiftKey ? 1 / 60 : K.beat;
        if (e.code === 'ArrowRight') { if (playing) toggle(); show(mod(cur + step, K.T)); }
        if (e.code === 'ArrowLeft') { if (playing) toggle(); show(mod(cur - step, K.T)); }
      });
      show(0);
    }

    // ---- audit: called by review.py. Flags small text, clipped/cramped text,
    // overlapping swap layers, and a shape crowding the frame edge.
    K.audit = (t, o = {}) => {
      K.seek(t);
      const out = [];
      const minText = o.minText ?? 22;
      const shape = o.shape || document.querySelector('[data-shape]');
      const sr = shape ? shape.getBoundingClientRect() : null;
      const stageR = K.stage.getBoundingClientRect();
      const effOpacity = (el) => {
        let a = 1;
        for (let e = el; e && e !== K.stage; e = e.parentElement) {
          const cs = getComputedStyle(e);
          if (cs.visibility === 'hidden' || cs.display === 'none') return 0;
          a *= parseFloat(cs.opacity);
        }
        return a;
      };
      const walker = document.createTreeWalker(K.stage, NodeFilter.SHOW_TEXT);
      const range = document.createRange();
      const seen = new Set();
      while (walker.nextNode()) {
        const node = walker.currentNode, el = node.parentElement;
        if (!node.textContent.trim() || !el || seen.has(el) || el.closest('.mk-cursor') || el === hudEl) continue;
        seen.add(el);
        const op = effOpacity(el);
        if (op < 0.35) continue;
        range.selectNodeContents(node);
        const g = range.getBoundingClientRect(); // the glyphs, not the (maybe wider) element box
        // clip by overflow ancestors between the text and the shape (digit strips, masks);
        // the shape's own clip is what the checks below measure, so stop there
        let r = { left: g.left, right: g.right, top: g.top, bottom: g.bottom };
        for (let a = el; a && a !== shape && a !== K.stage; a = a.parentElement) {
          const cs = getComputedStyle(a);
          if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') {
            const ar = a.getBoundingClientRect();
            r = { left: Math.max(r.left, ar.left), right: Math.min(r.right, ar.right), top: Math.max(r.top, ar.top), bottom: Math.min(r.bottom, ar.bottom) };
          }
        }
        if (r.right - r.left < 0.5 || r.bottom - r.top < 0.5) continue; // fully clipped: not visible
        const er = el.getBoundingClientRect();
        const scale = el.offsetWidth ? er.width / el.offsetWidth : 1;
        const fs = parseFloat(getComputedStyle(el).fontSize) * scale;
        const label = node.textContent.trim().slice(0, 24);
        if (fs < minText && op > 0.6) out.push(`small text ${fs.toFixed(1)}px on screen: "${label}"`);
        if (sr && shape.contains(el) && op > 0.6) {
          const over = Math.max(sr.left - r.left, r.right - sr.right, sr.top - r.top, r.bottom - sr.bottom);
          if (over > 1.5) out.push(`text outside the shape by ${over.toFixed(0)}px: "${label}"`);
          else {
            const gap = Math.min(r.left - sr.left, sr.right - r.right, r.top - sr.top, sr.bottom - r.bottom);
            if (gap < (o.minPad ?? 10) && op > 0.9) out.push(`text cramped against the shape edge (${gap.toFixed(0)}px): "${label}"`);
          }
        }
        if (el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflow !== 'visible') out.push(`text truncated: "${label}"`);
      }
      // swap overlap: two registered layers of one group both visibly rendered at once
      const groups = {};
      for (const L of K.layers) {
        const op = effOpacity(L.el);
        const hasContent = L.el.tagName.toLowerCase() === 'svg' || L.el.textContent.trim().length > 0;
        if (op > 0.25 && hasContent) (groups[L.group] ||= []).push(`${L.el.dataset.name || L.el.id || '?'} (${op.toFixed(2)})`);
      }
      for (const g in groups) if (groups[g].length > 1) out.push(`swap overlap in "${g}": ${groups[g].join(' + ')} visible together`);
      if (sr && !shape.hasAttribute('data-bleed')) {
        // margin to the safe area (the frame edge unless K.safe was set), in frame px
        const k = stageR.width / K.W, s = K.safe;
        const m = Math.min(sr.left - stageR.left - s.l * k, stageR.left + s.r * k - sr.right,
          sr.top - stageR.top - s.t * k, stageR.top + s.b * k - sr.bottom) / k;
        const safe = s.l || s.t || s.r < K.W || s.b < K.H;
        if (m < (o.minMargin ?? 48)) out.push(`shape ${m < 0 ? `outside the ${safe ? 'safe area' : 'frame'}` : `crowds the ${safe ? 'safe area' : 'frame'} edge`} (margin ${m.toFixed(0)}px)`);
      }
      return out;
    };

    // ---- loop sanity: every track must end where it began (checked at build time)
    K.checkClosed = (tracks) => Object.entries(tracks).filter(([, f]) => f && f.closed === false).map(([k]) => k);

    return K;
  }

  // macOS-style arrow: black with a white keyline, tiny shadow for separation.
  const CURSOR_SVG = '<svg width="100%" height="100%" viewBox="0 0 32 32" style="display:block;overflow:visible;filter:drop-shadow(0 1.5px 2px rgba(0,0,0,.28))"><path d="M6.5 3.8 L6.5 24.6 L11.6 19.9 L15.1 27.6 L18.9 25.9 L15.4 18.4 L22.3 18.4 Z" fill="#0A0A0A" stroke="#FFFFFF" stroke-width="1.7" stroke-linejoin="round"/></svg>';

  global.MorphKit = { create, spring, clamp, lerp, invLerp, remap, mod, minjerk, hash, rubber, oklab, oklabToCss, mixHex, smoothPath, playPause, icon, ICONS };
})(typeof window !== 'undefined' ? window : globalThis);
