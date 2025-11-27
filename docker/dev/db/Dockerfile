# Use the official PostgreSQL image as a base
FROM postgres:17 AS twiga_db

# Install pgvector extension
RUN apt-get update && \
    apt-get install -y postgresql-17-pgvector && \
    rm -rf /var/lib/apt/lists/*
