"""
AI-powered incident summary with structured JSON output.

Provider selection (automatic, in priority order):
  1. Anthropic Claude  — if ANTHROPIC_API_KEY is set
  2. Groq (free tier) — if GROQ_API_KEY is set  (llama-3.3-70b-versatile)
  3. Disabled         — if neither key is present

Output schema stored in incidents.ai_structured (JSONB):
  {
    "root_cause": str,
    "confidence": float (0-1),
    "risk_level": "Critical" | "High" | "Medium" | "Low",
    "recommended_actions": [str, ...],
    "estimated_impact": str,
    "similar_past_incident": str | null
  }
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

import anthropic
from anthropic.types import TextBlock
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import AsyncSessionLocal
from app.db.models import CheckResult, Incident, IncidentContext, Service

log = get_logger(__name__)


# ── Provider abstraction ──────────────────────────────────────────────────────


class LLMProvider(Protocol):
    async def complete(self, system: str, user: str, max_tokens: int) -> str: ...


class AnthropicProvider:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        response = await self._client.messages.create(
            model=settings.AI_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        block = next(b for b in response.content if isinstance(b, TextBlock))
        return block.text


class GroqProvider:
    def __init__(self) -> None:
        from groq import AsyncGroq

        self._client = AsyncGroq(api_key=settings.GROQ_API_KEY)

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        response = await self._client.chat.completions.create(
            model=settings.GROQ_MODEL,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""


_provider: LLMProvider | None = None


def _get_provider() -> LLMProvider | None:
    global _provider
    if _provider is not None:
        return _provider

    if settings.ANTHROPIC_API_KEY:
        _provider = AnthropicProvider()
        log.info("ai_provider_selected", provider="anthropic", model=settings.AI_MODEL)
    elif settings.GROQ_API_KEY:
        _provider = GroqProvider()
        log.info("ai_provider_selected", provider="groq", model=settings.GROQ_MODEL)
    else:
        log.warning("ai_no_provider_configured", hint="Set ANTHROPIC_API_KEY or GROQ_API_KEY")

    return _provider


def active_provider_name() -> str:
    if settings.ANTHROPIC_API_KEY:
        return "anthropic"
    if settings.GROQ_API_KEY:
        return "groq"
    return "none"


# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an expert SRE analyzing an API monitoring incident.
Based on the check results and context provided, produce a structured diagnosis.

Respond with ONLY valid JSON matching this exact schema — no markdown, no explanation outside the JSON:

{
  "root_cause": "One sentence identifying the most likely technical cause",
  "confidence": 0.0 to 1.0,
  "risk_level": "Critical" | "High" | "Medium" | "Low",
  "recommended_actions": ["action 1", "action 2", "action 3"],
  "estimated_impact": "One sentence on what users / downstream services are experiencing",
  "similar_past_incident": "Date and brief description of a matching past incident, or null"
}

Rules:
- root_cause must reference specific error messages, status codes, or latency numbers from the data
- confidence reflects how certain you are given the available evidence (low if data is sparse)
- recommended_actions should be concrete steps an on-call engineer takes right now, ordered by priority
- estimated_impact should describe real user-facing effects, not just "service is down"
- similar_past_incident: null if no past incidents were provided or none match
"""


async def generate_and_store_summary(incident_id: str) -> None:
    if not settings.AI_ENABLED:
        log.info("ai_disabled_skipping_summary", incident_id=incident_id)
        return

    provider = _get_provider()
    if provider is None:
        log.info("ai_no_provider_skipping_summary", incident_id=incident_id)
        return

    iid = uuid.UUID(incident_id)

    async with AsyncSessionLocal() as db:
        inc_r = await db.execute(select(Incident).options(selectinload(Incident.service)).where(Incident.id == iid))
        incident = inc_r.scalar_one_or_none()
        if incident is None:
            log.warning("ai_summary_incident_not_found", incident_id=incident_id)
            return

        service: Service = incident.service

        window = datetime.now(UTC) - timedelta(minutes=30)
        recent_r = await db.execute(
            select(CheckResult)
            .where(CheckResult.service_id == service.id, CheckResult.checked_at >= window)
            .order_by(CheckResult.checked_at.desc())
            .limit(50)
        )
        recent_checks = list(recent_r.scalars().all())

        past_r = await db.execute(
            select(Incident)
            .where(
                Incident.service_id == service.id,
                Incident.id != iid,
                Incident.resolved_at.is_not(None),
                Incident.ai_summary.is_not(None),
            )
            .order_by(Incident.started_at.desc())
            .limit(3)
        )
        past_incidents = list(past_r.scalars().all())

    prompt = _build_prompt(incident, service, recent_checks, past_incidents)

    try:
        raw = await provider.complete(SYSTEM_PROMPT, prompt, max_tokens=1024)
    except Exception as exc:
        log.error("ai_summary_error", incident_id=incident_id, provider=active_provider_name(), exc=str(exc))
        return

    structured, summary_text = _parse_response(raw, incident_id)

    async with AsyncSessionLocal() as db:
        inc_r = await db.execute(select(Incident).where(Incident.id == iid))
        incident = inc_r.scalar_one_or_none()
        if incident is None:
            return
        incident.ai_structured = structured
        incident.ai_summary = summary_text
        incident.ai_generated_at = datetime.now(UTC)

        chunk = _build_context_chunk(incident, recent_checks)
        db.add(IncidentContext(incident_id=iid, chunk_text=chunk))
        await db.commit()

    from app.api.v1.health import metrics

    metrics.ai_summaries_generated += 1
    log.info("ai_summary_generated", incident_id=incident_id, risk_level=structured.get("risk_level"))


def _parse_response(raw: str, incident_id: str) -> tuple[dict, str]:
    """Parse JSON from LLM response. Returns (structured_dict, display_text)."""
    raw = raw.strip()

    # Strip markdown code fences if the model wrapped the JSON anyway
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("ai_response_not_json", incident_id=incident_id, raw=raw[:200])
        data = {
            "root_cause": raw,
            "confidence": 0.5,
            "risk_level": "Unknown",
            "recommended_actions": [],
            "estimated_impact": "",
            "similar_past_incident": None,
        }

    # Build a readable text version for display / alerts
    actions = "\n".join(f"  • {a}" for a in data.get("recommended_actions", []))
    summary_text = (
        f"[{data.get('risk_level', 'Unknown')} — {int(data.get('confidence', 0) * 100)}% confidence]\n\n"
        f"Root Cause: {data.get('root_cause', '')}\n\n"
        f"Impact: {data.get('estimated_impact', '')}\n\n"
        f"Recommended Actions:\n{actions}"
    )
    if data.get("similar_past_incident"):
        summary_text += f"\n\nSimilar Past Incident: {data['similar_past_incident']}"

    return data, summary_text


def _build_prompt(incident: Incident, service: Service, checks: list[CheckResult], past: list[Incident]) -> str:
    lines = [
        f"## Incident: {incident.trigger_reason}",
        f"Service: {service.name} ({service.url})",
        f"Started: {incident.started_at.isoformat()}",
        "",
        "### Recent Check Results (newest first)",
    ]
    for c in checks[:30]:
        parts = [
            c.checked_at.strftime("%H:%M:%S"),
            f"node={c.checker_node_id}",
            f"status={c.status}",
        ]
        if c.status_code:
            parts.append(f"http={c.status_code}")
        if c.response_ms:
            parts.append(f"latency={c.response_ms}ms")
        if c.error_message:
            parts.append(f'error="{c.error_message}"')
        lines.append("  " + " | ".join(parts))

    if past:
        lines += ["", "### Historical Incidents (for context)"]
        for p in past:
            lines.append(f"- [{p.started_at.date()}] {p.trigger_reason}")
            if p.ai_summary:
                first_line = p.ai_summary.split("\n")[0]
                lines.append(f"  Previous assessment: {first_line}")

    return "\n".join(lines)


def _build_context_chunk(incident: Incident, checks: list[CheckResult]) -> str:
    statuses = [c.status for c in checks]
    errors = [c.error_message for c in checks if c.error_message]
    return (
        f"incident_id={incident.id} "
        f"reason={incident.trigger_reason} "
        f"statuses={','.join(statuses[:10])} "
        f"errors={' | '.join(set(errors[:5]))}"
    )
