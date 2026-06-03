"""
AI-powered incident summary with multi-provider support.

Provider selection (automatic, in priority order):
  1. Anthropic Claude  — if ANTHROPIC_API_KEY is set
  2. Groq (free tier) — if GROQ_API_KEY is set  (llama-3.3-70b-versatile by default)
  3. Disabled         — if neither key is present

Design: prompt-based RAG (no fine-tuning).
  1. Retrieve last N check results for the failing service → recent metrics.
  2. Retrieve up to 3 past resolved incidents for the same service → historical context.
  3. Build a structured prompt and call the selected LLM.
  4. Store the summary on the Incident row.
"""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import AsyncSessionLocal
from app.db.models import CheckResult, Incident, IncidentContext, Service

log = get_logger(__name__)


# ── Provider abstraction ──────────────────────────────────────────────────────

class LLMProvider(Protocol):
    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        ...


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
        return response.content[0].text


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
        return response.choices[0].message.content


_provider: LLMProvider | None = None


def _get_provider() -> LLMProvider | None:
    """Lazily build the provider once; returns None if AI is unconfigured."""
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
    """Returns 'anthropic', 'groq', or 'none' — used by /metrics."""
    if settings.ANTHROPIC_API_KEY:
        return "anthropic"
    if settings.GROQ_API_KEY:
        return "groq"
    return "none"


SYSTEM_PROMPT = """\
You are an expert SRE (Site Reliability Engineer) analyzing an API monitoring incident.
Your job is to produce a concise, actionable incident report in plain English.

Format your response as:
## Summary
One sentence describing what happened.

## Likely Root Causes
Bulleted list of 2-4 probable causes, ordered by likelihood.

## Recommended Actions
Bulleted list of immediate investigation steps.

## Risk Assessment
ONE of: Critical / High / Medium / Low — with a one-sentence justification.

Be specific. Reference actual error messages, status codes, and response times from the data provided.
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
        # Load incident + service
        inc_r = await db.execute(
            select(Incident)
            .options(selectinload(Incident.service))
            .where(Incident.id == iid)
        )
        incident = inc_r.scalar_one_or_none()
        if incident is None:
            log.warning("ai_summary_incident_not_found", incident_id=incident_id)
            return

        service: Service = incident.service

        # Recent check results (last 30 min, up to 50 rows)
        window = datetime.now(UTC) - timedelta(minutes=30)
        recent_r = await db.execute(
            select(CheckResult)
            .where(CheckResult.service_id == service.id, CheckResult.checked_at >= window)
            .order_by(CheckResult.checked_at.desc())
            .limit(50)
        )
        recent_checks = recent_r.scalars().all()

        # Past resolved incidents for RAG context (most recent 3)
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
        past_incidents = past_r.scalars().all()

    # Build prompt
    prompt = _build_prompt(incident, service, recent_checks, past_incidents)

    try:
        summary = await provider.complete(SYSTEM_PROMPT, prompt, max_tokens=1024)
    except Exception as exc:
        log.error("ai_summary_error", incident_id=incident_id, provider=active_provider_name(), exc=str(exc))
        return

    # Persist summary + context chunks
    async with AsyncSessionLocal() as db:
        inc_r = await db.execute(select(Incident).where(Incident.id == iid))
        incident = inc_r.scalar_one_or_none()
        if incident is None:
            return
        incident.ai_summary = summary
        incident.ai_generated_at = datetime.now(UTC)

        # Store context chunk for future RAG retrieval
        chunk = _build_context_chunk(incident, recent_checks)
        db.add(IncidentContext(incident_id=iid, chunk_text=chunk))
        await db.commit()

    from app.api.v1.health import metrics
    metrics.ai_summaries_generated += 1
    log.info("ai_summary_generated", incident_id=incident_id)


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
                # Include just the summary line to keep prompt concise
                first_line = p.ai_summary.split("\n")[0]
                lines.append(f"  Previous AI assessment: {first_line}")

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
