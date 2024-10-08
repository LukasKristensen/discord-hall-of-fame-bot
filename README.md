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
| !favorite_gifs | <user_id> \<msg_limit:10> | Get the most popular gifs from a user | !favorite_gifs 230698327589650432 5 |
| !server_gifs | \<msg_limit:10> | Get the most popular gifs in the server | !server_gifs 7 |
| !get_random_message | | Get a random hall-of-fame message from the database |


<br>


## Development Log

### 1.07
- [x] Solved async simultaneous reacting on posts

### 1.06
- [x] LLM outlier detection of voting-based messages, which should not be classified as a Hall Of Fame message. 

### 1.05
- [x] Hall-of-fame posts which are replies to previous messages will include the context.

### 1.04
- [x] Only count non-author reactions towards the total amount for threshold
- [x] When a post goes below the threshold remove the embed, but keep the message so that it would be able to be reposted again

### 1.03
- [x] When the reaction counter goes up on an existing hall-of-fame post, it should update the message with the total amount of reactions
- [x] Remove incoming non-bot posts in the hall-of-fame channel

### 1.02
- [x] New gifs should be added to the user/server database as they get posted, instead of having to use the fetch command
- [x] Servers most used gifs
- [x] Users most used gifs


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

### Future
- [ ] Gamebot: The user gets a hall-of-fame post and should guess if another post has more or less reactions
- [ ] Refactor code to use the discord "interactions" library (enables the slash commands feature)
- [ ] Make youtube videos available for preview in the hall-of-fame messages e.g. by posting the link separately (domains: https://youtu.be and https://www.youtube.com)
- [ ] Sending a file-embed and a message-embed in the same message (makes it easier for referencing)

### If bot should be invited to other servers
- [ ] Create a command for updating variable names (restricted to user permissions)
- [ ] Make a folder for each server with private value preferences
- [ ] Create and specify database configs for specific server
- [ ] Command for disabling/enabling user posts in hall-of-fame

