class Server:
    def __init__(self, hall_of_fame_channel_id: int, guild_id: int, reaction_threshold: int, post_due_date: int,
                 sweep_limit: int, sweep_limited: bool, include_author_in_reaction_calculation: bool,
                 allow_messages_in_hof_channel: bool, custom_emoji_check_logic: bool, whitelisted_emojis: list,
                 leaderboard_setup: bool, ignore_bot_messages: bool, reaction_count_calculation_method: str,
                 hide_hof_post_below_threshold: bool, leaderboard_message_ids: list, server_member_count: int,
                 require_image_or_video: bool):
        self.hall_of_fame_channel_id = hall_of_fame_channel_id
        self.guild_id = guild_id
        self.reaction_threshold = reaction_threshold
        self.post_due_date = post_due_date
        self.sweep_limit = sweep_limit
        self.sweep_limited = sweep_limited
        self.include_author_in_reaction_calculation = include_author_in_reaction_calculation
        self.allow_messages_in_hof_channel = allow_messages_in_hof_channel
        self.custom_emoji_check_logic = custom_emoji_check_logic
        self.whitelisted_emojis = whitelisted_emojis
        self.leaderboard_setup = leaderboard_setup
        self.leaderboard_message_ids = leaderboard_message_ids if leaderboard_message_ids is not None else []
        self.ignore_bot_messages = ignore_bot_messages
        self.reaction_count_calculation_method = reaction_count_calculation_method
        self.hide_hof_post_below_threshold = hide_hof_post_below_threshold
        self.server_member_count = server_member_count
        self.require_image_or_video = require_image_or_video

    def reaction_config(self) -> dict:
        """
        The configuration needed to count reactions, in the shape the reaction helpers expect.
        Served from memory so that the reaction event path does not query the database, and kept
        correct because every command that changes one of these values also updates this object.
        :return: The reaction related server configuration
        """
        return {
            "reaction_count_calculation_method": self.reaction_count_calculation_method,
            "include_author_in_reaction_calculation": self.include_author_in_reaction_calculation,
            "custom_emoji_check_logic": self.custom_emoji_check_logic,
            "whitelisted_emojis": self.whitelisted_emojis
        }


class ServerClass(Server):
    @staticmethod
    def from_row(row):
        return ServerClass(*row)
