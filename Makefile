SERVICE_DIR := services/watertwin-api
API_URL ?= http://localhost:8080

.PHONY: up down dev test lint typecheck scenario-degrade reset install

install:
	pip install -r $(SERVICE_DIR)/requirements-dev.txt

up:
	docker compose up --build -d

down:
	docker compose down

dev:
	cd $(SERVICE_DIR) && uvicorn watertwin.app:app --reload --host 0.0.0.0 --port 8080

test:
	cd $(SERVICE_DIR) && python -m pytest

lint:
	cd $(SERVICE_DIR) && ruff check .

typecheck:
	cd $(SERVICE_DIR) && mypy watertwin

scenario-degrade:
	curl -fsS -X POST $(API_URL)/api/v1/scenario \
		-H 'Content-Type: application/json' \
		-d '{"scenario":"degrade"}' ; echo

reset:
	curl -fsS -X POST $(API_URL)/api/v1/reset ; echo
