import os
from datetime import datetime
import json
from pymongo.mongo_client import MongoClient
from dotenv import load_dotenv
import psycopg2


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

def convert_mongodb_to_postgresql(db_client, connection):
    """
    Convert MongoDB collections to Postgresql-compatible JSON files
    """

    cursor = connection.cursor()
    production_db = db_client["production"]

    server_configs = production_db["server_configs"]
    for server_config in server_configs.find():
        guild_id = server_config.get("guild_id")
        hall_of_fame_channel_id = server_config.get("hall_of_fame_channel_id")
        reaction_threshold = server_config.get("reaction_threshold")
        post_due_date = server_config.get("post_due_date")
        leaderboard_message_ids = server_config.get("leaderboard_message_ids")
        sweep_limit = server_config.get("sweep_limit")
        sweep_limited = server_config.get("sweep_limited")
        include_author_in_reaction_calculation = server_config.get("include_author_in_reaction_calculation")
        allow_messages_in_hof_channel = server_config.get("allow_messages_in_hof_channel")
        custom_emoji_check_logic = server_config.get("custom_emoji_check_logic")
        whitelisted_emojis = server_config.get("whitelisted_emojis")
        joined_date = server_config.get("joined_date")
        leaderboard_setup = server_config.get("leaderboard_setup")
        ignore_bot_messages = server_config.get("ignore_bot_messages")
        server_member_count = server_config.get("server_member_count")
        reaction_count_calculation_method = server_config.get("reaction_count_calculation_method")
        hide_hof_post_below_threshold = server_config.get("hide_hof_post_below_threshold")

        cursor.execute("""
            INSERT INTO server_configs (
                guild_id, hall_of_fame_channel_id, reaction_threshold, post_due_date, leaderboard_message_ids,
                sweep_limit, sweep_limited, include_author_in_reaction_calculation, allow_messages_in_hof_channel,
                custom_emoji_check_logic, whitelisted_emojis, joined_date, leaderboard_setup, ignore_bot_messages,
                server_member_count, reaction_count_calculation_method, hide_hof_post_below_threshold
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (guild_id) DO NOTHING;
            """, (guild_id, hall_of_fame_channel_id, reaction_threshold, post_due_date, leaderboard_message_ids,
                   sweep_limit, sweep_limited, include_author_in_reaction_calculation, allow_messages_in_hof_channel,
                   custom_emoji_check_logic, whitelisted_emojis, joined_date, leaderboard_setup, ignore_bot_messages,
                   server_member_count, reaction_count_calculation_method, hide_hof_post_below_threshold)
        )

    hall_of_fame_messages = production_db["hall_of_fame_messages"]
    for hof_message in hall_of_fame_messages.find():
        message_id = hof_message.get("message_id")
        channel_id = hof_message.get("channel_id")
        guild_id = hof_message.get("guild_id")
        hall_of_fame_message_id = hof_message.get("hall_of_fame_message_id")
        reaction_count = hof_message.get("reaction_count")
        author_id = hof_message.get("author_id") or 0
        created_at = hof_message.get("created_at") or datetime(1970, 1, 1)
        video_link_message_id = hof_message.get("video_link_message_id")

        cursor.execute("""
            INSERT INTO hall_of_fame_message 
            (message_id, channel_id, guild_id, hall_of_fame_message_id, reaction_count, author_id, created_at, video_link_message_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (message_id) DO UPDATE SET
                channel_id=EXCLUDED.channel_id,
                guild_id=EXCLUDED.guild_id,
                hall_of_fame_message_id=EXCLUDED.hall_of_fame_message_id,
                reaction_count=EXCLUDED.reaction_count,
                author_id=EXCLUDED.author_id,
                created_at=EXCLUDED.created_at,
                video_link_message_id=EXCLUDED.video_link_message_id
        """, (message_id, channel_id, guild_id, hall_of_fame_message_id, reaction_count, author_id, created_at, video_link_message_id)
        )


    server_users = production_db["server_users"]
    for server_user in server_users.find():
        guild_id = server_user.get("guild_id")
        user_id = server_user.get("user_id")
        monthly_reaction_rank = server_user.get("monthly_reaction_rank")
        total_message_rank = server_user.get("total_message_rank")
        total_reaction_rank = server_user.get("total_reaction_rank")
        this_month_hall_of_fame_messages = server_user.get("this_month_hall_of_fame_messages")
        total_hall_of_fame_messages = server_user.get("total_hall_of_fame_messages")
        monthly_message_rank = server_user.get("monthly_message_rank")
        this_month_hall_of_fame_message_reactions = server_user.get("this_month_hall_of_fame_message_reactions")
        total_hall_of_fame_message_reactions = server_user.get("total_hall_of_fame_message_reactions")
        cursor.execute("""
            INSERT INTO server_user 
            (user_id, guild_id, monthly_reaction_rank, total_message_rank, total_reaction_rank,
             this_month_hall_of_fame_messages, total_hall_of_fame_messages, monthly_message_rank,
             this_month_hall_of_fame_message_reactions, total_hall_of_fame_message_reactions)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                guild_id=EXCLUDED.guild_id,
                monthly_reaction_rank=EXCLUDED.monthly_reaction_rank,
                total_message_rank=EXCLUDED.total_message_rank,
                total_reaction_rank=EXCLUDED.total_reaction_rank,
                this_month_hall_of_fame_messages=EXCLUDED.this_month_hall_of_fame_messages,
                total_hall_of_fame_messages=EXCLUDED.total_hall_of_fame_messages,
                monthly_message_rank=EXCLUDED.monthly_message_rank,
                this_month_hall_of_fame_message_reactions=EXCLUDED.this_month_hall_of_fame_message_reactions,
                total_hall_of_fame_message_reactions=EXCLUDED.total_hall_of_fame_message_reactions
        """, (user_id, guild_id, monthly_reaction_rank, total_message_rank, total_reaction_rank,
              this_month_hall_of_fame_messages, total_hall_of_fame_messages, monthly_message_rank,
              this_month_hall_of_fame_message_reactions, total_hall_of_fame_message_reactions)
        )

    connection.commit()
    cursor.close()


# Todo: Implement a recurring job to back up data every 15 min, then every hour, then every day, etc.

if __name__ == "__main__":
    load_dotenv()
    mongo_uri = os.getenv('MONGODB_URI')
    client = MongoClient(mongo_uri)
    backup_database(client)

    connection = psycopg2.connect(host=os.getenv('POSTGRES_HOST'),
                                  database=os.getenv('POSTGRES_DB'),
                                  user=os.getenv('POSTGRES_USER'),
                                  password=os.getenv('POSTGRES_PASSWORD'))
    convert_mongodb_to_postgresql(client, connection)
