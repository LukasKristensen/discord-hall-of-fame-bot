import discord as discord
from enums import calculation_method_type
from repositories import server_config_repo


def filter_whitelisted_reactions(reactions: list[discord.Reaction], config: dict) -> list[discord.Reaction]:
    """
    Keep only the reactions using a whitelisted emoji when the custom emoji check logic is enabled.
    :param reactions:
    :param config: The reaction related server configuration
    :return: The reactions that should be counted
    """
    if not config.get("custom_emoji_check_logic"):
        return reactions

    whitelisted_emojis = config.get("whitelisted_emojis") or []
    if len(whitelisted_emojis) == 0:
        return reactions

    whitelist = {str(emoji) for emoji in whitelisted_emojis}
    return [reaction for reaction in reactions if str(reaction.emoji) in whitelist]


async def author_has_reacted(reaction: discord.Reaction, author_id: int) -> bool:
    """
    Check whether the author of a message is among the users of a reaction.
    Only called when the author should be excluded, as it costs an API request per reaction.
    :param reaction:
    :param author_id:
    :return: True if the author reacted
    """
    async for user in reaction.users():
        if user.id == author_id:
            return True
    return False


# todo: make this return either a single emoji or null
def most_reacted_emoji(reactions: list[discord.Reaction], guild_id, connection, config: dict = None) -> discord.Reaction.emoji:
    """
    Returns the reaction with the most reactions.
    :param reactions:
    :param guild_id:
    :param connection:
    :param config: The reaction related server configuration, fetched when not supplied
    :return:
    """
    config = config if config is not None else server_config_repo.get_reaction_config(connection, guild_id)
    reactions = filter_whitelisted_reactions(reactions, config)

    if len(reactions) == 0:
        return ""
    if len(reactions) == 1:
        return reactions[0].emoji

    biggest = reactions[0]
    for reaction in reactions[1:]:
        if reaction.count > biggest.count:
            biggest = reaction

    return biggest.emoji


async def total_reaction_count(message: discord.Message, guild_id, connection, config: dict = None) -> int:
    """
    Returns the total number of reactions, taking into account the custom emoji check logic and whitelisted emojis.
    :param message:
    :param guild_id:
    :param connection:
    :param config: The reaction related server configuration, fetched when not supplied
    :return:
    """
    config = config if config is not None else server_config_repo.get_reaction_config(connection, guild_id)
    include_author_in_threshold = config.get("include_author_in_reaction_calculation")
    reactions = filter_whitelisted_reactions(message.reactions, config)

    total_count = 0
    for reaction in reactions:
        react_count = reaction.count
        if not include_author_in_threshold and await author_has_reacted(reaction, message.author.id):
            react_count -= 1
        total_count += react_count

    return total_count


async def unique_reactor_count(message: discord.Message, connection, config: dict = None) -> int:
    """
    Returns the number of unique reactors for a message, excluding the author if configured.
    :param message:
    :param connection:
    :param config: The reaction related server configuration, fetched when not supplied
    :return:
    """
    config = config if config is not None else server_config_repo.get_reaction_config(connection, message.guild.id)
    include_author_in_threshold = config.get("include_author_in_reaction_calculation")
    reactions = filter_whitelisted_reactions(message.reactions, config)

    unique_users = set()
    for reaction in reactions:
        async for user in reaction.users():
            if not include_author_in_threshold and user.id == message.author.id:
                continue
            unique_users.add(user.id)
    return len(unique_users)


async def most_reacted_emoji_from_message(message: discord.Message, connection, config: dict = None) -> int:
    """
    Returns the most reactions from the highest reacted emoji in a message.
    :param message:
    :param connection:
    :param config: The reaction related server configuration, fetched when not supplied
    :return:
    """
    config = config if config is not None else server_config_repo.get_reaction_config(connection, message.guild.id)
    include_author_in_threshold = config.get("include_author_in_reaction_calculation")
    reactions = filter_whitelisted_reactions(message.reactions, config)

    max_reaction_count = 0
    for reaction in reactions:
        react_count = reaction.count
        if not include_author_in_threshold and await author_has_reacted(reaction, message.author.id):
            react_count -= 1
        max_reaction_count = react_count if react_count > max_reaction_count else max_reaction_count

    return max_reaction_count


async def reaction_count(message, connection, config: dict = None) -> int:
    """
    Returns the reaction count of a message based on the server configuration.
    :param message:
    :param connection:
    :param config: The reaction related server configuration, fetched when not supplied
    :return:
    """
    config = config if config is not None else server_config_repo.get_reaction_config(connection, message.guild.id)
    calculation_method = config.get("reaction_count_calculation_method")

    if calculation_method == calculation_method_type.TOTAL_REACTIONS:
        return await total_reaction_count(message, message.guild.id, connection, config)
    if calculation_method == calculation_method_type.UNIQUE_USERS:
        return await unique_reactor_count(message, connection, config)
    return await most_reacted_emoji_from_message(message, connection, config)
