FROM python:3.12-slim

RUN pip install poetry==1.8.3

WORKDIR /src

COPY pyproject.toml poetry.lock ./

COPY . .

# Fastapi running on port 8000
EXPOSE 8000

# Apparently poetry needs a README.md file to work
RUN touch README.md

# Hide dev dependencies, right now there are none though --without dev
RUN poetry install 

# # use uvicorn to run app/main.py
# # "poetry", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"
# ENTRYPOINT ["poetry", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


