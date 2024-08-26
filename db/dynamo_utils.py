import datetime
import boto3
from typing import Dict, Literal, Tuple

from app.config import settings

# Initialize DynamoDB resource
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

# Table references
users_table = dynamodb.Table("Users")
threads_table = dynamodb.Table("Threads")
message_counts_table = dynamodb.Table("MessageCounts")
message_history_table = dynamodb.Table("MessageHistory")


def is_rate_limit_reached(wa_id: str) -> bool:
    count, last_message_time = get_message_count(wa_id)

    if datetime.datetime.now().date() > last_message_time.date():
        count = 0

    if count >= settings.daily_message_limit:
        return True

    increment_message_count(wa_id)
    return False


def get_message_count(wa_id: str) -> Tuple[int, datetime.datetime]:
    response = message_counts_table.get_item(Key={"wa_id": wa_id})
    if "Item" in response:
        item = response["Item"]
        count = item["count"]
        last_message_time = datetime.datetime.fromisoformat(item["last_message_time"])
        return count, last_message_time
    return 0, datetime.datetime.min


def increment_message_count(wa_id: str):
    count, last_message_time = get_message_count(wa_id)
    now = datetime.datetime.now()

    if now.date() > last_message_time.date():
        count = 0

    count += 1
    message_counts_table.put_item(
        Item={"wa_id": wa_id, "count": count, "last_message_time": now.isoformat()}
    )


def reset_conversation(wa_id: str):
    users_table.put_item(Item={"wa_id": wa_id, "state": "start"})


def get_user_state(wa_id: str):
    response = users_table.get_item(Key={"wa_id": wa_id})
    return response.get("Item", {"state": "start"})


def update_user_state(wa_id: str, state_update: Dict[str, str]):
    existing_state = get_user_state(wa_id)
    existing_state.update(state_update)
    users_table.put_item(Item=existing_state)


def check_if_thread_exists(wa_id: str):
    response = threads_table.get_item(Key={"wa_id": wa_id})
    return response.get("Item")


def store_thread(wa_id: str, thread_id: str):
    threads_table.put_item(Item={"wa_id": wa_id, "thread": thread_id})


def store_message(wa_id: str, message: str, role: Literal["user", "twiga"]):
    timestamp = datetime.datetime.now().isoformat()
    message_history_table.put_item(
        Item={"wa_id": wa_id, "timestamp": timestamp, "message": message, "role": role}
    )


def retrieve_messages(wa_id: str):
    response = message_history_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("wa_id").eq(wa_id)
    )
    return response.get("Items", [])


def print_messages(wa_id: str):
    messages = retrieve_messages(wa_id)
    for message in messages:
        timestamp = datetime.datetime.fromisoformat(message["timestamp"]).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        role = message["role"]
        msg = message["message"]
        print(f"[{timestamp}] ({role}): {msg}")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    print("\nmessage_counts database.")
    print_messages("some_wa_id")
