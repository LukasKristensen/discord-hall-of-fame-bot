import os
from pymongo.mongo_client import MongoClient
from dotenv import load_dotenv

load_dotenv('../../.env')
mongo_uri = os.getenv('MONGO_URI')
db_client = MongoClient(mongo_uri)


def run():
    print("Starting migration for global hall_of_fame_messages collection...")
    # hall_of_fame_messages()
    print("Starting migration for global server_configs collection...")
    # server_configs()
    print("Starting migration for global server_users collection...")
    # server_users()
    print("Migration completed for global collections.")


def hall_of_fame_messages():
    hall_of_fame_collection_db = db_client["production"]
    for guild in db_client.list_database_names():
        print(f"Processing guild: {guild}")
        server_collection = hall_of_fame_collection_db["hall_of_fame_messages"]
        if not guild.isdigit():
            continue
        source_collection = db_client[guild]["hall_of_fame_messages"]
        if source_collection.count_documents({}) > 0:
            documents = list(source_collection.find({}))
            server_collection.insert_many(documents)


def server_configs():
    hall_of_fame_collection_db = db_client["production"]
    for guild in db_client.list_database_names():
        print(f"Processing guild: {guild}")
        server_collection = hall_of_fame_collection_db["server_configs"]
        if not guild.isdigit():
            continue
        source_collection = db_client[guild]["server_config"]
        if source_collection.count_documents({}) > 0:
            documents = list(source_collection.find({}))
            server_collection.insert_many(documents)


def server_users():
    hall_of_fame_collection_db = db_client["production"]
    for guild in db_client.list_database_names():
        print(f"Processing guild: {guild}")
        server_collection = hall_of_fame_collection_db["server_users"]
        if not guild.isdigit():
            continue
        source_collection = db_client[guild]["users"]
        if source_collection.count_documents({}) > 0:
            documents = list(source_collection.find({}))
            for document in documents:
                document["guild_id"] = int(guild)
            server_collection.insert_many(documents)


if __name__ == "__main__":
    run()
    print("Migration for global hall_of_fame_messages collection executed.")
