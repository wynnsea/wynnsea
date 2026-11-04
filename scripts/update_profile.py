#!/usr/bin/env python3
"""Refreshes the profile from GitHub: the commit tide chart and the projects table.

Needs a token in GH_TOKEN. GitHub Actions provides one automatically.
To run it locally: GH_TOKEN=$(gh auth token) python3 scripts/update_profile.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USERNAME = "wynnsea"
ROOT = Path(__file__).resolve().parent.parent
TABLE_START, TABLE_END = "<!-- projects:start -->", "<!-- projects:end -->"

W, H = 720, 270
LEFT, RIGHT, TOP, BASE = 26, 694, 92, 216
FONT = "Georgia,'Times New Roman',Times,serif"

THEMES = {
    "light": dict(water="#A8D2E3", shallow="#DAEDF2", line="#12324A", text="#12324A", muted="#3D6478", mark="#B3126F"),
    "dark": dict(water="#24566F", shallow="#163A51", line="#E9F3F2", text="#E9F3F2", muted="#86AEBF", mark="#F06CB8"),
}


def plural(n):
    return f"{n:,} commit" + ("" if n == 1 else "s")


def points(commits):
    top = max(max(v for _, v in commits), 1)
    step = (RIGHT - LEFT) / (len(commits) - 1)
    return [(LEFT + i * step, BASE - (v / top) * (BASE - TOP)) for i, (_, v) in enumerate(commits)]


def curve(pts):
    """Catmull-Rom spline as cubic Beziers, clamped so the tide never overshoots its peak."""
    d = f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"
    for i in range(len(pts) - 1):
        p0, p1, p2, p3 = pts[max(i - 1, 0)], pts[i], pts[i + 1], pts[min(i + 2, len(pts) - 1)]
        c1y = min(max(p1[1] + (p2[1] - p0[1]) / 6, min(p1[1], p2[1])), max(p1[1], p2[1]))
        c2y = min(max(p2[1] - (p3[1] - p1[1]) / 6, min(p1[1], p2[1])), max(p1[1], p2[1]))
        d += f"C{p1[0] + (p2[0] - p0[0]) / 6:.1f} {c1y:.1f} {p2[0] - (p3[0] - p1[0]) / 6:.1f} {c2y:.1f} {p2[0]:.1f} {p2[1]:.1f}"
    return d


def svg(t, commits):
    pts = points(commits)
    line = curve(pts)
    total = sum(v for _, v in commits)
    peak = max(range(len(commits)), key=lambda i: commits[i][1])
    px, py = pts[peak]
    # Keep the high-water label inside the frame whichever month peaks.
    anchor = "end" if px > W * 0.6 else "start"
    lx = px - 12 if anchor == "end" else px + 12
    high_water = "" if not commits[peak][1] else (
        f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{px:.1f}" y2="{BASE}" stroke="{t["mark"]}" stroke-width="2" stroke-dasharray="7 5"/>'
        f'<circle cx="{px:.1f}" cy="{py:.1f}" r="6" fill="{t["mark"]}"/>'
        f'<text x="{lx:.1f}" y="{py - 16:.1f}" text-anchor="{anchor}" fill="{t["mark"]}" font-size="21" font-style="italic">'
        f'High water, {plural(commits[peak][1])}</text>'
    )
    months = "".join(
        f'<text x="{x:.1f}" y="{BASE + 32}" text-anchor="middle" fill="{t["muted"]}" font-size="19">{m}</text>'
        for (m, _), (x, _) in zip(commits, pts)
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Tide chart of {plural(total)} over the last 12 months" font-family="{FONT}">
<path d="{line}L{RIGHT} {BASE}L{LEFT} {BASE}Z" fill="{t["shallow"]}"/>
<path d="{line}" fill="none" stroke="{t["water"]}" stroke-width="9" stroke-linecap="round" opacity=".9"/>
<path d="{line}" fill="none" stroke="{t["line"]}" stroke-width="2.2" stroke-linecap="round"/>
<line x1="{LEFT}" y1="{BASE}" x2="{RIGHT}" y2="{BASE}" stroke="{t["line"]}" stroke-width="1.5"/>
{high_water}
<text x="{LEFT}" y="26" fill="{t["text"]}" font-size="21" font-style="italic">{plural(total)} over the last 12 months</text>
{months}
</svg>
'''


def graphql(query):
    token = os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("GH_TOKEN is not set. Run: GH_TOKEN=$(gh auth token) python3 scripts/update_profile.py")
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"Bearer {token}", "User-Agent": "profile-readme-updater"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.URLError as error:
        sys.exit(f"GitHub API request failed: {error}")
    if result.get("errors"):
        sys.exit(f"GitHub API returned errors: {result['errors']}")
    return result["data"]["user"]


def last_12_months(now):
    """(first letter, start, end) for each month, oldest first, ending with the current month."""
    months = []
    for back in range(11, -1, -1):
        total = now.year * 12 + now.month - 1 - back
        start = datetime(total // 12, total % 12 + 1, 1, tzinfo=timezone.utc)
        following = total + 1
        end = datetime(following // 12, following % 12 + 1, 1, tzinfo=timezone.utc)
        months.append((start.strftime("%b")[0], start, min(end, now)))
    return months


REPO_FIELDS = "name url description isPrivate primaryLanguage { name }"


def fetch(now):
    months = last_12_months(now)
    ranges = "\n".join(
        f'm{i}: contributionsCollection(from: "{start.isoformat()}", to: "{end.isoformat()}") {{ totalCommitContributions }}'
        for i, (_, start, end) in enumerate(months)
    )
    user = graphql(f"""{{ user(login: "{USERNAME}") {{
        {ranges}
        pinnedItems(first: 6, types: REPOSITORY) {{ nodes {{ ... on Repository {{ {REPO_FIELDS} }} }} }}
        repositories(first: 7, ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false,
                     orderBy: {{field: PUSHED_AT, direction: DESC}}) {{ nodes {{ {REPO_FIELDS} }} }}
    }} }}""")
    commits = [(m[0], user[f"m{i}"]["totalCommitContributions"]) for i, m in enumerate(months)]
    # Pinned repos win. Recently pushed public repos fill in until something is pinned.
    # A token that can read private repos could return private pins, so those are always dropped.
    pinned = [r for r in user["pinnedItems"]["nodes"] if not r["isPrivate"]]
    recent = [r for r in user["repositories"]["nodes"] if r["name"] != USERNAME][:6]
    return commits, pinned or recent


def cell(text):
    return " ".join((text or "").split()).replace("|", "\\|")


def write_projects(repos):
    if repos:
        # An all-empty column looks broken, so it only appears once a repo has a description.
        described = any(cell(r["description"]) for r in repos)
        rows = ["| Project | What it does | Built with |", "| :--- | :--- | :--- |"] if described else [
            "| Project | Built with |", "| :--- | :--- |"]
        for r in repos:
            language = (r["primaryLanguage"] or {}).get("name", "")
            middle = f" {cell(r['description'])} |" if described else ""
            rows.append(f"| [{cell(r['name'])}]({r['url']}) |{middle} {cell(language)} |")
        table = "\n".join(rows)
    else:
        table = "Nothing public yet."
    readme = ROOT / "README.md"
    text = readme.read_text()
    if TABLE_START not in text or TABLE_END not in text:
        sys.exit(f"README.md is missing the {TABLE_START} and {TABLE_END} markers.")
    before, rest = text.split(TABLE_START, 1)
    after = rest.split(TABLE_END, 1)[1]
    readme.write_text(f"{before}{TABLE_START}\n{table}\n{TABLE_END}{after}")


def main():
    commits, repos = fetch(datetime.now(timezone.utc))
    for name, theme in THEMES.items():
        (ROOT / "assets" / f"tide-{name}.svg").write_text(svg(theme, commits))
    write_projects(repos)
    print(f"{sum(v for _, v in commits)} commits, {len(repos)} projects")


if __name__ == "__main__":
    main()
