# Env
export PYTHONDONTWRITEBYTECODE=1

PY ?= 3.10
PYTEST_ARGS ?= tests
ARGS ?= --help

ifdef PY
  UV_PYTHON = --python $(PY)
else
  UV_PYTHON =
endif

.PHONY: help install build format lint run test

help: ## Show this help message.
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "\033[32m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install project and development dependencies with uv. Use PY=3.x to select Python.
	uv venv $(UV_PYTHON) --clear
	uv pip install -e ".[dev,binary]"

build: ## Build the standalone iact3 binary.
	uv run --extra binary python build.py

format: ## Format code and auto-fix lint issues with ruff.
	uv run ruff check --fix .
	uv run ruff format .

lint: ## Lint code with ruff and type-check with ty.
	uv run ruff check .
	uv run ty check

run: ## Run iact3. Pass CLI args with ARGS="...".
	uv run iact3 $(ARGS)

test: ## Run tests. Override with PYTEST_ARGS="...".
	uv run pytest $(PYTEST_ARGS)
