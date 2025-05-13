import os
from pymongo.mongo_client import MongoClient
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import numpy as np

# Load the .env file from the parent directory
load_dotenv('../.env')
mongo_uri = os.getenv('MONGO_URI_TEST_DEV')
db_client = MongoClient(mongo_uri)

# Get all the servers
servers = list(db_client.list_database_names())
server_stats = []

print("db client: ", db_client)
print("servers: ", servers)
# Update server_stats to include server_member_count
for server in servers:
    if not server.isdigit():
        continue

    db = db_client[server]
    server_config = db['server_config']
    config = server_config.find_one()
    if config:
        hall_of_fame_messages = db['hall_of_fame_messages']
        message_count = hall_of_fame_messages.count_documents({})
        server_stats.append({
            'server': server,
            'reaction_threshold': config.get('reaction_threshold', 'N/A'),
            'include_author_in_reaction_calculation': config.get('include_author_in_reaction_calculation', 'N/A'),
            'allow_messages_in_hof_channel': config.get('allow_messages_in_hof_channel', 'N/A'),
            'message_count': message_count,
            'server_member_count': config.get('server_member_count', 'N/A')  # Add server_member_count
        })


# Update the plot function to include server_member_count
def create_plot(server_stats):
    servers = [stat['server'] for stat in server_stats]
    reaction_thresholds = [stat['reaction_threshold'] for stat in server_stats]
    message_counts = [stat['message_count'] for stat in server_stats]
    # Convert non-numeric member counts to 0
    member_counts = [
        int(stat['server_member_count']) if str(stat['server_member_count']).isdigit() else 0
        for stat in server_stats
    ]

    x = np.arange(len(servers))
    width = 0.25

    fig, ax1 = plt.subplots()

    ax1.bar(x - width, reaction_thresholds, width, label='Reaction Thresholds')
    ax1.set_xlabel('Servers')
    ax1.set_ylabel('Reaction Thresholds')
    ax1.set_title('Reaction Thresholds, Message Counts, and Member Counts Across Servers')
    ax1.set_xticks(x)
    ax1.set_xticklabels(servers, rotation='vertical')

    ax2 = ax1.twinx()
    ax2.bar(x, message_counts, width, label='Message Counts', color='orange')
    ax2.set_ylabel('Message Counts')

    ax3 = ax1.twinx()
    ax3.bar(x + width, member_counts, width, label='Member Counts', color='green')
    ax3.set_ylabel('Member Counts')
    ax3.spines['right'].set_position(('outward', 60))  # Offset the third axis

    fig.tight_layout()
    fig.legend(loc='upper left', bbox_to_anchor=(0.1, 0.9))
    plt.show()


def create_plot_where_msg_count_greater_than_zero(server_stats):
    filtered_stats = [stat for stat in server_stats if stat['message_count'] > 0]
    create_plot(filtered_stats)


# Call the updated plot function
create_plot(server_stats)
create_plot_where_msg_count_greater_than_zero(server_stats)
