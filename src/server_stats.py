import os
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
import psycopg2
from repositories import server_config_repo, hall_of_fame_message_repo, server_user_repo, hof_wrapped_repo

load_dotenv('../.env')
connection = psycopg2.connect(host=os.getenv('POSTGRES_HOST'),
                              database=os.getenv('POSTGRES_DB'),
                              user=os.getenv('POSTGRES_USER'),
                              password=os.getenv('POSTGRES_PASSWORD'))

server_graph_folder = 'graphs'
show_plots = False

server_stats = []

for config in server_config_repo.get_all_server_configs(connection):
    if config:
        message_count = hall_of_fame_message_repo.count_messages_for_guild(connection, config.guild_id)
        server_stats.append({
            'server': config,
            'reaction_threshold': config.reaction_threshold,
            'include_author_in_reaction_calculation': config.include_author_in_reaction_calculation,
            'allow_messages_in_hof_channel': config.allow_messages_in_hof_channel,
            'message_count': message_count,
            'server_member_count': config.server_member_count
        })


# Update the plot function to include server_member_count
def create_plot(file_name, filtered_stats=None):
    filtered_stats = filtered_stats or [
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
    ax1.set_title('Reaction Thresholds, Message Counts, and Member Counts')

    ax2 = ax1.twinx()
    ax2.bar(x, message_counts, width, label='Message Counts', color='orange')
    ax2.set_ylabel('Message Counts')

    ax3 = ax1.twinx()
    ax3.bar(x + width, member_counts, width, label='Member Counts', color='green')
    ax3.set_ylabel('Member Counts')
    ax3.spines['right'].set_position(('outward', 60))  # Offset the third axis

    fig.tight_layout()
    fig.legend(loc='upper left', bbox_to_anchor=(0.1, 0.9))
    plt.savefig(os.path.join(folder_path, file_name))
    if show_plots:
        plt.show()


def create_plot_where_msg_count_greater_than_zero():
    filtered_stats = [stat for stat in server_stats if stat['message_count'] > 0]
    create_plot('server_stats_msg_count_gt_zero.png', filtered_stats)


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
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.plot(timestamps[-1], total_messages_list[-1], 'ro')
    ax.text(timestamps[-1], total_messages_list[-1], f' {total_messages_list[-1]}', color='red', va='bottom')
    ax.set_title('Total Messages Over Time')
    ax.legend()
    plt.savefig(os.path.join(folder_path, 'bot_total_messages.png'))
    if show_plots:
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
    plt.savefig(os.path.join(folder_path, 'server_count_and_total_members.png'))
    if show_plots:
        plt.show()


def create_bubble_chart():
    filtered_stats = [
        stat for stat in server_stats
        if isinstance(stat['reaction_threshold'], (int, float)) and isinstance(stat['server_member_count'], (int, float))
        and stat['reaction_threshold'] <= stat['server_member_count']
    ]

    reaction_thresholds = [stat['reaction_threshold'] for stat in filtered_stats]
    member_counts = [
        int(stat['server_member_count']) if str(stat['server_member_count']).isdigit() else 0
        for stat in filtered_stats
    ]
    message_counts = [stat['message_count'] for stat in filtered_stats]

    plt.figure(figsize=(10, 6))
    scatter = plt.scatter(reaction_thresholds, member_counts, s=[count * 3 for count in message_counts], alpha=0.5)
    for i, count in enumerate(message_counts):
        overlap = False
        for j in range(i):
            if abs(reaction_thresholds[i] - reaction_thresholds[j]) < 5 and abs(
                    member_counts[i] - member_counts[j]) < 5:
                overlap = True
                break
        if not overlap:
            plt.text(reaction_thresholds[i], member_counts[i], str(count), fontsize=8, ha='center', va='center')

    plt.xlabel('Reaction Thresholds')
    plt.legend(*scatter.legend_elements(), title="Message Count")
    plt.ylabel('Member Counts')
    plt.title('Bubble Chart of Reaction Thresholds vs Member Counts (Bubble Size = Message Count)')
    plt.grid(True)
    plt.savefig(os.path.join(folder_path, 'bubble_chart.png'))
    if show_plots:
        plt.show()


def create_average_messages_per_day_compared_to_member_count():
    avg_messages_per_day = []
    member_counts = []
    for stat in server_stats:
        if stat['message_count'] > 0:
            join_date = production_db['server_configs'].find_one({'guild_id': stat['server']}).get('joined_date')
            if not join_date:
                continue
            messages_per_day_value = stat['message_count'] / ((datetime.now() - join_date).days + 1)
            if messages_per_day_value > 0:
                avg_messages_per_day.append(messages_per_day_value)
                member_counts.append(int(stat['server_member_count']) if str(stat['server_member_count']).isdigit() else 0)

    plt.figure(figsize=(10, 6))
    plt.scatter(member_counts, avg_messages_per_day, alpha=0.7)
    plt.xlabel('Server Member Count')
    plt.ylabel('Average Messages per Day')
    plt.title('Average Messages per Day vs Server Member Count')
    plt.grid(True)
    plt.savefig(os.path.join(folder_path, 'avg_messages_per_day_vs_member_count.png'))
    if show_plots:
        plt.show()


def create_histogram_messages_per_day():
    messages_per_day = []
    for stat in server_stats:
        if stat['message_count'] > 0:
            join_date = production_db['server_configs'].find_one({'guild_id': stat['server']}).get('joined_date')
            if not join_date:
                continue
            messages_per_day_value = stat['message_count'] / ((datetime.now() - join_date).days + 1)
            if messages_per_day_value > 0:
                messages_per_day.append(messages_per_day_value)

    plt.figure(figsize=(10, 6))
    plt.hist(messages_per_day, bins=20, color='blue', alpha=0.7)
    plt.xlabel('Average Messages per Day')
    plt.ylabel('Number of Servers')
    plt.title('Histogram of Average Messages per Day Across All Servers')
    plt.grid(True)
    plt.savefig(os.path.join(folder_path, 'histogram_messages_per_day.png'))
    if show_plots:
        plt.show()


def create_histogram_of_messages_per_month():
    messages_per_month = {}
    start_date = datetime(2023, 11, 23)
    current_date = datetime.now()
    hall_of_fame_messages = production_db['hall_of_fame_messages']

    while start_date < current_date:
        end_date = datetime(start_date.year + (start_date.month // 12), ((start_date.month % 12) + 1), 1)
        query = {
            'created_at': {
                '$gte': start_date,
                '$lt': end_date
            }
        }
        count = hall_of_fame_messages.count_documents(query)
        server_count = hall_of_fame_messages.distinct('guild_id', query)
        month_str = start_date.strftime("%Y-%m")
        messages_per_month[month_str] = {'count': count, 'server_count': len(server_count)}
        start_date = end_date

    months = list(messages_per_month.keys())
    message_counts = [messages_per_month[month]['count'] for month in months]
    server_counts = [messages_per_month[month]['server_count'] for month in months]
    message_per_server = [
        message_counts[i] / server_counts[i] if server_counts[i] > 0 else 0
        for i in range(len(months))
    ]

    bar_width = 0.35
    x = np.arange(len(months))

    fig, ax1 = plt.subplots(figsize=(12, 6))

    ax1.bar(x - bar_width / 2, message_counts, bar_width, label='Message Counts', color='green', alpha=0.7)
    ax1.set_xlabel('Month')
    ax1.set_ylabel('Message Counts', color='green')
    ax1.tick_params(axis='y', labelcolor='green')
    ax1.set_xticks(x)
    ax1.set_xticklabels(months, rotation=45)

    ax2 = ax1.twinx()
    ax2.bar(x + bar_width / 2, message_per_server, bar_width, label='Messages per Server', color='blue', alpha=0.7)
    ax2.set_ylabel('Messages per Server', color='blue')
    ax2.tick_params(axis='y', labelcolor='blue')

    fig.suptitle('Histogram of Hall of Fame Messages and Messages per Server Per Month')
    ax1.grid(True, which='both', axis='y', linestyle='--', alpha=0.5)

    fig.legend(loc='upper left', bbox_to_anchor=(0.1, 0.9))

    plt.tight_layout()
    plt.savefig(os.path.join(folder_path, 'histogram_messages_and_per_server.png'))
    if show_plots:
        plt.show()


if __name__ == "__main__":
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not os.path.exists(server_graph_folder):
        os.makedirs(server_graph_folder)
    folder_path = os.path.join(server_graph_folder, timestamp_str)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

    create_histogram_of_messages_per_month()
    create_average_messages_per_day_compared_to_member_count()
    create_histogram_messages_per_day()
    create_plot_server_count_and_total_members()
    create_bot_stats_plot()
    create_bubble_chart()
    create_plot('server_stats_all.png')
    create_plot_where_msg_count_greater_than_zero()
