# Architecture: turtSlopFactory

## Stack

- **Backend:** FastAPI with async SQLAlchemy
- **Frontend:** Static HTML/JS served by FastAPI
- **Storage:** PostgreSQL
- **Agents:** In-process asyncio pipeline simulating autonomous development iterations
- **Deployment:** Docker + docker-compose

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| GET | /api/info | Service metadata |
| GET | /api/items | List items |
| POST | /api/items | Create item |
| GET | /api/items/{id} | Get item |
| GET | /api/projects | List projects |
| POST | /api/projects | Create and auto-start project |
| GET | /api/projects/{id} | Project status |
| POST | /api/projects/{id}/start | Resume/start agent loop |
| GET | /api/projects/{id}/events | Recent agent activity |

## Agent loop

Projects move through `requested → planning → implementing → testing → review → complete`. After each successful cycle the self-propelled loop proposes an improvement and starts another iteration (up to three by default) without user interaction.

## Testing strategy

- Unit tests via pytest + httpx AsyncClient against in-memory SQLite
- Integration tests for CRUD and project event flows
- Container smoke test on `/health`

## Deployment

`docker compose up --build` starts PostgreSQL and the app on port 8080.
