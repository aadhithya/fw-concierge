.DEFAULT_GOAL := help
.PHONY: help up down restart logs logs-api logs-worker ps build clean reset-db demo traces test lint fmt fmt-check check hooks

# The dev container runs as you, so files it writes into the mounted source are not owned by root.
DEV = docker compose --profile dev run --rm --build -u $$(id -u):$$(id -g)

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

test: ## Run the tests in Docker (starts Postgres; never calls a real model)
	$(DEV) dev pytest -q -p no:cacheprovider

lint: ## Lint the backend and the frontend, and type-check the frontend, in Docker
	$(DEV) --no-deps dev ruff check .
	docker run --rm -u $$(id -u):$$(id -g) -e HOME=/tmp $$(docker build -q --target ui .) npm run lint

fmt: ## Fix what the linter can and format the backend, in Docker
	$(DEV) --no-deps dev sh -c "ruff check --fix . ; ruff format ."

fmt-check: ## Check the backend's formatting, in Docker
	$(DEV) --no-deps dev ruff format --check .

check: lint fmt-check test ## Everything the pre-commit hooks run

hooks: ## Install the git hooks (run once per clone)
	pre-commit install --hook-type pre-commit --hook-type commit-msg
