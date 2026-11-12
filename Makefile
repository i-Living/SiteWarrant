.PHONY: check lint types test integration up down migrate audit-fixture web-build

# The single gate. AGENTS.md promises exactly this.
check: lint types test web-check

lint:
	cd api && uv run ruff check . && uv run ruff format --check .

types:
	cd api && uv run mypy app

test:
	cd api && uv run pytest -q -m "not integration and not network"

integration:
	cd api && uv run pytest -q -m integration

web-check:
	cd web && bunx biome check . && bunx tsc --noEmit

up:
	docker compose -f infra/docker-compose.yml up -d --wait

down:
	docker compose -f infra/docker-compose.yml down

migrate:
	cd api && uv run alembic upgrade head

# The acceptance command from docs/PLAN.md P0. Exits 1 while a blocker exists.
audit-fixture:
	cd api && uv run sitewarrant audit http://localhost:8081/ --allow-private --out ../report.json

web-build:
	cd web && bun install --frozen-lockfile && bun run build
