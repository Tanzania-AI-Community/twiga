# import datetime
# import os
# import shelve
# from typing import Dict, Literal, Tuple
# import threading

# from app.config import settings


# # TODO: Change the way we deal with rate limiting
# message_counts = {}  # In-memory dictionary to store message counts per user


# def is_rate_limit_reached(wa_id: str) -> bool:
#     count, last_message_time = get_message_count(wa_id)

#     if datetime.datetime.now().date() > last_message_time.date():
#         count = 0

#     if count >= settings.daily_message_limit:
#         return True

#     increment_message_count(wa_id)
#     return False


# # Function to reset counts at midnight (optional, if running a persistent service)
# def reset_counts() -> None:
#     now = datetime.datetime.now()
#     midnight = datetime.datetime.combine(now.date(), datetime.datetime.time())
#     seconds_until_midnight = (midnight + datetime.timedelta(days=1) - now).seconds
#     threading.Timer(seconds_until_midnight, reset_counts).start()
#     message_counts.clear()


# def clear_db(db_name: str):
#     with shelve.open(db_name, writeback=True) as db:
#         db.clear()


# def inspect_db(db_name: str):
#     with shelve.open(db_name) as db:
#         if len(db) == 0:
#             print(f"The {db_name} database is empty.")
#         else:
#             for key in db:
#                 print(f"Key: {key} -> Value: {db[key]}")


# """ Users Database Functions """


# def reset_conversation(wa_id: str, db_name: str = "db/users"):
#     with shelve.open(db_name) as db:
#         db[wa_id] = {"state": "start"}


# def get_user_state(wa_id: str, db_name: str = "db/users"):
#     with shelve.open(db_name) as db:
#         return db.get(wa_id, {"state": "start"})


# def update_user_state(
#     wa_id: str, state_update: Dict[str, str], db_name: str = "db/users"
# ):
#     with shelve.open(db_name) as db:
#         # Retrieve the existing state or create a new one if it doesn't exist
#         existing_state = dict(db.get(wa_id, {}))

#         # Update the existing state with the new state
#         existing_state.update(state_update)

#         # Save the updated state back to the database
#         db[wa_id] = existing_state


# """ Threads Database Functions """


# def check_if_thread_exists(wa_id: str, db_name: str = "db/threads"):
#     with shelve.open(db_name) as db:
#         return db.get(wa_id, None)


# def store_thread(wa_id: str, thread_id: str, db_name: str = "db/threads"):
#     with shelve.open(db_name, writeback=True) as db:
#         db[wa_id] = {"thread": thread_id}


# """ Rate Limit Database Functions """


# def get_message_count(
#     wa_id: str, db_name: str = "db/message_counts"
# ) -> Tuple[int, datetime.datetime]:
#     with shelve.open(db_name) as db:
#         if wa_id in db:
#             count, last_message_time = db[wa_id]
#             return count, last_message_time
#         return 0, datetime.datetime.min


# def increment_message_count(wa_id: str, db_name: str = "db/message_counts"):
#     with shelve.open(db_name, writeback=True) as db:
#         count, last_message_time = get_message_count(wa_id)
#         now = datetime.datetime.now()

#         if now.date() > last_message_time.date():
#             count = 0

#         count += 1
#         db[wa_id] = (count, now)


# """ Message History Database Functions """


# def store_message(
#     wa_id: str,
#     message: str,
#     role: Literal["user", "twiga"],
#     db_name: str = "db/message_history",
# ):
#     with shelve.open(db_name, writeback=True) as db:
#         if wa_id not in db:
#             db[wa_id] = []
#         db[wa_id].append(
#             {"timestamp": datetime.datetime.now(), "message": message, "role": role}
#         )


# def retrieve_messages(wa_id: str, db_name: str = "db/message_history"):
#     with shelve.open(db_name) as db:
#         return db.get(wa_id, [])


# def print_messages(wa_id: str, db_name: str = "db/message_history"):
#     messages = retrieve_messages(wa_id, db_name)
#     for message in messages:
#         timestamp = message["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
#         role = message["role"]
#         msg = message["message"]
#         print(f"[{timestamp}] ({role}): {msg}")


# if __name__ == "__main__":
#     from dotenv import load_dotenv

#     load_dotenv()
#     USERS_DATABASE = os.getenv("USERS_DATABASE", "users")
#     THREADS_DATABASE = os.getenv("THREADS_DATABASE", "threads")

#     # # Clear the threads database
#     # print("Threads database.")
#     # inspect_db(THREADS_DATABASE)
#     # clear_db(THREADS_DATABASE)
#     # print("Threads database cleared.")

#     # # # Clear the user-info database
#     # print("Users database.")
#     # inspect_db(USERS_DATABASE)
#     # clear_db(USERS_DATABASE)
#     # print("Onboarding database cleared.")

#     print("\nmessage_counts database.")
#     inspect_db("message_counts")
#     # clear_db("message_counts")
#     # print("Message counts database cleared.")

#     print("\nMessage database.")
#     # inspect_db("message_history")
#     # clear_db("message_history")
#     print_messages("46702717600")


import sqlite3
import datetime
from typing import Dict, Literal, Tuple

from app.config import settings


class AppDatabase:
    _instance = None

    def __new__(cls, db_name: str = "db/app.db", *args, **kwargs):
        if not cls._instance:
            cls._instance = super(AppDatabase, cls).__new__(cls, *args, **kwargs)
            cls._instance.db_name = db_name  # Ensure db_name is set early
            cls._instance.init_db()  # Initialize the database
            cls._instance.initialized = True
        return cls._instance

    def __init__(self, db_name: str = "app.db"):
        if not hasattr(self, "initialized"):  # Check if already initialized
            self.db_name = db_name
            self.init_db()
            self.initialized = True  # Mark the instance as initialized

    def get_connection(self):
        return sqlite3.connect(self.db_name)

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        # Create tables
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS message_counts (
                wa_id TEXT PRIMARY KEY,
                count INTEGER,
                last_message_time TEXT
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                wa_id TEXT PRIMARY KEY,
                state TEXT
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                wa_id TEXT PRIMARY KEY,
                thread_id TEXT
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS message_history (
                wa_id TEXT,
                timestamp TEXT,
                message TEXT,
                role TEXT
            )
        """
        )

        conn.commit()
        conn.close()

    # Rate Limiting Functions
    def is_rate_limit_reached(self, wa_id: str) -> bool:
        count, last_message_time = self.get_message_count(wa_id)

        if datetime.datetime.now().date() > last_message_time.date():
            count = 0

        if count >= settings.daily_message_limit:
            return True

        self.increment_message_count(wa_id)
        return False

    def get_message_count(self, wa_id: str) -> Tuple[int, datetime.datetime]:
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT count, last_message_time FROM message_counts WHERE wa_id = ?
        """,
            (wa_id,),
        )
        result = cursor.fetchone()

        conn.close()

        if result:
            count, last_message_time = result
            return count, datetime.datetime.fromisoformat(last_message_time)
        return 0, datetime.datetime.min

    def increment_message_count(self, wa_id: str):
        count, last_message_time = self.get_message_count(wa_id)
        now = datetime.datetime.now()

        if now.date() > last_message_time.date():
            count = 0

        count += 1

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO message_counts (wa_id, count, last_message_time)
            VALUES (?, ?, ?)
            ON CONFLICT(wa_id) DO UPDATE SET count = excluded.count, last_message_time = excluded.last_message_time
        """,
            (wa_id, count, now.isoformat()),
        )

        conn.commit()
        conn.close()

    # Users Database Functions
    def reset_conversation(self, wa_id: str):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO users (wa_id, state)
            VALUES (?, ?)
            ON CONFLICT(wa_id) DO UPDATE SET state = excluded.state
        """,
            (wa_id, "start"),
        )

        conn.commit()
        conn.close()

    def get_user_state(self, wa_id: str) -> Dict[str, str]:
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT state FROM users WHERE wa_id = ?
        """,
            (wa_id,),
        )
        result = cursor.fetchone()

        conn.close()

        if result:
            return {"state": result[0]}
        return {"state": "start"}

    def update_user_state(self, wa_id: str, state_update: Dict[str, str]):
        existing_state = self.get_user_state(wa_id)

        # Update the existing state with the new state
        existing_state.update(state_update)

        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO users (wa_id, state)
            VALUES (?, ?)
            ON CONFLICT(wa_id) DO UPDATE SET state = excluded.state
        """,
            (wa_id, existing_state["state"]),
        )

        conn.commit()
        conn.close()

    # Threads Database Functions
    def check_if_thread_exists(self, wa_id: str):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT thread_id FROM threads WHERE wa_id = ?
        """,
            (wa_id,),
        )
        result = cursor.fetchone()

        conn.close()

        return result

    def store_thread(self, wa_id: str, thread_id: str):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO threads (wa_id, thread_id)
            VALUES (?, ?)
            ON CONFLICT(wa_id) DO UPDATE SET thread_id = excluded.thread_id
        """,
            (wa_id, thread_id),
        )

        conn.commit()
        conn.close()

    # Message History Database Functions
    def store_message(self, wa_id: str, message: str, role: Literal["user", "twiga"]):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO message_history (wa_id, timestamp, message, role)
            VALUES (?, ?, ?, ?)
        """,
            (wa_id, datetime.datetime.now().isoformat(), message, role),
        )

        conn.commit()
        conn.close()

    def retrieve_messages(self, wa_id: str):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT timestamp, message, role FROM message_history WHERE wa_id = ?
        """,
            (wa_id,),
        )
        results = cursor.fetchall()

        conn.close()

        return [
            {
                "timestamp": datetime.datetime.fromisoformat(timestamp),
                "message": message,
                "role": role,
            }
            for timestamp, message, role in results
        ]

    def print_messages(self, wa_id: str):
        messages = self.retrieve_messages(wa_id)
        for message in messages:
            timestamp = message["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            role = message["role"]
            msg = message["message"]
            print(f"[{timestamp}] ({role}): {msg}")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    # Initialize the singleton database instance
    app_db = AppDatabase()

    # Example usage
    print("\nMessage counts database.")
    app_db.print_messages("46702717600")
