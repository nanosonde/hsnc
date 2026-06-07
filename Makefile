# sdn-manager — developer task runner.
#
# Uses the project virtualenv (.venv) automatically when present, otherwise
# falls back to the system python3. Override the interpreter with:
#     make PYTHON=/path/to/python <target>
#
# Targets (see `make help`): check lint unit integration test all clean

PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
PYBIN  := $(dir $(abspath $(PYTHON)))

PACKAGES      := sdnman sdnweb
SMOKE_TEST    := fakes/smoke_test.sh
FAKES_COMPOSE := fakes/docker-compose.yml
COMPOSE       := docker-compose.yml
DOCKER        ?= docker
IMAGE         ?= sdn-manager:latest

.DEFAULT_GOAL := help

.PHONY: help check lint unit integration test all clean up down logs fakes-up fakes-down docker-build docker-clean

help: ## Show this help.
	@echo "sdn-manager make targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

check: ## Compile-check all sources for syntax errors (fast).
	for pkg in $(PACKAGES); do $(PYTHON) -m compileall -q $$pkg/src $$pkg/tests || exit 1; done

lint: ## Lint both packages with ruff.
	for pkg in $(PACKAGES); do (cd $$pkg && $(abspath $(PYTHON)) -m ruff check src tests) || exit 1; done

unit: ## Run the unit test suite (pytest) for both packages.
	for pkg in $(PACKAGES); do (cd $$pkg && $(abspath $(PYTHON)) -m pytest) || exit 1; done

integration: ## Run integration tests against the fake SSH devices (needs docker + paramiko).
	PATH="$(PYBIN):$$PATH" bash $(SMOKE_TEST)

up: ## Build and start the application container (end users); UI on http://localhost:8080.
	$(DOCKER) compose -f $(COMPOSE) up -d --build
	@echo "sdn-manager is starting on http://localhost:8080 (default login admin/admin)."

down: ## Stop and remove the application container (data volume is kept).
	$(DOCKER) compose -f $(COMPOSE) down

logs: ## Follow the application container logs (Ctrl-C to stop).
	$(DOCKER) compose -f $(COMPOSE) logs -f

fakes-up: ## Build and start the fake SSH device containers (detached).
	$(DOCKER) compose -f $(FAKES_COMPOSE) up -d --build

fakes-down: ## Stop and remove the fake SSH device containers and their volumes.
	$(DOCKER) compose -f $(FAKES_COMPOSE) down -v

docker-build: ## Build the application Docker image (override name with IMAGE=...).
	$(DOCKER) build -t $(IMAGE) .

docker-clean: ## Remove the application Docker image.
	-$(DOCKER) image rm $(IMAGE)

test: unit integration ## Run all tests (unit + integration).

all: check lint test ## Run checking, linting and all tests in order (starts nothing).

clean: ## Remove Python caches, build and coverage artifacts.
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .coverage coverage.xml htmlcov \
		build dist */build */dist */src/*.egg-info
