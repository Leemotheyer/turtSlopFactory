"""Persist and verify Cursor account connections."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import CursorConnectionRow
from app.services.crypto import decrypt_value, encrypt_value, mask_value
from app.services.cursor_client import CursorApiError, CursorClient, CursorUsageSummary

logger = logging.getLogger(__name__)


async def get_connection_row(session: AsyncSession) -> CursorConnectionRow | None:
    result = await session.execute(
        select(CursorConnectionRow).order_by(CursorConnectionRow.connected_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def get_connection_status(session: AsyncSession) -> dict[str, Any]:
    row = await get_connection_row(session)
    if not row:
        return {"connected": False}

    return {
        "connected": True,
        "user_email": row.user_email,
        "api_key_name": row.api_key_name,
        "masked_api_key": mask_value(decrypt_value(row.encrypted_api_key)),
        "enterprise_billing": row.enterprise_billing,
        "connected_at": row.connected_at.isoformat(),
        "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
    }


async def connect_cursor(session: AsyncSession, api_key: str) -> dict[str, Any]:
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("API key is required")

    async with CursorClient(api_key) as client:
        me = await client.get_me()
        summary = await client.build_usage_summary()

    existing = await get_connection_row(session)
    if existing:
        await session.delete(existing)
        await session.flush()

    row = CursorConnectionRow(
        encrypted_api_key=encrypt_value(api_key),
        api_key_name=me.get("apiKeyName"),
        user_email=me.get("userEmail"),
        user_id=me.get("userId"),
        enterprise_billing=summary.enterprise_billing,
        connected_at=datetime.utcnow(),
        last_synced_at=datetime.utcnow(),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    return await get_connection_status(session)


async def disconnect_cursor(session: AsyncSession) -> dict[str, Any]:
    row = await get_connection_row(session)
    if row:
        await session.delete(row)
        await session.commit()
    return {"connected": False}


async def _api_key_from_row(row: CursorConnectionRow) -> str:
    return decrypt_value(row.encrypted_api_key)


async def fetch_usage(session: AsyncSession) -> dict[str, Any]:
    row = await get_connection_row(session)
    if not row:
        return {"connected": False, "note": "Connect your Cursor API key to view usage."}

    try:
        async with CursorClient(await _api_key_from_row(row)) as client:
            summary = await client.build_usage_summary()
    except CursorApiError as exc:
        if exc.status in (401, 403):
            return {
                "connected": False,
                "error": "Cursor API key is invalid or expired. Reconnect from settings.",
            }
        raise

    row.enterprise_billing = summary.enterprise_billing
    row.last_synced_at = datetime.utcnow()
    await session.commit()

    return _summary_to_dict(summary)


async def list_cursor_agents(session: AsyncSession) -> dict[str, Any]:
    row = await get_connection_row(session)
    if not row:
        return {"connected": False, "agents": []}

    async with CursorClient(await _api_key_from_row(row)) as client:
        agents = await client.list_agents(limit=50)
        enriched = []
        for agent in agents:
            agent_id = agent.get("id")
            tokens = 0
            if agent_id:
                try:
                    usage = await client.get_agent_usage(agent_id)
                    tokens = (usage.get("totalUsage") or {}).get("totalTokens", 0)
                except CursorApiError:
                    pass
            enriched.append(
                {
                    "id": agent_id,
                    "name": agent.get("name"),
                    "status": agent.get("status"),
                    "url": agent.get("url"),
                    "created_at": agent.get("createdAt"),
                    "total_tokens": tokens,
                }
            )

    row.last_synced_at = datetime.utcnow()
    await session.commit()
    return {"connected": True, "agents": enriched}


def _summary_to_dict(summary: CursorUsageSummary) -> dict[str, Any]:
    return {
        "connected": summary.connected,
        "user_email": summary.user_email,
        "api_key_name": summary.api_key_name,
        "enterprise_billing": summary.enterprise_billing,
        "spend_cents": summary.spend_cents,
        "overall_spend_cents": summary.overall_spend_cents,
        "spend_limit_dollars": summary.spend_limit_dollars,
        "remaining_budget_dollars": summary.remaining_budget_dollars,
        "subscription_cycle_start": summary.subscription_cycle_start,
        "tokens": {
            "input_tokens": summary.tokens.input_tokens,
            "output_tokens": summary.tokens.output_tokens,
            "cache_write_tokens": summary.tokens.cache_write_tokens,
            "cache_read_tokens": summary.tokens.cache_read_tokens,
            "total_tokens": summary.tokens.total_tokens,
        },
        "agents": summary.agents,
        "note": summary.note,
    }
