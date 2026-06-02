#!/usr/bin/env python3
import sys
import os
import json
import subprocess
from datetime import datetime, timedelta

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct:free")
CLICKHOUSE_BIN = "clickhouse-client"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CONFIG_FILE = "/opt/mundix360/configs/openrouter.env"
LOG_FILE = "/opt/mundix360/data/siem/triage.log"
HOURS_BACK = int(os.environ.get("TRIAGE_HOURS", "1"))

if os.path.isfile(CONFIG_FILE):
    with open(CONFIG_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key == "OPENROUTER_API_KEY" and not OPENROUTER_API_KEY:
                    OPENROUTER_API_KEY = val
                elif key == "OPENROUTER_MODEL" and OPENROUTER_MODEL == "mistralai/mistral-7b-instruct:free":
                    OPENROUTER_MODEL = val


def log(msg):
    ts = datetime.utcnow().isoformat() + "Z"
    line = f"{ts} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def fetch_alerts(hours=1):
    query = f"""
    SELECT event_id, timestamp, source, rule_name, severity, category,
           mitre_tactic, mitre_technique, src_ip, dst_ip, description
    FROM akvorado.siem_alerts
    WHERE timestamp > now64() - INTERVAL {hours} HOUR
      AND triage_notes = ''
    ORDER BY severity DESC, timestamp DESC
    LIMIT 50
    FORMAT JSONEachRow"""
    result = subprocess.run(
        [CLICKHOUSE_BIN, "--query", query],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        log(f"ERROR querying ClickHouse: {result.stderr}")
        return []
    alerts = []
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            alerts.append(json.loads(line))
    return alerts


def triage_single(alert):
    import requests
    prompt = f"""You are a security analyst for a SOCs platform called Mundix360.
Analyze the following SIEM alert and provide a JSON response with:
- "verdict": one of "true_positive", "false_positive", "needs_review"
- "priority": one of "critical", "high", "medium", "low"
- "summary": 1-2 sentence explanation
- "recommendation": suggested action
- "confidence": float 0.0 to 1.0

Respond ONLY with valid JSON, no markdown.

Alert:
- Source: {alert.get('source', 'unknown')}
- Rule: {alert.get('rule_name', '')}
- Severity: {alert.get('severity', 0)}
- Category: {alert.get('category', '')}
- MITRE Tactic: {alert.get('mitre_tactic', '')}
- MITRE Technique: {alert.get('mitre_technique', '')}
- Source IP: {alert.get('src_ip', '')}
- Dest IP: {alert.get('dst_ip', '')}
- Description: {alert.get('description', '')}
"""
    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://mundix360.local"
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 512
            },
            timeout=60
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(content)
    except Exception as e:
        log(f"ERROR triaging alert {alert.get('event_id', '?')}: {e}")
        return None


def update_alert(event_id, triage_obj):
    verdict = triage_obj.get("verdict", "needs_review")
    priority = triage_obj.get("priority", "medium")
    summary = triage_obj.get("summary", "").replace("'", "''")
    recommendation = triage_obj.get("recommendation", "").replace("'", "''")
    confidence = float(triage_obj.get("confidence", 0.5))
    fp_flag = 1 if verdict == "false_positive" else 0
    notes = json.dumps({
        "verdict": verdict,
        "priority": priority,
        "summary": summary,
        "recommendation": recommendation,
        "confidence": confidence,
        "model": OPENROUTER_MODEL,
        "triaged_at": datetime.utcnow().isoformat() + "Z"
    }, ensure_ascii=False).replace("'", "\\'")

    query = f"""
    ALTER TABLE akvorado.siem_alerts UPDATE
        triage_notes = '{notes}',
        false_positive = {fp_flag}
    WHERE event_id = '{event_id}'
    """
    result = subprocess.run(
        [CLICKHOUSE_BIN, "--query", query],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        log(f"ERROR updating alert {event_id}: {result.stderr}")
    else:
        log(f"UPDATED alert {event_id} verdict={verdict} confidence={confidence}")


def main():
    if not OPENROUTER_API_KEY:
        log("ERROR: OPENROUTER_API_KEY not set. Set env var or configure /opt/mundix360/configs/openrouter.env")
        sys.exit(1)

    alerts = fetch_alerts(HOURS_BACK)
    if not alerts:
        log("No alerts to triage.")
        return

    log(f"Fetched {len(alerts)} alert(s) for triage (last {HOURS_BACK}h)")

    triaged = 0
    for alert in alerts:
        eid = alert.get("event_id", "?")
        log(f"Triaging: {eid} | {alert.get('rule_name', '')} | severity={alert.get('severity', 0)}")
        result = triage_single(alert)
        if result:
            update_alert(eid, result)
            triaged += 1

    log(f"Done. Triaged {triaged}/{len(alerts)} alerts.")


if __name__ == "__main__":
    main()
