import discord
import utils
from constants import version
from enums import command_refs, calculation_method_type
from repositories import server_config_repo, server_user_repo
from caches import ExpiringSet
from translations import messages

def build_help_embed() -> discord.Embed:
    """
    The card /help answers with: every command, grouped by who uses it and what it changes.

    One field per group rather than one per command, so the whole list fits on a screen and a member
    looking for the leaderboard does not have to scroll past a dozen settings to find it. The groups
    follow the ones /get_server_config shows, so a setting is found under the same heading in both.
    :return: The embed to send
    """
    embed = discord.Embed(
        title="📖 Hall of Fame Commands",
        description=f"React to a message, and once it passes the threshold it is reposted to the hall "
                    f"of fame channel. To get started, pick a channel with "
                    f"{command_refs.SET_HALL_OF_FAME_CHANNEL} and a threshold with "
                    f"{command_refs.SET_REACTION_THRESHOLD}.",
        color=discord.Color.gold()
    )

    embed.add_field(
        name="🏆 For everyone",
        value=f"{command_refs.LEADERBOARD} the server's top members\n"
              f"{command_refs.USER_PROFILE} a member's standing\n"
              f"{command_refs.HOF_WRAPPED} your year in review\n"
              f"{command_refs.SERVER_HOF_WRAPPED} the server's year in review",
        inline=False)

    embed.add_field(
        name="⚙️ Board · Manage Server",
        value=f"{command_refs.SET_HALL_OF_FAME_CHANNEL} the channel posts go to\n"
              f"{command_refs.SET_REACTION_THRESHOLD} reactions needed\n"
              f"{command_refs.CALCULATION_METHOD} how reactions are counted\n"
              f"{command_refs.GET_SERVER_CONFIG} every current setting",
        inline=False)

    embed.add_field(
        name="🎯 What qualifies · Manage Server",
        value=f"{command_refs.SET_POST_DUE_DATE} how old a post can be\n"
              f"{command_refs.INCLUDE_AUTHORS_REACTION} count the author's own reaction\n"
              f"{command_refs.IGNORE_BOT_MESSAGES} skip messages from bots\n"
              f"{command_refs.REQUIRE_IMAGE_OR_VIDEO} only posts with an image or video",
        inline=False)

    embed.add_field(
        name="📋 Board behaviour · Manage Server",
        value=f"{command_refs.ALLOW_MESSAGES_IN_HOF_CHANNEL} let members chat in the board channel\n"
              f"{command_refs.HIDE_HOF_POST_BELOW_THRESHOLD} hide posts that drop below the threshold",
        inline=False)

    embed.add_field(
        name="😀 Emoji whitelist · Manage Server",
        value=f"{command_refs.CUSTOM_EMOJI_CHECK_LOGIC} count every emoji or only whitelisted ones\n"
              f"{command_refs.WHITELIST_EMOJI} · {command_refs.UNWHITELIST_EMOJI} · "
              f"{command_refs.CLEAR_WHITELIST}",
        inline=False)

    embed.add_field(
        name="🔗 Links",
        value=f"[Support server](https://discord.gg/r98WC5GHcn) · "
              f"[Add to a server](https://discord.com/oauth2/authorize?client_id=1177041673352663070) · "
              f"[Vote](https://top.gg/bot/1177041673352663070/vote) · "
              f"[Source](https://github.com/LukasKristensen/discord-hall-of-fame-bot)\n"
              f"Found a bug or have an idea? {command_refs.FEEDBACK}\n"
              f"Not working? Check the bot's permissions in the channel, or re-invite it.",
        inline=False)

    embed.set_footer(text=f"Hall of Fame {version.VERSION} · {version.DATE}")
    return embed


async def get_help(interaction: discord.Interaction):
    """
    Command to get a list of commands
    :param interaction:
    :return:
    """
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(embed=build_help_embed())


async def manual_sweep(interaction: discord.Interaction, guild_id: int, sweep_limit, sweep_limited: bool, bot: discord.Client,
                       collection, reaction_threshold: int, post_due_date: int, target_channel_id: int,
                       allow_messages_in_hof_channel: bool):
    """
    Command to manually sweep all messages in a server [DEV]
    :param interaction:
    :param guild_id:
    :param sweep_limit:
    :param sweep_limited:
    :param bot:
    :param collection:
    :param reaction_threshold:
    :param post_due_date:
    :param target_channel_id:
    :param allow_messages_in_hof_channel:
    :return:
    """
    await utils.check_all_server_messages(int(guild_id), sweep_limit, sweep_limited, bot, collection, reaction_threshold, post_due_date, target_channel_id, allow_messages_in_hof_channel, interaction)


async def set_reaction_threshold(interaction: discord.Interaction, reaction_threshold: int, connection,
                                 method_label: str, server_config):
    """
    Command to set the reaction threshold for posting a message in the Hall of Fame
    :param interaction:
    :param reaction_threshold:
    :param connection:
    :param method_label: How the server counts reactions, so the reply says what the number means
    :param server_config: The server's cached configuration, updated along with the database
    :return:
    """
    server_config_repo.update_server_config_param(interaction.guild.id, 'reaction_threshold', reaction_threshold, connection)
    # Updated before the reply is awaited, so a reaction handled meanwhile, or a reply that fails, does
    # not leave the cache on the old threshold while the database already holds the new one
    server_config.reaction_threshold = reaction_threshold
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(
        messages.SETTING_CHANGED.format(label="Reaction threshold", value=reaction_threshold) + "\n"
        + messages.REACTION_THRESHOLD_NOTE.format(threshold=reaction_threshold,
                                                  plural="" if reaction_threshold == 1 else "s",
                                                  method=method_label)
        + f" Change how reactions are counted with {command_refs.CALCULATION_METHOD}.")


async def user_server_profile(interaction, user, user_stats, connection, month_emoji: str, all_time_emoji: str):
    """
    Command to get the Hall of Fame profile for a user in a specific server
    :param interaction:
    :param user:
    :param user_stats:
    :param connection:
    :param month_emoji:
    :param all_time_emoji:
    :return:
    """
    user_has_most_this_month_hall_of_fame_messages = server_user_repo.check_if_user_is_top_of_stat(
        connection, user.id, interaction.guild.id, "this_month_hall_of_fame_messages")
    user_with_most_all_time_hall_of_fame_messages = server_user_repo.check_if_user_is_top_of_stat(
        connection, user.id, interaction.guild.id, "total_hall_of_fame_messages")

    embed = discord.Embed(
        title=f"📊 {user.name}'s Server Profile",
        description=f"Here are your stats for **{interaction.guild.name}**:",
        color=discord.Color.gold()
    )
    if user_has_most_this_month_hall_of_fame_messages and user_stats:
        embed.add_field(name=f"{month_emoji} **Monthly Hall of Fame Champion**",
                        value=f"**{user.name}** is the champion of this month's Hall of Fame with **{user_stats.get('this_month_hall_of_fame_messages', 0)}** messages!",
                        inline=False)
    if user_with_most_all_time_hall_of_fame_messages and user_stats:
        embed.add_field(name=f"{all_time_emoji} **All-Time Hall of Fame Champion**",
                        value=f"**{user.name}** is the all-time champion with **{user_stats.get('total_hall_of_fame_messages', 0)}** messages!",
                        inline=False)
    embed.add_field(name="", value="", inline=False)
    if user_stats:
        embed.add_field(name="🏆 **This Month's Hall of Fame Messages**",
                        value=f"**{user_stats.get('this_month_hall_of_fame_messages', 0)}** "
                              # A member with nothing featured this month is stored without a rank
                              f"(Rank: {user_stats.get('monthly_message_rank') or 'N/A'})", inline=False)
        embed.add_field(name="🌟 **Total Hall of Fame Messages**",
                        value=f"**{user_stats.get('total_hall_of_fame_messages', 0)}** "
                              f"(Rank: {user_stats.get('total_message_rank', 'N/A')})", inline=False)
        embed.add_field(name="💬 **Reactions Received This Month on Hall of Fame Messages**",
                        value=f"**{user_stats.get('this_month_hall_of_fame_message_reactions', 0)}** "
                              f"(Rank: {user_stats.get('monthly_reaction_rank') or 'N/A'})", inline=False)
        embed.add_field(name="💬 **Total Reactions Received on Hall of Fame Messages**",
                        value=f"**{user_stats.get('total_hall_of_fame_message_reactions', 0)}** "
                              f"(Rank: {user_stats.get('total_reaction_rank', 'N/A')})", inline=False)
    else:
        embed.add_field(name="🏆 **This Month's Hall of Fame Messages**", value="**0**", inline=False)
        embed.add_field(name="", value="", inline=False)
        embed.add_field(name="🌟 **Total Hall of Fame Messages**", value="**0**", inline=False)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Note that this is calculated every 24 hours, so it may not be up to date.")
    await interaction.response.send_message(embed=embed)


async def server_leaderboard(interaction, connection, month_emoji: str, all_time_emoji: str):
    """
    Command to get the Hall of Fame leaderboard for a server
    :param interaction:
    :param connection:
    :param month_emoji:
    :param all_time_emoji:
    :return:
    """
    # Defer the interaction response to prevent timeout
    await interaction.response.defer()

    embed = discord.Embed(
        title=f"📊 {interaction.guild.name} Hall of Fame Leaderboard",
        description="Here are the top users in this server:",
        color=discord.Color.blue()
    )

    # Consolidated Leaderboard
    leaderboard = ""

    # Top 5 This Month's Hall of Fame Messages
    top_monthly = server_user_repo.get_top_users_by_stat(connection, interaction.guild_id, "this_month_hall_of_fame_messages", limit=5)
    leaderboard += f"{month_emoji} **Top 5 This Month's Hall of Fame Messages**\n"
    for rank, user in enumerate(top_monthly, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('this_month_hall_of_fame_messages', 0)} messages\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('this_month_hall_of_fame_messages', 0)} messages\n"

    # Top 5 All-Time Hall of Fame Messages
    top_all_time = server_user_repo.get_top_users_by_stat(connection, interaction.guild_id, "total_hall_of_fame_messages", limit=5)
    leaderboard += f"\n{all_time_emoji} **Top 5 All-Time Hall of Fame Messages**\n"
    for rank, user in enumerate(top_all_time, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('total_hall_of_fame_messages', 0)} messages\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('total_hall_of_fame_messages', 0)} messages\n"

    # Top 5 This Month's Reactions
    top_monthly_reactions = server_user_repo.get_top_users_by_stat(connection, interaction.guild_id, "this_month_hall_of_fame_message_reactions", limit=5)
    leaderboard += f"\n💬 **Top 5 This Month's Reactions**\n"
    for rank, user in enumerate(top_monthly_reactions, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('this_month_hall_of_fame_message_reactions', 0)} reactions\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('this_month_hall_of_fame_message_reactions', 0)} reactions\n"

    # Top 5 All-Time Reactions
    top_all_time_reactions = server_user_repo.get_top_users_by_stat(connection, interaction.guild_id, "total_hall_of_fame_message_reactions", limit=5)
    leaderboard += f"\n💬 **Top 5 All-Time Reactions**\n"
    for rank, user in enumerate(top_all_time_reactions, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('total_hall_of_fame_message_reactions', 0)} reactions\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('total_hall_of_fame_message_reactions', 0)} reactions\n"

    embed.add_field(name="Leaderboard", value=leaderboard, inline=False)
    embed.set_footer(text="Note that this is calculated every 24 hours, so it may not be up to date.")
    await interaction.followup.send(embed=embed)


# A ping is answered at most once per channel in this window, so that it cannot be used to make the
# bot flood a channel
mention_cooldown_seconds = 30
recently_answered_mentions = ExpiringSet(ttl_seconds=mention_cooldown_seconds)


def is_bot_mention(message: discord.Message, bot_user) -> bool:
    """
    Decide whether a message is somebody pinging the bot to ask what it is.

    Deliberately narrow. A role ping or an @everyone is not addressed to the bot, a reply carries a
    mention of the author it is replying to, and a message that mentions the bot in passing is a
    conversation rather than a question. Answering any of those turns the bot into a nuisance.
    :param message: The message that was sent
    :param bot_user: The bot's own user
    :return: True when the message is a bare mention of the bot
    """
    if bot_user is None or message.author.bot:
        return False
    if not any(user.id == bot_user.id for user in message.mentions):
        return False
    if message.reference is not None:
        return False

    remaining = message.content
    for mention in (f"<@{bot_user.id}>", f"<@!{bot_user.id}>"):
        remaining = remaining.replace(mention, "")
    return remaining.strip() == ""


def build_bot_info_embed(guild, bot_user, server_config) -> discord.Embed:
    """
    The card the bot answers a ping with: what it is, how this server has it set up, and where to go
    :param guild: The server the ping came from
    :param bot_user: The bot's own user, for the thumbnail
    :param server_config: The server's configuration, or None when it has not been set up
    :return: The embed to send
    """
    embed = discord.Embed(
        title="🏆 Hall of Fame",
        description="Your server's best moments, and the members behind them. React to a message, "
                    "and once it passes the threshold it is reposted to the hall of fame channel "
                    "and credited to whoever posted it.\n\n"
                    "Landing there is meant to be worth something, so the bot keeps score: "
                    "leaderboards, member profiles and a yearly wrapped.",
        color=discord.Color.gold()
    )

    if server_config is not None:
        method = str(server_config.reaction_count_calculation_method).replace("_", " ")
        embed.add_field(
            name="Set up in this server",
            value=f"Board: <#{server_config.hall_of_fame_channel_id}>\n"
                  f"Reactions needed: **{server_config.reaction_threshold}**\n"
                  f"Counting: {method}\n"
                  f"Full configuration with {command_refs.GET_SERVER_CONFIG}",
            inline=False)
    else:
        embed.add_field(
            name="Not set up in this server yet",
            value=f"Point the bot at a channel with {command_refs.SET_HALL_OF_FAME_CHANNEL}, then "
                  f"pick how many reactions a message needs with {command_refs.SET_REACTION_THRESHOLD}. "
                  f"Both need the Manage Server permission.",
            inline=False)

    embed.add_field(
        name="For everyone",
        value=f"{command_refs.LEADERBOARD} rank the server\n"
              f"{command_refs.USER_PROFILE} a member's standing\n"
              f"{command_refs.HOF_WRAPPED} your year in review\n"
              f"{command_refs.HELP} every command",
        inline=True)
    embed.add_field(
        name="Links",
        value="[Add to a server](https://discord.com/oauth2/authorize?client_id=1177041673352663070)\n"
              "[Support server](https://discord.gg/r98WC5GHcn)\n"
              "[Vote](https://top.gg/bot/1177041673352663070/vote)\n"
              "[Source](https://github.com/LukasKristensen/discord-hall-of-fame-bot)",
        inline=True)

    if bot_user is not None and getattr(bot_user, "display_avatar", None) is not None:
        embed.set_thumbnail(url=bot_user.display_avatar.url)
    embed.set_footer(text=f"Hall of Fame {version.VERSION}")
    return embed


calculation_method_labels = {
    calculation_method_type.MOST_REACTIONS_ON_EMOJI: "Most reactions on a single emoji",
    calculation_method_type.TOTAL_REACTIONS: "Total reactions across all emojis",
    calculation_method_type.UNIQUE_USERS: "Unique members who reacted",
}

# Discord rejects an embed field value longer than 1024 characters, and a whitelist of custom emojis
# can pass that
embed_field_value_limit = 1024


def _toggle(enabled: bool, label: str) -> str:
    return f"{'✅' if enabled else '❌'} {label}"


def _whitelist_value(emojis) -> str:
    if not emojis:
        # An empty whitelist filters nothing out, see message_reactions.filter_whitelisted_reactions
        return f"Empty, so every emoji still counts. Add one with {command_refs.WHITELIST_EMOJI}"

    shown = []
    for index, emoji in enumerate(emojis):
        remaining = len(emojis) - index
        overflow = f" and {remaining} more"
        if len(" ".join(shown + [emoji])) + len(overflow) > embed_field_value_limit:
            return " ".join(shown) + overflow
        shown.append(emoji)
    return " ".join(shown)


def build_server_config_embed(guild, server_config) -> discord.Embed:
    """
    The card /get_server_config answers with: every setting, grouped by what it affects.

    Deliberately plain. The settings are what the reader came for, so the values are kept in one
    column with nothing between them: no thumbnail narrowing the text, and no command link on every
    row. Both of those wrap the values onto a second line and cost more in scanning than they give
    back, which is why the command that changes a setting is named once at the bottom instead.
    :param guild: The server the command was used in
    :param server_config: The server's configuration
    :return: The embed to send
    """
    embed = discord.Embed(
        title="⚙️ Hall of Fame Configuration",
        description=f"How the bot is set up in **{guild.name}**. "
                    f"Changing a setting needs the Manage Server permission.",
        color=discord.Color.gold()
    )

    channel = (f"<#{server_config.hall_of_fame_channel_id}>" if server_config.hall_of_fame_channel_id
               else "Not set")
    method = server_config.reaction_count_calculation_method
    method_label = calculation_method_labels.get(method, str(method).replace("_", " "))
    embed.add_field(
        name="🏆 Board",
        value=f"**Channel:** {channel}\n"
              f"**Reactions needed:** {server_config.reaction_threshold}\n"
              f"**Counting:** {method_label}",
        inline=False)

    embed.add_field(
        name="🎯 What qualifies",
        value=f"**Post age:** last {server_config.post_due_date} days\n"
              + "\n".join([
                  _toggle(server_config.include_author_in_reaction_calculation,
                          "Author's own reaction counts"),
                  _toggle(server_config.ignore_bot_messages, "Ignore messages from bots"),
                  _toggle(server_config.require_image_or_video, "Only posts with an image or video"),
              ]),
        inline=False)

    embed.add_field(
        name="📋 Board behaviour",
        value="\n".join([
            _toggle(server_config.allow_messages_in_hof_channel,
                    "Members can chat in the board channel"),
            _toggle(server_config.hide_hof_post_below_threshold,
                    "Hide posts that drop below the threshold"),
        ]),
        inline=False)

    if server_config.custom_emoji_check_logic:
        embed.add_field(
            name="😀 Emoji whitelist · on",
            value=_whitelist_value(server_config.whitelisted_emojis),
            inline=False)
    else:
        embed.add_field(
            name="😀 Emoji whitelist · off",
            value=f"Every emoji counts. Restrict it with {command_refs.CUSTOM_EMOJI_CHECK_LOGIC}",
            inline=False)

    # Discord rejects an empty field name, so a zero-width space keeps the spacer without a heading
    embed.add_field(
        name="​",
        value=f"Change any setting with its own command · {command_refs.HELP}",
        inline=False)
    embed.set_footer(text=f"Hall of Fame {version.VERSION}")
    return embed


async def answer_bot_mention(message: discord.Message, bot_user, server_config) -> bool:
    """
    Answer a ping with the information card, when the bot is able and has not just answered.
    :param message: The message that pinged the bot
    :param bot_user: The bot's own user
    :param server_config: The server's configuration, or None when it has not been set up
    :return: True when something was sent
    """
    permissions = message.channel.permissions_for(message.guild.me)
    if not permissions.send_messages:
        return False

    if not recently_answered_mentions.add_if_absent(message.channel.id):
        return False

    if not permissions.embed_links:
        # Without this permission an embed is dropped silently, so the answer is given as text
        await message.channel.send(
            f"**Hall of Fame** turns your server's best moments into a highlight reel and credits "
            f"the members behind them. Use {command_refs.HELP} for the commands. "
            f"(Grant the bot the Embed Links permission for the full card.)")
        return True

    await message.channel.send(embed=build_bot_info_embed(message.guild, bot_user, server_config))
    return True
