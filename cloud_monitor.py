import argparse
import base64
import html
import json
import os
import smtplib
import subprocess
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import email_report

BASE = Path(__file__).resolve().parent
SGT = ZoneInfo("Asia/Singapore")
LOG_PATH = BASE / "cloud" / "cloud_monitor.log"


def log(message):
    line = f"{datetime.now(SGT).strftime('%Y-%m-%d %H:%M:%S')} SGT {message}"
    print(line)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_dotenv():
    path = BASE / "cloud" / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def in_slot(now):
    if now.weekday() == 6:
        return False
    if now.minute == 0 and now.hour in (0, 4, 8, 12, 16, 19, 20):
        return True
    if now.hour == 21 and now.minute in (0, 15, 30):
        return True
    if now.minute == 30 and (now.hour >= 21 or now.hour <= 4):
        return True
    return False


def run_monitor():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(BASE / "monitor.py")],
        cwd=str(BASE),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-4000:] or "monitor.py failed")
    report = proc.stdout
    alert_count = 0
    for line in report.splitlines():
        if line.startswith("ALERT_COUNT="):
            alert_count = int(line.split("=", 1)[1].strip())
    session = ""
    alerts = []
    in_alerts = False
    for line in report.splitlines():
        if line.startswith("- 市场时段："):
            session = line.split("：", 1)[1].strip()
        if line.startswith("## 触发提醒"):
            in_alerts = True
            continue
        if in_alerts and line.startswith("## "):
            in_alerts = False
        if in_alerts and line.startswith("- "):
            alerts.append(line[2:].strip())
    output_path = BASE / "monitor_output.json"
    output = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else {}
    return report, alert_count, session, alerts, output


def send_email(subject, text, html_body=None, images=None):
    provider = os.environ.get("EMAIL_PROVIDER", "smtp").strip().lower()
    sender = os.environ.get("EMAIL_FROM", "").strip()
    recipients = [x.strip() for x in os.environ.get("EMAIL_TO", "").split(",") if x.strip()]
    if not sender or not recipients:
        raise RuntimeError("EMAIL_FROM and EMAIL_TO must be set")
    if html_body is None:
        html_body = (
            "<html><body>"
            "<pre style=\"font-family: Consolas, Menlo, monospace; white-space: pre-wrap; line-height: 1.45;\">"
            + html.escape(text)
            + "</pre></body></html>"
        )
    if provider == "resend":
        key = os.environ.get("RESEND_API_KEY", "").strip()
        if not key:
            raise RuntimeError("RESEND_API_KEY is not set")
        attachments = []
        for cid, png in (images or {}).items():
            attachments.append({
                "content": base64.b64encode(png).decode("ascii"),
                "filename": f"{cid}.png",
                "content_type": "image/png",
                "content_id": cid,
            })
        payload = {
            "from": sender,
            "to": recipients,
            "subject": subject,
            "text": text,
            "html": html_body,
        }
        if attachments:
            payload["attachments"] = attachments
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"Resend HTTP {resp.status_code}: {resp.text[:1000]}")
        return

    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "")
    use_ssl = os.environ.get("SMTP_USE_SSL", "false").strip().lower() in ("1", "true", "yes")
    if not host or not user or not password:
        raise RuntimeError("SMTP_HOST, SMTP_USER and SMTP_PASS must be set")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    if images:
        html_part = msg.get_payload()[1]
        for cid, png in images.items():
            html_part.add_related(png, maintype="image", subtype="png", cid=f"<{cid}>")
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="send email even outside the daily window or with no alerts")
    parser.add_argument("--dry-run", action="store_true", help="print the report without sending email")
    parser.add_argument("--schedule-check", action="store_true", help="exit unless the current SGT time is a scheduled slot")
    args = parser.parse_args()

    load_dotenv()
    now = datetime.now(SGT)
    if args.schedule_check and not args.force and not in_slot(now):
        print(f"{now:%Y-%m-%d %H:%M} SGT not a scheduled slot; skip")
        return

    report, alert_count, session, alerts, output = run_monitor()
    if "周末休市" in session or "美股假日休市" in session:
        log(f"skip: {session}")
        return

    is_daily = now.hour == 19 and now.minute < 60
    should_send = args.force or is_daily or alert_count > 0
    if not should_send:
        log(f"no email: session={session}, alerts=0")
        return

    subject, html_body, text_body, images = email_report.build_email(output, daily=is_daily)

    if args.dry_run:
        print("SUBJECT:", subject)
        print("RECIPIENTS:", os.environ.get("EMAIL_TO", ""))
        preview = BASE / "email_preview.html"
        preview.write_text(html_body, encoding="utf-8")
        for cid, png in images.items():
            (BASE / f"email_preview_{cid}.png").write_bytes(png)
        print("PREVIEW:", preview)
        print("IMAGES:", ", ".join(images))
        return

    send_email(subject, text_body, html_body, images)
    log(f"email sent: {subject} -> {os.environ.get('EMAIL_TO', '')}")


if __name__ == "__main__":
    main()
