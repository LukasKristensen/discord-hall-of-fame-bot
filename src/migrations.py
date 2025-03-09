import os
from pymongo.mongo_client import MongoClient
from dotenv import load_dotenv

load_dotenv('../.env')
mongo_uri = os.getenv('MONGO_URI')
db_client = MongoClient(mongo_uri)

dev_mongo_uri = os.getenv('DEV_MONGO_URI')
dev_db_client = MongoClient(dev_mongo_uri)

target_migrations = [dev_db_client]

for target_migration in target_migrations:
    for guild in target_migration.list_database_names():
        collection = target_migration[guild]["server_config"]
        collection.update_one({}, {"$set": {"allow_messages_in_hof_channel": False}})