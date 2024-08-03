import datetime
import os
import shelve
from typing import Dict, Literal, Tuple
import threading

from app.config import settings


# TODO: Change the way we deal with rate limiting
message_counts = {}  # In-memory dictionary to store message counts per user


def is_rate_limit_reached(wa_id: str) -> bool:
    count, last_message_time = get_message_count(wa_id)

    if datetime.datetime.now().date() > last_message_time.date():
        count = 0

    if count >= settings.daily_message_limit:
        return True

    increment_message_count(wa_id)
    return False


# Function to reset counts at midnight (optional, if running a persistent service)
def reset_counts() -> None:
    now = datetime.datetime.now()
    midnight = datetime.datetime.combine(now.date(), datetime.datetime.time())
    seconds_until_midnight = (midnight + datetime.timedelta(days=1) - now).seconds
    threading.Timer(seconds_until_midnight, reset_counts).start()
    message_counts.clear()


def clear_db(db_name: str):
    with shelve.open(db_name, writeback=True) as db:
        db.clear()


def inspect_db(db_name: str):
    with shelve.open(db_name) as db:
        if len(db) == 0:
            print(f"The {db_name} database is empty.")
        else:
            for key in db:
                print(f"Key: {key} -> Value: {db[key]}")


""" Users Database Functions """


def reset_conversation(wa_id: str, db_name: str = "db/users"):
    with shelve.open(db_name) as db:
        db[wa_id] = {"state": "start"}


def get_user_state(wa_id: str, db_name: str = "db/users"):
    with shelve.open(db_name) as db:
        return db.get(wa_id, {"state": "start"})


def update_user_state(
    wa_id: str, state_update: Dict[str, str], db_name: str = "db/users"
):
    with shelve.open(db_name) as db:
        # Retrieve the existing state or create a new one if it doesn't exist
        existing_state = dict(db.get(wa_id, {}))

        # Update the existing state with the new state
        existing_state.update(state_update)

        # Save the updated state back to the database
        db[wa_id] = existing_state


""" Threads Database Functions """


def check_if_thread_exists(wa_id: str, db_name: str = "db/threads"):
    with shelve.open(db_name) as db:
        return db.get(wa_id, None)


def store_thread(wa_id: str, thread_id: str, db_name: str = "db/threads"):
    with shelve.open(db_name, writeback=True) as db:
        db[wa_id] = {"thread": thread_id}


""" Rate Limit Database Functions """


def get_message_count(
    wa_id: str, db_name: str = "db/message_counts"
) -> Tuple[int, datetime.datetime]:
    with shelve.open(db_name) as db:
        if wa_id in db:
            count, last_message_time = db[wa_id]
            return count, last_message_time
        return 0, datetime.datetime.min


def increment_message_count(wa_id: str, db_name: str = "db/message_counts"):
    with shelve.open(db_name, writeback=True) as db:
        count, last_message_time = get_message_count(wa_id)
        now = datetime.datetime.now()

        if now.date() > last_message_time.date():
            count = 0

        count += 1
        db[wa_id] = (count, now)


""" Message History Database Functions """


def store_message(
    wa_id: str,
    message: str,
    role: Literal["user", "twiga"],
    db_name: str = "db/message_history",
):
    with shelve.open(db_name, writeback=True) as db:
        if wa_id not in db:
            db[wa_id] = []
        db[wa_id].append(
            {"timestamp": datetime.datetime.now(), "message": message, "role": role}
        )


def retrieve_messages(wa_id: str, db_name: str = "db/message_history"):
    with shelve.open(db_name) as db:
        return db.get(wa_id, [])


def print_messages(wa_id: str, db_name: str = "db/message_history"):
    messages = retrieve_messages(wa_id, db_name)
    for message in messages:
        timestamp = message["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        role = message["role"]
        msg = message["message"]
        print(f"[{timestamp}] ({role}): {msg}")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    USERS_DATABASE = os.getenv("USERS_DATABASE", "users")
    THREADS_DATABASE = os.getenv("THREADS_DATABASE", "threads")

    # # Clear the threads database
    # print("Threads database.")
    # inspect_db(THREADS_DATABASE)
    # clear_db(THREADS_DATABASE)
    # print("Threads database cleared.")

    # # # Clear the user-info database
    # print("Users database.")
    # inspect_db(USERS_DATABASE)
    # clear_db(USERS_DATABASE)
    # print("Onboarding database cleared.")

    print("\nmessage_counts database.")
    inspect_db("message_counts")
    # clear_db("message_counts")
    # print("Message counts database cleared.")

    print("\nMessage database.")
    # inspect_db("message_history")
    # clear_db("message_history")
    print_messages("46702717600")
