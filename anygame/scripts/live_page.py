"""One self-contained HTML page from a `--live` directory: the latest screen, a strip of recent screens, the milestones
and the last moves, images inlined, so it can be published or mailed as a snapshot of where a run is.

    python scripts/live_page.py /mnt/project-files/anygame/pokemon-red/live out.html [--run "stand-in"] ...
"""
from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path


def _img(p: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


def section(d: Path, label: str) -> str:
    s = json.loads((d / "status.json").read_text())
    frames = sorted((d / "frames").glob("*.png")) if (d / "frames").exists() else []
    strip = frames[-48::8][-6:]
    f = s.get("facts") or {}
    found = s.get("found") or {}
    pos = f"x {found.get('x')}, y {found.get('y')}" if found.get("x") is not None else "not found yet"
    truth = f"{f.get('map_name', '?')} ({f.get('x')}, {f.get('y')})" if f else "?"
    ms = "".join(f"<li><b>{html.escape(m['milestone'])}</b> <span class=dim>tick {m['tick']} · {m['at']}</span></li>" for m in s.get("milestone_log", [])) or "<li class=dim>none yet</li>"
    moves = "".join(f"<tr><td class=num>{r['tick']}</td><td>{html.escape(str(r['action']))}</td><td>{r.get('screen') or ''}</td><td>{'Jev' if r.get('jev') else 'auto/top'}</td></tr>" for r in reversed(s.get("recent", [])[-8:]))
    goal = (s.get("goal") or {}).get("instruction") if isinstance(s.get("goal"), dict) else s.get("goal")
    party = f.get("party_count", 0)
    return f"""
<section class=run>
  <div class=screen><img src="{_img(d / 'frame.png')}" alt="Game Boy screen at tick {s['tick']}"></div>
  <div class=info>
    <p class=eyebrow>{html.escape(label)}</p>
    <h2>Tick {s['tick']} <span class=chip>{html.escape(str(s.get('screen')))}</span></h2>
    <dl>
      <dt>Updated</dt><dd>{s['updated']}</dd>
      <dt>Where (grader)</dt><dd>{html.escape(truth)}</dd>
      <dt>Position it found</dt><dd>{pos}</dd>
      <dt>Party / badges</dt><dd>{party} Pokémon · {f.get('badges', 0)} badges</dd>
      <dt>Goal</dt><dd>{html.escape(str(goal or '—'))}</dd>
      <dt>Jev spend</dt><dd>${s.get('cost_usd', 0):.4f}</dd>
    </dl>
    <h3>Milestones ({len(s.get('milestones', []))} of {32 if f else '?'})</h3><ul class=ms>{ms}</ul>
  </div>
  <div class=strip>{''.join(f'<figure><img src="{_img(p)}" alt=""><figcaption>tick {int(p.stem)}</figcaption></figure>' for p in strip)}</div>
  <div class=moves><table><thead><tr><th>Tick</th><th>Move</th><th>Screen</th><th>By</th></tr></thead><tbody>{moves}</tbody></table></div>
</section>"""


CSS = """
:root{--bg:#e8eadf;--panel:#f4f5ee;--fg:#1f2a1c;--dim:#5d6a57;--line:#c9cfbd;--accent:#b4202a;--chip:#2f4a2a;
--display:"Press Start 2P",ui-monospace,monospace;--body:"IBM Plex Sans",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141912;--panel:#1d241a;--fg:#e2e8d8;--dim:#9aa891;--line:#33402e;--accent:#ff5a5f;--chip:#9fc58f;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#141912;--panel:#1d241a;--fg:#e2e8d8;--dim:#9aa891;--line:#33402e;--accent:#ff5a5f;--chip:#9fc58f;color-scheme:dark}
body{background:var(--bg);color:var(--fg);font:15px/1.5 var(--body);padding-inline:16px;padding-block:20px 40px}
main{max-width:1000px;margin:0 auto;display:grid;gap:28px}
h1{font:16px/1.6 var(--display);margin:0;letter-spacing:.02em;text-wrap:balance}
.lede{color:var(--dim);margin:6px 0 0;max-width:65ch}
.run{display:grid;grid-template-columns:minmax(0,480px) minmax(0,1fr);gap:20px;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:16px}
@media (max-width:760px){.run{grid-template-columns:1fr}}
.screen img{width:100%;image-rendering:pixelated;border:6px solid var(--fg);border-radius:4px;display:block;background:#fff}
.info{min-width:0}.eyebrow{font:11px var(--mono);text-transform:uppercase;letter-spacing:.12em;color:var(--accent);margin:0}
h2{font:14px/1.8 var(--display);margin:4px 0 10px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.chip{font:12px var(--mono);color:var(--bg);background:var(--chip);padding:1px 8px;border-radius:10px}
h3{font:12px var(--mono);text-transform:uppercase;letter-spacing:.1em;color:var(--dim);margin:14px 0 4px}
dl{display:grid;grid-template-columns:auto 1fr;gap:3px 14px;margin:0}dt{color:var(--dim)}dd{margin:0;font-variant-numeric:tabular-nums;min-width:0;overflow-wrap:anywhere}
.ms{margin:0;padding-left:18px}.dim{color:var(--dim);font-size:13px}
.strip{grid-column:1/-1;display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px}
figure{margin:0}figure img{width:100%;image-rendering:pixelated;border:1px solid var(--line)}figcaption{font:11px var(--mono);color:var(--dim)}
.moves{grid-column:1/-1;overflow-x:auto}table{border-collapse:collapse;width:100%;font:13px var(--mono)}
th,td{text-align:left;padding:4px 8px;border-bottom:1px solid var(--line)}th{color:var(--dim);font-weight:500}.num{font-variant-numeric:tabular-nums}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--run", nargs=2, action="append", metavar=("DIR", "LABEL"), required=True)
    ap.add_argument("--title", default="Pokémon Red Live")
    a = ap.parse_args()
    body = "".join(section(Path(d), label) for d, label in a.run if (Path(d) / "status.json").exists())
    Path(a.out).write_text(f"""<title>{html.escape(a.title)}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;600&family=Press+Start+2P&display=swap">
<style>{CSS}</style>
<main><header><h1>{html.escape(a.title)}</h1><p class=lede>Snapshot of the run as it plays: the latest screen, recent screens, milestones the grader has seen, and the last moves. Republished every few minutes while a run is live.</p></header>{body}</main>""")


if __name__ == "__main__":
    main()
