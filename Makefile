SHELL := /bin/sh

PYTHON ?= .venv/bin/python
PIP := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest
UVICORN := $(PYTHON) -m uvicorn
RUFF := $(PYTHON) -m ruff
MYPY := $(PYTHON) -m mypy
ALEMBIC := $(PYTHON) -m alembic
PIP_AUDIT := $(PYTHON) -m pip_audit

COMPOSE ?= docker compose

COV_FAIL_UNDER ?= 90
MSG ?=

.DEFAULT_GOAL := help

help:
	@echo "Available targets:"
	@echo "  make venv           - Create local virtualenv in .venv"
	@echo "  make install        - Install project + dev dependencies"
	@echo "  make run            - Run API locally with reload"
	@echo "  make test           - Run test suite"
	@echo "  make test-cov       - Run tests with coverage gate"
	@echo "  make lint           - Ruff lint"
	@echo "  make format         - Ruff format"
	@echo "  make format-check   - Ruff format check"
	@echo "  make typecheck      - Mypy type checking"
	@echo "  make security       - Dependency vulnerability audit"
	@echo "  make quality        - lint + format-check + typecheck"
	@echo "  make ci             - quality + security + migration-check + test-cov"
	@echo "  make migrate        - Alembic upgrade head"
	@echo "  make migrate-check  - Alembic drift check (upgrade + check)"
	@echo "  make migrate-new MSG=\"description\" - Create new migration"
	@echo "  make up             - Start docker compose services"
	@echo "  make down           - Stop docker compose services"
	@echo "  make logs           - Follow API logs from compose"
	@echo "  make clean          - Remove Python cache/coverage artifacts"

venv:
	python3 -m venv .venv

install:
	$(PIP) install --upgrade pip
	$(PIP) install -e .[dev]

run:
	$(UVICORN) app.main:app --reload

test:
	$(PYTEST) tests/

test-cov:
	$(PYTEST) tests/ --cov=app --cov-report=term-missing --cov-fail-under=$(COV_FAIL_UNDER)

lint:
	$(RUFF) check .

format:
	$(RUFF) format .

format-check:
	$(RUFF) format --check .

typecheck:
	$(MYPY) app tests

security:
	$(PIP) install --upgrade pip
	$(PIP_AUDIT) --ignore-vuln CVE-2024-23342 --ignore-vuln CVE-2026-30922

quality: lint format-check typecheck

migrate:
	$(ALEMBIC) upgrade head

migrate-check:
	$(ALEMBIC) upgrade head

	$(ALEMBIC) check

migrate-new:
	@if [ -z "$(MSG)" ]; then \
		echo "Usage: make migrate-new MSG=\"description\""; \
		exit 1; \
	fi
	$(ALEMBIC) revision --autogenerate -m "$(MSG)"

ci: quality security migrate-check test-cov

up:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f api

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage ci.db
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete

.PHONY: help venv install run test test-cov lint format format-check typecheck security quality migrate migrate-check migrate-new ci up down logs clean