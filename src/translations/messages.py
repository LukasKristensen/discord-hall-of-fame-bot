# Strings for bot responses
BOT_PERMISSIONS_ERROR = "The bot does not have the required permissions to setup the server"
SERVER_ALREADY_SETUP = "The server is already set up"
CUSTOM_EMOJI_CHECK_DISABLED = (
    "Custom emoji check logic is not enabled for this server. "
    "Use </custom_emoji_check_logic:1358208382473076848> to enable it."
)
# /invite and /vote answer with link buttons, so the text says why to click and leaves the URL to the button
VOTE_MESSAGE = "Votes on top.gg help more servers find Hall of Fame. You can vote every 12 hours."
INVITE_URL = "https://discord.com/oauth2/authorize?client_id=1177041673352663070"
VOTE_URL = "https://top.gg/bot/1177041673352663070/vote"
SUPPORT_SERVER_URL = "https://discord.gg/r98WC5GHcn"
INVITE_BUTTON = "Add to a server"
VOTE_BUTTON = "Vote on top.gg"
SUPPORT_SERVER_BUTTON = "Support server"
# Footer on every Hall of Fame post: the brand only, since the board is the server's showcase and an ask on
# every post would read as an ad. The ask goes on replies a member asked for instead
POST_FOOTER = "Hall of Fame"
# Footers render plain text only, so the command is named rather than a clickable command_refs mention
INVITE_FOOTER = "Run a server? Add Hall of Fame with /invite"
# /user_profile and /leaderboard, whose figures come from the daily task
STATS_FOOTER = f"Updated every 24 hours · {INVITE_FOOTER}"
INVITE_MESSAGE = "Add Hall of Fame to another server you run. Need a hand setting it up? Ask in the support server."
NOT_AUTHORIZED = "You are not authorized to use this command, only for members with manage server permission"
DEV_NOT_AUTHORIZED = "You are not authorized to use this command, only for developers"
WHITELIST_CLEARED = "✅ Whitelist cleared. Every emoji counts toward the threshold again until one is added with {command}."
WHITELIST_ALREADY_EMPTY = "ℹ️ The whitelist is already empty."
WHITELIST_ADDED = "✅ {emoji} added to the whitelist ({count} in total)."
WHITELIST_ALREADY_EXISTS = "ℹ️ {emoji} is already in the whitelist."
WHITELIST_REMOVED = "✅ {emoji} removed from the whitelist ({count} left)."
WHITELIST_NOT_FOUND = "{emoji} is not in the whitelist. See the current list with {command}."
WHITELIST_FULL = "The whitelist is full at {limit} emojis. Remove one with {command} before adding another."
WHITELIST_EMPTY_NOTE = "\nThe whitelist is empty, so every emoji counts until one is added with {command}."
FAILED_SETUP_HOF = ("Failed to setup Hall Of Fame for server {serverName}.\n"
                    "This may be due to missing permissions, try re-inviting the bot with the correct permissions.\n"
                    "If the problem persists, please contact support. https://discord.gg/r98WC5GHcn\n"
                    "Want to setup the Hall Of Fame manually? Use the </set_hall_of_fame_channel:1393576242237804768> command.")
ERROR_SERVER_NOT_SETUP = ("The server is not set up yet. Try re-inviting the bot with the correct permissions it is "
                          "asking for in the server join message. Giving the permissions after the bot has joined will "
                          "not work.")
BOT_LOADING = "Please wait while the bot is loading..."
COMMAND_ON_COOLDOWN = "This command is on a daily cooldown. Please try again later."
SETTING_CHANGED = "✅ {label}: **{value}**"
SETTING_UNCHANGED = "ℹ️ {label} is already **{value}**, so nothing changed."
REACTION_THRESHOLD_NOTE = ("A message reaches the Hall of Fame once it has {threshold} reaction{plural}, "
                           "counted as: {method}.")
POST_DUE_DATE_NOTE = "Messages older than {days} day{plural} can no longer reach the Hall of Fame."
HOF_CHANNEL_SET = "✅ Hall of Fame channel set to {channel}."
HOF_CHANNEL_SET_ANNOUNCEMENT_FAILED = ("✅ Hall of Fame channel set to {channel}, but the bot could not post its "
                                       "announcement there. Check that it can send messages in the channel.")
# Posted in the channel the board moved to. A brand-new setup posts its own welcome instead
HOF_CHANNEL_MOVED_ANNOUNCEMENT = ("🏆 **This is now the Hall of Fame channel!** 🏆\n"
                                  "{user} moved the Hall of Fame here. Messages that reach **{threshold}** reactions "
                                  "will be reposted in this channel from now on.\n"
                                  "Change the threshold with {threshold_command} or see every setting with "
                                  "{config_command}.")
HOF_CHANNEL_UNCHANGED ="ℹ️ {channel} is already the Hall of Fame channel."
HOF_CHANNEL_MISSING_PERMISSIONS = ("Could not use {channel} as the Hall of Fame channel. The bot is missing these "
                                   "permissions there: ``{missing_permissions}``\n"
                                   "Grant them in the channel settings and run the command again.")
HOF_CHANNEL_SETUP_FAILED = ("Could not set up the Hall of Fame in {channel}. Check that the bot can see and post "
                            "in it, then try again. If it keeps failing, ask in the support server: "
                            "<https://discord.gg/r98WC5GHcn>")
PROFILE_BOT_USER = "Bots do not have a Hall of Fame profile."
# Sent for any command that fails in a way nothing more specific covers, so it must not assume the
# command was changing a setting
COMMAND_FAILED = ("Something went wrong while running this command. Please try again in a moment. If it keeps "
                  "happening, let us know in the support server: <https://discord.gg/r98WC5GHcn>")
GUILD_ONLY = "This command only works inside a server."
LEADERBOARD_NO_DATA = "The leaderboard is currently empty. Data updates every 24 hours, so please check back later."
PROFILE_NO_DATA = "No profile data is available for this user yet. Data is refreshed every 24 hours."
MISSING_HOF_CHANNEL_PERMISSIONS = ("The bot is missing the required permissions to post in {channel}.\n"
                                   "Update the channel permission for the bot to have: ``{missing_permissions}``\n"
                                   f"If the hall of channel does not exist, set it up using </set_hall_of_fame_channel:1393576242237804768> "
                                   "and ensure the bot has the required permissions.")
FAILED_TO_FIND_HOF_CHANNEL = (
    "Failed to find the Hall of Fame channel - Ensure the bot has access with "
    "``View Channel, Send Messages, and Read Message History`` permissions.\n"
    f"Set it up using </set_hall_of_fame_channel:1393576242237804768> if it doesn't exist.\n"
    "For further assistance, contact support: <https://discord.gg/r98WC5GHcn>"
)
