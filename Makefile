# sdn-manager — developer task runner.
#
# Uses the project virtualenv (.venv) automatically when present, otherwise
# falls back to the system python3. Override the interpreter with:
#     make PYTHON=/path/to/python <target>
#
# Targets (see `make help`): check lint unit integration test all clean

PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
PYBIN  := $(dir $(abspath $(PYTHON)))

SRC_DIRS      := src tests
SMOKE_TEST    := mocks/smoke_test.sh
MOCKS_COMPOSE := mocks/docker-compose.yml
DOCKER        ?= docker

.DEFAULT_GOAL := help

.PHONY: help check lint unit integration test all clean mocks-up mocks-down

help: ## Show this help.
	@echo "sdn-manager make targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

check: ## Compile-check all sources for syntax errors (fast).
	$(PYTHON) -m compileall -q $(SRC_DIRS)

lint: ## Lint sources with ruff.
	$(PYTHON) -m ruff check $(SRC_DIRS)

unit: ## Run the unit test suite (pytest).
	$(PYTHON) -m pytest

integration: ## Run integration tests against the mock SSH devices (needs docker + paramiko).
	PATH="$(PYBIN):$$PATH" bash $(SMOKE_TEST)

mocks-up: ## Build and start the mock SSH device containers (detached).
	$(DOCKER) compose -f $(MOCKS_COMPOSE) up -d --build

mocks-down: ## Stop and remove the mock SSH device containers and their volumes.
	$(DOCKER) compose -f $(MOCKS_COMPOSE) down -v

test: unit integration ## Run all tests (unit + integration).

all: check lint test ## Run checking, linting and all tests in order (starts nothing).

clean: ## Remove Python caches, build and coverage artifacts.
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .coverage coverage.xml htmlcov \
		build dist src/*.egg-info
