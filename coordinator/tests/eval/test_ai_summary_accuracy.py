"""
AI Summary Accuracy Evaluation Harness.

Scores generated summaries against a small labeled set of known incidents.
Evaluation criteria (each scored 0-1):
  1. mentions_expected_cause:  Summary references the expected root cause keyword(s).
  2. has_recommended_action:   Summary includes at least one recommended action.
  3. correct_risk_level:       Risk level matches expected (within one level).
  4. no_hallucination_marker:  Does NOT reference services/errors not in the prompt.

Run with: pytest tests/eval/ -v -s --no-header
Requires ANTHROPIC_API_KEY to be set; otherwise skips.
"""

import os
from dataclasses import dataclass

import pytest

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SKIP_REASON = "ANTHROPIC_API_KEY not set"

RISK_LEVELS = ["low", "medium", "high", "critical"]


@dataclass
class EvalCase:
    name: str
    incident_trigger: str
    recent_checks_text: str
    expected_cause_keywords: list[str]
    expected_risk: str  # low/medium/high/critical


EVAL_CASES: list[EvalCase] = [
    EvalCase(
        name="connection_timeout",
        incident_trigger="Quorum failure: 3/3 checks failed (100%) in last 120s",
        recent_checks_text="""
  14:00:00 | node=checker-us-east | status=timeout | latency=5001ms | error="Timeout after 5001ms: ReadTimeout"
  14:00:00 | node=checker-eu-west | status=timeout | latency=5001ms | error="Timeout after 5001ms: ReadTimeout"
  14:00:00 | node=checker-ap-south | status=timeout | latency=5001ms | error="Timeout after 5001ms: ReadTimeout"
  13:59:00 | node=checker-us-east | status=up | http=200 | latency=45ms
  13:58:00 | node=checker-eu-west | status=up | http=200 | latency=52ms
""",
        expected_cause_keywords=["timeout", "network", "latency", "connectivity"],
        expected_risk="high",
    ),
    EvalCase(
        name="http_503_service_unavailable",
        incident_trigger="Quorum failure: 2/3 checks failed (67%) in last 120s",
        recent_checks_text="""
  15:00:00 | node=checker-us-east | status=down | http=503 | error="Expected 200, got 503"
  15:00:00 | node=checker-eu-west | status=down | http=503 | error="Expected 200, got 503"
  15:00:00 | node=checker-ap-south | status=up | http=200 | latency=88ms
  14:59:00 | node=checker-us-east | status=down | http=503 | error="Expected 200, got 503"
""",
        expected_cause_keywords=["503", "unavailable", "overload", "deploy", "restart"],
        expected_risk="high",
    ),
    EvalCase(
        name="intermittent_errors",
        incident_trigger="Quorum failure: 52/100 checks failed (52%) in last 120s",
        recent_checks_text="""
  16:00:00 | node=checker-us-east | status=up | http=200 | latency=234ms
  16:00:00 | node=checker-eu-west | status=down | http=500 | error="Expected 200, got 500"
  16:00:00 | node=checker-ap-south | status=up | http=200 | latency=189ms
  15:59:30 | node=checker-us-east | status=down | http=500 | error="Expected 200, got 500"
  15:59:30 | node=checker-eu-west | status=up | http=200 | latency=201ms
""",
        expected_cause_keywords=["intermittent", "500", "flapping", "error rate"],
        expected_risk="medium",
    ),
]


def _score_summary(summary: str, case: EvalCase) -> dict[str, float]:
    summary_lower = summary.lower()

    # 1. Mentions expected cause
    cause_hit = any(kw.lower() in summary_lower for kw in case.expected_cause_keywords)
    mentions_cause = 1.0 if cause_hit else 0.0

    # 2. Has recommended action
    has_action = (
        1.0
        if any(
            marker in summary_lower
            for marker in ["recommend", "check", "investigate", "review", "restart", "monitor", "contact", "escalate"]
        )
        else 0.0
    )

    # 3. Risk level accuracy (within one level)
    found_risk = "unknown"
    for level in RISK_LEVELS:
        if level in summary_lower:
            found_risk = level
            break
    expected_idx = RISK_LEVELS.index(case.expected_risk) if case.expected_risk in RISK_LEVELS else -1
    found_idx = RISK_LEVELS.index(found_risk) if found_risk in RISK_LEVELS else -1
    risk_score = 1.0 if abs(expected_idx - found_idx) <= 1 else 0.0

    # 4. No hallucination markers (references to services not in the prompt)
    hallucination_markers = (
        ["database", "redis", "postgres", "kafka"] if "database" not in case.recent_checks_text.lower() else []
    )  # noqa: E501
    no_hallucination = 0.0 if any(m in summary_lower for m in hallucination_markers) else 1.0

    overall = (mentions_cause + has_action + risk_score + no_hallucination) / 4.0

    return {
        "mentions_cause": mentions_cause,
        "has_recommended_action": has_action,
        "risk_level_accuracy": risk_score,
        "no_hallucination": no_hallucination,
        "overall": overall,
    }


async def _generate_summary(case: EvalCase) -> str:
    import anthropic

    from app.incidents.ai_summary import SYSTEM_PROMPT

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""## Incident: {case.incident_trigger}
Service: EvalTest (https://eval.example.com)
Started: 2024-01-15T14:00:00Z

### Recent Check Results (newest first)
{case.recent_checks_text}
"""
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",  # Use Haiku for eval to save cost
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


@pytest.mark.skipif(not ANTHROPIC_API_KEY, reason=SKIP_REASON)
@pytest.mark.asyncio
@pytest.mark.parametrize("case", EVAL_CASES, ids=[c.name for c in EVAL_CASES])
async def test_ai_summary_quality(case: EvalCase):
    """Each case must score ≥ 0.75 overall to pass."""
    summary = await _generate_summary(case)
    scores = _score_summary(summary, case)

    print(f"\n{'=' * 60}")
    print(f"Case: {case.name}")
    print(f"Summary:\n{summary}")
    print(f"\nScores: {scores}")
    print(f"{'=' * 60}")

    assert scores["overall"] >= 0.75, (
        f"AI summary quality too low ({scores['overall']:.2f} < 0.75). Scores: {scores}\n\nSummary:\n{summary}"
    )


@pytest.mark.skipif(not ANTHROPIC_API_KEY, reason=SKIP_REASON)
@pytest.mark.asyncio
async def test_aggregate_eval_score():
    """All cases combined must average ≥ 0.75."""
    scores_list = []
    for case in EVAL_CASES:
        summary = await _generate_summary(case)
        scores = _score_summary(summary, case)
        scores_list.append(scores["overall"])

    avg = sum(scores_list) / len(scores_list)
    print(f"\nAggregate eval score: {avg:.3f} across {len(EVAL_CASES)} cases")
    assert avg >= 0.75, f"Aggregate score {avg:.3f} below threshold 0.75"
