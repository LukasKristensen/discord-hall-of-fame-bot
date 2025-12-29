import discord as discord
import message_reactions
from discord.ext import commands
import datetime
from repositories import hof_wrapped_repo, hall_of_fame_message_repo, server_config_repo, hof_wrapped_guild_status
import psycopg2
import os
from dotenv import load_dotenv
import json
from constants import version

load_dotenv()
POSTGRES_HOST = os.getenv('POSTGRES_HOST')
POSTGRES_DB = os.getenv('POSTGRES_DB')
POSTGRES_USER = os.getenv('POSTGRES_USER')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD')

users = {}
total_hall_of_fame_posts = 0
rankings = None
reactionThreshold: int

class User:
    def __init__(self, user_id):
        self.reactionCount = 0  # Only reactions on HOF messages
        self.hallOfFameMessagePosts = 0
        self.fanOfUsers = {}
        self.usersFans = {}
        self.mostUsedChannels = {}
        self.mostReactedPost = {"post": None, "reaction_count": 0}
        self.mostUsedEmojis = {}
        self.id = user_id

    def get_hof_status(self):
        if self.hallOfFameMessagePosts > 50:
            return "🏆 Hall of Fame Superstar!"
        elif self.hallOfFameMessagePosts > 25:
            return "🏆 Hall of Fame All-Star!"
        elif self.hallOfFameMessagePosts > 10:
            return "🏆 Hall of Fame Legend!"
        elif self.hallOfFameMessagePosts > 0:
            return "🎉 Hall of Fame Member!"
        else:
            return "No Hall of Fame posts yet. Participate to get featured!"


def initialize_users(connection, guild_id: int):
    for user_id in hall_of_fame_message_repo.find_members_for_guild(connection, guild_id):
        users[user_id] = User(user_id)


async def process_message_reactions(message: discord.Message, connection):
    global total_hall_of_fame_posts

    user_author = users[message.author.id]
    users_reacted = []

    highest_reaction_count = await message_reactions.reaction_count(message, connection)
    if highest_reaction_count >= reactionThreshold:
        user_author.hallOfFameMessagePosts += 1
        total_hall_of_fame_posts += 1

    if highest_reaction_count > user_author.mostReactedPost["reaction_count"]:
        user_author.mostReactedPost["post"] = message
        user_author.mostReactedPost["reaction_count"] = highest_reaction_count

    for reaction in message.reactions:
        for user_id in [user.id async for user in reaction.users()]:
            if user_id not in users:
                continue
            if user_id not in users_reacted:
                users_reacted.append(user_id)

            user_reactor = users[user_id]

            # Feature: Reaction count
            user_reactor.reactionCount += 1

            # Feature: Most used emojis
            if reaction.emoji not in user_reactor.mostUsedEmojis:
                user_reactor.mostUsedEmojis[reaction.emoji] = 1
            else:
                user_reactor.mostUsedEmojis[reaction.emoji] += 1

    for user_id in users_reacted:
        user_reactor = users[user_id]
        user_reactor.reactionCount += 1


        # Feature: User's fans
        if user_reactor.id not in user_author.usersFans:
            user_author.usersFans[user_reactor.id] = 1
        else:
            user_author.usersFans[user_reactor.id] += 1

        # Feature: Fan of users
        if user_author.id not in user_reactor.fanOfUsers:
            user_reactor.fanOfUsers[user_author.id] = 1
        else:
            user_reactor.fanOfUsers[user_author.id] += 1


async def process_hof_messages_from_db(guild: discord.Guild, connection):
    messages = hall_of_fame_message_repo.get_all_hall_of_fame_messages_for_guild(connection, guild.id)
    print("rows fetched from DB:", len(messages))

    for message in messages:
        channel_id = message['channel_id']
        message_id = message['message_id']
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            continue
        try:
            message = await channel.fetch_message(message_id)
        except Exception:
            continue  # Skip if message not found or fetch fails
        if message.author.bot or message.author.id not in users:
            continue
        if message.created_at.year != version.WRAPPED_YEAR:
            continue
        user = users[message.author.id]
        user.hallOfFameMessagePosts += 1
        await process_message_reactions(message, connection)
        # Most used channels
        if channel.id not in user.mostUsedChannels:
            user.mostUsedChannels[channel.id] = 1
        else:
            user.mostUsedChannels[channel.id] += 1
    print("users:", users)
    return users


async def create_embed(discord_user, data_for_user_wrapped, bot):
    user_wrapped = User(discord_user.id)
    user_wrapped.reactionCount = data_for_user_wrapped['reaction_count']
    user_wrapped.hallOfFameMessagePosts = data_for_user_wrapped['hof_message_posts']
    user_wrapped.fanOfUsers = json.loads(data_for_user_wrapped['fan_of_users'])
    user_wrapped.usersFans = json.loads(data_for_user_wrapped['users_fans'])
    user_wrapped.mostUsedChannels = json.loads(data_for_user_wrapped['most_used_channels'])
    user_wrapped.mostUsedEmojis = json.loads(data_for_user_wrapped['most_used_emojis'])
    user_wrapped.userRanks = json.loads(data_for_user_wrapped['user_ranks'])
    if data_for_user_wrapped['most_reacted_post_message_id'] and data_for_user_wrapped['most_reacted_post_channel_id']:
        try:
            channel = bot.get_channel(data_for_user_wrapped['most_reacted_post_channel_id'])
            if isinstance(channel, discord.TextChannel):
                message = await channel.fetch_message(data_for_user_wrapped['most_reacted_post_message_id'])
                user_wrapped.mostReactedPost["post"] = message
        except Exception:
            user_wrapped.mostReactedPost["post"] = None
    user_wrapped.mostReactedPost["reaction_count"] = data_for_user_wrapped['most_reacted_post_reaction_count']

    embed = discord.Embed(
        title=f"✨ Hall Of Fame Wrapped {version.WRAPPED_YEAR} ✨",
        description=(
            f"📅 **User:** {discord_user.mention}\n"
        ),
        color=discord.Color.gold()
    )
    if hasattr(discord_user, 'avatar') and discord_user.avatar:
        embed.set_thumbnail(url=discord_user.avatar.url)
    elif hasattr(discord_user, 'default_avatar'):
        embed.set_thumbnail(url=discord_user.default_avatar.url)

    if user_wrapped.hallOfFameMessagePosts > 0:
        embed.description += f"\n{user_wrapped.get_hof_status()}\n"
        embed.add_field(name="🏅 Hall of Fame Posts", value=f"{user_wrapped.hallOfFameMessagePosts} posts", inline=True)
        embed.add_field(name="🎉 You gave", value=f"{user_wrapped.reactionCount} reactions on HOF posts", inline=True)
        embed.add_field(name="🎊 Reactions Received", value=f"{sum(user_wrapped.usersFans.values())} reactions on your HOF posts", inline=True)

        # Most Used Channels Section
        most_used_channel_names = sorted(user_wrapped.mostUsedChannels.items(), key=lambda x: x[1], reverse=True)[:5]
        channel_list = "\n".join(
            f"**<#{channel[0]}>**: {channel[1]} times"
            for channel in most_used_channel_names
        )
        embed.add_field(
            name="📢 Most Used Channels (HOF)",
            value=channel_list if channel_list else "No channels yet.",
            inline=False
        )
        embed.add_field(
            name="🧠 Total HOF Channels Used",
            value=f"Your HOF posts were from across **{len(user_wrapped.mostUsedChannels)}** different channels!",
            inline=True
        )

    # Most Used Emojis Section
    most_used_emojis = sorted(user_wrapped.mostUsedEmojis.items(), key=lambda x: x[1], reverse=True)[:5]
    emoji_list = "\n".join(f"{emoji[0]}: {emoji[1]} times" for emoji in most_used_emojis)
    embed.add_field(
        name="😄 Most Used Emojis (HOF)",
        value=emoji_list if emoji_list else "No emojis yet.",
        inline=False
    )

    # Fans and Fan Of
    top_fans = sorted(user_wrapped.usersFans.items(), key=lambda x: x[1], reverse=True)[:5]
    fans_list = "\n".join(
        f"**<@{fan[0]}>**: {fan[1]} reactions"
        for fan in top_fans
    )
    embed.add_field(
        name="👥 Your Top Fans (HOF)",
        value=fans_list if fans_list else "No fans yet.",
        inline=False
    )

    top_user_fans = sorted(user_wrapped.fanOfUsers.items(), key=lambda x: x[1], reverse=True)[:5]
    fan_of_list = "\n".join(
        f"**<@{fan[0]}>**: {fan[1]} reactions"
        for fan in top_user_fans
    )
    embed.add_field(
        name="💖 You Were a Fan Of (HOF)",
        value=fan_of_list if fan_of_list else "No fan-of data yet.",
        inline=False
    )

    embed = add_rankings(embed, user_wrapped.userRanks)

    if user_wrapped.mostReactedPost["post"] is not None:
        # Most Reacted Post Section
        post = user_wrapped.mostReactedPost["post"]
        if post is not None and hasattr(post, 'content'):
            most_reacted_post = user_wrapped.mostReactedPost
            embed.add_field(
                name="🔥 Most Reacted HOF Post",
                value=(
                    f"**Reactions:** {most_reacted_post['reaction_count']} 🎉\n"
                    f"**Content:** {post.content if post.content else '*No text content*'}"
                ),
                inline=False
            )
            if hasattr(post, 'attachments') and post.attachments:
                embed.set_image(url=post.attachments[0].url)
            if hasattr(post, 'jump_url'):
                embed.add_field(
                    name="🔗 Post Link",
                    value=f"[Jump to post]({post.jump_url})",
                    inline=False
                )

    return embed


def rank_stats(users: dict):
    rankings = {
        "hallOfFameMessagePosts": [],
        "reactionCount": [],
        "mostUsedChannels": [],
        "mostUsedEmojis": [],
        "fanOfUsers": [],
        "usersFans": [],
    }
    for user in users.values():
        rankings["hallOfFameMessagePosts"].append((user.id, user.hallOfFameMessagePosts))
        rankings["reactionCount"].append((user.id, user.reactionCount))
        rankings["mostUsedChannels"].append((user.id, len(user.mostUsedChannels)))
        rankings["mostUsedEmojis"].append((user.id, sum(user.mostUsedEmojis.values())))
        rankings["fanOfUsers"].append((user.id, sum(user.fanOfUsers.values())))
        rankings["usersFans"].append((user.id, sum(user.usersFans.values())))
    for key in rankings.keys():
        rankings[key].sort(key=lambda x: x[1], reverse=True)
    return rankings


def add_rankings(embed, user_ranks: dict):
    embed.add_field(
        name="📊 Your Rankings (HOF):",
        value=(
            f"**Hall of Fame Posts:** #{user_ranks['hallOfFameMessagePosts']}\n"
            f"**Reactions on HOF Posts:** #{user_ranks['reactionCount']}\n"
            f"**Most Used Channels:** #{user_ranks['mostUsedChannels']}\n"
            f"**Most Used Emojis:** #{user_ranks['mostUsedEmojis']}\n"
            f"**Received the Most Reactions:** #{user_ranks['usersFans']}\n"
            f"**Gave the Most Reactions:** #{user_ranks['fanOfUsers']}\n"
        ),
        inline=False
    )
    return embed


def get_user_rank(rankings: dict, user: User):
    user_ranks = {}
    for stat, ranked_list in rankings.items():
        user_rank = next((i + 1 for i, (member, _) in enumerate(ranked_list) if member == user.id), None)
        user_ranks[stat] = user_rank
    return user_ranks


def save_user_wrapped_to_db(guild_id, user, year):
    connection = psycopg2.connect(host=POSTGRES_HOST, database=POSTGRES_DB, user=POSTGRES_USER, password=POSTGRES_PASSWORD)
    cursor = connection.cursor()
    # Ensure rankings is not None
    user_ranks = get_user_rank(rankings, user) if rankings is not None else {}
    hof_wrapped_repo.insert_hof_wrapped(
        connection,
        guild_id=guild_id,
        user_id=user.id,
        year=year,
        reaction_count=user.reactionCount,
        hof_message_posts=user.hallOfFameMessagePosts,
        most_used_channels=json.dumps(user.mostUsedChannels),
        most_used_emojis=json.dumps({str(k): v for k, v in user.mostUsedEmojis.items()}),
        most_reacted_post_message_id=(user.mostReactedPost["post"].id if user.mostReactedPost["post"] and hasattr(user.mostReactedPost["post"], 'id') else None),
        most_reacted_post_channel_id=(user.mostReactedPost["post"].channel.id if user.mostReactedPost["post"] and hasattr(user.mostReactedPost["post"], 'channel') else None),
        most_reacted_post_reaction_count=user.mostReactedPost["reaction_count"],
        fan_of_users=json.dumps(user.fanOfUsers),
        users_fans=json.dumps(user.usersFans),
        user_ranks=json.dumps(user_ranks)
    )
    connection.commit()
    cursor.close()
    connection.close()


async def main(guild_id: int, bot: commands.Bot, get_reaction_threshold: int, connection):
    global rankings
    global reactionThreshold
    reactionThreshold = get_reaction_threshold

    print(f"Hall Of Fame Wrapped {version.WRAPPED_YEAR} is being prepared... 🎁")
    guild = bot.get_guild(guild_id)

    initialize_users(connection, guild_id)
    await process_hof_messages_from_db(guild, connection)

    rankings = rank_stats(users)

    for user in users.values():
        save_user_wrapped_to_db(guild.id, user, version.WRAPPED_YEAR)

def create_server_embed(guild, users):
    user_list = list(users)

    # Aggregate totals
    total_posts = sum(user.get('hof_message_posts', 0) if isinstance(user, dict) else user.hallOfFameMessagePosts for user in user_list)
    total_reactions = sum(user.get('reaction_count', 0) if isinstance(user, dict) else user.reactionCount for user in user_list)

    # Aggregate most used channels
    channel_counts = {}
    for user in user_list:
        channels = user.get('most_used_channels', '{}') if isinstance(user, dict) else user.mostUsedChannels
        if isinstance(channels, str):
            channels = json.loads(channels)
        for channel_id, count in channels.items():
            channel_counts[channel_id] = channel_counts.get(channel_id, 0) + count
    top_channels = sorted(channel_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    channel_list = "\n".join(f"**<#{channel_id}>**: {count} times" for channel_id, count in top_channels)

    # Aggregate most used emojis
    emoji_counts = {}
    most_reacted_post = None
    max_reactions = 0
    for user in user_list:
        count = user.get('most_reacted_post_reaction_count', 0)
        channel_id = user.get('most_reacted_post_channel_id')
        message_id = user.get('most_reacted_post_message_id')

        if count and count > max_reactions and channel_id and message_id:
            max_reactions = count
            most_reacted_post = (channel_id, message_id, count)

        emojis = user.get('most_used_emojis', '{}') if isinstance(user, dict) else user.mostUsedEmojis
        if isinstance(emojis, str):
            emojis = json.loads(emojis)
        for emoji, count in emojis.items():
            emoji_counts[emoji] = emoji_counts.get(emoji, 0) + count
    top_emojis = sorted(emoji_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    emoji_list = "\n".join(f"{emoji}: {count} times" for emoji, count in top_emojis)

    # Top HOF members by posts
    top_members = sorted(
        user_list,
        key=lambda u: u.get('hof_message_posts', 0) if isinstance(u, dict) else u.hallOfFameMessagePosts,
        reverse=True
    )[:5]
    member_list = "\n".join(
        f"**<@{member['user_id'] if isinstance(member, dict) else member.id}>**: {member.get('hof_message_posts', 0) if isinstance(member, dict) else member.hallOfFameMessagePosts} posts"
        for member in top_members if (member.get('hof_message_posts', 0) if isinstance(member, dict) else member.hallOfFameMessagePosts) > 0
    )

    # Top fans (users who reacted the most)
    top_fans = sorted(
        user_list,
        key=lambda u: u.get('reaction_count', 0) if isinstance(u, dict) else u.reactionCount,
        reverse=True
    )[:5]
    fans_list = "\n".join(
        f"**<@{fan['user_id'] if isinstance(fan, dict) else fan.id}>**: {fan.get('reaction_count', 0) if isinstance(fan, dict) else fan.reactionCount} reactions"
        for fan in top_fans if (fan.get('reaction_count', 0) if isinstance(fan, dict) else fan.reactionCount) > 0
    )

    embed = discord.Embed(
        title=f"🎁 Hall Of Fame Wrapped {version.WRAPPED_YEAR} - {guild.name} 🎁",
        description=(
            f"🏆 **Server Hall of Fame Recap**\n"
            f"Total HOF Posts: **{total_posts}**\n"
            f"Total Reactions on HOF Posts: **{total_reactions}**\n"
        ),
        color=discord.Color.purple()
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(
        name="📢 Most Used HOF Channels",
        value=channel_list if channel_list else "No HOF channels yet.",
        inline=False
    )
    embed.add_field(
        name="😄 Most Used HOF Emojis",
        value=emoji_list if emoji_list else "No HOF emojis yet.",
        inline=False
    )
    embed.add_field(
        name="🏅 Top Hall of Fame Members",
        value=member_list if member_list else "No HOF members yet.",
        inline=False
    )
    embed.add_field(
        name="👥 Top Fans (Most Reactions)",
        value=fans_list if fans_list else "No fans yet.",
        inline=False
    )

    if most_reacted_post:
        channel_id, message_id, count = most_reacted_post
        jump_url = f"https://discord.com/channels/{guild.id}/{channel_id}/{message_id}"
        embed.add_field(
            name="🔥 Most Reacted HOF Post",
            value=f"[Jump to post]({jump_url}) ({count} reactions)",
            inline=False
        )

    # should include that users can get their own hof wrapped for the server by using /hof_wrapped
    embed.add_field(
        name="🔔 Get Your Own Hall Of Fame Wrapped!",
        value="Use the `/hof_wrapped` command to see your personal Hall Of Fame Wrapped for this server!",
        inline=False
    )
    return embed



if __name__ == "__main__":
    from discord.ext import commands

    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        global users
        global total_hall_of_fame_posts
        global rankings

        print(f'Logged in as {bot.user} (ID: {bot.user.id})')
        print('------')

        connection = psycopg2.connect(host=POSTGRES_HOST, database=POSTGRES_DB, user=POSTGRES_USER, password=POSTGRES_PASSWORD)
        hof_wrapped_repo.create_hof_wrapped_table(connection)
        hof_wrapped_guild_status.create_hof_wrapped_progress_table(connection)

        for guild in bot.guilds:
            users.clear()
            total_hall_of_fame_posts = 0
            rankings = None

            print(f"Processing guild: {guild.name} (ID: {guild.id})")
            if hof_wrapped_guild_status.is_hof_wrapped_processed(connection, guild.id, version.WRAPPED_YEAR):
                print(f"Hall Of Fame Wrapped already processed for guild {guild.id}, skipping...")
                continue
            guild_id = guild.id
            reaction_threshold = server_config_repo.get_parameter_value(connection, guild_id, "reaction_threshold")

            await main(guild_id, bot, reaction_threshold, connection)
            hof_wrapped_guild_status.mark_hof_wrapped_as_processed(connection, guild.id, version.WRAPPED_YEAR)
        connection.close()
        await bot.close()

    print("Logging in the bot...")
    bot.token = os.getenv('DEV_KEY')
    bot.run(bot.token)