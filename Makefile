.DEFAULT_GOAL := help
.PHONY: help up down restart logs ps build clean reset-db demo traces

help: ## Show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

up: ## Build and start everything (waits until healthy). UI: http://localhost:8000
	docker compose up -d --build --wait

down: ## Stop the services (data is kept)
	docker compose down

restart: ## Restart api and worker (data is kept)
	docker compose restart api worker

logs: ## Follow logs (make logs S=worker for one service)
	docker compose logs -f $(S)

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
