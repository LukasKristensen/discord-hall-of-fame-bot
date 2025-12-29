import discord as discord
from enums import calculation_method_type
from repositories import server_config_repo

# todo: make this return either a single emoji or null
def most_reacted_emoji(reactions: list[discord.Reaction], guild_id, connection) -> discord.Reaction.emoji:
    """
    Returns the reaction with the most reactions.
    :param reactions:
    :param guild_id:
    :param connection:
    :return:
    """
    custom_emoji_check_logic = server_config_repo.get_parameter_value(connection, guild_id, "custom_emoji_check_logic")
    white_listed_emojis = server_config_repo.get_parameter_value(connection, guild_id, "whitelisted_emojis")

    if custom_emoji_check_logic and len(white_listed_emojis) > 0:
        corrected_reactions = []
        for reaction in reactions:
            if str(reaction.emoji) in str(white_listed_emojis):
                corrected_reactions.append(reaction)
        reactions = corrected_reactions

    if len(reactions) == 1:
        return reactions[0].emoji
    if len(reactions) == 0:
        return ""

    largest_num = reactions[0].count    
    biggest = reactions[0]

    for reaction in reactions[1:]:
        if reaction.count > largest_num:
            biggest = reaction
            largest_num = reaction.count
    
    return biggest.emoji


async def total_reaction_count(message: discord.Message, guild_id, connection) -> int:
    """
    Returns the total number of reactions, taking into account the custom emoji check logic and whitelisted emojis.
    :param message:
    :param guild_id:
    :param connection:
    :return:
    """
    custom_emoji_check_logic = server_config_repo.get_parameter_value(connection, guild_id, "custom_emoji_check_logic")
    whited_listed_emojis = server_config_repo.get_parameter_value(connection, guild_id, "whitelisted_emojis")
    include_author_in_threshold = server_config_repo.get_parameter_value(connection, guild_id, "include_author_in_reaction_calculation")
    reactions = message.reactions

    if custom_emoji_check_logic and len(whited_listed_emojis) > 0:
        corrected_reactions = []
        for reaction in reactions:
            if str(reaction.emoji) in str(whited_listed_emojis):
                corrected_reactions.append(reaction)
        reactions = corrected_reactions

    total_count = 0
    for reaction in reactions:
        react_count = reaction.count
        users_ids = [user.id async for user in reaction.users()]
        if not include_author_in_threshold and reactions[0].message.author.id in users_ids:
            continue
        total_count += react_count

    return total_count


async def unique_reactor_count(message: discord.Message, connection) -> int:
    """
    Returns the number of unique reactors for a message, excluding the author if configured.
    :param message:
    :param connection:
    :return:
    """
    server_includes_author_in_threshold = server_config_repo.get_parameter_value(connection, message.guild.id, "include_author_in_reaction_calculation")
    custom_emoji_check_logic = server_config_repo.get_parameter_value(connection, message.guild.id, "custom_emoji_check_logic")
    whited_listed_emojis = server_config_repo.get_parameter_value(connection, message.guild.id, "whitelisted_emojis")
    reactions = message.reactions

    if custom_emoji_check_logic and len(whited_listed_emojis) > 0:
        corrected_reactions = []
        for reaction in reactions:
            if str(reaction.emoji) in str(whited_listed_emojis):
                corrected_reactions.append(reaction)
        reactions = corrected_reactions

    unique_users = set()
    for reaction in reactions:
        users_ids = [user.id async for user in reaction.users()]
        if not server_includes_author_in_threshold and message.author.id in users_ids:
            users_ids.remove(message.author.id)
        unique_users.update(users_ids)
    return len(unique_users)


async def most_reacted_emoji_from_message(message: discord.Message, connection) -> int:
    """
    Returns the most reactions from the highest reacted emoji in a message.
    :param message:
    :param connection:
    :return:
    """
    server_includes_author_in_threshold = server_config_repo.get_parameter_value(connection, message.guild.id, "include_author_in_reaction_calculation")
    custom_emoji_check_logic = server_config_repo.get_parameter_value(connection, message.guild.id, "custom_emoji_check_logic")
    whited_listed_emojis = server_config_repo.get_parameter_value(connection, message.guild.id, "whitelisted_emojis")
    reactions = message.reactions
    max_reaction_count = 0

    if custom_emoji_check_logic and len(whited_listed_emojis) > 0:
        corrected_reactions = []
        for reaction in reactions:
            if str(reaction.emoji) in str(whited_listed_emojis):
                corrected_reactions.append(reaction)
        reactions = corrected_reactions

    if len(reactions) == 0:
        return 0

    for reaction in reactions:
        react_count = reaction.count

        users_ids = [user.id async for user in reaction.users()]
        if not server_includes_author_in_threshold:
            react_count = react_count-1 if message.author.id in users_ids else react_count
        max_reaction_count = react_count if react_count > max_reaction_count else max_reaction_count

    return max_reaction_count


async def reaction_count(message, connection) -> int:
    """
    Returns the reaction count of a message based on the server configuration.
    :param message:
    :param connection:
    :return:
    """
    calculation_method = server_config_repo.get_parameter_value(connection, message.guild.id, "reaction_count_calculation_method")

    if calculation_method == calculation_method_type.TOTAL_REACTIONS:
        return await total_reaction_count(message, message.guild.id, connection)
    elif calculation_method == calculation_method_type.UNIQUE_USERS:
        return await unique_reactor_count(message, connection)
    elif calculation_method == calculation_method_type.MOST_REACTIONS_ON_EMOJI:
        return await most_reacted_emoji_from_message(message, connection)
    else:
        return await most_reacted_emoji_from_message(message, connection)
