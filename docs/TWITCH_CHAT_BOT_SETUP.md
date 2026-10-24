# DENDICH / RADIO SILENCE — Twitch chatbot

This is an extension of the existing Discord Mega Bot, **not** a second process.
It uses the existing stream chat command engine and Twitch IRC connector.
Twitch's current recommended approach for future chat integrations is EventSub
for reading and Helix for sending; IRC remains a compatibility transport here.

## 1. Create a dedicated bot account

1. Register a separate Twitch user account for the bot.
2. In the main streaming channel chat, enter /mod <bot_username>.
   Moderation permission is useful but **not a substitute for OAuth**.
3. Register/use a Twitch Developer application at https://dev.twitch.tv/console/apps.
4. Authorize the **bot account** (not broadcaster) via OAuth authorization-code flow
   and request the scopes **chat:read chat:edit** for this IRC integration.
5. Keep the client secret and refresh token privately on your server.
   Never paste them in Discord, ChatGPT, GitHub or screenshots.
   For authorization-code flow guidance:
   https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/

## 2. Edit server .env (do not commit)

TWITCH_CHANNELS=<broadcaster_login>
TWITCH_BOT_LOGIN=<bot_account_login>
TWITCH_CLIENT_ID=<twitch_application_client_id>
TWITCH_CLIENT_SECRET=<twitch_application_client_secret>
TWITCH_BOT_REFRESH_TOKEN=<bot_account_refresh_token>
CHAT_COMMANDS_ENABLED=1
CHAT_COMMAND_PREFIX=!

If these are set and the access token is valid, the bot connects, receives
messages and responds under TWITCH_BOT_LOGIN. Rotated OAuth refresh credentials
are automatically written to data/twitch_bot_oauth.json (mode 0600). Back up
this private file with the server's existing protected data directory.

Legacy TWITCH_CHAT_TOKEN is still supported for manual bot authorization,
but such access tokens expire. Prefer TWITCH_BOT_REFRESH_TOKEN.

## 3. Set public links

SOCIALS_DISCORD=<your real Discord invite URL>
SOCIALS_YOUTUBE=https://www.youtube.com/@Dendosich
SOCIALS_DONATE=<your real donation URL>

If the Discord link is absent, !discord explicitly reports that it is not set.

## 4. Commands

!discord, !youtube, !игра, !сигналы, !награды, !позывной,
!links, !uptime, !расписание, !пинг, !help.

Other existing stream chat commands also remain available. The !сигналы
command **does not** return users' Twitch channel-points balance: channel
points and the bot's independent chat-coin system are different currencies.
Twitch points are redeemed through Twitch's native reward interface.

## 5. Live rollout

- Restart the bot after the variables are configured.
- Test !пинг, !сигналы and !discord in the Twitch chat.
- Check the bot username of the reply.
- No credentials should appear in application logs.
- If the bot is silent, verify OAuth scopes, TWITCH_BOT_LOGIN, account
  moderation authorization, Twitch account status and server outbound network.
- Existing Twitch live status / Discord announcements are unaffected.

**Important:** do not put OAuth secrets into the admin panel's public fields.
