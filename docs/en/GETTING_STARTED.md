> [!Warning]
> This document is not yet up to date and is based on an older version of Twiga. Ask the team for advice if you run into difficulties. We plan to update this ASAP!

# 🐣 Getting Started Guide

If you want to run Twiga on your own computer (and even text your own version of the chatbot) this is the guide for you.

> [!Warning]
> This document assumes you have already done steps 1-3 in `docs/CONTRIBUTING.md`.

## 👾 Setup Prerequisites

> [!Note]
>
> We're looking into the possibility of running and trying out Twiga without a Meta API Account. For now, the long way is the only way 😬

> [!Note]
>
> Many of the steps provided in the [setup prerequisites](#-setup-prerequisites) come from the [tutorial](https://github.com/daveebbelaar/python-whatsapp-bot) made by Dave Ebbelaar.

In the file [`architecture.md`](https://github.com/Tanzania-AI-Community/twiga/blob/main/docs/en/ARCHITECTURE.md), you can see the main components of the infrastructure used to run Twiga. To run Twiga on your own computer, you will have to replace the following:

- Neon Postgres with your local Postgres server
- Render with an Ngrok endpoint

> [!Note]
>
> You're welcome to test out Neon and Render as well (it's free), but it's not necessary.

With that said, you also need to create a Meta API account and get a Together AI API credential (OpenAI should also work with a minor adjustment). These are needed to fill out the `.env` file properly. This document will show how to do all that.

### Meta Accounts

1. Create a Meta [developer account](https://business.facebook.com/business/loginpage/?cma_account_switch=true&login_options%5B0%5D=SSO&login_options%5B1%5D=FB&is_logout_from_dfc=true&request_id=1ae9fb9b-49b7-4d48-aebe-da36751cedf1) with your Facebook account
2. Create a [business app](https://developers.facebook.com/docs/development/create-an-app/) within your developer account.

Tbd...

2. [Select phone numbers](https://github.com/daveebbelaar/python-whatsapp-bot?tab=readme-ov-file#step-1-select-phone-numbers)
3. [Send messages with the API](https://github.com/daveebbelaar/python-whatsapp-bot?tab=readme-ov-file#step-2-send-messages-with-the-api)
4. [Configure webhooks with ngrok](https://github.com/daveebbelaar/python-whatsapp-bot?tab=readme-ov-file#step-3-configure-webhooks-to-receive-messages)
5. Create an [OpenAI API account](https://platform.openai.com/docs/quickstart) to get an **API key**
6. Then create an [assistant](https://platform.openai.com/docs/assistants/overview) to get an **assistant ID** (give it the system prompt provided in _TBD_)

Create a `.env` file using `example.env`as a template and remove all comments and whitespace.

## 🖥️ Set up the coding environment

Start out by installing the [**Poetry**](https://python-poetry.org/) python package manager to your computer. Make sure you're in the root directory of the repository and run the command `poetry install`. This will read the dependencies needed to run Twiga and download them into a `.venv/` folder. Next run `poetry shell` to activate a shell in your command line using the created virtual environment. Finally, run **one of** the following two commands to start the FastAPI server. They are development servers meaning you have hot reload.

```sh
fastapi dev app.main.py
```

```sh
uvicorn app.main:app --port 8000 --reload
```

In order for the Meta API to access your local FastAPI server you need to activate the ngrok API gateway with the following command.

```sh
ngrok http 8000 --domain {YOUR-GATEWAY-NAME}.ngrok-free.app
```

If all is set up correctly, you should be able to have a basic version of Twiga up and running that you can text with on WhatsApp.

### Containerized with Docker

We are also using Docker for Twiga so that you can work on the project in a contained development to avoid some of the dependency and versioning issues that may occur on your own computer. Our `Dockerfile` and `docker-compose.yml` files ensure that the right version of python and poetry are installed to the system. All you need is to have [Docker](https://www.docker.com/) running on your computer.

We recommend reading up on docker to learn about images, containerization, volumes, etc. We use docker compose with volumes so that you even have hot reloads in the running container (read `docker-compose.yml` and `Dockerfile` for more details). Once docker is set up you can run the following command.

```sh
docker compose up
```

In order for the Meta API to access your local FastAPI server you need to activate the ngrok API gateway with the following command.

```sh
ngrok http 8000 --domain {YOUR-GATEWAY-NAME}.ngrok-free.app
```
