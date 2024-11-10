# syntax = docker/dockerfile:1.2

FROM python:3.12-slim

# RUN pip install poetry==1.8.3
RUN pip install uv==0.4.20
# Install uv.
# COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /src

# COPY pyproject.toml poetry.lock ./
COPY pyproject.toml uv.lock ./

COPY . .

# Fastapi running on port 8000
EXPOSE 8000

# Hide dev dependencies, right now there are none though --without dev (don't know how the command looks in uv)
# RUN uv sync --frozen --no-cache

# Install dependencies using the secret .env file
RUN --mount=type=secret,id=_env,dst=/etc/secrets/.env \
    uv sync --frozen --no-cache

# # use uvicorn to run app/main.py
CMD uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
# # "poetry", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"
# ENTRYPOINT ["poetry", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# build with:DOCKER_BUILDKIT=1 docker build --secret id=_env,src=.env -t twiga_dev .
# run with: docker run -p 8000:8000 --env-file .env --name twiga_dev_c twiga_dev
