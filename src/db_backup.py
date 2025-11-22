import os
from datetime import datetime
import json
from pymongo.mongo_client import MongoClient
from dotenv import load_dotenv


def backup_database(db_client):
    """
    Backup the production database to a new collection with a timestamp
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_folder = "db_backups"
    if not os.path.exists(backup_folder):
        os.makedirs(backup_folder)

    databases_to_backup = ["production", "migrations", "bot_stats"]
    for db_name in databases_to_backup:
        source_db = db_client[db_name]
        db_backup_folder = os.path.join(backup_folder, f"{db_name}_backup_{timestamp}")
        if not os.path.exists(db_backup_folder):
            os.makedirs(db_backup_folder)
        for collection_name in source_db.list_collection_names():
            source_collection = source_db[collection_name]
            collection_data = json.dumps(
                list(source_collection.find()),
                default=str,
                indent=4
            )
            with open(os.path.join(db_backup_folder, f"{collection_name}.json"), "w") as f:
                f.write(collection_data)
                f.close()
            print(f"Database backup completed for collection {collection_name} in database {db_name}")
    print(f"Database backup completed in folder {backup_folder}")


if __name__ == "__main__":
    load_dotenv()
    mongo_uri = os.getenv('MONGO_URI')
    client = MongoClient(mongo_uri)
    backup_database(client)
