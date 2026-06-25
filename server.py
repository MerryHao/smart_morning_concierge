"""
server.py — Flask Web Server for Smart Morning Concierge
Serves the frontend HTML and exposes an API endpoint that wraps the Gemini agent.
"""

import os
import json
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from weather_tool import get_weather
from main_agent import run_agent

load_dotenv()

app = Flask(__name__)


@app.route("/")
def index():
    """Serve the main frontend page."""
    return render_template("index.html")


@app.route("/api/advice", methods=["POST"])
def get_advice():
    """
    Accept a city name and return weather data + Gemini concierge advice.

    Request body (JSON):
        { "city": "桃園市" }

    Response (JSON):
        { "success": true, "city": "桃園市", "weather": {...}, "advice": "..." }
        or
        { "success": false, "error": "..." }
    """
    data = request.get_json(silent=True)
    if not data or not data.get("city", "").strip():
        return jsonify({"success": False, "error": "Please provide a city name."}), 400

    city = data["city"].strip()

    try:
        # Fetch raw weather data directly (reliable, structured)
        weather_raw = get_weather(city)

        # Parse weather fields from the structured raw string
        weather = _parse_weather(weather_raw)

        # Get AI concierge advice via Gemini agent
        advice = run_agent(city)

        return jsonify({
            "success": True,
            "city": city,
            "weather": weather,
            "advice": advice,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _parse_weather(raw: str) -> dict:
    """Extract structured fields from the weather_tool output string."""
    fields = {"location": "", "period": "", "wx": "", "pop": "", "minT": "", "maxT": ""}
    if raw.startswith("❌"):
        fields["error"] = raw
        return fields
    for line in raw.splitlines():
        if "地點" in line:
            fields["location"] = line.split("：", 1)[-1].strip()
        elif "預報時段" in line:
            fields["period"] = line.split("：", 1)[-1].strip()
        elif "天氣現象" in line:
            fields["wx"] = line.split("：", 1)[-1].strip()
        elif "降雨機率" in line:
            fields["pop"] = line.split("：", 1)[-1].replace("%", "").strip()
        elif "溫度範圍" in line:
            import re
            m = re.search(r"(\d+)°C ～ (\d+)°C", line)
            if m:
                fields["minT"] = m.group(1)
                fields["maxT"] = m.group(2)
    return fields


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    print(f"\n🌅 Smart Morning Concierge — Web Server starting...")
    print(f"   Open http://localhost:{port} to get started\n")
    app.run(debug=True, port=port)
