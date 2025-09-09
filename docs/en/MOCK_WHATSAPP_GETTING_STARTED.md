# 🐣 Quick Start with Mock WhatsApp

This guide provides a simplified setup for Twiga using a mock WhatsApp API, allowing you to bypass the Meta API setup process for development purposes.

> [!Note]
>
> This setup is for development purposes only. For production or to test with real WhatsApp, please follow the standard [GETTING_STARTED.md](./GETTING_STARTED.md) guide.

## Setup the virtual environment and download dependencies

Start out by installing the [**uv**](https://docs.astral.sh/uv/) python package manager to your computer. Make sure you're in the root directory of the repository and run the the following commands:

```bash
$ uv sync
$ source .venv/bin/activate
```

> [!Note]
>
> For **Windows** the second command would be `.venv\Scripts\activate`

The dependencies should now be installed and your shell environment should be set to use the virtual environment just created.

## 🤫 Create a `.env` file (Simple Version)

Start by creating a `.env` file in the main directory of Twiga and copy-paste the contents of `.env.template.simple` into it. You'll only need to fill in two variables:

1. `LLM_API_KEY` - Your Together AI or OpenAI API key
2. `DATABASE_URL` - If you want to modify the default database settings

The remaining variables are pre-filled with default values suitable for mock WhatsApp development.

## 📊 LangSmith Tracing (Optional)

For monitoring and debugging LLM interactions, you can optionally enable LangSmith tracing:

1. Create a [LangSmith account](https://smith.langchain.com/) (free tier available)
2. Get your API key from the LangSmith dashboard
3. Add the configuration to your `.env` file:

```bash
LANGSMITH_API_KEY=$YOUR_LANGSMITH_API_KEY
LANGSMITH_PROJECT=twiga-whatsapp-chatbot
LANGSMITH_TRACING=True
```

This will enable detailed tracking of all LLM conversations, tool usage, and performance metrics.

> [!Note]
>
> LangSmith integration is optional and won't affect the core functionality if not configured.

## 🧠 Set up your local Postgres database

Run the following command to set up your local environment:

```bash
make setup-env
```

This will build all Docker images and prepare local data needed for running the app.

## 📱 Set up the Mock WhatsApp integration

1. Clone the mock WhatsApp repository:

```bash
git clone https://github.com/Tanzania-AI-Community/mock-whatsapp.git
```

2. Navigate to the mock WhatsApp directory and follow the README instructions to install dependencies and start the server.

## 🖥️ Run the FastAPI application

Run the following command to run the project:

```sh
docker-compose -f docker/dev/docker-compose.yml --env-file .env up
```

or, alternatively:

```sh
make run
```

## 🥳 Testing your setup

Once the application is running, you can interact with Twiga through the mock WhatsApp interface. The mock interface simulates the WhatsApp API, allowing you to test your bot's functionality without needing a real WhatsApp account.

For any issues or questions, join our [Discord](https://discord.gg/bCe2HfZY2C) and write your question in `⚒-tech-support`.
