.PHONY: benchmarks
benchmarks: ## Run factory benchmarks (deterministic local backend, no docker needed)
	python3 scripts/run_benchmarks.py

.PHONY: up down dev deps logs test build install

# Production deploy (pull GHCR image, single container on :8044)
up:
	docker compose pull
	docker compose up -d

# Build from source
dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# Postgres + redis only for host-based API/dashboard dev
deps:
	docker compose -f docker-compose.deps.yml up -d

down:
	docker compose down

logs:
	docker compose logs -f

install:
	./install.sh

test:
	cd orchestrator && python3 -m pytest tests/ -q

dev-api:
	cd orchestrator && uvicorn app.main:app --reload --port 8000

dev-worker:
	cd orchestrator && WORKER_ENABLED=false python3 worker_main.py

dev-dashboard:
	cd dashboard && npm run dev

build:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml build

verify-deploy:
	./scripts/verify-deploy.sh
