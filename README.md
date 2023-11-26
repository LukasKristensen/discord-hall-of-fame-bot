# Discord Hall Of Fame Bot
The purpose of the bot is to monitor the maximum amount of message reactions and repost the message to a board if it surpasses a threshold value. Unlike star bots, this bot is not limited to one emoji but will prompt any emoji reactions.

<br>

## Installing
Create an .env file containing the bot key:
```KEY:SECRET```

Install packages:
```pip install -r requirements.txt```

<br>

## Configuring
Define your Hall Of Fame channel by updating the ID to the discord channel: ```YOUR_DEDICATED_CHANNEL_ID```

Define the amount of reactions necessary for posting: ```reaction_threshold```

<br>

## Commands

| Command | Parameters (optional) | Action | Example |
| :------------- |:-------------|:-------------|:-------------|
| !commands | | List of commands | !commands |
| !favorite_gifs | <user_id> \<msg_limit:10> | Get a random hall-of-fame message from the database | !favorite_gifs 230698327589650432 5 |
| !server_gifs | \<msg_limit:10> | Get a random hall-of-fame message from the database | !server_gifs 7 |
| !get_random_message | | Get a random hall-of-fame message from the database |


<br>


## Development Log

### Features
- [ ] Gamebot: The user gets a hall-of-fame post and should guess if another post has more or less reactions
- [ ] Top 5 reacted posts
- [ ] Top 3 most used emojis
- [ ] Top 3 most used channel
- [x] Servers most used gifs
- [x] Users most used gifs
- [ ] Compare the statistics to the rest of the server (e.g. "you were top 3% of users using emoji" or channel)
- [ ] Come with more ideas here

### If bot should be invited to other servers
- [ ] Create a command for updating variable names
- [ ] Make a folder for each server with private value preferences
- [ ] Create and specify database configs for specific server


### 1.01
- [x] Problem with using discord user profile pictures using Discord<=2.0.0
- [x] Deploy on a remote server
- [x] Improve the embed layout of messages
- [x] Improve media output
- [x] Improve database structure to mongodb
- [x] Functionality for checking historical messages (it should run through all the messages and post the ones above the reaction value threshold
- [x] When posting the message highlight the reaction emoji from the original message
- [x] Fix message IDs not being saved/loaded correctly when validating if it has already been sent
- [x] Create a getRandom() function for grabbing a random hall-of-fame post

