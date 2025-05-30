import discord as discord
import main


def most_reacted_emoji(reactions: [discord.Reaction]) -> [discord.Reaction]:
    """
    Returns the reaction with the most reactions.
    :param reactions:
    :return:
    """
    custom_emoji_check_logic = main.db_client[str(reactions[0].message.guild.id)]["server_config"].find_one({})["custom_emoji_check_logic"]
    whited_listed_emojis = main.db_client[str(reactions[0].message.guild.id)]["server_config"].find_one({})["whitelisted_emojis"]

    if custom_emoji_check_logic and len(whited_listed_emojis) > 0:
        corrected_reactions = []
        for reaction in reactions:
            if str(reaction.emoji) in str(whited_listed_emojis):
                corrected_reactions.append(reaction)
        reactions = corrected_reactions

    if len(reactions) == 1:
        return reactions
    if len(reactions) == 0:
        return []

    largest_num = reactions[0].count    
    biggest = [reactions[0]]

    for reaction in reactions[1:]:
        if reaction.count == largest_num:
            biggest.append(reaction)
        elif reaction.count > largest_num:
            biggest = [reaction]
            largest_num = reaction.count
    
    return biggest


async def total_reaction_count(reactions: [discord.Reaction]) -> int:
    """
    Returns the total number of reactions, taking into account the custom emoji check logic and whitelisted emojis.
    :param reactions:
    :return:
    """
    custom_emoji_check_logic = main.db_client[str(reactions[0].message.guild.id)]["server_config"].find_one({})["custom_emoji_check_logic"]
    whited_listed_emojis = main.db_client[str(reactions[0].message.guild.id)]["server_config"].find_one({})["whitelisted_emojis"]
    include_author_in_threshold = main.db_client[str(reactions[0].message.guild.id)]["server_config"].find_one({})["include_author_in_reaction_calculation"]

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


async def unique_reactor_count(message: discord.Message) -> int:
    """
    Returns the number of unique reactors for a message, excluding the author if configured.
    :param message:
    :return:
    """
    server_includes_author_in_threshold = main.db_client[str(message.guild.id)]["server_config"].find_one({})["include_author_in_reaction_calculation"]
    custom_emoji_check_logic = main.db_client[str(message.guild.id)]["server_config"].find_one({})["custom_emoji_check_logic"]
    whited_listed_emojis = main.db_client[str(message.guild.id)]["server_config"].find_one({})["whitelisted_emojis"]
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


async def most_reacted_emoji_from_message(message: discord.Message) -> [discord.Reaction]:
    """
    Returns the most reactions from the highest reacted emoji in a message.
    :param message:
    :return:
    """
    max_reaction_count = 0
    server_includes_author_in_threshold = main.db_client[str(message.guild.id)]["server_config"].find_one({})["include_author_in_reaction_calculation"]
    custom_emoji_check_logic = main.db_client[str(message.guild.id)]["server_config"].find_one({})["custom_emoji_check_logic"]
    whited_listed_emojis = main.db_client[str(message.guild.id)]["server_config"].find_one({})["whitelisted_emojis"]
    reactions = message.reactions

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


async def reaction_count(message) -> int:
    """
    Returns the reaction count of a message based on the server configuration.
    :param message:
    :return:
    """
    # Todo: Make a migration for all servers to set the reaction_count_calculation_method to "most_reactions_on_emoji"
    # Todo: Make the default calculation method "most_reactions_on_emoji" for new servers
    # Todo: Add the new field to the server_config collection
    calculation_method = main.db_client[str(message.guild.id)]["server_config"].find_one({})["reaction_count_calculation_method"]

    if calculation_method == "total_reactions":
        return await total_reaction_count(message.reactions)
    elif calculation_method == "unique_users":
        return await unique_reactor_count(most_reacted_emoji(message.reactions)[0])
    elif calculation_method == "most_reactions_on_emoji":
        return most_reacted_emoji_from_message(message)
    else:
        return most_reacted_emoji_from_message(message)
