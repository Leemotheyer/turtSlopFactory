"""HTTP client for Cursor Cloud Agents + Admin APIs."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CURSOR_API_BASE = "https://api.cursor.com"


class CursorApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


@dataclass
class TokenTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0

    def add(self, usage: dict[str, Any]) -> None:
        self.input_tokens += int(usage.get("inputTokens") or 0)
        self.output_tokens += int(usage.get("outputTokens") or 0)
        self.cache_write_tokens += int(usage.get("cacheWriteTokens") or 0)
        self.cache_read_tokens += int(usage.get("cacheReadTokens") or 0)
        self.total_tokens += int(usage.get("totalTokens") or 0)


@dataclass
class CursorUsageSummary:
    connected: bool = False
    user_email: str | None = None
    api_key_name: str | None = None
    enterprise_billing: bool = False
    spend_cents: float | None = None
    overall_spend_cents: float | None = None
    spend_limit_dollars: float | None = None
    remaining_budget_dollars: float | None = None
    subscription_cycle_start: str | None = None
    tokens: TokenTotals = field(default_factory=TokenTotals)
    agents: list[dict[str, Any]] = field(default_factory=list)
    note: str | None = None


class CursorClient:
    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self.api_key = api_key.strip()
        self._client = httpx.AsyncClient(
            base_url=CURSOR_API_BASE,
            auth=(self.api_key, ""),
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> CursorClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            detail = response.text[:500]
            try:
                payload = response.json()
                detail = payload.get("message") or payload.get("error") or detail
            except Exception:
                pass
            raise CursorApiError(response.status_code, str(detail))
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    async def get_me(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/me")

    async def list_agents(self, limit: int = 30) -> list[dict[str, Any]]:
        data = await self._request("GET", "/v1/agents", params={"limit": limit})
        return data.get("items") or data.get("agents") or []

    async def list_repositories(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/v1/repositories")
        return data.get("items") or data.get("repositories") or []

    async def list_models(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/v1/models")
        return data.get("items") or data.get("models") or []

    async def get_agent_usage(self, agent_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/agents/{agent_id}/usage")

    async def get_team_spend(self, search_term: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"page": 1, "pageSize": 50}
        if search_term:
            body["searchTerm"] = search_term
        return await self._request("POST", "/teams/spend", json=body)

    async def get_daily_usage(self, days: int = 30) -> dict[str, Any]:
        end = date.today()
        start = end - timedelta(days=days)
        return await self._request(
            "POST",
            "/teams/daily-usage-data",
            json={
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
            },
        )

    async def create_agent(
        self,
        prompt_text: str,
        *,
        name: str | None = None,
        repos: list[dict[str, str]] | None = None,
        starting_ref: str | None = None,
        model_id: str | None = None,
        model_params: list[dict[str, str]] | None = None,
        mode: str = "agent",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "prompt": {"text": prompt_text},
            "mode": mode,
        }
        if name:
            body["name"] = name[:100]
        if model_id:
            model_body: dict[str, Any] = {"id": model_id}
            if model_params:
                model_body["params"] = model_params
            body["model"] = model_body
        if repos:
            body["repos"] = repos
        return await self._request("POST", "/v1/agents", json=body)

    async def create_run(self, agent_id: str, prompt_text: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/agents/{agent_id}/runs",
            json={"prompt": {"text": prompt_text}},
        )

    async def get_run(self, agent_id: str, run_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/agents/{agent_id}/runs/{run_id}")

    async def wait_for_run(
        self,
        agent_id: str,
        run_id: str,
        *,
        poll_seconds: float = 5.0,
        timeout_seconds: int = 3600,
    ) -> dict[str, Any]:
        import asyncio
        import time

        terminal = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            run = await self.get_run(agent_id, run_id)
            status = (run.get("status") or "").upper()
            if status in terminal:
                return run
            await asyncio.sleep(poll_seconds)
        raise TimeoutError(f"Cursor run {run_id} did not finish within {timeout_seconds}s")

    async def build_usage_summary(self) -> CursorUsageSummary:
        summary = CursorUsageSummary(connected=True)
        me = await self.get_me()
        summary.api_key_name = me.get("apiKeyName")
        summary.user_email = me.get("userEmail")

        agents = await self.list_agents()
        for agent in agents:
            agent_id = agent.get("id")
            usage_data: dict[str, Any] = {}
            if agent_id:
                try:
                    usage_data = await self.get_agent_usage(agent_id)
                    summary.tokens.add(usage_data.get("totalUsage") or {})
                except CursorApiError as exc:
                    logger.debug("Agent usage unavailable for %s: %s", agent_id, exc.message)

            summary.agents.append(
                {
                    "id": agent_id,
                    "name": agent.get("name"),
                    "status": agent.get("status"),
                    "url": agent.get("url"),
                    "created_at": agent.get("createdAt"),
                    "total_tokens": (usage_data.get("totalUsage") or {}).get("totalTokens", 0),
                }
            )

        try:
            spend = await self.get_team_spend(summary.user_email)
            summary.enterprise_billing = True
            summary.subscription_cycle_start = _ms_to_iso(spend.get("subscriptionCycleStart"))
            member = _match_member_spend(spend.get("teamMemberSpend") or [], summary.user_email)
            if member:
                summary.spend_cents = float(member.get("spendCents") or 0)
                summary.overall_spend_cents = float(member.get("overallSpendCents") or 0)
                limit = member.get("effectivePerUserLimitDollars")
                if limit is not None:
                    summary.spend_limit_dollars = float(limit)
                    spent_dollars = (summary.spend_cents or 0) / 100.0
                    summary.remaining_budget_dollars = max(0.0, summary.spend_limit_dollars - spent_dollars)
        except CursorApiError as exc:
            if exc.status == 403:
                summary.note = (
                    "Token totals from your Cloud Agents are shown. "
                    "Connect an Enterprise Admin API key for full billing-cycle spend and limits."
                )
            elif exc.status != 404:
                summary.note = f"Billing API unavailable: {exc.message}"

        if not summary.note and not summary.enterprise_billing:
            summary.note = (
                "Showing token usage from Cloud Agents. "
                "Enterprise Admin API keys unlock billing-cycle spend and remaining budget."
            )

        return summary


def _ms_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _match_member_spend(members: list[dict], email: str | None) -> dict | None:
    if not email:
        return members[0] if members else None
    email_lower = email.lower()
    for member in members:
        if (member.get("email") or "").lower() == email_lower:
            return member
    return members[0] if members else None
