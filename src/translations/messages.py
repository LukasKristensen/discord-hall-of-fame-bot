# Strings for bot responses
BOT_PERMISSIONS_ERROR = "The bot does not have the required permissions to setup the server"
SERVER_ALREADY_SETUP = "The server is already set up"
CUSTOM_EMOJI_CHECK_DISABLED = (
    "Custom emoji check logic is not enabled for this server. "
    "Use </custom_emoji_check_logic:1358208382473076848> to enable it."
)
# /invite and /vote answer with link buttons, so the text says why to click and leaves the URL to the button
VOTE_MESSAGE = "Votes on top.gg help more servers find Hall of Fame. You can vote every 12 hours."
# The permissions the bot uses, asked for up front since granting them after the install does not
# work: View Channel, Send Messages, Read Message History, Embed Links, Use External Emojis (the
# leaderboard emojis), Manage Messages (chat in the board channel), Manage Channels and Manage Roles
# (creating the board channel and setting its overwrites), Send Messages in Threads (answering a ping
# inside a thread). Attach Files and Add Reactions are not used yet, but are asked for now so later
# features such as image cards work on servers that install today. tests/test_commands.py checks the value.
INVITE_PERMISSIONS = 275146730576
# integration_type=0 installs to a server, so the link keeps working if user installs are added
INVITE_URL = ("https://discord.com/oauth2/authorize?client_id=1177041673352663070"
              f"&permissions={INVITE_PERMISSIONS}&integration_type=0&scope=bot+applications.commands")
# integration_type=1 adds the bot to a member's own account, which offers the commands that need no server
# set up (see USER_INSTALL in main.py) in DMs and in servers without Hall of Fame
USER_INSTALL_URL = ("https://discord.com/oauth2/authorize?client_id=1177041673352663070"
                    "&integration_type=1&scope=applications.commands")
VOTE_URL = "https://top.gg/bot/1177041673352663070/vote"
SUPPORT_SERVER_URL = "https://discord.gg/r98WC5GHcn"
INVITE_BUTTON = "Add to a server"
USER_INSTALL_BUTTON = "Add to your account"
VOTE_BUTTON = "Vote on top.gg"
SUPPORT_SERVER_BUTTON = "Support server"
# Footer on every Hall of Fame post: the brand only, since the board is the server's showcase and an ask on
# every post would read as an ad. The ask goes on replies a member asked for instead
POST_FOOTER = "Hall of Fame"
# Footers render plain text only, so the command is named rather than a clickable command_refs mention
INVITE_FOOTER = "Run a server? Add Hall of Fame with /invite"
# /user_profile and /leaderboard, whose figures come from the daily task
STATS_FOOTER = f"Updated every 24 hours · {INVITE_FOOTER}"
PATCH_NOTES_URL = "https://discord.gg/GmFtfySetp"
# The bot's App Directory page. Opens its profile with an Add App button, and is a third the length of
# INVITE_URL, which reads as noise wherever the raw link is shown
APP_DIRECTORY_URL = "https://discord.com/discovery/applications/1177041673352663070"
# Topic of the board channel, shown to everyone who opens it. The install link goes first, since the
# channel header only shows the start of a long topic
HOF_CHANNEL_TOPIC = (f"The best moments of this server, picked by your reactions. Add Hall of Fame to your own "
                     f"server: {APP_DIRECTORY_URL} · Patch notes: {PATCH_NOTES_URL}")
# Topics the bot set itself in earlier versions, written out in full rather than built from the
# constants above, so a later change to those cannot hide an old topic. A board whose topic is still
# one of these is moved to HOF_CHANNEL_TOPIC, while a topic an admin wrote is never touched
LEGACY_HOF_CHANNEL_TOPICS = (
    "Patch notes for Hall Of Fame: https://discord.gg/GmFtfySetp",
    "The best moments of this server, picked by your reactions. Want one in your own server? Add Hall of Fame: "
    "https://discord.com/oauth2/authorize?client_id=1177041673352663070&permissions=275146730576"
    "&integration_type=0&scope=bot+applications.commands · Patch notes: https://discord.gg/GmFtfySetp",
)
INVITE_MESSAGE = ("Add Hall of Fame to a server you run, or to your account to see your own profile and data "
                  "anywhere, DMs included. Need a hand setting it up? Ask in the support server.")
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
FEEDBACK_ON_COOLDOWN = ("You have sent {limit} pieces of feedback today, the most allowed in a day. Try again "
                        "tomorrow, or ask in the support server: <https://discord.gg/r98WC5GHcn>")
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
COMMAND_NOT_IN_CLOSED_BOARD = "{channel} is kept for Hall of Fame posts only, so use this command in another channel."

# The section at the bottom of /user_profile with a member's totals across every server. Totals only:
# no server name, server ID or message content is ever shown
GLOBAL_PROFILE_HEADING = "🌍 Every server"
# The highlights under the profile columns. Each line is left out when there is nothing for it
HIGHLIGHTS_HEADING = "✨ Highlights"
HIGHLIGHT_BEST_POST = "🔥 Best post: {reactions} · [Jump to it]({url})"
HIGHLIGHT_LAST_FEATURED = "📅 Last featured {timestamp}"
HIGHLIGHT_BEHIND = "🎯 {posts} behind #{rank} {period}"
HIGHLIGHT_LEVEL_WITH = "🎯 Level with #{rank} {period}"
HIGHLIGHT_LEADING = "🎯 Leading {period} by {posts}"
HIGHLIGHT_SHARING_FIRST = "🎯 Sharing first place {period}"
# The badges field on /user_profile, one line of the badges a member has earned. A badge about other
# servers says how many, never which
BADGES_HEADING = "🏅 Badges"
BADGE_MONTHLY_CHAMPION = "🥇 Monthly champion"
BADGE_POSTS = "📈 {posts} posts"
BADGE_STREAK = "🔥 {months} months in a row"
BADGE_VETERAN = "🎂 Featured for a year"
BADGE_BIG_POST = "💯 100-reaction post"
BADGE_BIG_MONTH = "📅 10 posts in one month"
BADGE_SERVERS = "🌐 Featured in {servers} servers"
# Replaces STATS_FOOTER when the every-server column is shown, so the card carries one ask, not two
GLOBAL_STATS_FOOTER = "Updated every 24 hours · Only servers with Hall of Fame count · Add it to yours with /invite"
GLOBAL_PROFILE_COUNTING_ON_NOTE = ("Members' totals across servers include their posts from this server. The server itself "
                                   "is never named.")
GLOBAL_PROFILE_COUNTING_OFF_NOTE = ("Posts from this server no longer count toward anyone's totals across servers. Profiles "
                                    "inside this server are unchanged.")

# /my_data and its buttons, answered privately to the member who asked
PRIVACY_POLICY_URL = "https://github.com/LukasKristensen/discord-hall-of-fame-bot/blob/main/PRIVACY.md"
MY_DATA_STORED = ("📦 Hall of Fame stores {posts} featured post{posts_plural}, your standing in {servers} "
                  "server{servers_plural} and {wrapped} Wrapped entr{wrapped_plural} about you.")
# Also shown right after a deletion, when posts of the member's are still on boards, so it must not say
# that nothing of theirs was ever featured. It names what is not stored rather than saying nothing is,
# since a member's choices, such as not being featured, are stored and listed below it
MY_DATA_NOTHING_STORED = "📦 No posts, server standings or Wrapped entries are stored about you."
MY_DATA_TOTALS_SHOWN = "🌍 Your totals across servers are shown on your profile."
MY_DATA_TOTALS_SHOWN_ONCE_FEATURED = "🌍 Once you are featured, your totals across servers are shown on your profile."
MY_DATA_TOTALS_HIDDEN = ("🔒 Your totals across servers are hidden, so your profile shows only the numbers from the "
                         "server it is looked up in. Hall of Fame keeps your user ID and the date you hid them "
                         "({since}) to remember this.")
MY_DATA_NOT_FEATURED = ("🚫 You asked not to be featured, so your messages are not reposted to any board or stored, "
                        "and you are on no leaderboard, profile or Wrapped. Hall of Fame keeps only your user ID and "
                        "the date you asked ({since}), since without them it would have no way to know that your "
                        "future messages should be left out. **Feature me again** deletes them, and your messages "
                        "can be featured from then on.")
MY_DATA_FOOTER = ("Message text, images and your username are never stored. "
                  "Privacy policy: <" + PRIVACY_POLICY_URL + ">")
MY_DATA_DOWNLOAD_BUTTON = "Download my data"
HIDE_TOTALS_BUTTON = "Hide my totals across servers"
SHOW_TOTALS_BUTTON = "Show my totals across servers"
MY_DATA_EXPORT = "Everything Hall of Fame stores about you is in the attached file."
MY_DATA_DOWNLOAD_ON_COOLDOWN = "You already downloaded your data today. You can download it again tomorrow."
MY_DATA_DELETE_ON_COOLDOWN = "You already deleted your data today. You can delete it again tomorrow."
MY_DATA_NOT_YOURS = "Only the member who ran this command can use these buttons."
DELETE_MY_DATA_CONFIRM = ("Here is what happens when you delete your data. You are taken off every member "
                          "leaderboard, profile and Wrapped, in every server, and this cannot be undone. Your posts "
                          "stay on the boards, since they belong to those servers, but they are no longer credited to "
                          "you. If you hid your totals across servers, that choice is deleted too.\n\n"
                          "If you choose **Delete my data**, nothing about you is kept, and your messages can be "
                          "featured again in the future.\n\n"
                          "If you choose **Delete existing data, but keep a preference that I opted out of being "
                          "featured**, we keep just your user ID and the date, because otherwise the bot would have no "
                          "way to know it should skip your messages. Change your mind any time with **Feature me "
                          "again** on {command}.")
DELETE_MY_DATA_BUTTON = "Delete my data"
DELETE_AND_STOP_BUTTON = "Delete existing data, but keep a preference that I opted out of being featured"
DELETE_MY_DATA_DONE_STOPPED = ("✅ Your data is deleted, and your messages are not featured from now on: the bot "
                               "does not repost or store them. Posts already on a board stay there, no longer "
                               "credited to you. Run {command} to be featured again.")
FEATURE_ME_AGAIN_BUTTON = "Feature me again"
COUNTED_AGAIN = ("✅ Your messages can be featured again from now on. Posts from before you deleted your data "
                 "stay uncredited.")
CANCEL_BUTTON = "Cancel"
DELETE_MY_DATA_DONE = ("✅ Your data is deleted. You are no longer on any leaderboard, profile or Wrapped. To have "
                       "a repost removed from a board, ask that server's admins.")
DELETE_MY_DATA_CANCELLED = "Nothing was deleted."
DELETE_MY_DATA_EXPIRED = "This confirmation expired and nothing was deleted. Run {command} again to delete your data."
# Sent for any command that fails in a way nothing more specific covers, so it must not assume the
# command was changing a setting
COMMAND_FAILED = ("Something went wrong while running this command. Please try again in a moment. If it keeps "
                  "happening, let us know in the support server: <https://discord.gg/r98WC5GHcn>")
GUILD_ONLY = "This command only works inside a server."
LEADERBOARD_NO_DATA = "The leaderboard is currently empty. Data updates every 24 hours, so please check back later."
PROFILE_NO_DATA = "No profile data is available for this user yet. Data is refreshed every 24 hours."
# /user_profile through a user install, in a DM or a server without Hall of Fame. There is no server to rank
# the member in, so the card has their totals across servers alone, and only for the member who asked
PROFILE_EVERY_SERVER_DESCRIPTION = ("Your totals across every server with Hall of Fame. Use {command} in one of "
                                    "them to see your standing there too.")
PROFILE_OTHERS_OUTSIDE_SERVER = ("Outside a server with Hall of Fame you can only look up your own profile. "
                                 "Run {command} without a member to see yours.")
PROFILE_NOTHING_OUTSIDE_SERVER = ("You have no Hall of Fame posts yet in any server with Hall of Fame. "
                                  "Totals update every 24 hours.")
PROFILE_HIDDEN_OUTSIDE_SERVER_SELF = ("Your totals across servers are hidden, so there is nothing to show outside "
                                      "a server with Hall of Fame. Show them again from {command}.")
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

# The bot's status, shown in turn. Command mentions do not render in a status, so commands are plain
# text, and each stays within the 128 characters Discord shows
PRESENCE_MEMBER_COUNT = "🏆 Hall of Fame - {members:,} users"
PRESENCE_STATUSES = [
    "➕ /invite to add Hall of Fame to your server",
    "📊 /leaderboard - who rules your server?",
]
# Joins the statuses only in Wrapped season, December and January
PRESENCE_WRAPPED = "✨ /hof_wrapped - your year on the board"

# /check_setup, the Check setup button on the welcome message, and the report sent when the bot joins
CHECK_SETUP_BUTTON = "Check setup"
CHECK_TITLE = "🩺 Hall of Fame setup check"
# Posted in the board on join instead of the findings themselves, as everyone can read the board
CHECK_JOIN_NUDGE = ("⚠️ **Something may stop messages from reaching the Hall of Fame**, for example channels "
                    "the bot cannot read. An admin can press **Check setup** below, or run {command}, to see "
                    "what it is and how to fix it.")
CHECK_SUMMARY_OK = "Everything the bot needs is in place."
CHECK_SUMMARY_PROBLEMS = "Found {count} thing{plural} that can stop messages from reaching the board."
CHECK_FOOTER = "Fixed something? Press Check setup or run /check_setup again."
CHECK_AND_MORE = " and {count} more"
CHECK_BOARD_MISSING_TITLE = "No board channel"
CHECK_BOARD_MISSING = ("The channel posts go to was deleted, or the bot can no longer see it. "
                       "Pick a channel with {command}.")
CHECK_BOARD_PERMISSIONS_TITLE = "The bot cannot post on the board"
CHECK_BOARD_PERMISSIONS = ("The bot is missing these permissions in {channel}: {missing}. "
                           "Grant them in the channel settings.")
CHECK_BOARD_OK_TITLE = "Board"
CHECK_BOARD_OK = "Posting to {channel}."
CHECK_BOARD_CLEANUP_TITLE = "The bot cannot keep the board clean"
CHECK_BOARD_CLEANUP = ("Chat in {channel} is off, but the bot does not have Manage Messages there, so messages "
                       "members send stay. Grant it, or allow chat with {command}.")
CHECK_CHANNELS_TITLE = "Reads {readable} of {total} channels"
CHECK_CHANNELS_ALL = "Reactions in every channel can count."
CHECK_CHANNELS_BLOCKED = "Members can see these, but the bot cannot, so reactions there never count: {channels}"
CHECK_CHANNELS_ROLE_FIX = "Giving the bot the {role} role opens {opens} of these {total}."
CHECK_CHANNELS_FIX = "Give the bot View Channel and Read Message History in them, or the role that opens them."
CHECK_CHANNELS_PRIVATE = ("{count} more are hidden from regular members too, such as staff channels, so the bot "
                          "is likely left out of them on purpose: {channels}")
CHECK_CHANNELS_MOSTLY_CLOSED = ("The bot cannot read {channels}\n"
                                "No regular role can see them either, but that is most of the server. If messages "
                                "there should reach the board, give the bot View Channel and Read Message History "
                                "in them, or the role that opens them.")
CHECK_EMPTY_WHITELIST_TITLE = "No emoji can count"
CHECK_EMPTY_WHITELIST = ("Only whitelisted emojis count, and the whitelist is empty. Add one with {whitelist}, "
                         "or count every emoji with {logic}.")
CHECK_THRESHOLD_UNREACHABLE_TITLE = "The threshold is higher than the member count"
CHECK_THRESHOLD_UNREACHABLE = ("A message needs {threshold} reactions, but the server has {members} members, so "
                               "none can reach it. Lower it with {command}.")
CHECK_DAILY_LIMIT_TITLE = "Daily post limit reached"
CHECK_DAILY_LIMIT = "The board has had {limit} posts today, the most allowed in a day. Posting resumes at midnight UTC."
CHECK_NO_POSTS_TITLE = "No posts yet"
CHECK_NO_POSTS = ("No message has reached {threshold} reactions in the {days} days since the bot joined. "
                  "A lower threshold with {command} usually gets the board going.")
CHECK_NO_POSTS_YET_TITLE = "No posts yet"
CHECK_NO_POSTS_YET = "The bot joined recently. The first post appears once a message reaches the threshold."
CHECK_LAST_POST_TITLE = "Activity"
CHECK_LAST_POST = "Last post {when}, {total} in total."
CHECK_LAST_POST_STALE = "Nothing has reached the board in a month. If reactions are still coming in, try a lower threshold with {command}."
