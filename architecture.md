# Architecture: turtSlopFactory

## Stack

- **Backend:** FastAPI (async)
- **Frontend:** Static HTML/CSS/JS served by FastAPI
- **Storage:** PostgreSQL (SQLAlchemy + asyncpg)
- **Background work:** asyncio agent worker loop
- **Deployment:** Docker + docker-compose on port 8080

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| GET | /api/info | Service metadata |
| GET | /api/items | List demo items |
| POST | /api/items | Create demo item |
| GET | /api/items/{id} | Get demo item |
| GET | /api/projects | List projects |
| POST | /api/projects | Create and auto-start a project |
| GET | /api/projects/{id} | Project detail with events |
| POST | /api/projects/{id}/advance | Manually trigger agent step (optional) |

## Data model

- **projects:** id, name, idea, status, phase, progress_pct, created_at, updated_at
- **project_events:** id, project_id, message, level, created_at
- **items:** in-memory demo CRUD (pipeline contract)

## Agent pipeline

Projects move through phases: `queued` → `planning` → `implementing` → `testing` → `ready`. A background worker picks queued/active projects and advances them on a timer without user input.

## Testing strategy

- Unit tests via pytest + TestClient (`tests/test_app.py`)
- Integration tests for project lifecycle (`tests/test_integration.py`)
- Container smoke test on `/health`

## Deployment

```bash
docker compose -f docker-compose.app.yml up -d
```

Open http://localhost:8080
