"""Honeycomb infill: regular hexagonal cells, the same in every layer, so the
cells stack into vertical channels.

A path-pattern plugin (see templates/path_template.py for the contract).

Every hexagon edge is printed exactly once (no double-laid shared walls): the
edges are joined into long polylines by walking the grid and preferring the
straightest unused edge at each corner.  Cell side a = 2*spacing/sqrt(3) gives
1/spacing mm of strand per mm^2, the same as rectilinear at that spacing, so
Infill % means the same thing.  The grid is turned by the base angle.
"""
import math

PATTERN = {
    "name": "Honeycomb",
    "description": "Hexagonal cells stacked into vertical channels (base angle turns the grid). "
                   "Many short strands: every cell corner joins three walls.",
}


def generate(region, layer, settings, spacing):
    a = 2.0 * spacing / math.sqrt(3.0)           # hexagon side
    h = math.sqrt(3.0) / 2.0 * a                 # half the hexagon height (flat-top)
    theta = math.radians(settings.infill_angle)
    c, s = math.cos(theta), math.sin(theta)

    # cover the region's bounding circle in grid coordinates
    minx, miny, maxx, maxy = region.bounds
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    r = math.hypot(maxx - minx, maxy - miny) / 2.0 + 2 * a

    def key(x, y):
        return (round(x, 6), round(y, 6))

    adj = {}

    def edge(p, q):
        kp, kq = key(*p), key(*q)
        adj.setdefault(kp, set()).add(kq)
        adj.setdefault(kq, set()).add(kp)

    # flat-top hexagons: centres on columns 1.5a apart, rows 2h apart, odd
    # columns shifted by h
    cols = int(2 * r / (1.5 * a)) + 2
    rows = int(2 * r / (2 * h)) + 2
    for i in range(-cols // 2, cols // 2 + 1):
        for j in range(-rows // 2, rows // 2 + 1):
            hx = i * 1.5 * a
            hy = j * 2 * h + (h if i % 2 else 0.0)
            corners = [(hx + a * math.cos(math.radians(60 * k)),
                        hy + a * math.sin(math.radians(60 * k))) for k in range(6)]
            for k in range(6):
                edge(corners[k], corners[(k + 1) % 6])

    def to_world(p):
        x, y = p
        return (cx + x * c - y * s, cy + x * s + y * c)

    def turn(prev, cur, nxt):
        ax, ay = cur[0] - prev[0], cur[1] - prev[1]
        bx, by = nxt[0] - cur[0], nxt[1] - cur[1]
        return -(ax * bx + ay * by)              # smaller = straighter

    strokes = []
    # start walks at odd-degree corners first so paths end where they must
    starts = sorted(adj, key=lambda v: (len(adj[v]) % 2 == 0, v))
    for start in starts:
        while adj.get(start):
            path = [start]
            cur, prev = start, None
            while adj.get(cur):
                options = adj[cur]
                nxt = min(options, key=lambda q: turn(prev, cur, q)) if prev else min(options)
                adj[cur].discard(nxt)
                adj[nxt].discard(cur)
                path.append(nxt)
                prev, cur = cur, nxt
            strokes.append([to_world(p) for p in path])
    return strokes
