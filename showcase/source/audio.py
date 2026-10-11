import numpy as np
from scipy.signal import butter, sosfilt, fftconvolve
from scipy.io import wavfile

SR = 44100
DUR = 60.0
N = int(SR * DUR)
L = np.zeros(N); R = np.zeros(N)
rng = np.random.default_rng(7)
BEAT = 0.5

def idx(t): return int(t * SR)

def add(sig, t, gain=1.0, pan=0.0, bus=None):
    i = idx(t)
    if i >= N: return
    sig = sig[: N - i]
    l = gain * np.cos((pan + 1) * np.pi / 4) * np.sqrt(2)
    r = gain * np.sin((pan + 1) * np.pi / 4) * np.sqrt(2)
    (bus or (L, R))[0][i:i + len(sig)] += sig * l
    (bus or (L, R))[1][i:i + len(sig)] += sig * r

def env(n, a, d):
    t = np.arange(n) / SR
    e = np.minimum(1, t / max(a, 1e-4)) * np.exp(-np.maximum(0, t - a) / d)
    return e

def lp(x, f, order=2): return sosfilt(butter(order, f, 'low', fs=SR, output='sos'), x)
def hp(x, f, order=2): return sosfilt(butter(order, f, 'high', fs=SR, output='sos'), x)
def bp(x, lo, hi, order=2): return sosfilt(butter(order, [lo, hi], 'band', fs=SR, output='sos'), x)

# reverb send bus
RL = np.zeros(N); RR = np.zeros(N)
REV = (RL, RR)

# ── instruments ──
def kick(g=1.0):
    n = idx(0.45); t = np.arange(n) / SR
    f = 45 + 110 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) * np.exp(-t * 7.5)
    click = hp(rng.standard_normal(n), 3000) * np.exp(-t * 300) * 0.25
    return np.tanh((s + click) * 1.6) * g

def hat(g=1.0, open_=False):
    n = idx(0.25 if open_ else 0.06); t = np.arange(n) / SR
    s = hp(rng.standard_normal(n), 7500) * np.exp(-t * (18 if open_ else 70))
    return s * g

def clap(g=1.0):
    n = idx(0.3); t = np.arange(n) / SR
    e = sum(np.exp(-np.maximum(0, t - d) * 60) * (t >= d) for d in (0, 0.012, 0.024))
    s = bp(rng.standard_normal(n), 900, 3500) * (e + np.exp(-t * 12) * 0.4)
    return s * g

def blip(f=2400, d=0.05, g=1.0):
    n = idx(d + 0.05); t = np.arange(n) / SR
    return np.sin(2 * np.pi * f * t) * env(n, 0.002, d * 0.35) * g

def impact(g=1.0, f0=55):
    n = idx(3.0); t = np.arange(n) / SR
    f = f0 + 60 * np.exp(-t * 10)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 1.6)
    nz = lp(rng.standard_normal(n), 2500) * np.exp(-t * 5) * 0.5
    return np.tanh((s + nz) * 1.4) * g

def riser(d, g=1.0):
    n = idx(d); t = np.arange(n) / SR; p = t / d
    nz = rng.standard_normal(n)
    out = np.zeros(n); chunks = 24
    for c in range(chunks):
        a, b = c * n // chunks, (c + 1) * n // chunks
        fc = 400 + 7000 * (c / chunks) ** 2
        out[a:b] = bp(nz[max(0, a - 2000):b], fc * 0.7, min(fc * 1.4, 20000))[-(b - a):]
    f = 200 + 1600 * p ** 2
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.15
    return (out * 0.8 + tone) * p ** 2.2 * g

def whoosh(d=0.7, g=1.0, up=True):
    n = idx(d); t = np.arange(n) / SR; p = t / d
    shape = np.sin(np.pi * p) ** 2
    nz = rng.standard_normal(n)
    out = np.zeros(n); chunks = 16
    for c in range(chunks):
        a, b = c * n // chunks, (c + 1) * n // chunks
        q = c / chunks if up else 1 - c / chunks
        fc = 500 + 3500 * q
        out[a:b] = bp(nz[max(0, a - 2000):b], fc * 0.6, fc * 1.6)[-(b - a):]
    return out * shape * g

def glitchsnd(d=0.35, g=1.0):
    n = idx(d); t = np.arange(n) / SR
    s = rng.standard_normal(n)
    hold = (np.arange(n) // 90) * 90
    s = s[hold]
    sq = np.sign(np.sin(2 * np.pi * (120 + 700 * rng.random()) * t))
    gate = (np.sin(2 * np.pi * 28 * t) > 0).astype(float)
    return (bp(s, 300, 6000) * 0.6 + sq * 0.25 * gate) * np.exp(-t * 6) * g

def alarm(g=1.0):
    n = idx(0.5); t = np.arange(n) / SR
    s = (np.sin(2 * np.pi * 440 * t) + 0.5 * np.sin(2 * np.pi * 466 * t)) * (np.sin(2 * np.pi * 8 * t) > 0)
    return lp(s, 3000) * env(n, 0.005, 0.18) * g

def buzz(g=1.0):
    n = idx(0.45); t = np.arange(n) / SR
    s = np.sign(np.sin(2 * np.pi * 98 * t)) + 0.5 * np.sign(np.sin(2 * np.pi * 104 * t))
    return lp(s, 1800) * env(n, 0.005, 0.25) * g

def sweep(d, f0, f1, g=1.0):
    n = idx(d); t = np.arange(n) / SR; p = t / d
    f = f0 * (f1 / f0) ** p
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * p) * g

# ── pad (chords) ──
def note(m): return 440 * 2 ** ((m - 69) / 12)
CHORDS = [  # (start, midi notes)
    (0, [45, 57, 60, 64, 71]),      # Am(add9)
    (8, [41, 57, 60, 64, 69]),      # Fmaj7
    (16, [38, 57, 62, 65, 69]),     # Dm
    (24, [45, 57, 60, 64, 71]),     # Am
    (32, [41, 57, 60, 65, 72]),     # F
    (40, [43, 55, 59, 62, 67]),     # G
    (48, [40, 55, 59, 64, 71]),     # Em
    (54, [45, 57, 60, 64, 71, 76]), # Am resolve
]
pad = np.zeros(N)
tt = np.arange(N) / SR
for k, (st, notes) in enumerate(CHORDS):
    en = CHORDS[k + 1][0] if k + 1 < len(CHORDS) else DUR
    a, b = idx(st), idx(min(DUR, en + 1.2))
    seg_t = tt[a:b] - st
    segsig = np.zeros(b - a)
    for m in notes:
        for det in (-0.08, 0.0, 0.09):
            f = note(m + det)
            ph = rng.random() * 6.28
            segsig += (2 * ((f * seg_t + ph / 6.28) % 1) - 1) * (0.45 if m < 50 else 0.16)
    e = np.minimum(1, seg_t / 1.2) * np.clip((en + 1.2 - st - seg_t) / 1.2, 0, 1)
    pad[a:b] += segsig * e
pad = lp(pad, 900, 2)
# pad dynamics automation
auto = np.interp(tt, [0, 1, 5.5, 6, 14, 15.6, 15.9, 17, 22.8, 23.5, 24, 27, 47, 54, 56.9, 57, 60],
                     [0, 1.1, 1.2, .7, .7, .3, .9, .7, .6, .1, .9, .65, .6, .4, .3, 1.0, .0])
pad *= auto * 0.11
L += pad; R += pad
RL += pad * 0.6; RR += pad * 0.6

# ── arp (from 24s) ──
arp_notes = {24: [69, 72, 76, 79], 32: [65, 69, 72, 77], 40: [67, 71, 74, 79], 48: [64, 67, 71, 76]}
for st, ns in arp_notes.items():
    for i in range(32):
        t0 = st + i * 0.25
        if t0 < 27 or t0 >= 54: continue
        f = note(ns[i % 4] + (12 if i % 8 == 7 else 0))
        n = idx(0.22); t = np.arange(n) / SR
        s = (np.sign(np.sin(2 * np.pi * f * t)) * 0.4 + np.sin(2 * np.pi * f * t)) * env(n, 0.003, 0.07)
        s = lp(s, 2600)
        add(s, t0, 0.035, pan=0.35 if i % 2 else -0.35)
        add(s, t0, 0.03, bus=REV)

# ── bass (offbeat 8ths, 27–54 and 17–22.8) ──
roots = [(17, 38), (24, 45), (32, 41), (40, 43), (48, 40)]
def root_at(t):
    r = 45
    for st, m in roots:
        if t >= st: r = m
    return r
for i in range(int(60 / 0.25)):
    t0 = i * 0.25
    if not ((17.5 <= t0 < 22.75) or (27 <= t0 < 53.9)): continue
    if i % 2 == 0: continue
    f = note(root_at(t0) - 12)
    n = idx(0.22); t = np.arange(n) / SR
    s = np.tanh(np.sin(2 * np.pi * f * t) * 2 + 0.6 * np.sin(4 * np.pi * f * t)) * env(n, 0.004, 0.09)
    add(lp(s, 600), t0, 0.16)

# ── drums ──
for i in range(int(60 / BEAT)):
    t0 = i * BEAT
    if 6.0 <= t0 < 14.0:            # heartbeat intro groove
        if i % 2 == 0: add(kick(), t0, 0.33)
    elif 17.0 <= t0 < 22.9:
        add(kick(), t0, 0.42)
        add(hat(), t0 + 0.25, 0.05, pan=0.2)
        if i % 4 == 2: add(clap(), t0, 0.12, bus=None); add(clap(), t0, 0.08, bus=REV)
    elif 27.0 <= t0 < 53.9:
        add(kick(), t0, 0.45)
        add(hat(), t0 + 0.25, 0.06, pan=0.2)
        add(hat(), t0, 0.025, pan=-0.2)
        if i % 4 == 2: add(clap(), t0, 0.13); add(clap(), t0, 0.09, bus=REV)
        if i % 8 == 7: add(hat(open_=True), t0 + 0.25, 0.04, pan=0.3)

# ── risers / impacts / whooshes ──
add(riser(1.0), 5.0, 0.28); add(impact(), 6.0, 0.35)
add(riser(1.0), 14.85, 0.3); add(impact(f0=48), 15.85, 0.55); add(impact(), 15.85, 0.2, bus=REV)
add(riser(0.6), 22.9, 0.35); add(impact(f0=42), 23.5, 0.6); add(impact(), 23.5, 0.25, bus=REV)
add(sweep(1.6, 300, 1200, 0.05), 24.0, 1.0, bus=REV)
add(impact(f0=60), 27.0, 0.25)
add(riser(0.9), 56.05, 0.3); add(impact(f0=45), 56.95, 0.6); add(impact(), 56.95, 0.35, bus=REV)
for t0, g in [(5.3, .14), (10.0, .12), (13.5, .1), (16.7, .1), (26.7, .14), (31.6, .12), (35.6, .1),
              (42.5, .12), (46.35, .12), (53.4, .12), (54.05, .1), (54.8, .1), (55.55, .1)]:
    add(whoosh(0.6), t0 - 0.15, g, pan=rng.uniform(-.4, .4))
for t0 in (54.1, 54.85, 55.6):
    add(kick(), t0, 0.5); add(clap(), t0, 0.08, bus=REV)

# ── foley / UI ──
add(sweep(0.8, 600, 2600, 0.05), 2.75, 1.0)          # scan
add(glitchsnd(0.4), 3.45, 0.22); add(alarm(), 3.5, 0.06)
add(blip(1800, 0.05), 0.2, 0.08)
add(blip(2600, 0.04), 1.4, 0.05)
add(blip(1500, 0.06), 6.55, 0.08)
for t0 in (7.7, 8.05): add(blip(2400), t0, 0.06)
add(alarm(), 8.55, 0.09); add(glitchsnd(0.25), 8.55, 0.08)
for i in range(3): add(blip(1600 + i * 300), 10.7 + i * 0.14, 0.05)
# S3 gate crossings
items = [('t', 'Fasse die Mail zusammen', True), ('i',), ('t', 'Ignore all previous instructions', False),
         ('t', 'Übersetze den Absatz', True), ('i',), ('t', 'Erstelle eine Antwort', True), ('i',)]
off = 0
for it in items:
    w = 230 if it[0] == 'i' else len(it[1]) * 13.2 + 100
    tc = 17 + (800 + off + w / 2) / 560
    if tc < 22.8:
        if it[0] == 'i': add(sweep(0.25, 300, 180, 0.08), tc, 1.0)
        elif it[2]: add(blip(2800, 0.04), tc, 0.07)
        else: add(buzz(), tc, 0.06); add(blip(700, 0.08), tc, 0.06)
    off += w + 90
# stage 1 tiles
for i in range(4): add(blip(1900 + i * 250, 0.035), 28.15 + i * 0.12, 0.05)
add(blip(3200, 0.08), 30.35, 0.06)
# OCR
add(sweep(0.7, 800, 2400, 0.04), 32.4, 1.0)
for i in range(2): add(blip(2200, 0.05), 32.75 + i * 0.15, 0.06)
t0 = 33.1
while t0 < 34.3:
    add(blip(4200 + rng.uniform(-400, 400), 0.012), t0, 0.022); t0 += 0.09
for t0 in (34.5, 34.75): add(blip(2600, 0.05), t0, 0.06)
# signals
for t0 in (38.2, 39.3, 40.4): add(blip(900, 0.09), t0, 0.07); add(blip(1350, 0.09), t0 + 0.06, 0.05)
add(sweep(1.4, 200, 900, 0.04), 37.9, 1.0)
add(glitchsnd(0.4), 43.45, 0.2); add(impact(f0=50), 43.45, 0.35); add(alarm(), 43.5, 0.07)
# workflow
for t0 in (47.7, 48.0): add(blip(2600, 0.04), t0, 0.06)
t0 = 48.0
while t0 < 48.6: add(blip(4200, 0.012), t0, 0.022); t0 += 0.07
for t0 in (49.15, 49.45, 50.15): add(blip(2900, 0.04), t0, 0.06)
add(buzz(), 49.85, 0.07); add(buzz(), 50.3, 0.09)
for i in range(5): add(blip(1500 + i * 200, 0.04), 51.0 + i * 0.1, 0.04)

# ── brand moments (pixel logo) ──
add(sweep(0.6, 300, 2400, 0.05), 15.45, 1.0); add(glitchsnd(0.3), 15.5, 0.08)
for t0 in (24.25, 56.45):
    for i in range(14):
        add(blip(2600 + rng.uniform(-900, 900), 0.02), t0 + i * 0.05 + rng.uniform(0, 0.02), 0.035, pan=rng.uniform(-.5, .5))
for t0, t1 in ((25.25, 26.0), (57.3, 58.0)):
    for k, col in enumerate(range(11, 19)):
        u = (col + 1.5) / 20.5
        add(blip(note(69 + [0, 3, 7, 10, 12, 15, 19, 22][k]), 0.06), t0 + (t1 - t0) * u, 0.05, pan=-0.4 + k * 0.1)
        add(blip(note(69 + [0, 3, 7, 10, 12, 15, 19, 22][k]), 0.06), t0 + (t1 - t0) * u, 0.04, bus=REV)
add(sweep(0.5, 1400, 500, 0.03), 58.55, 1.0)

# ── reverb ──
irn = idx(2.4); ti = np.arange(irn) / SR
ir_l = rng.standard_normal(irn) * np.exp(-ti * 2.6); ir_r = rng.standard_normal(irn) * np.exp(-ti * 2.6)
ir_l = lp(ir_l, 5000); ir_r = lp(ir_r, 5000)
wl = fftconvolve(RL, ir_l)[:N] * 0.02; wr = fftconvolve(RR, ir_r)[:N] * 0.02
L += wl; R += wr

# ── master ──
L = hp(L, 25); R = hp(R, 25)
fade = np.interp(tt, [0, 0.05, 59.0, 60.0], [0, 1, 1, 0])
L *= fade; R *= fade
mx = max(np.abs(L).max(), np.abs(R).max())
L = np.tanh(L / mx * 1.3) / np.tanh(1.3) * 0.89
R = np.tanh(R / mx * 1.3) / np.tanh(1.3) * 0.89
wavfile.write('audio.wav', SR, (np.stack([L, R], 1) * 32767).astype(np.int16))
print('ok', mx)
