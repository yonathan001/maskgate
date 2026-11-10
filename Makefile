.PHONY: up down test lint typecheck check migrate seed loadtest build clean

up:
	docker compose up --build -d

down:
	docker compose down

build:
	docker compose build

migrate:
	cd gateway && alembic upgrade head

seed:
	python3 -c "print('Seed placeholder - keys created via admin API')"

lint:
	cd gateway && ruff check .

lint-fix:
	cd gateway && ruff check --fix .
	cd gateway && ruff format .

typecheck:
	cd gateway && mypy app

test:
	cd gateway && pytest -v

check: lint typecheck test

loadtest:
	@echo "Running load test..."
	@if command -v k6 >/dev/null 2>&1; then \
		k6 run load-test/k6/overhead.js; \
	else \
		echo "k6 is not installed. Please install k6 to run load tests."; \
	fi

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
