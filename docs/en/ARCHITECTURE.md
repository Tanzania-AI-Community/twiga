# Platform infrastructure

<div align="center">

![Twiga Architecture](https://github.com/user-attachments/assets/33e4e394-b724-4ea4-af2a-7e75f93615aa)

</div>

This diagram is an overview of the infrastructure for the first iteration of Twiga in production. We appreciate simple architectures and want to minimize the number of platforms we use all while maintaining good performance.

# Code architecture

We have designed Twiga's backend for simplicity and modularity.

## `app`

Everything used to run the Twiga application is within the `app` folder. Requests coming from the WhatsApp users (via the Meta API) are first received by the endpoints in the `app/main.py` file (the `webhooks` endpoint). Some WhatsApp signatures are controlled by the decorators in `app/security.py`and then the `handle_request` function in `app/services/messaging_service.py` routes the requests in the right direction depending on the type of request and the state of the user.

All environment variables are fetched from `app/config.py`, so when using these in any way just import the settings to your file.

> [!Note]
>
> Don't use `dotenv`, just use our settings.

The AI-relevant code is mainly handled in the `app/llm_service.py`. Conveniently, if you're planning on creating any new tools, you can create it in the `app/tools/` folder. Just follow the convention we've set.

We'll leave it up to you to explore the rest.

> [!Warning]
>
> If anything here appears off it may not be up to date. Let us know 😁

## `scripts`

Within the `scripts` folder we keep files that are run intermittently from the developer side. Look in there if you want to populate your own version of the database with some textbook data.

## `tests`

> [!Note]
>
> We are yet to make tests but it's in the roadmap.

# Database schema

We're using tiangolos [SQLModel](https://sqlmodel.tiangolo.com/) as an [ORM](https://en.wikipedia.org/wiki/Object%E2%80%93relational_mapping) to interact with the Neon Postgres database in this project. Instead of statically sharing the database schema here (which is likely to change over time) we refer you to the `app/database/model.py` file which should contain everything you need to know regarding what tables are used in Twiga. We also have an [entity-relationship diagram](https://drive.google.com/file/d/10dKIW6I6_d-712rt0s-7KltTWTmBjRIP/view?usp=sharing) (ERD) providing an overview of the table relations but it is not consistently maintained and may not match exactly with the current database version.

## `migrations`

This folder keeps track of the database history. We use [_alembic_](https://medium.com/@kasperjuunge/how-to-get-started-with-alembic-and-sqlmodel-288700002543) migrations. Unless you want to use _alembic_ for your own copy of the database you can ignore this folder. If you're in the core team and have access to our Neon database, it might be good to know how it works and why we use it.
