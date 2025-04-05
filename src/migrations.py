import os
from pymongo.mongo_client import MongoClient
from dotenv import load_dotenv

load_dotenv('../.env')
mongo_uri = os.getenv('MONGO_URI')
db_client = MongoClient(mongo_uri)

dev_mongo_uri = os.getenv('DEV_MONGO_URI')
dev_db_client = MongoClient(dev_mongo_uri)

target_migrations = [db_client]

for target_migration in target_migrations:
    for guild in target_migration.list_database_names():
        if not guild.isdigit():
            continue
        collection = target_migration[guild]["server_config"]
        collection.update_one({}, {"$set": {"whitelisted_emojis": []}})
        collection.update_one({}, {"$set": {"custom_emoji_check_logic": False}})
    print("Updated total of ", target_migration.list_database_names(), " databases")