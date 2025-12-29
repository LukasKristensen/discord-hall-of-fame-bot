import os
import importlib
import discord
from pymongo.mongo_client import MongoClient
from dotenv import load_dotenv
from datetime import datetime, UTC

load_dotenv('../.env')
mongo_uri = os.getenv('MONGO_URI')
db_client = MongoClient(mongo_uri)
migration_collection = db_client["migrations"]["migration_status"]


def run_migrations(production: bool = True):
    migrations_folder = "migrations"
    completed_migrations = []

    for file_name in os.listdir(migrations_folder):
        if not file_name.endswith(".py") or file_name == "__init__.py":
            continue
        print(f"Processing migration file: {file_name}")

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
            {"$set": {"completed": production, "timestamp": datetime.now(UTC)}},
            upsert=True
        )
        print(f"Migration '{migration_name}' completed.")
        completed_migrations.append(migration_name)
    return completed_migrations


async def add_author_id_and_message_created_field_to_all_messages(bot: discord.Client):
    """
    Add author_id and message_created fields to all messages in the hall_of_fame_messages collection.
    :param bot: Discord client instance
    """
    print("Starting migration to add author_id and message_created fields to all messages...")

    for guild_id in db_client.list_database_names():
        if not guild_id.isdigit():
            continue
        server_collection = db_client[guild_id]["hall_of_fame_messages"]
        for message in server_collection.find():
            try:
                if "author_id" not in message:
                    channel_id = message.get("channel_id")
                    message_id = message.get("message_id")
                    discord_message = await bot.get_channel(channel_id).fetch_message(message_id)
                    author_id = discord_message.author.id if discord_message.author else None
                    created_at = discord_message.created_at if discord_message else None

                    print(f"Updating message {message_id} in channel {channel_id} with author_id {author_id} and message_created: {created_at}")
                    server_collection.update_one(
                        {"_id": message["_id"]},
                        {"$set": {"author_id": author_id, "created_at": discord_message.created_at}}
                    )
                    print(f"Updated message {message_id} in channel {channel_id} with author_id and message_created.")
            except Exception as e:
                print(f"Failed to update message {message['_id']} in guild {guild_id}: {e}")
