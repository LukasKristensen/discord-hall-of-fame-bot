from src.classes import Command_refs

AUTHOR_REACTION_INCLUDED = "Author's own reaction included in the reaction threshold: {include}"
BOT_PERMISSIONS_ERROR = "The bot does not have the required permissions to setup the server"
SERVER_ALREADY_SETUP = "The server is already set up"
CUSTOM_EMOJI_CHECK_DISABLED = (
    "Custom emoji check logic is not enabled for this server. "
    f"Use {Command_refs.CUSTOM_EMOJI_CHECK_LOGIC} to enable it."
)
INVALID_EMOJI_FORMAT = "Can only whitelist one emoji at a time"
VOTE_MESSAGE = "Vote for the bot on top.gg: https://top.gg/bot/1177041673352663070/vote"
INVITE_MESSAGE = "Invite the bot to your server: <https://discord.com/oauth2/authorize?client_id=1177041673352663070>"
NOT_AUTHORIZED = "You are not authorized to use this command, only for members with manage server permission"
DEV_NOT_AUTHORIZED = "You are not authorized to use this command, only for developers"
IGNORE_BOT_MESSAGES = "Ignore bot messages set to {should_ignore_bot_messages}"
POST_DUE_DATE_SET = "Post due date set to {post_due_date} days"
WHITELIST_CLEARED = "Whitelist cleared"
WHITELIST_ADDED = "Emoji {emoji} added to the whitelist"
WHITELIST_ALREADY_EXISTS = "Emoji {emoji} is already in the whitelist"
WHITELIST_REMOVED = "Emoji {emoji} removed from the whitelist"
WHITELIST_NOT_FOUND = "Emoji {emoji} is not in the whitelist"
ALLOW_POST_IN_HOF = "People are allowed to send messages in the Hall of Fame channel: {allow}"
SERVER_CONFIG = (
    "**Server Configuration:**\n"
    "```"
    "Reaction Threshold: {reaction_threshold}\n"
    f"Allow Messages in HOF Channel: {Command_refs.ALLOW_MESSAGES_IN_HOF_CHANNEL}\n"
    f"Include Author in Reaction Calculation: {Command_refs.INCLUDE_AUTHORS_REACTION}\n"
    f"Ignore Bot Messages: {Command_refs.IGNORE_BOT_MESSAGES}\n"
    f"Post Validity (How many days back a post is considered valid): {Command_refs.SET_POST_DUE_DATE}\n"
    f"Calculation Method: {Command_refs.CALCULATION_METHOD}\n"
    f"Hide hall of fame posts when they are below the threshold: {Command_refs.HIDE_HOF_POST_BELOW_THRESHOLD}\n"
    f"Custom Emoji Check Logic: {Command_refs.CUSTOM_EMOJI_CHECK_LOGIC}\n"
)
FAILED_SETUP_HOF = ("Failed to setup Hall Of Fame for server {serverName}.\n"
                    "This may be due to missing permissions, try re-inviting the bot with the correct permissions.\n"
                    "If the problem persists, please contact support. https://discord.gg/r98WC5GHcn\n"
                    f"Want to setup the Hall Of Fame manually? Use the {Command_refs.SET_HALL_OF_FAME_CHANNEL} command.")
ERROR_SERVER_NOT_SETUP = ("The server is not set up yet. Try re-inviting the bot with the correct permissions it is "
                          "asking for in the server join message. Giving the permissions after the bot has joined will "
                          "not work.")
BOT_LOADING = "Please wait while the bot is loading..."
COMMAND_ON_COOLDOWN = "This command is on a daily cooldown. Please try again later."
LEADERBOARD_NO_DATA = "The leaderboard is currently empty. Data updates every 24 hours, so please check back later."
PROFILE_NO_DATA = "No profile data is available for this user yet. Data is refreshed every 24 hours."
MISSING_HOF_CHANNEL_PERMISSIONS = ("The bot is missing the required permissions to post in {channel}.\n"
                                   "Update the channel permission for the bot to have: ``{missing_permissions}``\n"
                                   f"If the hall of channel does not exist, set it up using {Command_refs.SET_HALL_OF_FAME_CHANNEL} "
                                   "and ensure the bot has the required permissions.")
