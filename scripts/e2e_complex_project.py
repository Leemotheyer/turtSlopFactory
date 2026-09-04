#!/usr/bin/env python3
"""Drive a moderately complex project through the live factory API."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8044"

COMPLEX_DESCRIPTION = """
Build a Warehouse Inventory & Order Management System — a moderately complex multi-module web app.

## Core domain
- Product catalog: SKU, name, description, category, unit price, quantity on hand, reorder threshold
- Categories: CRUD with name and description; products belong to one category
- Customers: name, email, phone (no authentication — single-tenant internal tool)
- Orders: create orders with multiple line items, auto-calculate subtotal/tax/total, order status (draft/submitted/shipped)
- Stock adjustments: record receive/shipment/adjustment events with reason and timestamp; updates product quantity
- Low-stock dashboard: highlight products at or below reorder threshold

## UI (multi-page browser app)
- Dashboard with KPIs (total products, open orders, low-stock count)
- Products list with search, category filter, sort by name/SKU/stock
- Product detail + edit form
- Categories management page
- Customers list + create/edit
- Orders list + create order flow (pick customer, add line items, submit)
- Stock adjustment form
- Responsive layout, clear navigation

## API
- REST JSON API for all entities under /api/
- /health returns 200
- Proper validation and 404/422 error responses
- SQLite persistence (file-backed, survives restarts)

## Operations
- Dockerfile exposing port 8080
- docker-compose.yml for local deploy
- README with setup and API overview
- pytest unit tests for API behavior
- tests/acceptance/ with tests named test_r*_* matching contract requirements

## Explicitly out of scope
- User authentication / login
- Payment processing
- Email notifications
- Mobile native apps

## Success criteria
- docker compose up --build serves the UI on port 8080
- Full CRUD workflows work in browser and via API
- Creating an order decrements stock; stock adjustments update quantities
- Search and filters return correct results
- All pytest and acceptance tests pass
""".strip()


def api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def wait_for_discovery(project_id: str, timeout: int = 180) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        disc = api("GET", f"/api/projects/{project_id}/discovery")
        status = disc.get("status")
        if status == "awaiting_user":
            return disc
        if status in ("submitted", "auto_submitted"):
            return disc
        time.sleep(3)
    raise TimeoutError("Discovery did not complete")


def build_intake_responses(discovery: dict) -> dict[str, str | list[str]]:
    defaults = {
        "primary_goal": "Warehouse inventory and order management for a small business",
        "target_users": "Warehouse staff and office managers (single team, no login)",
        "must_have_features": "\n".join(
            [
                "Product catalog with SKU, categories, pricing, and stock levels",
                "Customer records and multi-line-item orders with tax calculation",
                "Stock adjustments with audit trail and low-stock dashboard",
                "Multi-page web UI with search, filters, and CRUD for all entities",
                "REST JSON API backed by SQLite persistence",
                "Docker deploy on port 8080 with README and pytest coverage",
            ]
        ),
        "out_of_scope": "\n".join(
            [
                "Authentication and user accounts",
                "Payment processing",
                "Email or push notifications",
                "Native mobile apps",
            ]
        ),
        "app_surface": "Web browser UI + REST API",
        "auth_model": "No auth (single-user / internal tool)",
        "data_storage": "SQLite file database",
        "success_criteria": "docker compose up --build; full order and inventory workflows work in UI and API; all tests pass",
        "main_entities": "Product, Category, Customer, Order, OrderLine, StockAdjustment",
    }
    responses: dict[str, str | list[str]] = {}
    for field in discovery.get("form_fields") or []:
        fid = field["id"]
        if fid in defaults:
            responses[fid] = defaults[fid]
        elif field.get("default"):
            responses[fid] = field["default"]
        elif field["type"] == "multiselect":
            responses[fid] = field.get("options") or []
        else:
            responses[fid] = defaults.get(fid, "As described in the project brief")
    return responses


def poll_project(project_id: str, timeout_hours: float = 6.0) -> None:
    deadline = time.time() + timeout_hours * 3600
    last_state = None
    last_sub = None
    while time.time() < deadline:
        detail = api("GET", f"/api/projects/{project_id}/detail")
        state = detail.get("state")
        substage = (detail.get("pipeline_substage") or {}).get("step")
        running = detail.get("pipeline_running")
        if state != last_state or substage != last_sub:
            print(
                f"[{time.strftime('%H:%M:%S')}] state={state} substage={substage or '-'} "
                f"running={running} failed_gate={detail.get('failed_gate')} "
                f"failed_substage={detail.get('failed_substage')}",
                flush=True,
            )
            last_state = state
            last_sub = substage

        if state == "PRODUCTION":
            print(f"DONE production_url={detail.get('production_url') or detail.get('preview_url')}")
            return
        if state == "AUTONOMOUSLY_BLOCKED":
            log = api("GET", f"/api/projects/{project_id}/logs/pipeline.log")
            lines = (log.get("content") or "").splitlines()
            print("BLOCKED — last 30 log lines:")
            for line in lines[-30:]:
                print(" ", line)
            raise SystemExit(1)
        if state == "REVIEW" and not running:
            print("Review ready — auto-promote should handle this; waiting briefly...")
            time.sleep(15)
            continue
        time.sleep(20)
    raise TimeoutError("Pipeline did not finish in time")


def main() -> int:
    print("Creating complex project...")
    project = api(
        "POST",
        "/api/projects",
        {
            "name": "Warehouse Inventory System",
            "description": COMPLEX_DESCRIPTION,
            "max_enrichment_passes": 1,
        },
    )
    project_id = project["id"]
    print(f"Project id={project_id} state={project['state']}")

    discovery = wait_for_discovery(project_id)
    if discovery.get("status") == "awaiting_user":
        responses = build_intake_responses(discovery)
        print(f"Submitting intake ({len(responses)} fields)...")
        api("POST", f"/api/projects/{project_id}/discovery/submit", {"responses": responses})
    else:
        print(f"Intake already {discovery.get('status')}")

    detail = api("GET", f"/api/projects/{project_id}/detail")
    if not detail.get("pipeline_running") and detail.get("state") == "PLANNING":
        print("Starting pipeline...")
        api("POST", f"/api/projects/{project_id}/run")

    poll_project(project_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
