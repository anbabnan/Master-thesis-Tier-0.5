from flask import Blueprint, jsonify, request, render_template_string
from pathlib import Path
import json

alerts_bp = Blueprint("alerts", __name__, url_prefix="/")

# SAME path as before — no discovery, no changes
DATA_DIR = Path("RagData/alert").resolve()

@alerts_bp.get("/")
def index():
    def extract_meta(payload):
        customer_name = None
        alert_name = None
        severity = None

        if isinstance(payload, list):
            for obj in payload:
                if not isinstance(obj, dict):
                    continue

                # First Customer.name
                if customer_name is None and "Customer" in obj and isinstance(obj["Customer"], dict):
                    val = obj["Customer"].get("name")
                    if isinstance(val, str) and val.strip():
                        customer_name = val.strip()

                # First alert_name
                if alert_name is None and "alert_name" in obj:
                    val = obj.get("alert_name")
                    if isinstance(val, str) and val.strip():
                        alert_name = val.strip()

                # First non-null/non-empty severity
                if severity is None and "severity" in obj:
                    val = obj.get("severity")
                    if isinstance(val, str):
                        if val.strip():
                            severity = val.strip()
                    elif val is not None:
                        severity = val

                # Early exit if we’ve found everything
                if customer_name is not None and alert_name is not None and severity is not None:
                    break

        return customer_name, alert_name, severity

    alerts = []
    for p in sorted(DATA_DIR.glob("*.json")):
        try:
            with p.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            customer_name, alert_name, severity = extract_meta(payload)
            alerts.append({
                # display_name becomes the card title (alert_name preferred)
                "display_name": alert_name or p.stem,
                # keep filename for slug/nav logic
                "filename": p.name,
                "payload": payload,
                "customer_name": customer_name,
                "severity": severity
            })
        except Exception as e:
            alerts.append({
                "display_name": f"{p.name} (failed to load: {e})",
                "filename": p.name,
                "payload": None,
                "customer_name": None,
                "severity": None
            })

    tmpl = """
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8"/>
      <meta name="viewport" content="width=device-width,initial-scale=1"/>
      <title>Alerts · Tier 0.5</title>
      <link rel="stylesheet" href="/static/site.css">
    </head>

    <header>
      <div class="logo"><a href="/">Tier 0.5</a></div>
      <h1 class="page-title">Alerts</h1>
      <div class="actions">
      </div>
    </header>
      <div class="wrap">
        <main>
          <div class="grid" id="cards"></div>
        </main>
      </div>
      <script>
        (function(){
          const CARDS  = document.getElementById("cards");
          const ALERTS = {{ alerts|tojson|safe }};

          function slugFromFilename(name){
            if (!name) return "";
            let base = name;
            if (base.toLowerCase().endsWith(".json")) {
              base = base.slice(0, -5);
            }
            const underscore = base.indexOf("_");
            return underscore > -1 ? base.slice(0, underscore) : base;
          }

          function textOrFallback(v, fb){ return (v === null || v === undefined || v === "") ? fb : v; }

          function makeCard(item){
            const card = document.createElement("div");
            card.className = "card";

            const h3 = document.createElement("h3");
            // Show alert_name as the title (provided by display_name from server)
            h3.textContent = textOrFallback(item.display_name, "Unnamed alert");

            const meta = document.createElement("div");
            meta.className = "muted";
            const who = textOrFallback(item.customer_name, "Unknown customer");
            const sev = textOrFallback(item.severity, "unknown");
            meta.textContent = who + " · Severity: " + sev;

            const btn = document.createElement("button");
            btn.className = "btn";
            btn.textContent = "Open";
            btn.addEventListener("click", async () => {
              // Use filename for slugging/navigation (kept separate)
              const slug = slugFromFilename(item.filename || "");
              const endpoint = "/logs/" + encodeURIComponent(slug || "");
              try {
                await fetch(endpoint, {
                  method: "POST",
                  headers: {"Content-Type":"application/json"},
                  body: JSON.stringify(item.payload || {})
                });
              } catch (_) { /* ignore and still navigate */ }
              window.location.assign(endpoint);
            });

            card.appendChild(h3);
            card.appendChild(meta);
            card.appendChild(btn);
            return card;
          }

          if (Array.isArray(ALERTS) && ALERTS.length){
            ALERTS.forEach(a => CARDS.appendChild(makeCard(a)));
          } else {
            const empty = document.createElement("div");
            empty.className = "muted";
            empty.style.marginTop = "8px";
            empty.textContent = "No alerts found.";
            CARDS.appendChild(empty);
          }
        })();
      </script>
    </body>
    </html>
    """
    return render_template_string(tmpl, alerts=alerts, data_dir=str(DATA_DIR))


@alerts_bp.post("/json_test")
def json_test():
    data = request.get_json(force=True, silent=True)
    print("\n=== /json_test received ===")
    try:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        print(data)
    print("=== end ===\n")
    return jsonify(ok=True, type=("null" if data is None else type(data).__name__)), 200
