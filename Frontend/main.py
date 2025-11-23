# app.py
from flask import Flask, jsonify, request, render_template_string
from pathlib import Path
from routes import alerts_bp, logs_bp,analysis_bp

app = Flask(__name__)
app.register_blueprint(alerts_bp)
app.register_blueprint(logs_bp)
app.register_blueprint(analysis_bp)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
