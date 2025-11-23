from flask import Blueprint, jsonify, request, render_template_string, current_app, Response
from pathlib import Path
import json
import copy
import requests
from datetime import datetime
import io
import markdown as md
from playwright.sync_api import sync_playwright

JSON_PAYLOAD = ""
INITIAL_ANALYSIS = ""
analysis_bp = Blueprint("analysis", __name__, url_prefix="/analysis")

PDF_CSS = """
@page {
  size: A4;
  margin: 24mm 18mm 24mm 18mm;
}
html { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, Arial, "Noto Sans", sans-serif; }
h1,h2,h3 { margin: 0 0 8px 0; line-height: 1.2; }
h1 { font-size: 20pt; border-bottom: 2px solid #111; padding-bottom: 6px; }
h2 { font-size: 16pt; margin-top: 18px; border-bottom: 1px solid #444; padding-bottom: 4px; }
h3 { font-size: 13pt; margin-top: 12px; }
p, li { font-size: 10.5pt; line-height: 1.45; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; font-size: 9.5pt; }
pre { background: #f6f8fa; padding: 10px; border: 1px solid #e5e7eb; border-radius: 6px; white-space: pre-wrap; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; }
th, td { border: 1px solid #d1d5db; padding: 6px 8px; font-size: 10pt; vertical-align: top; }
blockquote { border-left: 3px solid #9ca3af; padding-left: 10px; color: #374151; }
hr { border: none; border-top: 1px solid #ddd; margin: 12px 0; }
.small { color: #6b7280; font-size: 9pt; }
.header {
  display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px;
}
"""

def markdown_to_pdf(markdown_text: str) -> bytes:
    # MD -> HTML
    html_body = md.markdown(
        markdown_text,
        extensions=["extra", "sane_lists", "toc", "smarty", "nl2br"]
    )

    # Extract Title/Date if present
    title = "Incident Report"
    date_str = datetime.now().strftime("%Y-%m-%d")
    for line in markdown_text.splitlines():
        low = line.strip().lower()
        if low.startswith("title:"):
            title = line.split(":", 1)[1].strip() or title
        elif low.startswith("date:"):
            date_str = line.split(":", 1)[1].strip() or date_str

    full_html = f"""<!doctype html>
<html><head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>{PDF_CSS}</style>
</head>
<body>
  <div class="header">
    <div><strong>{title}</strong></div>
    <div class="small">{date_str}</div>
  </div>
  {html_body}
</body></html>"""

    # HTML -> PDF with headless Chromium
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        # Ensure fonts & sizing match print layout
        page.set_content(full_html, wait_until="load")
        pdf_bytes = page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "24mm", "right": "18mm", "bottom": "24mm", "left": "18mm"}
        )
        browser.close()
    return pdf_bytes

@analysis_bp.post("/export-pdf")
def export_pdf():
    try:
        data = request.get_json(force=True) or {}
        content = data.get("content", "")
        if not isinstance(content, str):
            content = str(content)

        pdf_bytes = markdown_to_pdf(content)
        filename = f'llm_suggestion_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        hint = ""
        if "playwright" in str(e).lower():
            hint = " (Did you run: python -m playwright install chromium ?)"
        return jsonify({"error": f"failed_to_export_pdf: {e}{hint}"}), 400

def build_json_payload_for_llm():
    try:
        jp = globals().get("JSON_PAYLOAD", {}) or {}
        ia = globals().get("INITIAL_ANALYSIS", "")
        log_lines = copy.deepcopy(jp.get("lines", []))
        siem_alert = copy.deepcopy(jp.get("last_json_body", {}))
        if not isinstance(log_lines, list):
            log_lines = [str(log_lines)]
        if not isinstance(siem_alert, dict):
            siem_alert = {"raw": siem_alert}
        envelope = {
            "log_lines": log_lines,
            "siem_alert": siem_alert,
            "initial_analysis": str(ia) if ia is not None else ""
        }
        return envelope
    except Exception as e:
        return {
            "log_lines": [], "siem_alert": {}, "initial_analysis": "",
            "error": f"build_siem_envelope_failed: {e.__class__.__name__}: {e}"
        }

@analysis_bp.route("/", methods=["GET"])
def analysis_form():
    envelope = build_json_payload_for_llm()
    slug = request.args.get("slug", "")  # for "Back to logs"
    html = """
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8"/>
      <meta name="viewport" content="width=device-width,initial-scale=1"/>
      <title>Generate Draft — Tier 0.5</title>
      <link rel="stylesheet" href="/static/site.css">
    </head>

    <body>
      <header>
      <div class="logo"><a href="/">Tier 0.5</a></div>
      <h1 class="page-title">Generate Draft</h1>
      <div class="actions">
        <a class="btn secondary" id="backLink" href="/logs">Back to logs</a>
      </div>
    </header>


      <div class="wrap">
        <div class="card">
          <form id="ia-form" method="post" action="#" onsubmit="event.preventDefault();">
            <label for="initial_analysis">Initial analysis</label>
            <textarea id="initial_analysis" name="initial_analysis" rows="8"
              placeholder="Write or paste your initial triage/notes here...">{{ envelope.initial_analysis }}</textarea>

            <label for="llm_suggestion">LLM suggestion</label>
            <textarea id="llm_suggestion" name="llm_suggestion" rows="8"
              placeholder="Paste a suggested response or remediation from an LLM here..."></textarea>

            <button id="generate-btn" class="btn" type="submit">Generate Draft</button>
            <button id="export-btn" class="btn" type="button" style="margin-left:.5rem;">Generate PDF</button>
          </form>
        </div>
      </div>

<script>
  (function () {
    const form  = document.getElementById('ia-form');
    const btn   = document.getElementById('generate-btn');
    const ta    = document.getElementById('initial_analysis');
    const llmTa = document.getElementById('llm_suggestion');
    const exportBtn = document.getElementById('export-btn');
    const backLink = document.getElementById('backLink');

    // If ?slug=... exists, point Back to that logs page
    const params = new URLSearchParams(window.location.search);
    const slug = params.get('slug');
    if (slug) {
      backLink.href = '/logs/' + encodeURIComponent(slug);
    }

    form.addEventListener('submit', async function () {
      const payload = { initial_analysis: ta.value };
      btn.disabled = true;
      const original = btn.textContent;
      btn.textContent = 'Generating draft…';

      try {
        const res = await fetch('/analysis/initial-analysis', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || res.statusText);

        if (typeof data.llm_suggestion === 'string') {
          llmTa.value = data.llm_suggestion;
        }

        btn.textContent = 'Saved!';
        setTimeout(() => { btn.textContent = original; btn.disabled = false; }, 600);
      } catch (err) {
        alert('Error saving Initial analysis: ' + err.message);
        btn.textContent = original;
        btn.disabled = false;
      }
    });

    exportBtn.addEventListener('click', async function () {
      const text = llmTa.value || '';
      if (!text.trim()) {
        alert('LLM suggestion is empty.');
        return;
      }

      const original = exportBtn.textContent;
      exportBtn.textContent = 'Generating…';
      exportBtn.disabled = true;

      try {
        const res = await fetch('/analysis/export-pdf', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: text })
        });
        if (!res.ok) {
          const msg = await res.text().catch(() => '');
          throw new Error(msg || res.statusText);
        }

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `llm_suggestion_${new Date().toISOString().replace(/[:.]/g,'-')}.txt`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch (err) {
        alert('Failed to generate file: ' + err.message);
      } finally {
        exportBtn.textContent = original;
        exportBtn.disabled = false;
      }
    });
  })();
</script>
    </body>
    </html>
    """
    return render_template_string(html, envelope=envelope, slug=slug)

@analysis_bp.route("/initial-analysis", methods=["POST"])
def send_analysis_to_llm():
    global INITIAL_ANALYSIS
    try:
        data = request.get_json(silent=True) or {}
        text = data.get("initial_analysis")
        if text is None:
            text = request.form.get("initial_analysis", "")
        INITIAL_ANALYSIS = str(text or "")
        full_llm_request = build_json_payload_for_llm()
        resp = requests.post("http://127.0.0.1:8000/llm", json=full_llm_request, timeout=1200)
        resp.raise_for_status()
        llm_answer = resp.text
        return jsonify({"status": "ok","initial_analysis": INITIAL_ANALYSIS,"llm_suggestion": llm_answer}), 200
    except Exception as e:
        return jsonify({"error": f"failed_to_set_initial_analysis: {e}"}), 400

@analysis_bp.route("/payload", methods=["POST"])
def print_json_payload():
    try:
        global JSON_PAYLOAD
        data = request.get_json(force=True)
        JSON_PAYLOAD = data
    except Exception as e:
        return jsonify({"error": f"Invalid JSON: {e}"}), 400
    return jsonify({"status": "ok"}), 200
