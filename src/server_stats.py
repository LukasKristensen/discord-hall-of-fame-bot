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
for server in servers:
    if not server.isdigit():
        continue

    print("server: ", server)
    db = db_client[server]
    print("db: ", db)
    server_config = db['server_config']
    print("server config: ", server_config)
    config = server_config.find_one()
    if config:
        hall_of_fame_messages = db['hall_of_fame_messages']
        message_count = hall_of_fame_messages.count_documents({})
        server_stats.append({
            'server': server,
            'reaction_threshold': config.get('reaction_threshold', 'N/A'),
            'include_author_in_reaction_calculation': config.get('include_author_in_reaction_calculation', 'N/A'),
            'allow_messages_in_hof_channel': config.get('allow_messages_in_hof_channel', 'N/A'),
            'message_count': message_count
        })

# Display the stats
for stat in server_stats:
    print(f"Server: {stat['server']}")
    print(f"  Reaction Threshold: {stat['reaction_threshold']}")
    print(f"  Include Author in Reaction Calculation: {stat['include_author_in_reaction_calculation']}")
    print(f"  Allow Messages in HOF Channel: {stat['allow_messages_in_hof_channel']}")
    print(f"  Total Messages in HOF: {stat['message_count']}")
    print()


# Optionally, create a plot with matplotlib
def create_plot(server_stats):
    servers = [stat['server'] for stat in server_stats]
    reaction_thresholds = [stat['reaction_threshold'] for stat in server_stats]
    message_counts = [stat['message_count'] for stat in server_stats]

    x = np.arange(len(servers))
    width = 0.35

    fig, ax1 = plt.subplots()

    ax1.bar(x - width/2, reaction_thresholds, width, label='Reaction Thresholds')
    ax1.set_xlabel('Servers')
    ax1.set_ylabel('Reaction Thresholds')
    ax1.set_title('Reaction Thresholds and Message Counts Across Servers')
    ax1.set_xticks(x)
    ax1.set_xticklabels(servers, rotation='vertical')

    ax2 = ax1.twinx()
    ax2.bar(x + width/2, message_counts, width, label='Message Counts', color='orange')
    ax2.set_ylabel('Message Counts')

    fig.tight_layout()
    fig.legend(loc='upper left', bbox_to_anchor=(0.1,0.9))
    plt.show()


def create_plot_where_msg_count_greater_than_zero(server_stats):
    filtered_stats = [stat for stat in server_stats if stat['message_count'] > 0]
    create_plot(filtered_stats)


create_plot(server_stats)
create_plot_where_msg_count_greater_than_zero(server_stats)
