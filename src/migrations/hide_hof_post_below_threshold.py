import os
from pymongo.mongo_client import MongoClient
from dotenv import load_dotenv

load_dotenv('../.env')
mongo_uri = os.getenv('MONGO_URI')
db_client = MongoClient(mongo_uri)


def run():
    for guild in db_client.list_database_names():
        if not guild.isdigit():
            continue
        db_client[guild]["server_config"].update_one(
            {}, {"$set": {"hide_hof_post_below_threshold": True}}
        )
    print("Migration for hiding HOF posts below threshold executed.")
