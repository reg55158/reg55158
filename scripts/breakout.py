"""Generate an animated Breakout SVG from a GitHub contribution graph.

Usage:
    GITHUB_TOKEN=... python scripts/breakout.py <username> <out_dir>

Without a token, random demo data is used (handy for local previews).
"""

import json
import math
import os
import random
import sys
import urllib.request

CELL = 11
GAP = 3
STEP = CELL + GAP
PAD = 24
GRID_TOP = 40
PADDLE_GAP = 120
PADDLE_W = 56
PADDLE_H = 6
BALL_R = 4
SPEED = 420.0  # px / second
DT = 1 / 600
MAX_SIM = 120.0
MAX_ANGLE = math.radians(58)
HOLD = 3.0

THEMES = {
    "dark": {
        "bg": "#0d1117",
        "empty": "#161b22",
        "levels": ["#0e4429", "#006d32", "#26a641", "#39d353"],
        "paddle": "#58a6ff",
        "ball": "#f0f6fc",
        "text": "#8b949e",
        "accent": "#39d353",
    },
    "light": {
        "bg": "#ffffff",
        "empty": "#ebedf0",
        "levels": ["#9be9a8", "#40c463", "#30a14e", "#216e39"],
        "paddle": "#0969da",
        "ball": "#24292f",
        "text": "#57606a",
        "accent": "#2da44e",
    },
}

LEVELS = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionLevel weekday } }
      }
    }
  }
}
"""


def fetch_grid(username, token):
    body = json.dumps({"query": QUERY, "variables": {"login": username}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as res:
        data = json.load(res)
    if "errors" in data:
        raise RuntimeError(data["errors"])
    cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    grid = []
    for w in cal["weeks"]:
        col = [None] * 7
        for d in w["contributionDays"]:
            col[d["weekday"]] = LEVELS[d["contributionLevel"]]
        grid.append(col)
    return grid, cal["totalContributions"]


def demo_grid(seed=7):
    rng = random.Random(seed)
    grid = []
    for _ in range(53):
        grid.append([rng.choice([0, 0, 0, 1, 1, 2, 3, 4]) for _ in range(7)])
    return grid, sum(sum(c) for c in grid)


class Brick:
    def __init__(self, col, row, level):
        self.col, self.row, self.level = col, row, level
        self.x = PAD + col * STEP
        self.y = GRID_TOP + row * STEP
        self.alive = True
        self.t = None

    @property
    def cx(self):
        return self.x + CELL / 2

    @property
    def cy(self):
        return self.y + CELL / 2


def simulate(grid, seed):
    rng = random.Random(seed)
    cols = len(grid)
    width = PAD * 2 + cols * STEP - GAP
    paddle_y = GRID_TOP + 7 * STEP + PADDLE_GAP
    left, right, top = PAD / 2, width - PAD / 2, GRID_TOP - 16

    bricks = {}
    for c, col in enumerate(grid):
        for r, lvl in enumerate(col):
            if lvl:
                bricks[(c, r)] = Brick(c, r, lvl)
    alive = set(bricks)

    x, y = width / 2, paddle_y - BALL_R
    ang = rng.uniform(-0.5, 0.5)
    vx, vy = SPEED * math.sin(ang), -SPEED * math.cos(ang)
    t = 0.0
    ball_path = [(0.0, x, y)]
    paddle_keys = [(0.0, width / 2)]

    def hit(bx, by):
        c0 = int((bx - BALL_R - PAD) // STEP)
        c1 = int((bx + BALL_R - PAD) // STEP)
        r0 = int((by - BALL_R - GRID_TOP) // STEP)
        r1 = int((by + BALL_R - GRID_TOP) // STEP)
        for c in range(c0, c1 + 1):
            for r in range(r0, r1 + 1):
                if (c, r) in alive:
                    b = bricks[(c, r)]
                    if (bx + BALL_R > b.x and bx - BALL_R < b.x + CELL
                            and by + BALL_R > b.y and by - BALL_R < b.y + CELL):
                        return b
        return None

    def kill(b):
        b.alive = False
        b.t = t
        alive.discard((b.col, b.row))

    while alive and t < MAX_SIM:
        t += DT
        bounced = False
        # x axis
        x += vx * DT
        if x - BALL_R < left or x + BALL_R > right:
            x = min(max(x, left + BALL_R), right - BALL_R)
            vx = -vx
            bounced = True
        b = hit(x, y)
        if b:
            kill(b)
            x -= vx * DT
            vx = -vx
            bounced = True
        # y axis
        y += vy * DT
        if y - BALL_R < top:
            y = top + BALL_R
            vy = -vy
            bounced = True
        b = hit(x, y)
        if b:
            kill(b)
            y -= vy * DT
            vy = -vy
            bounced = True
        # paddle: aim at a remaining brick
        if vy > 0 and y + BALL_R >= paddle_y:
            y = paddle_y - BALL_R
            if alive:
                tgt = bricks[rng.choice(sorted(alive))]
                a = math.atan2(tgt.cx - x, y - tgt.cy)
            else:
                a = 0.0
            a = max(-MAX_ANGLE, min(MAX_ANGLE, a + rng.uniform(-0.05, 0.05)))
            vx, vy = SPEED * math.sin(a), -SPEED * math.cos(a)
            offset = (a / MAX_ANGLE) * (PADDLE_W / 2 - 4)
            px = min(max(x - offset, PADDLE_W / 2), width - PADDLE_W / 2)
            paddle_keys.append((t, px))
            bounced = True
        if bounced:
            ball_path.append((t, x, y))

    # leftover bricks (if capped) all pop at the end
    for b in bricks.values():
        if b.alive:
            b.t = t
    ball_path.append((t, x, y))
    return bricks, ball_path, paddle_keys, t, width, paddle_y


def pct(t, total):
    return f"{100 * t / total:.3f}%"


def render(grid, total_contribs, theme, sim):
    bricks, ball_path, paddle_keys, end, width, paddle_y = sim
    th = THEMES[theme]
    total = end + HOLD + 1.0
    height = paddle_y + 40
    css, body = [], []

    css.append(
        f"svg{{background:{th['bg']}}}"
        f".e{{fill:{th['empty']}}}"
        f".b{{transform-box:fill-box;transform-origin:center;"
        f"animation:{total:.2f}s linear infinite}}"
        f".t{{font:600 12px ui-monospace,SFMono-Regular,Menlo,monospace;fill:{th['text']}}}"
    )

    for c, col in enumerate(grid):
        for r, lvl in enumerate(col):
            if lvl is None:
                continue
            body.append(
                f'<rect class="e" x="{PAD + c * STEP}" y="{GRID_TOP + r * STEP}" '
                f'width="{CELL}" height="{CELL}" rx="2"/>'
            )

    for i, b in enumerate(bricks.values()):
        p = 100 * b.t / total
        css.append(
            f"@keyframes k{i}{{0%,{p:.3f}%{{opacity:1;transform:scale(1);fill:{th['levels'][b.level - 1]}}}"
            f"{p + 0.15:.3f}%{{opacity:1;transform:scale(1.5);fill:#fff}}"
            f"{p + 0.9:.3f}%,99.5%{{opacity:0;transform:scale(0)}}100%{{opacity:1;transform:scale(1)}}}}"
        )
        body.append(
            f'<rect class="b" style="animation-name:k{i}" x="{b.x}" y="{b.y}" '
            f'width="{CELL}" height="{CELL}" rx="2" fill="{th["levels"][b.level - 1]}"/>'
        )

    # ball
    frames = [f"{pct(t, total)}{{transform:translate({x:.1f}px,{y:.1f}px)}}" for t, x, y in ball_path]
    lx, ly = ball_path[-1][1], ball_path[-1][2]
    frames.append(f"{pct(end + 0.4, total)}{{transform:translate({lx:.1f}px,{ly:.1f}px);opacity:1}}")
    frames.append(f"{pct(end + 0.8, total)},99.9%{{opacity:0}}")
    frames.append(f"100%{{transform:translate({ball_path[0][1]:.1f}px,{ball_path[0][2]:.1f}px);opacity:1}}")
    css.append("@keyframes ball{" + "".join(frames) + "}")
    css.append(f".ball{{animation:ball {total:.2f}s linear infinite}}")
    for i, (delay, op) in enumerate([(0.045, 0.15), (0.03, 0.25), (0.015, 0.45)]):
        body.append(
            f'<circle r="{BALL_R - 0.5}" fill="{th["accent"]}" opacity="{op}" class="ball" '
            f'style="animation-delay:{delay}s;animation-fill-mode:backwards"/>'
        )
    body.append(f'<circle r="{BALL_R}" fill="{th["ball"]}" class="ball"/>')

    # paddle
    frames = [f"{pct(t, total)}{{transform:translateX({px - PADDLE_W / 2:.1f}px)}}" for t, px in paddle_keys]
    frames.append(f"{pct(end + HOLD, total)}{{transform:translateX({paddle_keys[-1][1] - PADDLE_W / 2:.1f}px)}}")
    frames.append(f"100%{{transform:translateX({width / 2 - PADDLE_W / 2:.1f}px)}}")
    css.append("@keyframes pad{" + "".join(frames) + "}")
    css.append(f".pad{{animation:pad {total:.2f}s ease-in-out infinite}}")
    body.append(
        f'<rect class="pad" y="{paddle_y}" width="{PADDLE_W}" height="{PADDLE_H}" rx="3" fill="{th["paddle"]}"/>'
    )

    # HUD + victory banner
    n = len(bricks)
    body.append(f'<text class="t" x="{PAD}" y="24">BREAKOUT // {total_contribs} contributions</text>')
    body.append(f'<text class="t" x="{width - PAD}" y="24" text-anchor="end">BRICKS: {n}</text>')
    css.append(
        f"@keyframes win{{0%,{pct(end + 0.3, total)}{{opacity:0}}"
        f"{pct(end + 0.8, total)},{pct(end + HOLD, total)}{{opacity:1}}100%{{opacity:0}}}}"
        f".win{{animation:win {total:.2f}s linear infinite;opacity:0;"
        f"font:700 22px ui-monospace,SFMono-Regular,Menlo,monospace;fill:{th['accent']}}}"
    )
    body.append(
        f'<text class="win" x="{width / 2}" y="{GRID_TOP + 7 * STEP / 2 + 8}" '
        f'text-anchor="middle">ALL CLEAR!</text>'
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}"><style>{"".join(css)}</style>'
        f'<rect width="100%" height="100%" rx="6" fill="{th["bg"]}"/>{"".join(body)}</svg>'
    )


def main():
    username = sys.argv[1] if len(sys.argv) > 1 else "demo"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "dist"
    token = os.environ.get("GITHUB_TOKEN")
    grid, total = fetch_grid(username, token) if token else demo_grid()
    sim = simulate(grid, seed=username)
    os.makedirs(out_dir, exist_ok=True)
    for theme, name in [("dark", "breakout-dark.svg"), ("light", "breakout.svg")]:
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            f.write(render(grid, total, theme, sim))
    print(f"bricks={len(sim[0])} duration={sim[3]:.1f}s -> {out_dir}")


if __name__ == "__main__":
    main()
