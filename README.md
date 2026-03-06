# Twitch Daily Earnings

Real-time Twitch stream monitor that tracks subs, bits, and chat across multiple channels via IRC WebSocket. Stats are persisted to a local SQLite database.

## Features

- **`monitor`** — Live dashboard of top N streams with sub/bit/message tracking
  - j/k to scroll, Enter to view a channel's chat, Esc to go back, q to quit
  - Tracks T1/T2/T3/Prime/Gift subs and bits from IRC USERNOTICE + PRIVMSG tags
  - Stats persist to SQLite — restart without losing data
- **`chat`** — Stream a single channel's chat to your terminal
- **`start`** — Run a chat bot on your own channel that responds to `!todaysearnings`
  - Tracks your subs/bits/ads via EventSub WebSocket with real data from your own OAuth token

## Setup

```bash
# Clone and install
git clone <repo-url>
cd twitch-daily-earnings
uv sync

# Create .env from template
cp .env.example .env
# Fill in your Twitch app credentials from https://dev.twitch.tv/console
```

### Twitch App Registration

1. Go to https://dev.twitch.tv/console
2. Register a new application
3. Set OAuth Redirect URL to `http://localhost:4343/oauth/callback`
4. Category: Chat Bot, Client Type: Confidential
5. Copy Client ID and Client Secret to `.env`

## Usage

### Monitor top streams (main command, no auth needed)

```bash
uv run twitch-earnings monitor -n 100
```

### Watch a single channel's chat

```bash
uv run twitch-earnings chat supertf
```

### Run the earnings bot on your channel

```bash
# Start the bot (will prompt for OAuth on first run)
uv run twitch-earnings start yourchannelname

# Then type !todaysearnings in your Twitch chat
```

### Other commands

```bash
# Show current config
uv run twitch-earnings status

# Print OAuth URL
uv run twitch-earnings auth-url
```

## How It Works

### Sub/Bit Tracking for Other Channels

Connects anonymously to Twitch IRC (`justinfan`) via WebSocket (`wss://irc-ws.chat.twitch.tv`) and parses:
- **USERNOTICE** messages for subs, resubs, gift subs, mystery gifts (with tier from `msg-param-sub-plan`)
- **PRIVMSG** `bits` tag for cheer amounts

This is the same method services like TwitchTracker use. Limitations:
- Only tracks events while the monitor is running
- Offline subs and silent auto-renewals are invisible
- Can't see another channel's actual sub count or revenue (requires their OAuth token)

### Your Own Channel

Uses twitchio 3.x EventSub WebSocket with your OAuth token to get real sub/bit/ad data.

## Data

Stats are saved to `twitch_earnings.db` (SQLite) keyed by `(channel, date)`. The database is included in the repo for data sharing.

## Tech Stack

- **twitchio 3.x** — EventSub WebSocket for your own channel's bot
- **websockets** — Anonymous IRC WebSocket for monitoring other channels
- **typer + rich** — CLI and terminal UI
- **SQLite** — Local persistence with WAL mode
- **pydantic-settings** — Config from `.env`
