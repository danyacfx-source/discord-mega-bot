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

## Quick chat-only setup without Client Secret (temporary option)

If you already have a valid Twitch IRC chat **user access token** for your
dedicated bot account, you can skip our OAuth wizard and Client Secret entirely.

For an easy token generator, a third-party option is
https://twitchtokengenerator.com/ → **Bot Chat Token**. Authenticate there as
your **bot** account; do not enter your own Twitch developer Client ID or
Client Secret. Use only the minimal IRC scopes `chat:read` and `chat:edit`.
This service is not Twitch-operated: only use it if you trust that external
OAuth application. Never share its generated access token in chat or GitHub.

Put the generated **Access Token** (not the refresh token) in the
existing server environment:

    TWITCH_CHANNELS=your_broadcaster_login
    TWITCH_BOT_LOGIN=your_bot_login
    TWITCH_CHAT_TOKEN=the_private_bot_user_access_token
    TWITCH_BOT_REFRESH_TOKEN=
    CHAT_COMMANDS_ENABLED=1

The IRC bot will validate that the token belongs to your bot login, has
`chat:read` and `chat:edit` scopes, and is not about to expire. It does not
need this token's Client ID to match the Twitch API app configured for the
broadcaster's stream tracking. Keep existing stream API Client ID/Secret
separate and unchanged.

**Limitation:** This manually supplied access token expires. Without a
bot refresh token and its associated app credentials, the bot cannot
renew it automatically. Repeat token authorization and update the server
secret when needed. For unattended long-term use, use the private local
authorization-code setup below.

## 2. Easiest private token setup (Python + your own browser)

The Twitch developer console shows **Client ID** and **Client Secret**, but it
does not directly give you a bot account **Refresh Token**.

Run this built-in helper on your **own computer with a browser** (Python 3.11+):

    python scripts/twitch_bot_oauth_setup.py

- In the developer console, set OAuth redirect URL exactly to
  `http://localhost:3000/callback` and choose a **Confidential** application.
- Enter your Twitch application Client ID, Client Secret and intended bot login.
- The helper opens the **official** Twitch OAuth consent page. Make sure the
  signed-in Twitch user is the *bot account*, not your broadcaster account.
- The helper only listens on `127.0.0.1:3000`, verifies OAuth state, exchanges
  the code directly with Twitch and validates the authenticated user and scopes.
- The resulting private credentials are written to
  `~/dendich_twitch_bot_credentials.env` (permissions 0600 on Unix).
  The helper never prints your credentials or uploads them to a third party.
- Copy the four values from this file into the **server** `.env`. Do not send
  that file through chat, screenshots, GitHub, or an unencrypted public link.
- If port 3000 is occupied, close the conflicting application and try again.
- If you already use the Twitch app for stream status, use the **same**
  Client ID and Client Secret rather than creating unrelated credentials.

The browser and helper must run on the *same computer*. The localhost
callback will not work if you launch the helper on a remote server and open
the Twitch URL on another device.

## 3. Edit server .env (do not commit)

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

## 4. Set public links

SOCIALS_DISCORD=<your real Discord invite URL>
SOCIALS_YOUTUBE=https://www.youtube.com/@Dendosich
SOCIALS_DONATE=<your real donation URL>

If the Discord link is absent, !discord explicitly reports that it is not set.

## 5. Commands

!discord, !youtube, !игра, !сигналы, !награды, !позывной,
!links, !uptime, !расписание, !пинг, !help.

Other existing stream chat commands also remain available. The !сигналы
command **does not** return users' Twitch channel-points balance: channel
points and the bot's independent chat-coin system are different currencies.
Twitch points are redeemed through Twitch's native reward interface.

## 6. Live rollout

- Restart the bot after the variables are configured.
- Test !пинг, !сигналы and !discord in the Twitch chat.
- Check the bot username of the reply.
- No credentials should appear in application logs.
- If the bot is silent, verify OAuth scopes, TWITCH_BOT_LOGIN, account
  moderation authorization, Twitch account status and server outbound network.
- Existing Twitch live status / Discord announcements are unaffected.

**Important:** do not put OAuth secrets into the admin panel's public fields.
