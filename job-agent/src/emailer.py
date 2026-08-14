from __future__ import annotations

import logging
import os
import smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

LOGGER = logging.getLogger(__name__)

REQUIRED_ENV = [
    "EMAIL_SMTP_HOST",
    "EMAIL_SMTP_PORT",
    "EMAIL_USERNAME",
    "EMAIL_APP_PASSWORD",
    "EMAIL_FROM",
    "EMAIL_TO",
]


def send_report_if_configured(report_path: str | Path) -> bool:
    load_dotenv()
    missing = [key for key in REQUIRED_ENV if not os.getenv(key)]
    if missing:
        LOGGER.warning("Email not configured; missing variables: %s", ", ".join(missing))
        return False
    if not Path(report_path).exists():
        LOGGER.warning("Email report skipped; report file does not exist: %s", report_path)
        return False

    body = Path(report_path).read_text(encoding="utf-8")
    message = EmailMessage()
    message["Subject"] = f"Job Agent Report - {date.today().isoformat()}"
    message["From"] = os.environ["EMAIL_FROM"]
    message["To"] = os.environ["EMAIL_TO"]
    message.set_content(body)

    host = os.environ["EMAIL_SMTP_HOST"]
    port = int(os.environ["EMAIL_SMTP_PORT"])
    username = os.environ["EMAIL_USERNAME"]
    password = os.environ["EMAIL_APP_PASSWORD"]

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(message)
        LOGGER.info("Email report sent to %s", os.environ["EMAIL_TO"])
        return True
    except Exception as exc:
        LOGGER.warning("Email send failed: %s", exc)
        return False
