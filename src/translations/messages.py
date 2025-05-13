# Strings for bot responses
AUTHOR_REACTION_INCLUDED = "Author's own reaction included in the reaction threshold: {include}"
BOT_PERMISSIONS_ERROR = "The bot does not have the required permissions to setup the server"
SERVER_ALREADY_SETUP = "The server is already set up"
CUSTOM_EMOJI_CHECK_DISABLED = (
    "Custom emoji check logic is not enabled for this server. "
    "Use </custom_emoji_check_logic:1358208382473076848> to enable it."
)
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
    "Allow Messages in HOF Channel: {allow_messages_in_hof_channel}\n"
    "Include Author in Reaction Calculation: {include_author_in_reaction_calculation}\n"
    "Ignore Bot Messages: {ignore_bot_messages}\n"
    "Post Validity (How many days back a post is considered valid): {post_due_date}\n"
    "Custom Emoji Check Logic: {custom_emoji_check_logic}\n"
)
FAILED_SETUP_HOF = ("Failed to setup Hall Of Fame for server {serverName}. This may be due to missing permissions, "
                    "try re-inviting the bot with the correct permissions. "
                    "If the problem persists, please contact support. https://discord.gg/awZ83mmGrJ")
