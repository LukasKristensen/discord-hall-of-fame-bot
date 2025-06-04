import os
import importlib
from pymongo.mongo_client import MongoClient
from dotenv import load_dotenv
from datetime import datetime

load_dotenv('../.env')
mongo_uri = os.getenv('MONGO_URI')
db_client = MongoClient(mongo_uri)
migration_collection = db_client["migrations"]["migration_status"]


def run_migrations(production: bool = True):
    migrations_folder = "migrations"
    completed_migrations = []

    for file_name in os.listdir(migrations_folder):
        print(f"Processing migration file: {file_name}")
        if file_name.endswith(".py") and file_name != "__init__.py":
            module_name = f"{migrations_folder}.{file_name[:-3]}"
            migration_name = file_name[:-3]

            migration_status = migration_collection.find_one({"migration_name": migration_name})
            if migration_status and migration_status.get("completed", False):
                print(f"Migration '{migration_name}' has already been run. Skipping...")
                continue

            # Dynamically import and execute migration
            importlib.import_module(module_name).run()

            migration_collection.update_one(
                {"migration_name": migration_name},
                {"$set": {"completed": production, "timestamp": datetime.utcnow()}},
                upsert=True
            )
            print(f"Migration '{migration_name}' completed.")
            completed_migrations.append(migration_name)
    return completed_migrations
