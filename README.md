# Discord Hall Of Fame Bot
The purpose of the bot is to monitor the maximum amount of message reactions and repost the message to a board if it surpasses a threshold value. Unlike star bots, this bot is not limited to one emoji but will prompt any emoji reactions.

<br>

## Configuring

Add the bot to your discord server: https://discord.com/oauth2/authorize?client_id=1177041673352663070

Join the Hall of Fame communit server: https://discord.gg/r98WC5GHcn

<br>

## Commands

| Command | Parameters | Action | Example |
| :------------- |:--------------------------|:----------------------------------------------------|:--------------------|
| /help | | List of commands | /help |
| /reaction_threshold_configure | <reaction_threshold:int> | Sets the Hall Of Fame reaction threshold for your server | /reaction_threshold_configure 5
| /manual_sweep | <sweep_limit> \<guild_id> | Manually trigger a server sweep | /manual_sweep 2000 1180006529575960616 |
| /get_random_message | | Get a random hall-of-fame message from the database | /get_random_message



<br>


## Development Log

### 1.11
- [x] Refactored code-base for cloud deployment and for handling multiple servers

### 1.10
- [x] Threshold increase and general adjustments

### 1.09
- [x] Hall Of Fame Wrapped]

### 1.08
- [x] Better context vísualization of replied messages
- [x] Added user's role color to embed color

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
