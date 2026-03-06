from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from twitch_earnings.config import Settings

if TYPE_CHECKING:
    from twitch_earnings.streamer import StreamerStats

app = typer.Typer(help="Twitch Daily Earnings Bot")
console = Console()


def _load_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        console.print("Copy .env.example to .env and fill in your credentials.")
        raise typer.Exit(1)


@app.command()
def start(channel: str = typer.Argument(help="Twitch channel name to track")) -> None:
    """Start the earnings tracking bot."""
    settings = _load_settings()

    console.print(
        Panel.fit(
            f"[bold green]Twitch Earnings Bot[/bold green]\n"
            f"Channel: [cyan]{channel}[/cyan]\n"
            f"Sub split: [yellow]{settings.sub_split_percent}%[/yellow] | "
            f"Ad CPM: [yellow]${settings.ad_cpm:.2f}[/yellow]",
            title="Starting",
        )
    )

    import twitchio
    from twitch_earnings.bot import EarningsBot

    twitchio.utils.setup_logging(level=20)  # INFO level

    async def run() -> None:
        bot = await EarningsBot.create(settings, channel)
        async with bot:
            await bot.start(with_adapter=False)
            await bot._adapter.run()
            # Keep alive forever (Ctrl+C to stop)
            await asyncio.Event().wait()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")


def _fetch_stream_start(settings: Settings, channel: str) -> datetime | None:
    """Fetch the current stream's started_at from the Twitch API."""
    from datetime import datetime

    import requests

    token = _get_app_token(settings)
    if not token:
        return None

    resp = requests.get(
        "https://api.twitch.tv/helix/streams",
        params={"user_login": channel.lower()},
        headers={
            "Client-ID": settings.twitch_client_id,
            "Authorization": f"Bearer {token}",
        },
    )
    if resp.status_code != 200:
        return None
    data = resp.json().get("data", [])
    if not data:
        return None

    started_str = data[0].get("started_at", "")
    if started_str:
        return datetime.fromisoformat(started_str.replace("Z", "+00:00"))
    return None


def _parse_irc_tags(tags_str: str) -> dict[str, str]:
    """Parse IRC tags string like '@key1=val1;key2=val2' into a dict."""
    tags: dict[str, str] = {}
    for tag in tags_str.lstrip("@").split(";"):
        if "=" in tag:
            k, v = tag.split("=", 1)
            tags[k] = v
    return tags


def _build_stats_panel(channel: str, stats: "StreamerStats") -> Panel:
    """Build the sticky top panel showing live stats."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    if stats.stream_started_at:
        elapsed = now - stats.stream_started_at
        h, rem = divmod(int(elapsed.total_seconds()), 3600)
        m = rem // 60
        stream_str = f"[green]LIVE[/green] {h}h {m}m"
    else:
        stream_str = "[dim]Offline[/dim]"

    tracking_elapsed = now - stats.tracking_since
    track_mins = int(tracking_elapsed.total_seconds() // 60)

    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column(style="green")
    table.add_row("Stream", stream_str)
    table.add_row("Subs (T1)", str(stats.subs_t1))
    table.add_row("Subs (T2)", str(stats.subs_t2))
    table.add_row("Subs (T3)", str(stats.subs_t3))
    table.add_row("Prime", str(stats.subs_prime))
    table.add_row("Gift Subs", str(stats.gift_subs))
    table.add_row("Total Subs", f"[bold]{stats.total_subs}[/bold]")
    table.add_row("Messages", f"{stats.messages:,}")
    table.add_row("Tracking", f"{track_mins}m")

    return Panel(
        table,
        title=f"[bold cyan]{channel}[/bold cyan] — Live Stats",
        border_style="green",
    )


@app.command()
def chat(channel: str = typer.Argument(help="Twitch channel to read chat from")) -> None:
    """Live-stream a channel's chat to the terminal via WebSocket with live stats."""
    import sys
    from datetime import datetime, timezone

    from twitch_earnings.streamer import StreamerStats

    stats = StreamerStats(name=channel.lower())

    settings = _load_settings()
    stream_started = _fetch_stream_start(settings, channel)
    if stream_started:
        stats.stream_started_at = stream_started

    HEADER_LINES = 4

    def print_header() -> None:
        """Overwrite the top lines with current stats using ANSI escape."""
        now = datetime.now(timezone.utc)
        if stats.stream_started_at:
            elapsed = now - stats.stream_started_at
            h, rem = divmod(int(elapsed.total_seconds()), 3600)
            m = rem // 60
            stream_str = f"LIVE {h}h{m}m"
        else:
            stream_str = "Offline"

        header = (
            f"\033[s"  # save cursor
            f"\033[1;1H"  # move to top-left
            f"\033[K\033[1;32m{channel}\033[0m | {stream_str} | "
            f"Subs: \033[1m{stats.total_subs}\033[0m "
            f"(T1:{stats.subs_t1} T2:{stats.subs_t2} T3:{stats.subs_t3} "
            f"Prime:{stats.subs_prime} Gift:{stats.gift_subs}) | "
            f"Msgs: {stats.messages:,}\r\n"
            f"\033[K\033[2m{'─' * 80}\033[0m\r\n"
            f"\033[u"  # restore cursor
        )
        sys.stdout.write(header)
        sys.stdout.flush()

    def handle_line(line: str) -> str | None:
        """Process IRC line, update stats, return display string or None."""
        if "PRIVMSG" in line:
            tags = {}
            if line.startswith("@"):
                tags_str, rest = line.split(" ", 1)
                tags = _parse_irc_tags(tags_str)
            else:
                rest = line

            parts = rest.split(" ", 3)
            if len(parts) >= 4:
                user = tags.get("display-name") or parts[0].split("!")[0].lstrip(":")
                msg = parts[3].lstrip(":")
                stats.messages += 1
                if "bits" in tags:
                    try:
                        stats.bits += int(tags["bits"])
                    except ValueError:
                        pass
                    return f"\033[1;35m💎 {user} cheered {tags['bits']} bits:\033[0m {msg}"
                return f"\033[1;36m{user}\033[0m: {msg}"

        elif "USERNOTICE" in line:
            tags = {}
            if line.startswith("@"):
                tags_str, rest = line.split(" ", 1)
                tags = _parse_irc_tags(tags_str)
            else:
                rest = line

            stats.process_usernotice(tags)
            system_msg = tags.get("system-msg", "").replace("\\s", " ")
            if system_msg:
                return f"\033[1;33m★ {system_msg}\033[0m"

        return None

    async def ws_loop() -> None:
        import websockets

        uri = "wss://irc-ws.chat.twitch.tv:443"
        async with websockets.connect(uri) as ws:
            await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
            await ws.send("NICK justinfan42069")
            await ws.send(f"JOIN #{channel.lower()}")

            # Set up scrolling region below header
            sys.stdout.write(f"\033[2J\033[1;1H")  # clear screen
            sys.stdout.write(f"\n" * HEADER_LINES)  # reserve header space
            sys.stdout.write(f"\033[{HEADER_LINES + 1};999r")  # scroll region
            sys.stdout.write(f"\033[{HEADER_LINES + 1};1H")  # move below header
            sys.stdout.flush()
            print_header()

            msg_count = 0
            while True:
                raw_msg = await ws.recv()
                # Process this frame + drain any queued frames
                frames = [raw_msg]
                while True:
                    try:
                        frames.append(await asyncio.wait_for(ws.recv(), timeout=0.01))
                    except (asyncio.TimeoutError, TimeoutError):
                        break

                for frame in frames:
                    for line in frame.split("\r\n"):
                        if not line:
                            continue
                        if line.startswith("PING"):
                            await ws.send("PONG :tmi.twitch.tv")
                            continue
                        output = handle_line(line)
                        if output:
                            sys.stdout.write(output + "\r\n")
                            msg_count += 1

                print_header()
                sys.stdout.flush()

    try:
        asyncio.run(ws_loop())
    except KeyboardInterrupt:
        pass
    # Reset scroll region and clean up
    sys.stdout.write("\033[r\033[999;1H\n")
    console.print("[yellow]Disconnected.[/yellow]")


def _get_app_token(settings: Settings) -> str | None:
    """Get a Twitch app access token."""
    import requests

    resp = requests.post(
        "https://id.twitch.tv/oauth2/token",
        data={
            "client_id": settings.twitch_client_id,
            "client_secret": settings.twitch_client_secret,
            "grant_type": "client_credentials",
        },
    )
    if resp.status_code != 200:
        return None
    return resp.json()["access_token"]


def _fetch_top_streams(settings: Settings, count: int) -> list[dict]:
    """Fetch top N live streams from Twitch API."""
    import requests

    token = _get_app_token(settings)
    if not token:
        return []

    streams = []
    cursor = None
    while len(streams) < count:
        params: dict = {"first": min(count - len(streams), 100)}
        if cursor:
            params["after"] = cursor
        resp = requests.get(
            "https://api.twitch.tv/helix/streams",
            params=params,
            headers={
                "Client-ID": settings.twitch_client_id,
                "Authorization": f"Bearer {token}",
            },
        )
        if resp.status_code != 200:
            break
        data = resp.json()
        streams.extend(data.get("data", []))
        cursor = data.get("pagination", {}).get("cursor")
        if not cursor:
            break

    return streams[:count]


@app.command()
def monitor(
    count: int = typer.Option(20, "--count", "-n", help="Number of top streams to monitor"),
) -> None:
    """Monitor top live streams and track subs in real-time. j/k to scroll, Enter for chat, Esc to go back."""
    import sys
    import termios
    import tty
    from datetime import datetime, timezone

    from rich.live import Live
    from rich.text import Text

    from twitch_earnings.streamer import StreamerStats

    settings = _load_settings()

    console.print(f"Fetching top {count} live streams...")
    streams_data = _fetch_top_streams(settings, count)
    if not streams_data:
        console.print("[red]Failed to fetch streams.[/red]")
        raise typer.Exit(1)

    all_stats: dict[str, StreamerStats] = {}
    for s in streams_data:
        name = s["user_login"].lower()
        started = None
        if s.get("started_at"):
            started = datetime.fromisoformat(s["started_at"].replace("Z", "+00:00"))
        all_stats[name] = StreamerStats(
            name=name,
            viewers=s.get("viewer_count", 0),
            game=s.get("game_name", ""),
            stream_started_at=started,
        )

    # Load persisted stats from SQLite
    from datetime import date as date_type

    from twitch_earnings.db import get_db, load_stats, save_stats

    db = get_db()
    today = date_type.today().isoformat()
    for name, stats in all_stats.items():
        saved = load_stats(db, name, today)
        if saved:
            stats.subs_t1 = saved["subs_t1"]
            stats.subs_t2 = saved["subs_t2"]
            stats.subs_t3 = saved["subs_t3"]
            stats.subs_prime = saved["subs_prime"]
            stats.gift_subs = saved["gift_subs"]
            stats.bits = saved["bits"]
            stats.messages = saved["messages"]

    channels = list(all_stats.keys())
    console.print(f"Connecting to {len(channels)} channels...")

    # UI state
    selected = 0
    scroll_offset = 0
    viewing_channel: str | None = None  # None = table view, str = chat detail view

    def get_sorted_stats() -> list[StreamerStats]:
        return sorted(
            all_stats.values(),
            key=lambda s: s.viewers,
            reverse=True,
        )

    def build_table() -> Table:
        nonlocal scroll_offset
        sorted_stats = get_sorted_stats()
        total = len(sorted_stats)

        # Viewport: show rows that fit on screen (approx terminal height - 6 for borders/header)
        import shutil
        term_h = shutil.get_terminal_size().lines
        visible_rows = max(term_h - 6, 10)

        # Keep selected row in view
        if selected < scroll_offset:
            scroll_offset = selected
        elif selected >= scroll_offset + visible_rows:
            scroll_offset = selected - visible_rows + 1

        window = sorted_stats[scroll_offset:scroll_offset + visible_rows]

        pos_str = f"{selected + 1}/{total}"
        table = Table(
            title=f"Live Stream Monitor  [dim]j/k: scroll | Enter: chat | q: quit | {pos_str}[/dim]",
            expand=True,
        )
        table.add_column("#", style="dim", width=3)
        table.add_column("Channel", width=18)
        table.add_column("Viewers", justify="right", width=9)
        table.add_column("Game", width=22, no_wrap=True)
        table.add_column("Subs", justify="right", style="green bold", width=5)
        table.add_column("T1", justify="right", width=4)
        table.add_column("T2", justify="right", width=4)
        table.add_column("T3", justify="right", width=4)
        table.add_column("Prime", justify="right", width=5)
        table.add_column("Gift", justify="right", width=5)
        table.add_column("Bits", justify="right", style="magenta", width=8)
        table.add_column("Msgs", justify="right", width=7)

        for i, s in enumerate(window):
            actual_idx = scroll_offset + i
            is_selected = actual_idx == selected
            style = "bold reverse" if is_selected else ""
            ch_style = "cyan bold reverse" if is_selected else "cyan bold"
            table.add_row(
                str(actual_idx + 1),
                Text(s.name, style=ch_style),
                f"{s.viewers:,}",
                s.game[:22] if s.game else "",
                str(s.total_subs),
                str(s.subs_t1),
                str(s.subs_t2),
                str(s.subs_t3),
                str(s.subs_prime),
                str(s.gift_subs),
                f"{s.bits:,}" if s.bits else "",
                f"{s.messages:,}",
                style=style,
            )
        return table

    def build_chat_view() -> Panel:
        assert viewing_channel is not None
        stats = all_stats[viewing_channel]

        now = datetime.now(timezone.utc)
        if stats.stream_started_at:
            elapsed = now - stats.stream_started_at
            h, rem = divmod(int(elapsed.total_seconds()), 3600)
            m = rem // 60
            live_str = f"LIVE {h}h{m}m"
        else:
            live_str = "Offline"

        header = Text()
        header.append(f"{stats.name}", style="bold cyan")
        header.append(f" | {live_str} | Viewers: {stats.viewers:,}")
        header.append(
            f" | Subs: {stats.total_subs} "
            f"(T1:{stats.subs_t1} T2:{stats.subs_t2} T3:{stats.subs_t3} "
            f"Prime:{stats.subs_prime} Gift:{stats.gift_subs})"
        )
        header.append(f" | Bits: {stats.bits:,}")
        header.append(f" | Msgs: {stats.messages:,}")
        header.append("\n")
        header.append("─" * 80, style="dim")
        header.append("\n")

        # Show chat log
        lines = list(stats.chat_log)[-50:]  # last 50
        for kind, user, text in lines:
            if kind == "sub":
                header.append(f"★ {text}\n", style="bold yellow")
            elif kind == "bits":
                header.append(f"💎 {user}: {text}\n", style="bold magenta")
            else:
                header.append(user, style="bold cyan")
                header.append(f": {text}\n")

        return Panel(
            header,
            title=f"[bold]{stats.name}[/bold] [dim]Esc: back[/dim]",
            border_style="green",
        )

    def build_view():
        if viewing_channel is not None:
            return build_chat_view()
        return build_table()

    def poll_key(fd: int) -> str:
        """Non-blocking read of a keypress. Returns empty string if nothing."""
        import select

        if not select.select([fd], [], [], 0)[0]:
            return ""
        ch = sys.stdin.read(1)
        # Drain escape sequences
        while select.select([fd], [], [], 0.005)[0]:
            ch += sys.stdin.read(1)
        return ch

    async def irc_listener() -> None:
        import websockets

        uri = "wss://irc-ws.chat.twitch.tv:443"
        async with websockets.connect(uri) as ws:
            await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
            await ws.send("NICK justinfan42069")
            for ch in channels:
                await ws.send(f"JOIN #{ch}")

            while True:
                raw_msg = await ws.recv()
                frames = [raw_msg]
                while True:
                    try:
                        frames.append(await asyncio.wait_for(ws.recv(), timeout=0.01))
                    except (asyncio.TimeoutError, TimeoutError):
                        break

                for frame in frames:
                    for line in frame.split("\r\n"):
                        if not line:
                            continue
                        if line.startswith("PING"):
                            await ws.send("PONG :tmi.twitch.tv")
                            continue

                        ch_name = None
                        if "PRIVMSG #" in line or "USERNOTICE #" in line:
                            try:
                                idx = line.index("#")
                                ch_name = line[idx + 1:].split(" ", 1)[0].split(":")[0].lower()
                            except (ValueError, IndexError):
                                pass

                        if not ch_name or ch_name not in all_stats:
                            continue

                        stats = all_stats[ch_name]

                        if "PRIVMSG" in line:
                            stats.messages += 1
                            tags = {}
                            if line.startswith("@"):
                                tags_str, rest = line.split(" ", 1)
                                tags = _parse_irc_tags(tags_str)
                            else:
                                rest = line
                            parts = rest.split(" ", 3)
                            if len(parts) >= 4:
                                user = tags.get("display-name") or parts[0].split("!")[0].lstrip(":")
                                msg = parts[3].lstrip(":")
                                # Track bits from cheer messages
                                if "bits" in tags:
                                    try:
                                        stats.bits += int(tags["bits"])
                                        stats.chat_log.append(("bits", user, f"{tags['bits']} bits - {msg}"))
                                    except ValueError:
                                        pass
                                else:
                                    stats.chat_log.append(("msg", user, msg))

                        elif "USERNOTICE" in line:
                            tags = {}
                            if line.startswith("@"):
                                tags_str = line.split(" ", 1)[0]
                                tags = _parse_irc_tags(tags_str)
                            stats.process_usernotice(tags)
                            stats.messages += 1
                            system_msg = tags.get("system-msg", "").replace("\\s", " ")
                            if system_msg:
                                stats.chat_log.append(("sub", "", system_msg))

    def flush_to_db() -> None:
        for name, stats in all_stats.items():
            save_stats(
                db, name, today,
                subs_t1=stats.subs_t1,
                subs_t2=stats.subs_t2,
                subs_t3=stats.subs_t3,
                subs_prime=stats.subs_prime,
                gift_subs=stats.gift_subs,
                bits=stats.bits,
                messages=stats.messages,
            )

    async def db_saver() -> None:
        while True:
            await asyncio.sleep(1)
            flush_to_db()

    async def run_monitor() -> None:
        nonlocal selected, viewing_channel

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)

        listener_task = asyncio.create_task(irc_listener())
        saver_task = asyncio.create_task(db_saver())

        FPS = 240
        frame_time = 1.0 / FPS

        with Live(build_view(), console=console, refresh_per_second=FPS, screen=True) as live:
            try:
                while True:
                    # Poll keys (non-blocking)
                    key = await asyncio.get_event_loop().run_in_executor(None, poll_key, fd)

                    if key:
                        if viewing_channel is None:
                            if key == "j":
                                selected = min(selected + 1, len(all_stats) - 1)
                            elif key == "k":
                                selected = max(selected - 1, 0)
                            elif key in ("\r", "\n"):
                                sorted_stats = get_sorted_stats()
                                if 0 <= selected < len(sorted_stats):
                                    viewing_channel = sorted_stats[selected].name
                            elif key == "q":
                                break
                        else:
                            if key.startswith("\x1b"):
                                viewing_channel = None
                            elif key == "q":
                                break

                    live.update(build_view())
                    await asyncio.sleep(frame_time)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                saver_task.cancel()
                listener_task.cancel()
                flush_to_db()

    try:
        asyncio.run(run_monitor())
    except KeyboardInterrupt:
        pass
    flush_to_db()
    db.close()
    console.print("[yellow]Disconnected. Stats saved.[/yellow]")


@app.command(name="auth-url")
def auth_url() -> None:
    """Print the OAuth authorization URL."""
    _load_settings()

    scopes = (
        "channel:read:subscriptions+bits:read+channel:read:ads"
        "+user:read:chat+user:write:chat+user:bot"
    )
    url = f"http://localhost:4343/oauth?scopes={scopes}"

    console.print(
        Panel.fit(
            f"[bold]1.[/bold] Start the bot: [cyan]twitch-earnings start[/cyan]\n"
            f"[bold]2.[/bold] Open this URL in your browser:\n"
            f"   [link={url}]{url}[/link]\n"
            f"[bold]3.[/bold] Authorize with Twitch\n"
            f"[bold]4.[/bold] Tokens will be saved automatically",
            title="OAuth Setup",
        )
    )


@app.command()
def status() -> None:
    """Show current configuration and token status."""
    settings = _load_settings()

    table = Table(title="Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    client_id = settings.twitch_client_id
    table.add_row(
        "Client ID",
        client_id[:8] + "..." if len(client_id) > 8 else client_id,
    )
    table.add_row("Bot Name", settings.twitch_bot_name)
    table.add_row("Sub Split", f"{settings.sub_split_percent}%")
    table.add_row("Ad CPM", f"${settings.ad_cpm:.2f}")
    console.print(table)

    tier_table = Table(title="Revenue Rates")
    tier_table.add_column("Tier")
    tier_table.add_column("Streamer Cut")
    labels = {"1000": "Tier 1", "2000": "Tier 2", "3000": "Tier 3"}
    for tier, rate in settings.tier_revenue.items():
        tier_table.add_row(labels[tier], f"${rate:.2f}")
    console.print(tier_table)

    token_file = Path(".tio.tokens.json")
    if token_file.exists():
        console.print("[green]Token file found[/green] (.tio.tokens.json)")
    else:
        console.print(
            "[yellow]No token file[/yellow] — run "
            "[cyan]twitch-earnings start[/cyan] then authorize via OAuth"
        )
