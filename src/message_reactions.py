import discord as discord
import main


def most_reacted_emoji(reactions: [discord.Reaction]) -> [discord.Reaction]:
    """
    Returns the reaction with the most reactions.
    :param reactions:
    :return:
    """
    server_config = main.production_db["server_configs"].find_one({"guild_id": int(reactions[0].message.guild.id)})
    custom_emoji_check_logic = server_config["custom_emoji_check_logic"]
    whited_listed_emojis = server_config["whitelisted_emojis"]

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
    server_config = main.production_db["server_configs"].find_one({"guild_id": int(reactions[0].message.guild.id)})

    custom_emoji_check_logic = server_config["custom_emoji_check_logic"]
    whited_listed_emojis = server_config["whitelisted_emojis"]
    include_author_in_threshold = server_config["include_author_in_reaction_calculation"]

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
    server_config = main.production_db["server_configs"].find_one({"guild_id": int(message.guild.id)})

    server_includes_author_in_threshold = server_config["include_author_in_reaction_calculation"]
    custom_emoji_check_logic = server_config["custom_emoji_check_logic"]
    whited_listed_emojis = server_config["whitelisted_emojis"]
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
    server_config = main.production_db["server_configs"].find_one({"guild_id": int(message.guild.id)})
    max_reaction_count = 0

    server_includes_author_in_threshold = server_config["include_author_in_reaction_calculation"]
    custom_emoji_check_logic = server_config["custom_emoji_check_logic"]
    whited_listed_emojis = server_config["whitelisted_emojis"]
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
    server_config = main.production_db["server_configs"].find_one({"guild_id": int(message.guild.id)})
    calculation_method = server_config["reaction_count_calculation_method"]

    if calculation_method == "total_reactions":
        return await total_reaction_count(message.reactions)
    elif calculation_method == "unique_users":
        return await unique_reactor_count(message)
    elif calculation_method == "most_reactions_on_emoji":
        return await most_reacted_emoji_from_message(message)
    else:
        return await most_reacted_emoji_from_message(message)
