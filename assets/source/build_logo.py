"""VIPI pixel logo – 'VI' in solid pixels, hidden 'PI' as micro-pixels on the same grid.
Builds all SVG files into ./out_pixel"""
import os
from shapely.geometry import box
from shapely.ops import unary_union

OUT = os.environ.get('VIPI_OUT', 'out_pixel'); os.makedirs(OUT, exist_ok=True)
DARK, LIGHT = '#0B0C10', '#F2F3F5'
TITLE = 'VIPI'
U = 10            # pixel size in SVG units
DOT = 0.30        # hidden pixels: 30 % of a full pixel
ROWS = 7
GLYPHS = {
    'V': ["XX...XX", "XX...XX", "XX...XX", ".XX.XX.", ".XX.XX.", "..XXX..", "...X..."],
    'I': ["XX"] * 7,
    'P': ["XXXX.", "XX.XX", "XX.XX", "XXXX.", "XX...", "XX...", "XX..."],
}

def n(v): return f'{v:.2f}'.rstrip('0').rstrip('.')

def cells(word, x0=0, y0=0):
    out, x = [], x0
    for ch in word:
        g = GLYPHS[ch]
        out += [(x + c, y0 + r) for r, row in enumerate(g) for c, v in enumerate(row) if v == 'X']
        x += len(g[0]) + 1
    return out, x - 1

def solid_d(cs, ox=0, oy=0, u=U):
    geom = unary_union([box(x, y, x + 1, y + 1) for x, y in cs])
    parts = []
    for g in getattr(geom, 'geoms', [geom]):
        for ring in [g.exterior, *g.interiors]:
            pts = list(ring.coords)[:-1]
            # drop collinear points
            keep = [p for i, p in enumerate(pts)
                    if not ((pts[i-1][0] == p[0] == pts[(i+1) % len(pts)][0]) or (pts[i-1][1] == p[1] == pts[(i+1) % len(pts)][1]))]
            parts.append('M' + ' L'.join(f'{n(ox + x*u)},{n(oy + y*u)}' for x, y in keep) + ' Z')
    return ' '.join(parts)

def dots_d(cs, ox=0, oy=0, u=U, s=DOT):
    o = (1 - s) / 2
    return ' '.join(f'M{n(ox + (x+o)*u)},{n(oy + (y+o)*u)} h{n(s*u)} v{n(s*u)} h{n(-s*u)} Z' for x, y in cs)

VI, W_VI = cells('VI')
PI, W_ALL = cells('PI', x0=W_VI + 1)
PI_ST, W_PI = cells('PI', x0=1, y0=ROWS + 1)          # stacked variant

def svg(w, h, body, vb=None):
    vb = vb or f'0 0 {n(w)} {n(h)}'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" width="{n(w)}" height="{n(h)}" '
            f'role="img" aria-label="{TITLE}"><title>{TITLE}</title>{body}</svg>\n')
def write(name, s): open(f'{OUT}/{name}', 'w').write(s)

def logo(fill, ox=0, oy=0, u=U):
    return f'<path fill="{fill}" d="{solid_d(VI, ox, oy, u)} {dots_d(PI, ox, oy, u)}"/>'
def logo_stacked(fill, ox=0, oy=0, u=U):
    return f'<path fill="{fill}" d="{solid_d(VI, ox, oy, u)} {dots_d(PI_ST, ox, oy, u)}"/>'

LW, LH = W_ALL * U, ROWS * U
# 1 · primary logo
write('vipi-logo-white.svg', svg(LW, LH, logo(LIGHT)))
write('vipi-logo-black.svg', svg(LW, LH, logo(DARK)))
# 2 · stacked logo
SW, SH = W_VI * U, (2 * ROWS + 1) * U
write('vipi-logo-stacked-white.svg', svg(SW, SH, logo_stacked(LIGHT)))
write('vipi-logo-stacked-black.svg', svg(SW, SH, logo_stacked(DARK)))

# 4 · app icon (stacked, 512) + favicon (VI only)
def icon(bg, fg, size=512):
    u = 21; ox = (512 - SW / U * u) / 2; oy = (512 - SH / U * u) / 2
    return svg(size, size, f'<rect width="512" height="512" rx="112" fill="{bg}"/>' + logo_stacked(fg, ox, oy, u), vb='0 0 512 512')
write('vipi-icon-dark.svg', icon(DARK, LIGHT))
write('vipi-icon-light.svg', icon('#FFFFFF', DARK))
def favicon():
    u = 2.6; ox = (32 - W_VI * u) / 2; oy = (32 - ROWS * u) / 2
    return svg(32, 32, f'<rect width="32" height="32" rx="7" fill="{DARK}"/><path fill="{LIGHT}" d="{solid_d(VI, ox, oy, u)}"/>', vb='0 0 32 32')
write('vipi-favicon.svg', favicon())

# 5 · animated reveal: scan line sweeps left→right, hidden pixels grow to full size, then sink back
def reveal():
    pw, ph = 960, 400; u = 36
    ox = (pw - W_ALL * u) / 2; oy = (ph - ROWS * u) / 2
    D = 6.0; t0, t1 = 0.10, 0.45            # scan from t0 to t1 (fraction of loop)
    x_start, x_end = ox - 30, ox + W_ALL * u + 30
    b = f'<rect width="{pw}" height="{ph}" fill="{DARK}"/><path fill="{LIGHT}" d="{solid_d(VI, ox, oy, u)}"/>'
    for (x, y) in PI:
        cx = ox + (x + .5) * u; cy = oy + (y + .5) * u
        k = t0 + (t1 - t0) * (cx - x_start) / (x_end - x_start)
        kt = f'0;{k:.3f};{min(k+.06,.7):.3f};.78;.9;1'
        b += (f'<g transform="translate({n(cx)},{n(cy)})"><rect x="{-u/2}" y="{-u/2}" width="{u}" height="{u}" fill="{LIGHT}" transform="scale({DOT})">'
              f'<animateTransform attributeName="transform" type="scale" values="{DOT};{DOT};1;1;{DOT};{DOT}" keyTimes="{kt}" '
              f'dur="{D}s" repeatCount="indefinite" calcMode="spline" keySplines="0 0 1 1;.2 .8 .2 1;0 0 1 1;.6 0 .4 1;0 0 1 1"/></rect></g>')
    b += (f'<rect x="{n(x_start)}" y="{n(oy - 40)}" width="2" height="{n(ROWS*u + 80)}" fill="{LIGHT}" opacity="0">'
          f'<animate attributeName="x" values="{n(x_start)};{n(x_start)};{n(x_end)};{n(x_end)}" keyTimes="0;{t0};{t1};1" dur="{D}s" repeatCount="indefinite"/>'
          f'<animate attributeName="opacity" values="0;0;.85;.85;0;0" keyTimes="0;{t0-.01:.2f};{t0+.01:.2f};{t1-.01:.2f};{t1+.02:.2f};1" dur="{D}s" repeatCount="indefinite"/></rect>')
    return svg(pw, ph, b)
write('vipi-reveal.svg', reveal())
print(sorted(os.listdir(OUT)))
