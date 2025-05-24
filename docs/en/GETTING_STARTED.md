> [!Warning]
>
> This document assumes you have already done steps 1-3 in `docs/CONTRIBUTING.md`.

# 🐣 Getting Started Guide

If you want to run Twiga on your own computer (and even test your own version of the chatbot) this is the guide for you.

> [!Note]
>
> For a simpler setup with mock WhatsApp, please follow the instructions in [MOCK_WHATSAPP_GETTING_STARTED.md](./MOCK_WHATSAPP_GETTING_STARTED.md).

## Setup the virtual environment and download dependencies

Start out by installing the [**uv**](https://docs.astral.sh/uv/) python package manager to your computer. Make sure you're in the root directory of the repository and run the the following commands:

```bash
$ uv sync
$ source .venv/bin/activate
```

> [!Note]
>
> For **Windows** the second command would be `.venv\Scripts\activate`

The dependencies should now be installed and your shell environment should be set to use the virtual environment just created. Now you can run the FastAPI application.

## 🤫 Create a `.env`

Start by creating a `.env` file in the main directory of Twiga and copy-paste the contents of `.env.template` into it (or use `.env.template.simple` for a more streamlined setup). Remove the comments and whitespace. The template should be quite self-explanatory. The rest of this document will help you fill out the `.env` file with your own values to get a running version of Twiga.

## 👾 Setup Prerequisites

> [!Note]
>
> Many of the steps provided in the [setup prerequisites](#-setup-prerequisites) come from the [tutorial](https://github.com/daveebbelaar/python-whatsapp-bot) made by Dave Ebbelaar.

In the file [`architecture.md`](https://github.com/Tanzania-AI-Community/twiga/blob/main/docs/en/ARCHITECTURE.md), you can see the main components of the infrastructure used to run Twiga. However, it's not necessary to use Neon and Render, as these can be replaced with a 'local' version. However, you're welcome to test them out if you want since they offer quite generous free versions. With that said, you should start off by creating a Meta API account.

### Meta Account (Optional if using Mock WhatsApp)

1. Create a Meta developer account [here](https://developers.facebook.com/)

2. Create a [business app](https://developers.facebook.com/docs/development/create-an-app/) within your developer account

https://github.com/user-attachments/assets/34877110-2023-4520-b134-ca9efd2f76bb

3. Set the app up for WhatsApp

As soon as you press `Create app` from step 2 you are brought to the App Dashboard. Select `Set up` under the WhatsApp box. This will connect the WhatsApp and Webhooks "products" to your app.

Go to basic **App settings** in the sidebar and copy the App ID and App Secret into the `.env` file.

```bash
META_APP_ID="<App ID>"
META_APP_SECRET="<App Secret>"
```

4. Get phone number and generate an access token

When you created the WhatsApp app you got a free Test Number from Meta that you can use to test your bot with 5 users. Go to **WhatsApp/API Setup** in the sidebar. If the Test Number isn't already selected then choose it and copy the **Phone number ID**. You can also create a 24 hour access token with **Generate access token**. These values should also be added to the `.env` file.

```bash
WHATSAPP_CLOUD_NUMBER_ID="<Phone number ID>"
WHATSAPP_API_TOKEN="<Access token>"
```

> [!Note]
>
> You can create a 60 day (or longer) access token by following the steps [here](https://github.com/daveebbelaar/python-whatsapp-bot?tab=readme-ov-file#step-2-send-messages-with-the-api)

You can then, within the Dashboard, add your phone number as a recipient phone number so that the App has permission to text your phone. Just follow the steps it gives you. Then you can send a template message with the API to see if it works.

> [!Warning]
>
> You need to reply to this template message in your phone so that the bot is allowed to send you messages other than template messages.

## 🪝 Configure webhooks with [Ngrok](https://ngrok.com/)

When you later run the FastAPI application, your computer will be listening for connections to your local server at `http://127.0.0.1:8000` (this is localhost). In order to make this server visible to the big broad internet, we use a personal (and free) endpoint from Ngrok that redirects all requests to our localhost. So, go over to [Ngrok](https://ngrok.com/) and create an account. Then, download the Ngrok agent for your computer. It should be visible in **Getting Started** as soon as you finished creating your account.

Then copy your personal Ngrok authtoken (also within **Getting Started**) and run the following in your command line.

```bash
ngrok config add-authtoken $YOUR_AUTHTOKEN
```

On the left sidebar of the Ngrok dashboard, open up **Domains** and click **New Domain** to get your own free Ngrok endpoint. When this is complete run the following command in your command line.

```bash
ngrok http 8000 --domain {your-free-domain}.ngrok-free.app
```

If all worked smoothly, the command line output should suggest that ngrok is actively redirecting requests to the free domain to your localhost port 8000.

> [!Note]
>
> It's not yet connected to your WhatsApp app, but we'll come back to that at the end of this guide.

## 🤖 Get a Together AI or OpenAI API token

In order to use large language and embedding models we need access to a high performance inference service. By default, this project uses Together AI, which gives us access to a wide range of open source models that can be run with OpenAI's software development kit (SDK).

- If you want to use Together AI, [create an account](https://api.together.ai/) and get an API key
- If you want to use OpenAI, [create an account](https://platform.openai.com/) and get an API key

Both providers have a free tier with a starting amount of free credits. Add the key to the `.env` file.

```bash
LLM_API_KEY=$YOUR_API_KEY
```

> [!Important]
>
> We recommend using Together AI, but if you decide on OpenAI there are a few extra steps to fill.

Search the repository for the identifier `XXX:` and make sure to update the values according to the instructions so that the FastAPI application will run OpenAI models. At the time of writing, this should be within `app/config.py` and `app/database/models.py`.

## 🧠 Set up your local Postgres database

As any chatbot should do, Twiga keeps track of chat histories, users, classes, resources (i.e. the documents relevant to classes), a vector database, etc. Fortunately, everything (including the vector database) is stored in tables in a Postgres database. We're using Neon to host our database, but for local development we use PostgreSQL.

First of all, you need to add the required env variables to your `.env`.

```bash
DATABASE_USER=postgres
DATABASE_PASSWORD=$YOUR_PASSWORD
DATABASE_NAME=twiga_db
DATABASE_URL=postgresql+asyncpg://postgres:$YOUR_PASSWORD@db:5432/twiga_db
```

This link assumes you are running the Postgres database on port 5432, which is the standard.

Next up, let's build all Docker images and local data, needed for further steps and for running the app. This command will take some time, run:

```bash
make setup-env
```

## 🖥️ Set up the FastAPI application

Run the following command to run the project.

```sh
docker-compose -f docker/dev/docker-compose.yml --env-file .env up
```

or, alternatively,

```sh
make run
```

If everything went well, your server is ready to accept connections!

## 📱 Complete WhatsApp configuration

The final step is to integrate your Ngrok endpoint with your WhatsApp bot.

Start out by going to your `.env` file and creating a **Verify Token**. It can be anything you want, like a password:

```bash
WHATSAPP_VERIFY_TOKEN=$YOUR_RANDOM_VERIFY_TOKEN
```

Now, make sure that your Ngrok endpoint is active in a command line (terminal) and restart the FastAPI application in another command line so that it will recognize the changed `.env` file. How to run these was described in sections [Configure webhooks with Ngrok](#-configure-webhooks-with-ngrok) and [Set up the FastAPI application](#️-set-up-the-fastapi-application).

Now, in your Meta App Dashboard, go to **WhatsApp > Configuration**. In the **Webhook** section fill in the values for **Callback URL** and **Verify Token**.

> [!Important]
>
> The callback url should be `https://{your-free-domain}.ngrok-free.app/webhooks` (don't forget /webhooks) and the verify token should be what you defined in the `.env` file `$YOUR_RANDOM_VERIFY_TOKEN`

Once you press **Verify and save** a confirmation request will be sent to your server via the Ngrok endpoint (you should see logs show up in both terminals). Finally, scroll down to the Webhook Fields and **subscribe** do the _messages_ endpoint.

<img width="1215" alt="Screenshot 2024-11-28 at 13 01 39" src="https://github.com/user-attachments/assets/d5f24761-710f-43fb-a075-345d546e1309">

If you filled the `.env` correctly you should get a success in the logs and some visual confirmation in the Meta App Dashboard. Otherwise you're likely to see a `403 forbidden` log in your server.

## 🥳 Congratulations!

If you made it this far without issues, you should now have a running server for Twiga that you can text directly from your WhatsApp account. If you're encountering issues at this point still join our [Discord](https://discord.gg/bCe2HfZY2C) and write your question in `⚒-tech-support`.
