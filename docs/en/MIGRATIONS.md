# Migrations

You might run into some database troubles that require you to do database migrations. In the folder `migrations/versions/` you find the list of past database migrations. We're using [Alembic](https://alembic.sqlalchemy.org/en/latest/). They're docs aren't great so here's a beginner [article](https://medium.com/@kasperjuunge/how-to-get-started-with-alembic-and-sqlmodel-288700002543) on it.

By default, our Docker images use the alembic versioning system to initialize the database. If you wan't to rebuild the database to your needs, you can run new migrations and rebuild the Docker containers.

If you're not using Docker to run Twiga, then you can initialize the database and inject seed data with the command:

```
uv run python -m scripts.database.seed --create --sample-data --vector-data chunks_BAAI.json
```

This will remove all tables in the database if they exist, create new ones, install pgvector and inject sample data and vector data so that the database is ready to accept new users.
