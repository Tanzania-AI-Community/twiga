# 🐣 Getting Started Guide

> [!Note]
>
> We're looking into the possibility of running and trying out Twiga without a Meta API Account. For now, the long way is the only way 😬

If you want to run Twiga on your own computer (and even text your own version of the chatbot) this is the guide for you.

> [!Warning]
>
> This document assumes you have already done steps 1-3 in `docs/CONTRIBUTING.md`.

### 🤫 Create a `.env`

Start by creating a `.env` file in the main directory of Twiga and copy-paste the contents of `.env.template` into it. Remove the comments and whitespace. The template should be quite self-explanatory.

## 👾 Setup Prerequisites

> [!Note]
>
> Many of the steps provided in the [setup prerequisites](#-setup-prerequisites) come from the [tutorial](https://github.com/daveebbelaar/python-whatsapp-bot) made by Dave Ebbelaar.

In the file [`architecture.md`](https://github.com/Tanzania-AI-Community/twiga/blob/main/docs/en/ARCHITECTURE.md), you can see the main components of the infrastructure used to run Twiga. However, it's not necessary to use Neon and Render, as these can be replaced with a 'local' version. However, you're welcome to test them out if you want since they offer quite generous free versions. With that said, you should start off by creating a Meta API account.

### Meta Account

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

2. Select phone number and generate an access token

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
> You need to reply to this template message in your phone to activate the connection.

## 🪝 Configure webhooks with [Ngrok](https://ngrok.com/)

When you later run the FastAPI application, your computer will be listening for connections to your local server at `http://127.0.0.1:8000` (this is localhost). In order to make this server visible to the big broad world, we use a personal (and free) endpoint from Ngrok that redirects all requests to our localhost. So, go over to [Ngrok](https://ngrok.com/) and create an account. Then, download the Ngrok agent for your computer. It should be visible in **Getting Started** as soon as you finished creating your account.

Then copy your personal Ngrok authtoken (also within **Getting Started**) and run the following in your command line.

```bash
ngrok config add-authtoken $YOUR_AUTHTOKEN
```

On the left sidebar of the Ngrok dashboard, open up **Domains** and click **New Domain** to get your own free Ngrok endpoint. When this is complete run the following command in your command line.

```bash
ngrok http 8000 --domain your-free-domain.ngrok-free.app
```

If all worked smoothly, the command line output should suggest that ngrok is actively redirecting requests to the free domain to your localhost port 8000.

> [!Note]
>
> It's not yet connected to your WhatsApp app, but we'll come back to that at the end of this guide.

## 🧠 Set up your local Postgres database

...tbd

## 🖥️ Set up the FastAPI application

Start out by installing the [**uv**](https://docs.astral.sh/uv/) python package manager to your computer. Make sure you're in the root directory of the repository and run the the following commands:

```bash
$ uv sync
$ source .venv/bin/activate
```

> [!Note]
> For **Windows** the second command would be `.venv\Scripts\activate`

The dependencies should now be installed and your shell environment should be set to use the virtual environment just created. Now you can run the FastAPI application.

```sh
uvicorn app.main:app --port 8000 --reload
```

## 📱 Complete WhatsApp configuration

The final step is to integrate this with your WhatsApp bot. In your Meta App Dashboard, go to **WhatsApp > Configuration**.

> [!Warning]
> Everything from this point on is based on an older version of Twiga. Ask the team for advice if you run into difficulties. We plan to update this ASAP!

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
