SHELL := /bin/bash

API_URL ?= http://localhost:8000
PYTHON ?= python3
SBOM_DIR := docs/licensing/sbom
SERVICES := watertwin-api hydraulic-sim treatment-sim

.PHONY: up down logs ps test lint sbom scenario-degrade reset demo help

help:
	@echo "S3M-WaterTwin — make targets"
	@echo "  up               Build + start the whole persistent stack (docker compose)"
	@echo "  down             Stop the stack"
	@echo "  logs             Tail stack logs"
	@echo "  test             Run pytest for every service"
	@echo "  lint             Run ruff for every service"
	@echo "  sbom             Generate CycloneDX SBOMs (python services + dashboard)"
	@echo "  scenario-degrade Inject an HPP/pump-outage degradation what-if (end-to-end)"
	@echo "  reset            Clear cached runs, recommendations, and audit trail"
	@echo "  demo             scenario-degrade then reset (smoke test the demo path)"

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

test:
	@set -e; for s in $(SERVICES); do \
		echo "== pytest $$s =="; \
		( cd services/$$s && python -m pytest -q ); \
	done

lint:
	@set -e; for s in $(SERVICES); do \
		echo "== ruff $$s =="; \
		( cd services/$$s && ruff check . ); \
	done

sbom:
	@mkdir -p $(SBOM_DIR)
	@for s in $(SERVICES); do \
		echo "== SBOM $$s =="; \
		$(PYTHON) -m cyclonedx_py requirements services/$$s/requirements.txt \
			-o $(SBOM_DIR)/sbom-$$s.cdx.json; \
	done
	@echo "== SBOM dashboard (npm) =="
	@cd apps/dashboard && npx --yes @cyclonedx/cyclonedx-npm@latest --package-lock-only \
		--output-format JSON --output-file ../../$(SBOM_DIR)/sbom-dashboard.cdx.json

# Inject a pump-outage / HPP degradation what-if and show the impact + the
# advisory recommendation. Read-only end to end; nothing is written to plant.
scenario-degrade:
	@echo "Injecting pump-outage (HPP degradation) what-if against $(API_URL) ..."
	@curl -fsS -X POST $(API_URL)/api/v1/simulation-center/run \
		-H 'Content-Type: application/json' \
		-d '{"scenario":"pump_outage","parameters":{"pump_id":"PU-PROD-2"},"create_recommendation":true}' \
		| $(PYTHON) -m json.tool | sed -n '1,40p'
	@echo "(read-only advisory what-if — no control action taken)"

reset:
	@echo "Resetting cached runs, recommendations, and audit trail ..."
	@curl -fsS -X POST $(API_URL)/api/v1/reset ; echo

demo: scenario-degrade reset
	@echo "Demo smoke path complete."
