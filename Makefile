.PHONY: up down logs test build dev

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

test:
	cd orchestrator && python3 -m pytest tests/ -v
	cd dashboard && npm run build

dev-api:
	cd orchestrator && uvicorn app.main:app --reload --port 8000

dev-worker:
	cd orchestrator && WORKER_ENABLED=false python3 worker_main.py

dev-dashboard:
	cd dashboard && npm run dev

build:
	docker compose build
