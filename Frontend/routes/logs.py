# logs.py  (patched)
from flask import Blueprint, jsonify, request, render_template_string
from pathlib import Path
import json
import base64
import csv

logs_bp = Blueprint("logs", __name__, url_prefix="/logs")

DATA_DIR = Path("RagData/logs").resolve()
LAST_RAW_BODY = None
LAST_JSON_BODY = None
LAST_RAW_CONTENT_TYPE = None   # NEW


def csv_path_for_slug(slug: str) -> Path:
    return DATA_DIR / f"{slug}_log.csv"

def list_available_csvs() -> list[str]:
    return sorted([p.name for p in DATA_DIR.glob("*_log.csv")], key=str.lower)

def read_csv_lines_as_text(path: Path, max_lines: int | None = None) -> list[str]:
    lines: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        for i, raw in enumerate(fh):
            if max_lines is not None and i >= max_lines:
                break
            lines.append(raw.rstrip("\r\n"))
    return lines

def parse_csv_for_table(path: Path, max_rows: int | None = None):
    """
    Read CSV robustly for pretty table display only.
    Does NOT affect what we send on to analysis.
    """
    headers = []
    rows = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        for r_i, row in enumerate(reader):
            if r_i == 0:
                headers = row
            else:
                rows.append(row)
            if max_rows is not None and r_i >= max_rows:
                break
    return headers, rows


@logs_bp.get("/<slug>")
def show_slug(slug):
    csv_path = csv_path_for_slug(slug)
    if not csv_path.exists():
        available = list_available_csvs()
        return render_template_string(
            """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><title>logs/{{ slug }} · Tier 0.5</title>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <link rel="stylesheet" href="/static/site.css">
</head>



  <body>
<header>
  <div class="logo"><a href="/">Tier 0.5</a></div>
  <h1 class="page-title">{{ slug }}</h1>
  <div class="actions">
    <button id="btnSelectAll" class="btn secondary" type="button">Select All</button>
    <button id="btnToggle" class="btn secondary" type="button" aria-pressed="true">Switch to Raw</button>
    <a class="btn secondary" href="/">Back to alerts</a>
    <button id="btnNext" class="btn" type="button">Next</button>
  </div>
</header>
    <main>
      <h1>No CSV found for <code>{{ slug }}</code></h1>
      <p>Expected file: <code>{{ expected }}</code></p>
      <h2>Available *_log.csv files:</h2>
      <ul>
        {% for name in available %}
          <li>{{ name }}</li>
        {% endfor %}
      </ul>
    </main>
  </body>
</html>""",
            slug=slug,
            expected=f"{slug}_log.csv",
            available=available
        ), 404

    # Raw lines for fidelity, plus parsed for pretty table
    lines = read_csv_lines_as_text(csv_path)
    headers, table_rows = parse_csv_for_table(csv_path)

    # Safe, lossless exposure of the last raw request body to the UI (may be None)
    last_raw_b64 = base64.b64encode(LAST_RAW_BODY).decode("ascii") if LAST_RAW_BODY is not None else None

    return render_template_string(
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>logs/{{ slug }} · Tier 0.5</title>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <link rel="stylesheet" href="/static/site.css">
</head>

  <body>
<header>
  <div class="logo"><a href="/">Tier 0.5</a></div>
  <div class="title">
  </div>
  <div class="actions">
    <button id="btnSelectAll" class="btn secondary" type="button">Select All</button>  <!-- NEW -->
    <button id="btnToggle" class="btn secondary" type="button" aria-pressed="true">Switch to Raw</button> <!-- CHANGED default -->
    <a class="btn secondary" href="/">Back to alerts</a>
    <button id="btnNext" class="btn" type="button">Next</button>
  </div>
</header>

<div class="wrap">
  <main>
    <!-- RAW / LIST VIEW -->
    <div id="listView" hidden> <!-- CHANGED: hidden by default -->
      <div id="rows">
        {% for line in lines %}
          <div class="row" data-i="{{ loop.index0 }}">{{ line | e }}</div>
        {% endfor %}
      </div>
    </div>

    <!-- PRETTY / TABLE VIEW -->
    <div id="tableView"> <!-- CHANGED: visible by default -->
      <table>
        <thead>
          <tr>
            <th>#</th>
            {% for h in headers %}
              <th>{{ h }}</th>
            {% endfor %}
          </tr>
        </thead>
        <tbody>
          {% for row in table_rows %}
            <tr data-i="{{ loop.index0 }}">
              <td>{{ loop.index0 }}</td>
              {% for cell in row %}
                <td>{{ cell }}</td>
              {% endfor %}
            </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </main>
</div>

<script>
  const lastJsonBody = {{ (last_json_body or none) | tojson | safe }};
  const lastRawBodyB64 = {{ (last_raw_b64 or none) | tojson | safe }};
  const lastRawContentType = {{ (last_raw_content_type or none) | tojson | safe }};
  const slug = {{ slug | tojson | safe }};
  const csvName = {{ csv_name | tojson | safe }};
  const allLines = {{ lines | tojson | safe }}; // authoritative raw lines for sending

  const listView = document.getElementById("listView");
  const tableView = document.getElementById("tableView");
  const btnToggle = document.getElementById("btnToggle");
  const btnSelectAll = document.getElementById("btnSelectAll"); // NEW

  addEventListener("click",(e)=>{
    const row = e.target.closest(".row");
    if(row) row.classList.toggle("selected");

    const tr = e.target.closest("tr[data-i]");
    if(tr) tr.classList.toggle("selected");
  });

  // Helper to know which view is active
  function isPrettyActive(){
    return !tableView.hasAttribute("hidden");
  }

  btnToggle.addEventListener("click", ()=>{
    if(isPrettyActive()){
      // switch to raw
      tableView.setAttribute("hidden","");
      listView.removeAttribute("hidden");
      btnToggle.textContent = "Switch to Pretty";
      btnToggle.setAttribute("aria-pressed","false");
    }else{
      // switch to pretty
      listView.setAttribute("hidden","");
      tableView.removeAttribute("hidden");
      btnToggle.textContent = "Switch to Raw";
      btnToggle.setAttribute("aria-pressed","true");
    }
  });

  // NEW: Select All for the active view
  btnSelectAll.addEventListener("click", ()=>{
    if(isPrettyActive()){
      document.querySelectorAll("tr[data-i]").forEach(tr => tr.classList.add("selected"));
    }else{
      document.querySelectorAll(".row[data-i]").forEach(div => div.classList.add("selected"));
    }
  });

  function getSelectedIndices(){
    // collect indices from both views (in case user flips views mid-selection)
    const fromRows=[...document.querySelectorAll(".row.selected")].map(el=>Number(el.getAttribute("data-i")));
    const fromTable=[...document.querySelectorAll("tr.selected[data-i]")].map(el=>Number(el.getAttribute("data-i")));
    return [...new Set([...fromRows, ...fromTable])].sort((a,b)=>a-b);
  }

  function getAllIfEmpty(indices){
    if(indices.length>0) return indices;
    return allLines.map((_,i)=>i);
  }

  document.getElementById("btnNext").addEventListener("click", async (e)=>{
    const btn=e.currentTarget; btn.disabled=true; const original=btn.textContent; btn.textContent="Sending…";
    const indices = getAllIfEmpty(getSelectedIndices());
    const payload = {
      slug,
      csv_name: csvName,
      selected_indices: indices,
      // IMPORTANT: always send the ORIGINAL raw lines by index
      lines: indices.map(i => allLines[i]),
      last_json_body: lastJsonBody,
      raw_body_b64: lastRawBodyB64,
      raw_content_type: lastRawContentType
    };
    try{
      const res=await fetch("/analysis/payload",{ method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify(payload) });
      if(!res.ok) throw new Error(`HTTP ${res.status}`);
      const redirectUrl=`/analysis?slug=${encodeURIComponent(slug)}`;
      window.location.assign(redirectUrl);
    }catch(err){
      console.error(err); btn.disabled=false; btn.textContent=original; alert("Failed to send payload. See console for details.");
    }
  });
</script>

  </body>
</html>""",
        slug=slug,
        csv_name=csv_path.name,
        csv_path=str(csv_path),
        lines=lines,
        headers=headers,
        table_rows=table_rows,
        last_json_body=LAST_JSON_BODY,
        last_raw_b64=last_raw_b64,
        last_raw_content_type=LAST_RAW_CONTENT_TYPE,
    )

@logs_bp.post("/<slug>")
def handle_log(slug):
    global LAST_RAW_BODY, LAST_JSON_BODY, LAST_RAW_CONTENT_TYPE
    LAST_RAW_BODY = request.get_data(cache=True)
    LAST_JSON_BODY = request.get_json(cache=True, force=True, silent=True)
    LAST_RAW_CONTENT_TYPE = request.headers.get("Content-Type")  # NEW
    data = request.get_json(force=True, silent=True)
    print(f"\n=== /logs/{slug} received ===")
    try:
        print("DATA:", LAST_JSON_BODY)
    except Exception:
        print(data)
    return jsonify(received=data), 200
