#!make
include .env

build:
	@echo 'Building images ...'
	@docker-compose -f docker/dev/docker-compose.yml --env-file .env build --no-cache

run:
	@echo 'Running containers ...'
	@docker-compose -f docker/dev/docker-compose.yml --env-file .env up -d

stop:
	@echo 'Stopping containers ...'
	@docker-compose -f docker/dev/docker-compose.yml down

restart: stop run

generate-local-data:
	@echo 'Generating local data ...'
	@docker-compose -f docker/dev/docker-compose.yml --env-file .env run --rm app bash -c "PYTHONPATH=/app uv run python scripts/database/seed.py --create --sample-data --vector-data chunks_BAAI.json"

ingest-book:
	@echo 'Ingesting book ...'
	@docker-compose -f docker/dev/docker-compose.yml --env-file .env run --rm app bash -c "PYTHONPATH=/app uv run python scripts/database/resource_ingestion.py --parsed_book_name $(filename)"

setup-env: build generate-local-data run

generate-migration:
	@echo 'Genarating migration $(message)...'
	@docker-compose -f docker/dev/docker-compose.yml --env-file .env run --rm app bash -c 'PYTHONPATH=/app DATABASE_URL=${DATABASE_URL} uv run alembic revision --autogenerate -m "$(message)"'

migrate-up:
	@echo 'Upgrading DB version...'
	@docker-compose -f docker/dev/docker-compose.yml --env-file .env exec app bash -c 'PYTHONPATH=/app DATABASE_URL=${DATABASE_URL} uv run alembic upgrade head'

migrate-down:
	@echo 'Downgrading DB version to $(version)...'
	@docker-compose -f docker/dev/docker-compose.yml --env-file .env exec app bash -c 'PYTHONPATH=/app DATABASE_URL=${DATABASE_URL} uv run alembic downgrade $(version)'
