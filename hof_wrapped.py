import discord as discord
import message_reactions
from discord.ext import commands

users = {}

class User:
    def __init__(self, member: discord.Member):
        self.member = member
        self.messageCount = 0 # Implemented
        self.reactionCount = 0 # Implemented
        self.reactionToNonHallOfFamePosts = 0 # Implemented
        self.reactionToHallOfFamePosts = 0 # Implemented
        self.hallOfFameMessagePosts = 0 # Implemented
        self.fanOfUsers = {} # Implemented
        self.usersFans = {} # Implemented
        self.mostUsedChannels = {} # Implemented
        self.mostReactedPost = {"post": None, "reaction_count": 0} # Implemented
        self.mostUsedEmojis = {} # Implemented
        self.id = member.id

    def get_ration_hall_of_fame_posts_to_normal_posts(self):
        ratio = self.hallOfFameMessagePosts / self.messageCount if self.messageCount > 0 else 0

        if ratio > 0.2:
            return "Hall of fame addict: You have a delicate taste for hall of fame posts"
        elif ratio > 0.05:
            return "Hall of fame enthusiast: You have a good taste for hall of fame posts"
        elif ratio > 0.01:
            return "Hall of fame regular: You either have your own niche or react to a lot of posts"
        elif ratio > 0.001:
            return "Hall of fame casual: Not a big fan of hall of fame posts"
        else:
            return "Hall of fame hater: You don't react to hall of fame posts at all"


def initialize_users(guild: discord.Guild):
    for member in guild.members:
        users[member.id] = User(member)

async def process_message_reactions(message: discord.Message):
    user_author = users[message.author.id]
    hall_of_fame_post = False
    users_reacted = []

    highest_reaction_count = await message_reactions.reaction_count_without_author(message)
    if highest_reaction_count >= 6:
        user_author.hallOfFameMessagePosts += 1
        hall_of_fame_post = True
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


async def process_all_server_messages(guild: discord.Guild):
    for channel in guild.channels:
        print("Checking channel: " + channel.name, channel.id)
        if not isinstance(channel, discord.TextChannel):
            continue
        async for message in channel.history(limit=1000):
            if not isinstance(channel, discord.TextChannel):
                continue  # Ignore if the current channel is not a text channel
            if message.author.bot:
                continue # Ignore if the author of the message is a bot
            if message.author.id not in users:
                continue # Ignore if the author of the message is not in the users list
            if message.created_at.year != 2024:
                print("Breaking at: " + str(message.created_at))
                break # Check if message is from current year

            user = users[message.author.id]
            user.messageCount += 1
            await process_message_reactions(message)

            # Feature: Most used channels
            if channel.id not in user.mostUsedChannels:
                user.mostUsedChannels[channel.id] = 1
            else:
                user.mostUsedChannels[channel.id] += 1
    return users

def create_embed(user: User, guild: discord.Guild):
    if len(user.mostUsedChannels) < 3 or len(user.mostUsedEmojis) < 3 or len(user.usersFans) < 3 or len(user.fanOfUsers) < 3:
        return None
    else:
        print("Creating embed")
    embed = discord.Embed(
        title="🏆 Hall Of Fame Wrapped 2024 🏆",
        description=f"**User:** {user.member.name}",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=user.member.avatar.url if user.member.avatar else guild.icon.url)

    # General stats
    embed.add_field(name="💬 Total Messages", value=f"{user.messageCount} messages", inline=True)
    embed.add_field(name="🎉 Total Reactions", value=f"{user.reactionCount} reactions", inline=True)
    embed.add_field(name="🏅 Hall of Fame Posts", value=f"{user.hallOfFameMessagePosts} posts", inline=True)

    # Most used channels
    most_used_channel_names = sorted(user.mostUsedChannels.items(), key=lambda x: x[1], reverse=True)[:3]
    if most_used_channel_names:
        channel_list = "\n".join(
            f"**#{guild.get_channel(channel[0]).name if guild.get_channel(channel[0]) else 'Unknown'}**: {channel[1]} messages"
            for channel in most_used_channel_names
        )
        embed.add_field(name="📢 Most Used Channels", value=channel_list, inline=False)

    # Most used emojis
    most_used_emojis = sorted(user.mostUsedEmojis.items(), key=lambda x: x[1], reverse=True)[:3]
    if most_used_emojis:
        emoji_list = "\n".join(f"{emoji[0]}: {emoji[1]} times" for emoji in most_used_emojis)
        embed.add_field(name="😄 Most Used Emojis", value=emoji_list, inline=False)

    # Top fans
    top_fans = sorted(user.usersFans.items(), key=lambda x: x[1], reverse=True)[:3]
    if top_fans:
        fans_list = "\n".join(
            f"**{guild.get_member(fan[0]).name if guild.get_member(fan[0]) else 'Unknown'}**: {fan[1]} reactions"
            for fan in top_fans
        )
        embed.add_field(name="👥 Top Fans", value=fans_list, inline=False)

    # Users they were a fan of
    top_user_fans = sorted(user.fanOfUsers.items(), key=lambda x: x[1], reverse=True)[:3]
    if top_user_fans:
        fan_of_list = "\n".join(
            f"**{guild.get_member(fan[0]).name if guild.get_member(fan[0]) else 'Unknown'}**: {fan[1]} reactions"
            for fan in top_user_fans
        )
        embed.add_field(name="💖 You Were a Fan Of", value=fan_of_list, inline=False)

    # Hall of Fame ratio
    embed.add_field(name="📊 Hall of Fame Reaction Ratio", value=f"{user.get_ration_hall_of_fame_posts_to_normal_posts()}",
                    inline=False)

    # Most reacted post
    if user.mostReactedPost["post"] is not None:
        most_reacted_post = user.mostReactedPost
        embed.add_field(
            name="🔥 Most Reacted Post",
            value=f"{most_reacted_post['reaction_count']} reactions",
            inline=False
        )
        embed.add_field(
            name="Post Content",
            value=most_reacted_post["post"].content if most_reacted_post["post"].content else "*No text content*",
            inline=False
        )
        if most_reacted_post["post"].attachments:
            embed.set_image(url=most_reacted_post["post"].attachments[0].url)
        embed.add_field(
            name="Post Link",
            value=f"[Jump to post]({most_reacted_post['post'].jump_url})",
            inline=False
        )
    return embed

async def main(guild: discord.Guild, bot: commands.Bot):
    initialize_users(guild)
    await process_all_server_messages(guild)
    for user in users.values():
        wrappedEmbed = create_embed(user, guild)
        wrappedChannel = bot.get_channel(1322667427829518387)

        if wrappedEmbed is not None:
            await wrappedChannel.send("Your Hall Of Fame Wrapped 2024 is here <@" + str(user.id) + "> 🎉", embed=wrappedEmbed)
    return users