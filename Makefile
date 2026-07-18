SHELL := /bin/bash

API_URL ?= http://localhost:8000
PYTHON ?= python3
SBOM_DIR := docs/licensing/sbom
SERVICES := watertwin-api hydraulic-sim treatment-sim edge-gateway
# Services with CycloneDX SBOMs generated + reconciled (see the `sbom` target).
SERVICES := watertwin-api hydraulic-sim treatment-sim watertwin-ingest
# All Python services with lint + pytest suites (superset of SERVICES).
TEST_SERVICES := watertwin-api hydraulic-sim treatment-sim edge-gateway watertwin-ingest
LOAD_PROFILE ?= smoke

HELM_CHART := infrastructure/helm/watertwin
HELM_ENV ?= dev

.PHONY: up down logs ps test lint sbom reconcile backup scenario-degrade reset demo help \
	helm-deps helm-lint helm-template security
.PHONY: up down logs ps test lint sbom reconcile backup scenario-degrade reset \
        demo load-smoke chaos dr-drill help

help:
	@echo "S3M-WaterTwin — make targets"
	@echo "  up               Build + start the whole persistent stack (docker compose)"
	@echo "  down             Stop the stack"
	@echo "  logs             Tail stack logs"
	@echo "  test             Run pytest for every service"
	@echo "  lint             Run ruff for every service"
	@echo "  sbom             Generate CycloneDX SBOMs (python services + dashboard)"
	@echo "  reconcile        Reconcile the SBOMs against the open-source register"
	@echo "  security         Run the ADR-0014 ingestion threat-model test suite"
	@echo "  backup           Back up the audit/Timescale database (pg_dump)"
	@echo "  scenario-degrade Inject an HPP/pump-outage degradation what-if (end-to-end)"
	@echo "  reset            Clear cached runs, recommendations, and audit trail"
	@echo "  demo             scenario-degrade then reset (smoke test the demo path)"
	@echo "  helm-deps        Vendor Helm chart dependencies (watertwin-common)"
	@echo "  helm-lint        helm lint the umbrella chart (HELM_ENV=dev|staging|prod)"
	@echo "  helm-template    Render the umbrella chart for HELM_ENV"
	@echo "  load-smoke       Run the k6 load smoke profile (boots a local in-memory API)"
	@echo "  chaos            Kill the edge-gateway mid-stream; assert store-and-forward recovery"
	@echo "  dr-drill         pg_dump backup + restore + audit-chain integrity check"

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

test:
	@set -e; \
	echo "== pytest packages =="; \
	( cd packages && python -m pytest -q ); \
	echo "== pytest scripts =="; \
	( python -m pytest scripts/tests -q ); \
	for s in $(TEST_SERVICES); do \
		echo "== pytest $$s =="; \
		( cd services/$$s && python -m pytest -q ); \
	done; \
	echo "== npm test dashboard =="; \
	( cd apps/dashboard && npm test )

lint:
	@set -e; for s in $(TEST_SERVICES); do \
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
	@$(MAKE) reconcile

# Reconcile every generated SBOM's direct dependencies against the
# open-source register. Fails if any direct dependency is unregistered.
reconcile:
	@$(PYTHON) scripts/reconcile_sbom.py

# Run the ADR-0014 ingestion threat-model suite (one test per threat row).
security:
	@PYTHONPATH=packages $(PYTHON) -m pytest security/tests -q

# Back up the audit + Timescale database via pg_dump (see docs/deployment).
backup:
	@bash scripts/backup_audit_db.sh

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

# --- Kubernetes / Helm ------------------------------------------------------
# Vendor the watertwin-common library into every component subchart.
helm-deps:
	@bash infrastructure/helm/build-deps.sh

# Lint the umbrella chart for a given environment (HELM_ENV=dev|staging|prod).
helm-lint: helm-deps
	@helm lint $(HELM_CHART) -f $(HELM_CHART)/values-$(HELM_ENV).yaml

# Render the umbrella chart for a given environment.
helm-template: helm-deps
	@helm template watertwin $(HELM_CHART) -n watertwin \
		-f $(HELM_CHART)/values-$(HELM_ENV).yaml
# Run the k6 load smoke profile. Boots a self-contained in-memory API unless
# BASE_URL is set. Requires k6 (https://k6.io/docs/get-started/installation/).
load-smoke:
	@LOAD_PROFILE=$(LOAD_PROFILE) bash tests/load/run_smoke.sh

# Chaos drill: kill the edge-gateway mid-stream and assert store-and-forward
# recovers with no data loss/duplication and a valid audit chain (needs docker).
chaos:
	@bash tests/chaos/edge_gateway_chaos.sh

# Disaster-recovery drill: pg_dump backup + pg_restore into a fresh DB, then
# verify audit-chain integrity post-restore (needs the docker stack running).
dr-drill:
	@bash scripts/dr_drill.sh
