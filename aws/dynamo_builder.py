import boto3

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")  # todo: change region


def create_table(name, key_schema, attribute_definitions):
    table = dynamodb.create_table(
        TableName=name,
        KeySchema=key_schema,
        AttributeDefinitions=attribute_definitions,
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    return table


users_table = create_table(
    name="Users",
    key_schema=[{"AttributeName": "wa_id", "KeyType": "HASH"}],
    attribute_definitions=[{"AttributeName": "wa_id", "AttributeType": "S"}],
)

threads_table = create_table(
    name="Threads",
    key_schema=[{"AttributeName": "wa_id", "KeyType": "HASH"}],
    attribute_definitions=[{"AttributeName": "wa_id", "AttributeType": "S"}],
)

message_counts_table = create_table(
    name="MessageCounts",
    key_schema=[{"AttributeName": "wa_id", "KeyType": "HASH"}],
    attribute_definitions=[{"AttributeName": "wa_id", "AttributeType": "S"}],
)

message_history_table = create_table(
    name="MessageHistory",
    key_schema=[
        {"AttributeName": "wa_id", "KeyType": "HASH"},
        {"AttributeName": "timestamp", "KeyType": "RANGE"},
    ],
    attribute_definitions=[
        {"AttributeName": "wa_id", "AttributeType": "S"},
        {"AttributeName": "timestamp", "AttributeType": "S"},
    ],
)

print("Tables are being created. This might take a few minutes.")
