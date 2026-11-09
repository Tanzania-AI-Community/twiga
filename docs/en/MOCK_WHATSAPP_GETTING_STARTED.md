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

Start by creating a `.env` file in the main directory of Twiga and copy-paste the contents of `.env.template.simple` into it. You'll only need to fill in these variables:

1. `LLM_API_KEY` - Your Together AI or OpenAI API key
2. `EMBEDDING_PROVIDER` and `GOOGLE_CLOUD_PROJECT` - Follow [Set up Google Cloud for embeddings](./GETTING_STARTED.md#-set-up-google-cloud-for-embeddings)
3. `DATABASE_URL` - If you want to modify the default database settings

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

3. Configure the WhatsApp receiver in Twiga's environment:

```dotenv
ENVIRONMENT=local
MOCK_WHATSAPP=True
MOCK_WHATSAPP_API_URL=http://127.0.0.1:3000/api/whatsapp
MOCK_WHATSAPP_TOKEN=change-me-local-token
```

Set the same local token in the mock's environment, along with `CHATBOT_CALLBACK_URL=http://127.0.0.1:8000/devhooks`. Keep the placeholder Meta values from the simple template; real Meta credentials are not needed.

The mock displays accepted text chunks, progress notifications, media, interactive messages, read receipts, and typing actions. Its local event log survives restarts. Observer mode remains a separate read-only database view.

When Twiga runs in Docker, try `http://host.docker.internal:3000/api/whatsapp` for the receiver URL. Host loopback connectivity depends on the Docker platform; verify that the container can reach the mock without exposing the host listener publicly.

To run the transport integration test, start the mock with a temporary event directory and `CHATBOT_CALLBACK_URL=http://127.0.0.1:1/devhooks`, then run:

```sh
MOCK_WHATSAPP_TEST_URL=http://127.0.0.1:3000 uv run pytest tests/integration/test_mock_whatsapp_transport.py
```

This test uses the actual WhatsApp client and mock receiver, without model calls or database queries.

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

## Media, interactive messages, and Flows

In mock mode Twiga uploads generated images and PDFs to the mock, sends them by
media ID and then deletes the uploaded copy, as it does with Meta. The chat
keeps showing delivered media after that deletion and after restarts.

The mock stores its event log and media under `MOCK_WHATSAPP_DATA_DIR` (default
`.mock-whatsapp`). To reset history and media, stop the mock and remove that
directory; Twiga's database is not affected. The composer can attach images,
PDFs and audio and record voice notes, and button and list replies are sent in
Meta's webhook format.
Twiga currently answers incoming media with "Sorry, I only understand textual
messages." Code that downloads incoming media should build the media URL with
`whatsapp_client.media_url(media_id)` so it works against both Meta and the mock.

### Configure the settings Flow locally

In the mock environment, set:

```dotenv
MOCK_WHATSAPP_FLOW_DIR=/absolute/path/to/twiga/app/assets/flows
MOCK_WHATSAPP_FLOW_PUBLIC_KEY_FILE=/absolute/path/to/local-flow-public.pem
```

Create a development-only encrypted RSA key pair outside Git:

```sh
umask 077
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
  -aes-256-cbc -out local-flow-private.pem
openssl pkey -in local-flow-private.pem -pubout -out local-flow-public.pem
uv run python -c 'from cryptography.fernet import Fernet; from pathlib import Path; Path("local-flow-token.key").write_bytes(Fernet.generate_key())'
```

Then add these to Twiga's `.env`:

| Variable | Value |
| --- | --- |
| `SUBJECTS_CLASSES_FLOW_ID` | A numeric ID, e.g. `1000000000000001` (Twiga's flow token parser does not accept underscores) |
| `WHATSAPP_BUSINESS_PRIVATE_KEY` | The encrypted private PEM, quoted across lines |
| `WHATSAPP_BUSINESS_PRIVATE_KEY_PASSWORD` | The key passphrase |
| `FLOW_TOKEN_ENCRYPTION_KEY` | Contents of `local-flow-token.key` |

The mock sends encrypted screen requests to `/flows` on the same origin as its
`CHATBOT_CALLBACK_URL`. Send `settings`, choose Classes and Subjects, open the
Flow and complete it. When Twiga returns `SUCCESS`, the mock sends the
`nfm_reply` webhook and Twiga saves the teacher's classes. Request a new Flow
message after changing keys or the Flow ID.

Only the shipped subject and class screens are rendered. Other Flow components,
including the onboarding form, are not simulated.

### Local-only safeguards

In mock mode the WhatsApp client only talks to the configured local mock URL and
ignores proxy environment variables; any other destination, including
`graph.facebook.com`, fails before a request is sent. Production routing and
payloads are unchanged. The mock's fault injection endpoint
(`PUT /api/whatsapp/faults`) is described in its README.

Mock mode does not change where LLM and embedding requests go. For fully offline
testing, point both providers at a local stand-in and disable tracing.
