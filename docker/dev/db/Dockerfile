# Use the official PostgreSQL image as a base
FROM postgres:17 as twiga_db

# Install pgvector extension
RUN apt-get update && \
    apt-get install -y postgresql-server-dev-17 && \
    apt-get install -y build-essential && \
    apt-get install -y git && \
    git clone https://github.com/pgvector/pgvector.git && \
    cd pgvector && \
    make && \
    make install && \
    cd .. && \
    rm -rf pgvector
