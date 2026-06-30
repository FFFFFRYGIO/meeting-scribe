# Creating the Discord bot

You only need to do this once. At the end you'll have a `DISCORD_BOT_TOKEN` to
put in the app's environment.

## 1. Create the application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. **New Application** → give it a name (e.g. *Meeting Scribe*) → **Create**.

## 2. Create the bot user and copy the token

1. In the left sidebar open **Bot**.
2. Click **Reset Token** → **Copy**. This is your `DISCORD_BOT_TOKEN`.
   Keep it secret — anyone with it controls the bot.

## 3. Enable the required intents

Still on the **Bot** page, under **Privileged Gateway Intents**, turn on:

- **Message Content Intent** — so the bot can read the text after you @mention it.
- **Server Members Intent** — so it can resolve who spoke into participant names.

(The bot also uses voice state, which is a default intent — no toggle needed.)
Click **Save Changes**.

## 4. Invite the bot to your server

1. Left sidebar → **OAuth2** → **URL Generator**.
2. Under **Scopes**, check **bot**.
3. Under **Bot Permissions**, check:
   - **View Channels**
   - **Send Messages**
   - **Connect** (join voice channels)
   - **Speak** *(not strictly needed to record, but harmless)*
4. Copy the generated URL at the bottom, open it in a browser, pick your server,
   and **Authorize**.

You need **Manage Server** on the target server to add a bot. For testing, create
your own server (Discord → **+** → *Create My Own*) and a voice channel in it.

## 5. Wire up the token

Set the token where the app runs:

- Local: put it in `.env` as `DISCORD_BOT_TOKEN=...` (see `.env.example`).
- Coolify: add `DISCORD_BOT_TOKEN` as an environment variable on the service.

Restart the app. On startup you should see `Discord bot logged in as ...` in the
logs.

## 6. Use it

In a server text channel, with yourself connected to a voice channel:

| You type | The bot does |
|---|---|
| `@Meeting Scribe` | Joins your voice channel and starts recording |
| `@Meeting Scribe stop` | Stops, transcribes, summarises, and posts the summary |
| `@Meeting Scribe question what did we decide?` | Answers from the most recent meeting |
| `@Meeting Scribe question 2026-06-30 who owns the docs?` | Answers from the meeting on that date |

Everything also shows up in the web UI, where you can read full transcripts,
ask more questions, and tune what gets extracted.
