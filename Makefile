build:
	@echo 'Building images ...'
	@docker-compose build --no-cache

run:
	@echo 'Running containers ...'
	@docker-compose up -d

stop:
	@echo 'Stopping containers ...'
	@docker-compose down

restart: stop run

generate-local-data:
	@echo 'Generating local data ...'
	@docker-compose run --rm app bash -c "PYTHONPATH=/app uv run python scripts/database/init_twigadb.py --sample-data --vector-data"

setup-env: build generate-local-data run
