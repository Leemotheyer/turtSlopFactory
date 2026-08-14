# Requirements: turtSlopFactory

## Overview

turtSlopFactory is a self-hosted agentic software factory for home labbers. Users start a project with minimal input, then autonomous development agents plan, implement, and iterate until a releasable Docker web application is ready.

## Functional requirements

1. Expose a `/health` endpoint returning JSON status
2. Provide REST API for demo item management (create, list, get)
3. Allow users to create software projects with a name and optional brief idea
4. Run self-propelled background agents that advance projects through planning, implementation, and testing stages
5. Persist projects and agent activity in PostgreSQL
6. Serve a mobile-friendly web UI to start projects and check progress without babysitting
7. Run in Docker with healthcheck support on port 8080

## Exclusions

- Commercial licensing or paid tiers (open source only)
- Multi-user authentication (single-user internal tool)

## Non-functional requirements

- Python 3.12 + FastAPI
- PostgreSQL for durable project state
- Unit and integration test coverage via pytest
- Containerized deployment with docker-compose
- Responsive UI usable on phones and tablets

## Success criteria

A user can open the dashboard, start a project in seconds, leave, and return later to find meaningful progress toward a complete Docker-deployable product.
