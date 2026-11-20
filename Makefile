.DEFAULT_GOAL := help
.PHONY: help up down restart logs logs-api logs-worker ps build clean reset-db demo traces test

help: ## Show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

up: ## Build and start everything (waits until healthy). UI: http://localhost:8000
	docker compose up -d --build --wait

down: ## Stop the services (data is kept)
	docker compose down

restart: ## Restart api and worker (data is kept)
	docker compose restart api worker

logs: ## Follow the logs of everything (make logs S=worker for one service)
	docker compose logs -f --tail=100 $(S)

logs-api: ## Follow the API logs (requests, the chat)
	docker compose logs -f --tail=100 api

logs-worker: ## Follow the worker logs (jobs, agent runs and why an attempt failed)
	docker compose logs -f --tail=100 worker

ps: ## Show service status
	docker compose ps

build: ## Build the image
	docker compose build

clean: ## Stop and delete containers, database volume and the built image
	docker compose down -v --rmi local --remove-orphans

reset-db: ## Wipe the database and start again with fresh seed data
	docker compose down -v
	docker compose up -d --build --wait

demo: ## Run the scripted walkthrough against the running system
	./scripts/demo.sh

traces: ## Open the Jaeger UI
	open http://localhost:16686

test: ## Run the tests (needs `make up`; no real model calls)
	cd backend && uv run pytest -q
