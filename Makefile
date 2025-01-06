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

setup-env: build generate-local-data run
