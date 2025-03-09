import discord as discord
import main

def most_reactions(reactions: [discord.Reaction]) -> [discord.Reaction]:
    if len(reactions) == 1:
        return reactions

    largest_num = reactions[0].count    
    biggest = [reactions[0]]

    for reaction in reactions[1:]:
        if reaction.count == largest_num:
            biggest.append(reaction)
        elif reaction.count > largest_num:
            biggest = [reaction]
            largest_num = reaction.count
    
    return biggest


async def reaction_count_without_author(message):
    max_reaction_count = 0
    server_includes_author_in_threshold = main.db_client[str(message.guild.id)]["server_config"].find_one({})["include_author_in_reaction_calculation"]

    for reaction in message.reactions:
        react_count = reaction.count

        users_ids = [user.id async for user in reaction.users()]
        if not server_includes_author_in_threshold:
            react_count = react_count-1 if message.author.id in users_ids else react_count
        max_reaction_count = react_count if react_count > max_reaction_count else max_reaction_count

    return max_reaction_count
