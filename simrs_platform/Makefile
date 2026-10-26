.PHONY: install lock migrate seed test lint typecheck audit run

install:
	uv sync --all-groups

lock:
	uv lock

migrate:
	uv run python manage.py migrate

seed:
	uv run python manage.py seed_demo

test:
	uv run pytest --cov=organization --cov=identity --cov=terminology --cov=mpi --cov=platform_core

lint:
	uv run ruff check .

typecheck:
	uv run mypy mpi/services.py platform_core/audit.py platform_core/permissions.py

audit:
	uv run bandit -q -r config organization identity terminology mpi platform_core
	uv run pip-audit

run:
	uv run python manage.py runserver 127.0.0.1:8000
