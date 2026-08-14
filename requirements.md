# Requirements: turtSlopFactory

## Overview

turtSlopFactory is a self-hosted agentic software factory for home-lab users. Give it a rough idea, start a project, and autonomous agents plan, implement, test, and iterate with minimal supervision.

## Functional requirements

1. Expose a `/health` endpoint returning JSON status
2. Provide REST APIs for lightweight item management (create, list, get)
3. Provide REST APIs for software projects (create, list, status, events)
4. Self-propelled development agents that advance projects through planning, implementation, testing, and review without user input
5. Serve a mobile-friendly web UI for starting projects and checking progress
6. Persist projects and events in PostgreSQL
7. Run in Docker with healthcheck support

## Exclusions

- Commercial licensing constraints (project is open source)
- Multi-user authentication (single-user / internal tool)

## Non-functional requirements

- Python 3.12 + FastAPI
- PostgreSQL for durable state
- Unit and integration test coverage via pytest
- Containerized deployment on port 8080
- Mobile-friendly responsive UI
- Minimal required user input — users can start a project and check back later
