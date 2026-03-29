import os
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
import psycopg2
from repositories import server_config_repo, hall_of_fame_message_repo

# Make exports deterministic regardless of the current working directory.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))

load_dotenv('../.env')
connection = psycopg2.connect(host=os.getenv('POSTGRES_HOST'),
                              database=os.getenv('POSTGRES_DB'),
                              user=os.getenv('POSTGRES_USER'),
                              password=os.getenv('POSTGRES_PASSWORD'))

server_graph_folder = os.path.join(PROJECT_ROOT, 'graphs')
show_plots = False

server_stats = []

for config in server_config_repo.get_all_server_configs(connection):
    if config:
        message_count = hall_of_fame_message_repo.count_messages_for_guild(connection, config.guild_id)
        joined_date = server_config_repo.get_parameter_value(connection, config.guild_id, "joined_date")
        server_stats.append({
            'server': config,
            'guild_id': config.guild_id,
            'reaction_threshold': config.reaction_threshold,
            'include_author_in_reaction_calculation': config.include_author_in_reaction_calculation,
            'allow_messages_in_hof_channel': config.allow_messages_in_hof_channel,
            'message_count': message_count,
            'server_member_count': config.server_member_count,
            'joined_date': joined_date
        })


def fetch_time_series(connection, table_name: str, value_column: str):
    """Fetch (timestamp,value) from a Postgres bot-stats style table.

    This script used to read from MongoDB `bot_stats.*` collections. In Postgres we expect
    equivalent tables with a `timestamp` column and a numeric value column (e.g. `total_messages`).
    If the table doesn't exist, return an empty list.
    """
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"SELECT timestamp, {value_column} FROM {table_name} ORDER BY timestamp ASC"
        )
        rows = cursor.fetchall()
        return [(row[0], row[1]) for row in rows]
    except psycopg2.Error:
        # Missing table/column etc. Keep the script usable for installations that don't track bot stats.
        connection.rollback()
        return []
    finally:
        cursor.close()


# Update the plot function to include server_member_count
def create_plot(file_name, filtered_stats=None):
    filtered_stats = filtered_stats or [
        stat for stat in server_stats
        if isinstance(stat['reaction_threshold'], (int, float))
        and isinstance(stat['server_member_count'], (int, float))
        and stat['reaction_threshold'] <= stat['server_member_count']
    ]

    servers = [stat['guild_id'] for stat in filtered_stats]
    reaction_thresholds = [stat['reaction_threshold'] for stat in filtered_stats]
    message_counts = [stat['message_count'] for stat in filtered_stats]
    member_counts = [int(stat['server_member_count'] or 0) for stat in filtered_stats]

    x = np.arange(len(servers))
    width = 0.25

    fig, ax1 = plt.subplots()

    ax1.bar(x - width, reaction_thresholds, width, label='Reaction Thresholds')
    ax1.set_xlabel('Servers (guild_id)')
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
    """Export total messages over time.

    Source priority:
      1) Postgres time-series table `bot_stats_total_messages(timestamp, total_messages)` if present.
      2) Otherwise compute a cumulative series from `hall_of_fame_message.created_at`.

    This ensures the graph is *always* exported and reflects Postgres data.
    """
    series = fetch_time_series(connection, 'bot_stats_total_messages', 'total_messages')

    if series:
        timestamps = [ts for ts, _ in series]
        total_messages_list = [val for _, val in series]
        source_note = "source: bot_stats_total_messages"
    else:
        # Build a cumulative time series from hall_of_fame_message.
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT date_trunc('day', created_at) AS day, COUNT(*)
                FROM hall_of_fame_message
                WHERE created_at >= TIMESTAMP '2000-01-01'
                GROUP BY day
                ORDER BY day ASC
                """
            )
            rows = cursor.fetchall()
        finally:
            cursor.close()

        if not rows:
            print("Skipping bot_total_messages.png (no hall_of_fame_message rows found)")
            return

        timestamps = [r[0] for r in rows]
        counts = [r[1] for r in rows]
        total_messages_list = np.cumsum(counts).tolist()
        source_note = "source: hall_of_fame_message cumulative"

    fig, ax = plt.subplots()
    ax.plot(timestamps, total_messages_list, label='Total Messages')
    ax.set_xlabel('Timestamp')
    ax.set_ylabel('Total Messages')

    ax.plot(timestamps[-1], total_messages_list[-1], 'ro')
    ax.annotate(
        str(total_messages_list[-1]),
        xy=(timestamps[-1], total_messages_list[-1]),
        xytext=(5, 5),
        textcoords='offset points',
        color='red',
    )

    ax.set_title(f'Total Messages Over Time ({source_note})')
    ax.legend()

    out_path = os.path.abspath(os.path.join(folder_path, 'bot_total_messages.png'))
    fig.savefig(out_path)
    plt.close(fig)

    if os.path.exists(out_path):
        print(f"Wrote: {out_path}")
    else:
        print(f"WARNING: savefig returned but file not found: {out_path}")


def create_plot_server_count_and_total_members():
    # Expected tables:
    # - bot_stats_server_count(timestamp TIMESTAMP, server_count INT)
    # - bot_stats_total_users(timestamp TIMESTAMP, total_users BIGINT)
    server_series = fetch_time_series(connection, 'bot_stats_server_count', 'server_count')
    users_series = fetch_time_series(connection, 'bot_stats_total_users', 'total_users')
    if not server_series or not users_series:
        return

    server_counts = [val for _, val in server_series]
    timestamps = [ts for ts, _ in server_series]
    fig, ax1 = plt.subplots()
    ax1.plot(timestamps, server_counts, label='Server Count', color='blue')
    ax1.set_xlabel('Timestamp')
    ax1.set_ylabel('Server Count', color='blue')
    ax1.tick_params(axis='y', labelcolor='blue')
    ax1.set_title('Server Count Over Time')
    ax1.legend(loc='upper left')
    ax1.grid()

    timestamps2 = [ts for ts, _ in users_series]
    total_members = [val for _, val in users_series]
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
        if isinstance(stat['reaction_threshold'], (int, float))
        and isinstance(stat['server_member_count'], (int, float))
        and stat['reaction_threshold'] <= stat['server_member_count']
    ]

    reaction_thresholds = [stat['reaction_threshold'] for stat in filtered_stats]
    member_counts = [int(stat['server_member_count'] or 0) for stat in filtered_stats]
    message_counts = [stat['message_count'] for stat in filtered_stats]

    plt.figure(figsize=(10, 6))
    scatter = plt.scatter(reaction_thresholds, member_counts, s=[count * 3 for count in message_counts], alpha=0.5)
    for i, count in enumerate(message_counts):
        overlap = False
        for j in range(i):
            if abs(reaction_thresholds[i] - reaction_thresholds[j]) < 5 and abs(member_counts[i] - member_counts[j]) < 5:
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
            join_date = stat.get('joined_date')
            if not join_date:
                continue
            messages_per_day_value = stat['message_count'] / ((datetime.now() - join_date).days + 1)
            if messages_per_day_value > 0:
                avg_messages_per_day.append(messages_per_day_value)
                member_counts.append(int(stat['server_member_count'] or 0))

    if not avg_messages_per_day:
        return

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
            join_date = stat.get('joined_date')
            if not join_date:
                continue
            messages_per_day_value = stat['message_count'] / ((datetime.now() - join_date).days + 1)
            if messages_per_day_value > 0:
                messages_per_day.append(messages_per_day_value)

    if not messages_per_day:
        return

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
    # Uses hall_of_fame_message.created_at in Postgres
    cursor = connection.cursor()
    try:
        # Filter out epoch/placeholder timestamps (common when legacy data used 1970-01-01).
        cursor.execute(
            """
            SELECT MIN(created_at), MAX(created_at)
            FROM hall_of_fame_message
            WHERE created_at >= TIMESTAMP '2000-01-01'
            """
        )
        row = cursor.fetchone()
        if not row or not row[0] or not row[1]:
            return
        start_date = row[0].replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_max = row[1]

        messages_per_month = {}
        current = start_date
        while current <= end_max:
            # next month
            next_month = datetime(current.year + (current.month // 12), ((current.month % 12) + 1), 1)
            cursor.execute(
                """
                SELECT COUNT(*) AS message_count,
                       COUNT(DISTINCT guild_id) AS server_count
                FROM hall_of_fame_message
                WHERE created_at >= %s AND created_at < %s
                  AND created_at >= TIMESTAMP '2000-01-01'
                """,
                (current, next_month),
            )
            count, server_count = cursor.fetchone()
            month_str = current.strftime("%Y-%m")
            messages_per_month[month_str] = {'count': count or 0, 'server_count': server_count or 0}
            current = next_month

    finally:
        cursor.close()

    if not messages_per_month:
        return

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
    # Downsample tick labels so the chart stays readable for long time ranges
    if len(months) > 24:
        step = max(1, len(months) // 24)
        tick_positions = x[::step]
        tick_labels = [months[i] for i in range(0, len(months), step)]
        ax1.set_xticks(tick_positions)
        ax1.set_xticklabels(tick_labels, rotation=45, ha='right')
    else:
        ax1.set_xticklabels(months, rotation=45, ha='right')

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

    print(f"Exporting graphs to: {os.path.abspath(folder_path)}")

    create_histogram_of_messages_per_month()
    create_average_messages_per_day_compared_to_member_count()
    create_histogram_messages_per_day()
    create_plot_server_count_and_total_members()
    create_bot_stats_plot()
    create_bubble_chart()
    create_plot('server_stats_all.png')
    create_plot_where_msg_count_greater_than_zero()
