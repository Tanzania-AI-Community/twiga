# Contributor Manual

We welcome contributions of any size and skill level. As an open source project, we believe in giving back to our contributors and are happy to help with guidance on PRs, technical writing, and turning any feature idea into a reality.

> [!Tip]
>
> **For new contributors:** Take a look at [https://github.com/firstcontributions/first-contributions](https://github.com/firstcontributions/first-contributions) for helpful information on contributing

## 🖥️ Local Development Quick Guide

As this project uses a combination of cloud services, dependencies, and API's with authtokens we are working on making the local development experience smoother for open source contributors. In some cases you may need to use your own credentials (such as _OpenAI_ API keys).

If you want to set up the project locally on your own computer we recommend to complete the following steps. Start by forking :fork*and_knife: this repository. When forking make sure to deselect "\_copy the `main` branch only*".

Once you have forked you can clone it locally on your computer. Using Visual Studio code as your IDE is recommended but not neccessary. Run the following steps in the folder you want to keep the code.

```sh
git clone git@github.com:{USERNAME}/twiga.git
git checkout -b {YOUR BRANCH}
```

This creates a new branch under the name you decide so you can work on whatever feature / issue you're interested in.

### Setup prerequisites

If you want to run a local server and test your Twiga build on WhatsApp directly, I recommend following some steps from the [tutorial](https://github.com/daveebbelaar/python-whatsapp-bot) made by Dave Ebbelaar. Note that these are all free to do.

1. Create a Meta [developer account](https://developers.facebook.com/) and [business app](https://developers.facebook.com/docs/development/create-an-app/)
2. [Select phone numbers](https://github.com/daveebbelaar/python-whatsapp-bot?tab=readme-ov-file#step-1-select-phone-numbers)
3. [Send messages with the API](https://github.com/daveebbelaar/python-whatsapp-bot?tab=readme-ov-file#step-2-send-messages-with-the-api)
4. [Configure webhooks with ngrok](https://github.com/daveebbelaar/python-whatsapp-bot?tab=readme-ov-file#step-3-configure-webhooks-to-receive-messages)
5. Create an [OpenAI API account](https://platform.openai.com/docs/quickstart) to get an **API key**
6. Then create an [assistant](https://platform.openai.com/docs/assistants/overview) to get an **assistant ID** (give it the system prompt provided in _TBD_)

Create a `.env` file using `example.env`as a template and remove all comments and whitespace.

### Own computer

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

## 🤝 Sharing your contribution with us
