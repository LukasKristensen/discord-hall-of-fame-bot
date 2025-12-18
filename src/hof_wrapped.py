import discord as discord
import message_reactions
from discord.ext import commands
import datetime
from repositories import hof_wrapped_repo, hall_of_fame_message_repo, server_config_repo, server_user_repo
import psycopg2
import os
from dotenv import load_dotenv
import json

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
    def __init__(self, member: discord.Member):
        self.member = member
        self.messageCount = 0  # Implemented
        self.reactionCount = 0  # Implemented
        self.reactionToNonHallOfFamePosts = 0  # Implemented
        self.reactionToHallOfFamePosts = 0  # Implemented
        self.hallOfFameMessagePosts = 0  # Implemented
        self.fanOfUsers = {}  # Implemented
        self.usersFans = {}  # Implemented
        self.mostUsedChannels = {}  # Implemented
        self.mostReactedPost = {"post": None, "reaction_count": 0}  # Implemented
        self.mostUsedEmojis = {}  # Implemented
        self.id = member.id

    def get_ratio_hall_of_fame_posts_to_normal_posts(self):
        ratio = self.reactionToHallOfFamePosts / total_hall_of_fame_posts if total_hall_of_fame_posts > 0 else 0

        if ratio > 0.4:
            return f"Hall of Fame Connoisseur: You have an unmatched eye for iconic moments! (Ratio: {round(ratio * 100, 2)}%)"
        elif ratio > 0.2:
            return f"Hall of Fame Admirer: You consistently celebrate the best posts. (Ratio: {round(ratio * 100, 2)}%)"
        elif ratio > 0.1:
            return f"Hall of Fame Explorer: You enjoy diving into standout content. (Ratio: {round(ratio * 100, 2)}%)"
        elif ratio > 0.03:
            return f"Hall of Fame Observer: You give credit where it’s due—occasionally. (Ratio: {round(ratio * 100, 2)}%)"
        elif ratio > 0.005:
            return f"Hall of Fame Wanderer: You rarely react to Hall of Fame posts, but it happens. (Ratio: {round(ratio * 100, 2)}%)"
        else:
            return f"Hall of Fame Ghost: The Hall of Fame isn't your scene. (Ratio: {round(ratio * 100, 2)}%)"


def initialize_users(connection, guild_id: int):
    for member in hall_of_fame_message_repo.find_guild_ids_from_server(connection, guild_id):
        users[member.id] = User(member)


async def process_message_reactions(message: discord.Message):
    global total_hall_of_fame_posts

    user_author = users[message.author.id]
    hall_of_fame_post = False
    users_reacted = []

    highest_reaction_count = await message_reactions.reaction_count(message)
    if highest_reaction_count >= reactionThreshold:
        user_author.hallOfFameMessagePosts += 1
        hall_of_fame_post = True
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

        # Feature: HOF ratio
        if hall_of_fame_post:
            user_reactor.reactionToHallOfFamePosts += 1
        else:
            user_reactor.reactionToNonHallOfFamePosts += 1

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
    rows = hall_of_fame_message_repo.get_all_hall_of_fame_messages_for_guild(connection, guild.id)
    print("rows fetched from DB:", len(rows))

    for channel_id, message_id in rows:
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            continue
        try:
            message = await channel.fetch_message(message_id)
        except Exception:
            continue  # Skip if message not found or fetch fails
        if message.author.bot or message.author.id not in users:
            continue
        if message.created_at.year != datetime.datetime.now().year:
            continue

        user = users[message.author.id]
        user.messageCount += 1
        await process_message_reactions(message)

        # Feature: Most used channels
        if channel.id not in user.mostUsedChannels:
            user.mostUsedChannels[channel.id] = 1
        else:
            user.mostUsedChannels[channel.id] += 1
    print("users:", users)
    return users


# Todo: this should be called from an external command to generate the embed for a user, which will also give more flexibility for data handling
def create_embed(user: User, guild: discord.Guild):
    if len(user.mostUsedChannels) < 3:
        return None
    embed = discord.Embed(
        title=f"✨ Hall Of Fame Wrapped {datetime.datetime.now().year} ✨",
        description=(
            f"📅 **User:** {user.member.mention}\n"
        ),
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=user.member.avatar.url if user.member.avatar else guild.icon.url)

    embed.add_field(name="💬 Total Messages", value=f"{user.messageCount} messages", inline=True)
    embed.add_field(name="🎉 Total Reactions", value=f"{user.reactionCount} reactions", inline=True)
    embed.add_field(name="🏅 Hall of Fame", value=f"{user.hallOfFameMessagePosts} posts", inline=True)
    embed.add_field(name="🏆 Percentage of Your Posts Posted in HOF:", value=f"{round(user.hallOfFameMessagePosts * 100 / user.messageCount, 2)}%", inline=True)

    # Hall of Fame Contribution
    if total_hall_of_fame_posts > 0:
        embed.add_field(
            name="🏆 Hall of Fame Contribution",
            value=(
                f"You represented **{round(user.hallOfFameMessagePosts * 100 / total_hall_of_fame_posts, 2)}%** "
                f"of all Hall of Fame posts this year!"
            ),
            inline=False
        )

    # Most Used Channels Section
    most_used_channel_names = sorted(user.mostUsedChannels.items(), key=lambda x: x[1], reverse=True)[:5]

    channel_list = "\n".join(
        f"**#{guild.get_channel(channel[0]).name if guild.get_channel(channel[0]) else 'Unknown'}**: {channel[1]} messages"
        for channel in most_used_channel_names
    )
    embed.add_field(
        name="📢 Most Used Channels",
        value=channel_list,
        inline=False
    )
    embed.add_field(
        name="🧠 Total amount of channels used",
        value=f"{len(user.mostUsedChannels)} channels",
        inline=True
    )

    # Most Used Emojis Section
    most_used_emojis = sorted(user.mostUsedEmojis.items(), key=lambda x: x[1], reverse=True)[:5]
    emoji_list = "\n".join(f"{emoji[0]}: {emoji[1]} times" for emoji in most_used_emojis)
    embed.add_field(
        name="😄 Most Used Emojis",
        value=emoji_list,
        inline=False
    )

    # Fans and Fan Of
    top_fans = sorted(user.usersFans.items(), key=lambda x: x[1], reverse=True)[:5]
    fans_list = "\n".join(
        f"**{guild.get_member(fan[0]).global_name if guild.get_member(fan[0]) else 'Unknown'}**: {fan[1]} reactions"
        for fan in top_fans
    )
    embed.add_field(
        name="👥 Your Top Fans",
        value=fans_list,
        inline=False
    )

    top_user_fans = sorted(user.fanOfUsers.items(), key=lambda x: x[1], reverse=True)[:5]
    fan_of_list = "\n".join(
        f"**{guild.get_member(fan[0]).global_name if guild.get_member(fan[0]) else 'Unknown'}**: {fan[1]} reactions"
        for fan in top_user_fans
    )
    embed.add_field(
        name="💖 You Were a Fan Of",
        value=fan_of_list,
        inline=False
    )

    # Hall of Fame Reaction Ratio
    embed.add_field(
        name="📊 Hall of Fame Reaction Ratio",
        value=user.get_ratio_hall_of_fame_posts_to_normal_posts(),
        inline=False
    )

    embed = add_rankings(embed, user, rankings)

    # Most Reacted Post Section
    if user.mostReactedPost["post"] is not None:
        most_reacted_post = user.mostReactedPost
        embed.add_field(
            name="🔥 Most Reacted Post",
            value=(
                f"**Reactions:** {most_reacted_post['reaction_count']} 🎉\n"
                f"**Content:** {most_reacted_post['post'].content if most_reacted_post['post'].content else '*No text content*'}"
            ),
            inline=False
        )
        if most_reacted_post["post"].attachments:
            embed.set_image(url=most_reacted_post["post"].attachments[0].url)
        embed.add_field(
            name="🔗 Post Link",
            value=f"[Jump to post]({most_reacted_post['post'].jump_url})",
            inline=False
        )

    return embed


def rank_stats(users: dict):
    rankings = {
        "messageCount": [],
        "reactionCount": [],
        "hallOfFameMessagePosts": [],
        "reactionToHallOfFamePosts": [],
        "mostUsedChannels": [],
        "mostUsedEmojis": [],
        "fanOfUsers": [],
        "usersFans": [],
    }

    # Add users to rankings for each stat
    for user in users.values():
        rankings["messageCount"].append((user.member, user.messageCount))
        rankings["hallOfFameMessagePosts"].append((user.member, user.hallOfFameMessagePosts))
        rankings["reactionToHallOfFamePosts"].append((user.member, user.reactionToHallOfFamePosts))
        rankings["mostUsedChannels"].append((user.member, len(user.mostUsedChannels)))
        rankings["mostUsedEmojis"].append((user.member, sum(user.mostUsedEmojis.values())))
        rankings["fanOfUsers"].append((user.member, sum(user.fanOfUsers.values())))
        rankings["usersFans"].append((user.member, sum(user.usersFans.values())))

    # Sort each ranking in descending order
    for key in rankings.keys():
        rankings[key].sort(key=lambda x: x[1], reverse=True)
    return rankings


def get_user_rank(rankings: dict, user: User):
    user_ranks = {}
    for stat, ranked_list in rankings.items():
        user_rank = next((i + 1 for i, (member, _) in enumerate(ranked_list) if member.id == user.member.id), None)
        user_ranks[stat] = user_rank
    return user_ranks


def add_rankings(embed, user: User, rankings: dict):
    user_ranks = get_user_rank(rankings, user)

    # Add rankings to the embed
    embed.add_field(
        name="📊 Your Rankings:",
        value=(
            f"**Message Count:** #{user_ranks['messageCount']}\n"
            f"**Hall of Fame Posts:** #{user_ranks['hallOfFameMessagePosts']}\n"
            f"**Reactions to Hall of Fame Posts:** #{user_ranks['reactionToHallOfFamePosts']}\n"
            f"**Most Used Channels:** #{user_ranks['mostUsedChannels']}\n"
            f"**Received the Most Reactions:** #{user_ranks['usersFans']}\n"
            f"**Gave the Most Reactions:** #{user_ranks['fanOfUsers']}\n"
        ),
        inline=False
    )
    return embed


def save_user_wrapped_to_db(guild_id, user, year):
    connection = psycopg2.connect(host=POSTGRES_HOST, database=POSTGRES_DB, user=POSTGRES_USER, password=POSTGRES_PASSWORD)
    cursor = connection.cursor()
    hof_wrapped_repo.insert_hof_wrapped(
        connection,
        guild_id=guild_id,
        user_id=user.id,
        year=year,
        message_count=user.messageCount,
        reaction_count=user.reactionCount,
        reaction_to_non_hof_posts=user.reactionToNonHallOfFamePosts,
        reaction_to_hof_posts=user.reactionToHallOfFamePosts,
        hof_message_posts=user.hallOfFameMessagePosts,
        most_used_channels=json.dumps(user.mostUsedChannels),
        most_used_emojis=json.dumps(user.mostUsedEmojis),
        most_reacted_post_id=(user.mostReactedPost["post"].id if user.mostReactedPost["post"] else None),
        most_reacted_post_reaction_count=user.mostReactedPost["reaction_count"],
        fan_of_users=json.dumps(user.fanOfUsers),
        users_fans=json.dumps(user.usersFans)
    )
    connection.commit()
    cursor.close()
    connection.close()


async def main(guild_id: int, bot: commands.Bot, get_reaction_threshold: int, connection):
    global rankings
    global reactionThreshold
    reactionThreshold = get_reaction_threshold

    print(f"Hall Of Fame Wrapped {datetime.datetime.now().year} is being prepared... 🎁")
    guild = bot.get_guild(guild_id)

    initialize_users(connection, guild_id)
    await process_hof_messages_from_db(guild, connection)

    rankings = rank_stats(users)

    for user in users.values():
        save_user_wrapped_to_db(guild.id, user, datetime.datetime.now().year)

if __name__ == "__main__":
    from discord.ext import commands

    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        print(f'Logged in as {bot.user} (ID: {bot.user.id})')
        print('------')

        connection = psycopg2.connect(host=POSTGRES_HOST, database=POSTGRES_DB, user=POSTGRES_USER, password=POSTGRES_PASSWORD)
        for guild in bot.guilds:
            guild_id = guild.id
            reaction_threshold = server_config_repo.get_parameter_value(connection, guild_id, "reaction_threshold")

            await main(guild_id, bot, reaction_threshold, connection)
            await bot.close()

        connection.close()

    print("Logging in the bot...")
    bot.token = os.getenv('DEV_KEY')
    bot.run(bot.token)