class Server:
    hall_of_fame_channel_id: int
    guild_id: int
    reaction_threshold: int
    post_due_date: int
    sweep_limit: int
    sweep_limited: bool
    include_author_in_reaction_calculation: bool
    allow_messages_in_hof_channel: bool

    def __init__(self, hall_of_fame_channel_id: int, guild_id: int, reaction_threshold: int, post_due_date: int,
                 sweep_limit: int, sweep_limited: bool, include_author_in_reaction_calculation: bool, allow_messages_in_hof_channel: bool):
        self.hall_of_fame_channel_id = hall_of_fame_channel_id
        self.guild_id = guild_id
        self.reaction_threshold = reaction_threshold
        self.post_due_date = post_due_date
        self.sweep_limit = sweep_limit
        self.sweep_limited = sweep_limited
        self.include_author_in_reaction_calculation = include_author_in_reaction_calculation
        self.allow_messages_in_hof_channel = allow_messages_in_hof_channel