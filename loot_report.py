"""
Loot report — generates a self-contained interactive HTML file
from the loot data (all-time totals + per-session breakdowns).
"""

import json
from typing import Dict, List


# WoW-inspired colour palette for fish items
_COLOURS = [
    "#4FC3F7",  # light blue
    "#81C784",  # green
    "#FFB74D",  # orange
    "#E57373",  # red
    "#BA68C8",  # purple
    "#FFD54F",  # gold
    "#4DB6AC",  # teal
    "#F06292",  # pink
    "#90A4AE",  # grey-blue
    "#AED581",  # lime
    "#7986CB",  # indigo
    "#FF8A65",  # deep orange
]


def _colour(i: int) -> str:
    return _COLOURS[i % len(_COLOURS)]


def _item_rows_html(items: List[Dict], max_count: int) -> str:
    rows = []
    for i, item in enumerate(items):
        bar_width = (item["count"] / max_count * 100) if max_count else 0
        colour = _colour(i)
        rows.append(f"""
        <div class="item-row">
          <div class="item-name">{item["name"]}</div>
          <div class="item-bar-bg">
            <div class="item-bar" style="width:{bar_width:.1f}%;background:{colour}"></div>
          </div>
          <div class="item-count">x{item["count"]}</div>
          <div class="item-pct">{item["pct"]:.1f}%</div>
        </div>""")
    return "\n".join(rows)


def _donut_data_js(items: List[Dict]) -> str:
    entries = []
    for i, item in enumerate(items):
        entries.append(
            f'{{name:"{item["name"]}",count:{item["count"]},'
            f'pct:{item["pct"]},colour:"{_colour(i)}"}}'
        )
    return "[" + ",".join(entries) + "]"


def _session_html(idx: int, session: Dict) -> str:
    start = session["start"].replace("T", " ")
    end = session["end"].replace("T", " ")
    total = session["total"]
    items = session["items"]
    max_count = items[0]["count"] if items else 1

    return f"""
    <div class="session" id="session-{idx}">
      <div class="session-header" onclick="toggleSession({idx})">
        <span class="session-arrow" id="arrow-{idx}">\u25b6</span>
        <span class="session-title">Session {idx + 1}</span>
        <span class="session-meta">{start} \u2014 {end}</span>
        <span class="session-total">{total} fish</span>
      </div>
      <div class="session-body" id="body-{idx}" style="display:none">
        <div class="session-content">
          <div class="session-chart">
            <canvas id="donut-{idx}" width="180" height="180"></canvas>
          </div>
          <div class="session-items">
            {_item_rows_html(items, max_count)}
          </div>
        </div>
      </div>
    </div>"""


def generate_loot_html(data: Dict) -> str:
    all_time = data.get("all_time", {"total": 0, "items": []})
    sessions = data.get("sessions", [])
    total = all_time["total"]
    items = all_time["items"]
    max_count = items[0]["count"] if items else 1

    sessions_html = "\n".join(
        _session_html(i, s) for i, s in enumerate(sessions)
    )

    # Build JS data for all donut charts
    donut_datasets = {
        "allTime": _donut_data_js(items),
    }
    for i, s in enumerate(sessions):
        donut_datasets[f"session{i}"] = _donut_data_js(s["items"])

    donut_init_js = f"drawDonut(document.getElementById('donut-all'), {donut_datasets['allTime']});\n"
    # Session donuts are drawn when opened (lazy)

    session_donut_cases = "\n".join(
        f"    case {i}: drawDonut(document.getElementById('donut-{i}'), {donut_datasets[f'session{i}']}); break;"
        for i in range(len(sessions))
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Laksefisk Loot Report</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: #0a0e17;
    color: #e0e0e0;
    min-height: 100vh;
  }}
  .container {{ max-width: 900px; margin: 0 auto; padding: 20px; }}

  /* Header */
  .header {{
    text-align: center;
    padding: 30px 0 20px;
    border-bottom: 1px solid #1e2a3a;
    margin-bottom: 24px;
  }}
  .header h1 {{
    font-size: 28px;
    color: #4FC3F7;
    letter-spacing: 2px;
    margin-bottom: 6px;
  }}
  .header .fish-icon {{ font-size: 36px; }}
  .header .subtitle {{ color: #607D8B; font-size: 14px; }}

  /* All-time card */
  .card {{
    background: #111827;
    border: 1px solid #1e2a3a;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
  }}
  .card-title {{
    font-size: 18px;
    font-weight: 600;
    color: #4FC3F7;
    margin-bottom: 4px;
  }}
  .card-total {{
    font-size: 40px;
    font-weight: 700;
    color: #fff;
    margin: 8px 0;
  }}
  .card-total span {{ color: #607D8B; font-size: 16px; font-weight: 400; }}

  /* Layout: chart + items */
  .overview {{
    display: flex;
    gap: 24px;
    align-items: flex-start;
    flex-wrap: wrap;
  }}
  .overview-chart {{
    flex: 0 0 200px;
    display: flex;
    justify-content: center;
    padding-top: 8px;
  }}
  .overview-items {{ flex: 1; min-width: 300px; }}

  /* Item rows */
  .item-row {{
    display: flex;
    align-items: center;
    padding: 6px 0;
    gap: 10px;
    border-bottom: 1px solid #1a2233;
  }}
  .item-row:last-child {{ border-bottom: none; }}
  .item-name {{
    flex: 0 0 220px;
    font-size: 14px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .item-bar-bg {{
    flex: 1;
    height: 16px;
    background: #1a2233;
    border-radius: 8px;
    overflow: hidden;
    min-width: 80px;
  }}
  .item-bar {{
    height: 100%;
    border-radius: 8px;
    transition: width 0.5s ease;
  }}
  .item-count {{
    flex: 0 0 45px;
    text-align: right;
    font-size: 13px;
    color: #90A4AE;
    font-family: 'Consolas', monospace;
  }}
  .item-pct {{
    flex: 0 0 50px;
    text-align: right;
    font-size: 13px;
    color: #4FC3F7;
    font-weight: 600;
    font-family: 'Consolas', monospace;
  }}

  /* Sessions */
  .sessions-title {{
    font-size: 18px;
    color: #4FC3F7;
    margin: 24px 0 12px;
    padding-left: 4px;
  }}
  .session {{
    background: #111827;
    border: 1px solid #1e2a3a;
    border-radius: 10px;
    margin-bottom: 8px;
    overflow: hidden;
  }}
  .session-header {{
    display: flex;
    align-items: center;
    padding: 12px 16px;
    cursor: pointer;
    gap: 12px;
    transition: background 0.15s;
  }}
  .session-header:hover {{ background: #1a2233; }}
  .session-arrow {{
    color: #4FC3F7;
    font-size: 12px;
    transition: transform 0.2s;
    flex: 0 0 16px;
  }}
  .session-arrow.open {{ transform: rotate(90deg); }}
  .session-title {{ font-weight: 600; font-size: 15px; }}
  .session-meta {{ color: #607D8B; font-size: 13px; flex: 1; }}
  .session-total {{
    background: #1a2233;
    color: #4FC3F7;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 13px;
    font-weight: 600;
  }}
  .session-body {{ border-top: 1px solid #1e2a3a; }}
  .session-content {{
    display: flex;
    gap: 20px;
    padding: 16px;
    align-items: flex-start;
    flex-wrap: wrap;
  }}
  .session-chart {{
    flex: 0 0 180px;
    display: flex;
    justify-content: center;
  }}
  .session-items {{ flex: 1; min-width: 280px; }}

  /* Tooltip */
  .tooltip {{
    position: fixed;
    background: #1e2a3a;
    color: #e0e0e0;
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 13px;
    pointer-events: none;
    z-index: 100;
    border: 1px solid #2a3a4a;
    display: none;
  }}

  /* Footer */
  .footer {{
    text-align: center;
    padding: 20px 0;
    color: #37474F;
    font-size: 12px;
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="fish-icon">\U0001F41F</div>
    <h1>LAKSEFISK</h1>
    <div class="subtitle">Loot Report &mdash; {len(sessions)} session(s)</div>
  </div>

  <div class="card">
    <div class="card-title">All Time</div>
    <div class="card-total">{total} <span>fish caught</span></div>
    <div class="overview">
      <div class="overview-chart">
        <canvas id="donut-all" width="200" height="200"></canvas>
      </div>
      <div class="overview-items">
        {_item_rows_html(items, max_count)}
      </div>
    </div>
  </div>

  <div class="sessions-title">Sessions</div>
  {sessions_html}

  <div class="footer">Generated by Laksefisk</div>
</div>

<div class="tooltip" id="tooltip"></div>

<script>
function drawDonut(canvas, data) {{
  if (!canvas || canvas.dataset.drawn) return;
  canvas.dataset.drawn = "1";
  const ctx = canvas.getContext("2d");
  const cx = canvas.width / 2, cy = canvas.height / 2;
  const r = Math.min(cx, cy) - 10;
  const inner = r * 0.55;
  const total = data.reduce((s, d) => s + d.count, 0);
  let angle = -Math.PI / 2;

  // Store segments for hover
  canvas._segments = [];

  data.forEach(d => {{
    const slice = (d.count / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(angle) * inner, cy + Math.sin(angle) * inner);
    ctx.arc(cx, cy, r, angle, angle + slice);
    ctx.arc(cx, cy, inner, angle + slice, angle, true);
    ctx.closePath();
    ctx.fillStyle = d.colour;
    ctx.fill();

    canvas._segments.push({{
      startAngle: angle, endAngle: angle + slice,
      name: d.name, count: d.count, pct: d.pct, colour: d.colour
    }});

    angle += slice;
  }});

  // Centre text
  ctx.fillStyle = "#fff";
  ctx.font = "bold 22px 'Segoe UI'";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(total, cx, cy - 8);
  ctx.fillStyle = "#607D8B";
  ctx.font = "12px 'Segoe UI'";
  ctx.fillText("total", cx, cy + 12);

  // Hover
  const tooltip = document.getElementById("tooltip");
  canvas.addEventListener("mousemove", e => {{
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left - cx;
    const my = e.clientY - rect.top - cy;
    const dist = Math.sqrt(mx * mx + my * my);
    let a = Math.atan2(my, mx);
    if (a < -Math.PI / 2) a += Math.PI * 2;

    let hit = null;
    if (dist >= inner && dist <= r) {{
      for (const seg of canvas._segments) {{
        let sa = seg.startAngle, ea = seg.endAngle;
        if (a >= sa && a < ea) {{ hit = seg; break; }}
      }}
    }}
    if (hit) {{
      tooltip.style.display = "block";
      tooltip.style.left = (e.clientX + 14) + "px";
      tooltip.style.top = (e.clientY - 10) + "px";
      tooltip.innerHTML = `<b>${{hit.name}}</b><br>x${{hit.count}} &mdash; ${{hit.pct.toFixed(1)}}%`;
    }} else {{
      tooltip.style.display = "none";
    }}
  }});
  canvas.addEventListener("mouseleave", () => {{
    tooltip.style.display = "none";
  }});
}}

function toggleSession(idx) {{
  const body = document.getElementById("body-" + idx);
  const arrow = document.getElementById("arrow-" + idx);
  if (body.style.display === "none") {{
    body.style.display = "block";
    arrow.classList.add("open");
    // Lazy draw donut
    switch(idx) {{
{session_donut_cases}
    }}
  }} else {{
    body.style.display = "none";
    arrow.classList.remove("open");
  }}
}}

// Draw all-time donut on load
{donut_init_js}
</script>
</body>
</html>"""
