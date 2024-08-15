FROM python:3.12-alpine

RUN pip install poetry==1.8.3

WORKDIR /app

COPY pyproject.toml poetry.lock ./

# I believe I would also need the db folder
COPY app ./app

# Apparently poetry needs a README.md file to work
RUN touch README.md

# Hide dev dependencies, right now there are none though
RUN poetry install --without dev


ENTRYPOINT ["poetry", "run", "fastapi", "dev", "app/main.py"]
