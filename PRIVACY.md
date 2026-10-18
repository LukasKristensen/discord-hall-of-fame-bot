# Privacy Policy for Hall of Fame

Effective date: 18 October 2026

Hall of Fame is a Discord bot operated by Lukas Kristensen, Denmark, who is responsible for the data
described here. Contact: githublukas@gmail.com, or the
[Hall of Fame support server](https://discord.gg/r98WC5GHcn).

## 1. What the bot stores

- **Server settings:** the server ID, the Hall of Fame channel ID, your configuration, the date the bot
  joined, and monthly member counts.
- **Featured messages:** the IDs of the message, its channel and its author, its reaction count and
  time, and the ID of the bot's repost. The text, images and usernames are not stored in our database.
  The repost itself lives in your server's Hall of Fame channel on Discord.
- **Member statistics:** per-server totals and ranks for featured messages and reactions.
- **Totals across servers:** your posts, reactions, titles and badges added up across every server that
  uses the bot, worked out from the data above and shown at the bottom of your profile in any of those
  servers. They are numbers only, never a server name, server ID or message content. If you hide them
  with `/profile_privacy`, your user ID is stored with the date you hid them. Server admins can leave
  their server out of everyone's totals with `/count_in_global_profiles`.
- **Hall of Fame Wrapped:** yearly statistics per member, including most-used channels and emojis and
  which members react to each other's posts most often.
- **Not counted:** if you choose "Delete and stop counting me" on `/delete_my_data`, your user ID is
  stored with the date, so the bot remembers to leave you out of posts featured from then on.
- **Support:** feedback sent with `/feedback` and custom profile requests, delivered to a private
  developer channel on Discord.
- **Logs:** which commands were used, with the username and server name, posted to private developer
  channels on Discord for troubleshooting.

## 2. What the bot reads but does not store

To work, the bot reads reactions and the content and attachments of messages that reach the threshold,
so it can count them and repost them in the same server. Message content is not saved to our database.

When the bot joins a server, and whenever an admin runs `/check_setup`, it also reads the server's
channels, roles, channel permissions and member count, to find setup problems such as channels it
cannot see. The result is posted in that server and is not saved.

## 3. How the data is used

Only to provide the bot's features: posting to the Hall of Fame, leaderboards, profiles and Wrapped,
plus support and troubleshooting. Your totals across servers can be shown in any server with the bot, but only
as totals, so it does not reveal which servers you are in. Aggregated statistics that cannot identify anyone are used to improve
the bot. Data is never used for advertising, sold, used to track who people are or which servers they
are in, or used to train AI models. The legal basis is our legitimate interest in running the features a server has chosen to
use.

## 4. Who receives data

- Discord, which hosts all messages, reposts and log channels.
- Bot listing sites where the bot is listed, such as top.gg, which receive only the bot's server count
  and its public command list.
- Authorities, if the law requires it.

Nothing else is shared.

## 5. How long data is kept

- Removing the bot from a server immediately deletes that server's featured messages, member
  statistics, Wrapped data and settings. If the bot was offline when it was removed, Discord does not
  tell it, so the data is deleted once the server has been gone for 7 days and Discord confirms the bot
  no longer has access to it.
- Join and leave dates and monthly member counts are kept as anonymous server statistics.
- Your choice to hide your totals across servers is kept until you show it again or delete your data.
- Other data is kept while the bot is in the server, and deleted on request as described in section 6.
- `/delete_my_data` immediately deletes your member statistics, Wrapped data and privacy choice,
  removes you from other members' Wrapped, and removes your user ID from your featured messages. The
  reposts stay in each server's Hall of Fame channel, since they belong to that server, but are no
  longer linked to you. Messages of yours featured after that are stored again as usual, unless you
  choose "Delete and stop counting me". Then they can still be reposted to a server's Hall of Fame, but
  are stored without your user ID, until you run `/delete_my_data` again and choose to be counted again.

## 6. Your rights

- **See your data:** `/my_data` sends you a file with everything stored about you.
- **Delete your data:** `/delete_my_data` deletes it after you confirm, as described in section 5.
- **Object to being counted:** choose "Delete and stop counting me" on `/delete_my_data`, and the bot
  stops crediting posts to you from then on.
- **Hide your totals across servers:** `/profile_privacy`.

These three commands only answer you, and work in any server with the bot and in DMs once you add the
bot to your account.

You can also ask us to correct your data, limit or object to its use, or send it in a portable format,
by messaging us in the support server. Requests must come from your own Discord account so we know who
is asking; a request by email is answered with a request to confirm it there. We reply within 30 days.
Server admins can delete any repost from their Hall of Fame channel at any time.

You also have the right to complain to a data protection authority; in Denmark that is
[Datatilsynet](https://www.datatilsynet.dk).

## 7. Age

Discord requires users to be at least 13 years old, and so does this bot.

## 8. Security

The database is kept on an access-controlled machine, and the bot's credentials are never shared. No
system is perfectly secure, and we will tell affected users and Discord about any breach as required.

## 9. Changes

Changes are made to this file in the
[GitHub repository](https://github.com/LukasKristensen/discord-hall-of-fame-bot), where its history
shows every earlier version. The effective date above is updated with each change, and significant
changes are announced in the support server.
