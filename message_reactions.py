import discord as discord

def most_reactions(reactions: [discord.Reaction]) -> [discord.Reaction]:
    if len(reactions) == 1:
        return reactions[0]

    largest_num = reactions[0].count    
    biggest = [reactions[0]]

    for reaction in reactions[1:]:
        if reaction.count == largest_num:
            biggest.append(reaction)
        elif reaction.count > largest_num:
            biggest = [reaction]
            largest_num = reaction.count
    
    return biggest


    


