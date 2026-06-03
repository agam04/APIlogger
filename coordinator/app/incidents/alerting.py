"""Email + Slack/Discord webhook alerting on incident open/resolve."""

import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import AsyncSessionLocal
from app.db.models import AlertRule, Incident, Service

log = get_logger(__name__)


async def send_incident_alert(incident_id: str, event: str) -> None:
    """event is 'opened' or 'resolved'."""
    iid = uuid.UUID(incident_id)
    async with AsyncSessionLocal() as db:
        inc_r = await db.execute(
            select(Incident)
            .options(selectinload(Incident.service).selectinload(Service.alert_rules))
            .where(Incident.id == iid)
        )
        incident = inc_r.scalar_one_or_none()
        if incident is None:
            return

        rules: list[AlertRule] = incident.service.alert_rules
        if not rules:
            return

        for rule in rules:
            if event == "opened" and not rule.on_incident:
                continue
            if event == "resolved" and not rule.on_resolve:
                continue
            await _dispatch(rule, incident, event)

        incident.alert_sent = True
        await db.commit()

    from app.api.v1.health import metrics

    metrics.alerts_sent += 1


async def _dispatch(rule: AlertRule, incident: Incident, event: str) -> None:
    try:
        if rule.channel == "email":
            await _send_email(rule.destination, incident, event)
        elif rule.channel in ("slack", "discord"):
            await _send_webhook(rule.destination, incident, event)
    except Exception as exc:
        log.error("alert_dispatch_failed", channel=rule.channel, exc=str(exc))


def _format_body(incident: Incident, event: str) -> str:
    emoji = "🔴" if event == "opened" else "🟢"
    verb = "opened" if event == "opened" else "resolved"
    lines = [
        f"{emoji} Incident {verb}: {incident.service.name}",
        f"Reason: {incident.trigger_reason}",
        f"Started: {incident.started_at.isoformat()}",
    ]
    if incident.resolved_at:
        duration = incident.resolved_at - incident.started_at
        lines.append(f"Duration: {duration}")
    if incident.ai_summary:
        lines.append("")
        lines.append("AI Analysis:")
        lines.append(incident.ai_summary)
    return "\n".join(lines)


async def _send_email(to: str, incident: Incident, event: str) -> None:
    if not settings.SMTP_USER:
        log.warning("smtp_not_configured_skipping_email")
        return

    verb = "opened" if event == "opened" else "resolved"
    subject = f"[APILogger] Incident {verb}: {incident.service.name}"
    body = _format_body(incident, event)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.ALERT_FROM_EMAIL
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
        log.info("email_alert_sent", to=to, incident_id=str(incident.id))
    except Exception as exc:
        log.error("email_send_failed", to=to, exc=str(exc))
        raise


async def _send_webhook(url: str, incident: Incident, event: str) -> None:
    body = _format_body(incident, event)
    emoji = "🔴" if event == "opened" else "🟢"

    # Slack and Discord both accept {"text": "..."} for simple payloads
    payload = {"text": body, "username": "APILogger", "icon_emoji": emoji}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
    log.info("webhook_alert_sent", url=url[:40], incident_id=str(incident.id))
