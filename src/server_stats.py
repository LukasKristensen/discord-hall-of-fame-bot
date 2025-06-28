import os
from pymongo.mongo_client import MongoClient
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import numpy as np

# Load the .env file from the parent directory
load_dotenv('../.env')
mongo_uri = os.getenv('MONGO_URI_TEST_DEV')
db_client = MongoClient(mongo_uri)
production_db = db_client['production']

server_stats = []
servers = production_db['server_configs'].distinct('guild_id')

print("db client: ", production_db)
print("servers: ", servers)
for server in servers:
    config = production_db['server_configs'].find_one({'guild_id': server})
    if config:
        message_count = production_db["hall_of_fame_messages"].count_documents({'guild_id': server})
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
    filtered_stats = [
        stat for stat in server_stats
        if isinstance(stat['reaction_threshold'], (int, float)) and isinstance(stat['server_member_count'], (int, float))
        and stat['reaction_threshold'] <= stat['server_member_count']
    ]

    servers = [stat['server'] for stat in filtered_stats]
    reaction_thresholds = [stat['reaction_threshold'] for stat in filtered_stats]
    message_counts = [stat['message_count'] for stat in filtered_stats]
    member_counts = [
        int(stat['server_member_count']) if str(stat['server_member_count']).isdigit() else 0
        for stat in filtered_stats
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


def create_bot_stats_plot():
    bot_stats = db_client['bot_stats']['total_messages']
    timestamps = []
    total_messages_list = []
    for stat in bot_stats.find():
        timestamps.append(stat['timestamp'])
        total_messages_list.append(stat['total_messages'])
    fig, ax = plt.subplots()
    ax.plot(timestamps, total_messages_list, label='Total Messages')
    ax.set_xlabel('Timestamp')
    ax.set_ylabel('Total Messages')
    ax.set_title('Total Messages Over Time')
    ax.legend()
    plt.show()


def create_plot_server_count_and_total_members():
    server_count_data = list(db_client['bot_stats']['server_count'].find())
    total_users_data = list(db_client['bot_stats']['total_users'].find())

    server_counts = [data['server_count'] for data in server_count_data]
    timestamps = [data['timestamp'] for data in server_count_data]
    fig, ax1 = plt.subplots()
    ax1.plot(timestamps, server_counts, label='Server Count', color='blue')
    ax1.set_xlabel('Timestamp')
    ax1.set_ylabel('Server Count', color='blue')
    ax1.tick_params(axis='y', labelcolor='blue')
    ax1.set_title('Server Count Over Time')
    ax1.legend(loc='upper left')
    ax1.grid()

    timestamps2 = [data['timestamp'] for data in total_users_data]
    total_members = [data['total_users'] for data in total_users_data]
    ax2 = ax1.twinx()
    ax2.plot(timestamps2, total_members, label='Total Members', color='orange')
    ax2.set_ylabel('Total Members', color='orange')
    ax2.tick_params(axis='y', labelcolor='orange')
    ax2.legend(loc='upper right')
    plt.show()


create_plot_server_count_and_total_members()
create_bot_stats_plot()
create_plot(server_stats)
create_plot_where_msg_count_greater_than_zero(server_stats)
