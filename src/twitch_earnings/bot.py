from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import aiohttp
import twitchio
from twitchio import eventsub
from twitchio.ext import commands

from twitch_earnings.components.earnings import EarningsComponent
from twitch_earnings.config import Settings
from twitch_earnings.tracker import RevenueTracker

logger = logging.getLogger(__name__)


async def resolve_user_id(
    client_id: str, client_secret: str, username: str
) -> str:
    """Resolve a Twitch username to a numeric user ID using an app access token."""
    async with aiohttp.ClientSession() as session:
        # Get app access token
        resp = await session.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
        )
        token_data = await resp.json()
        token = token_data["access_token"]

        # Look up user
        resp = await session.get(
            "https://api.twitch.tv/helix/users",
            params={"login": username},
            headers={
                "Client-ID": client_id,
                "Authorization": f"Bearer {token}",
            },
        )
        data = await resp.json()
        if not data.get("data"):
            raise RuntimeError(f"Twitch user '{username}' not found")
        return data["data"][0]["id"]


class EarningsBot(commands.Bot):
    def __init__(
        self, settings: Settings, channel: str, bot_id: str, channel_owner_id: str
    ) -> None:
        self.settings = settings
        self.channel = channel
        self.channel_owner_id = channel_owner_id
        self.tracker = RevenueTracker(
            _tier_rates=settings.tier_revenue,
            _ad_cpm=settings.ad_cpm,
        )
        self.current_viewers: int = 0
        self._viewer_task: asyncio.Task[None] | None = None

        super().__init__(
            client_id=settings.twitch_client_id,
            client_secret=settings.twitch_client_secret,
            bot_id=bot_id,
            prefix="!",
        )

    @classmethod
    async def create(cls, settings: Settings, channel: str) -> EarningsBot:
        """Create a bot, resolving usernames to IDs."""
        bot_id, channel_owner_id = await asyncio.gather(
            resolve_user_id(
                settings.twitch_client_id,
                settings.twitch_client_secret,
                settings.twitch_bot_name,
            ),
            resolve_user_id(
                settings.twitch_client_id,
                settings.twitch_client_secret,
                channel,
            ),
        )
        logger.info(
            "Resolved %s -> %s, %s -> %s",
            settings.twitch_bot_name, bot_id, channel, channel_owner_id,
        )
        return cls(settings, channel, bot_id, channel_owner_id)

    async def setup_hook(self) -> None:
        await self.add_component(EarningsComponent(self, self.tracker))

    async def _subscribe_authed_events(self) -> None:
        owner = self.channel_owner_id
        bot = self.bot_id

        subscriptions = [
            eventsub.ChatMessageSubscription(
                broadcaster_user_id=owner, user_id=bot
            ),
            eventsub.ChannelSubscribeSubscription(broadcaster_user_id=owner),
            eventsub.ChannelSubscriptionGiftSubscription(
                broadcaster_user_id=owner
            ),
            eventsub.ChannelSubscribeMessageSubscription(
                broadcaster_user_id=owner
            ),
            eventsub.ChannelCheerSubscription(broadcaster_user_id=owner),
            eventsub.AdBreakBeginSubscription(broadcaster_user_id=owner),
        ]

        for sub in subscriptions:
            await self.subscribe_websocket(payload=sub)
        logger.info("Subscribed to EventSub events for channel %s", self.channel)

    async def event_ready(self) -> None:
        logger.info("Bot is ready — bot_id=%s", self.bot_id)
        # Try subscribing (works if tokens already saved from previous run)
        try:
            await self._subscribe_authed_events()
            await self.bootstrap_bits()
            self._viewer_task = asyncio.create_task(self._poll_viewers())
        except Exception:
            scopes = "channel:read:subscriptions+bits:read+channel:read:ads+user:read:chat+user:write:chat+user:bot"
            logger.warning(
                "No user tokens yet. Authorize at: http://localhost:4343/oauth?scopes=%s",
                scopes,
            )

    async def event_oauth_authorized(
        self, payload: twitchio.authentication.UserTokenPayload
    ) -> None:
        await self.add_token(payload.access_token, payload.refresh_token)
        logger.info("OAuth token stored for user %s", payload.user_id)
        # Subscribe now that we have tokens
        try:
            await self._subscribe_authed_events()
            await self.bootstrap_bits()
            if not self._viewer_task or self._viewer_task.done():
                self._viewer_task = asyncio.create_task(self._poll_viewers())
        except Exception:
            logger.exception("Failed to subscribe after OAuth")

    async def bootstrap_bits(self) -> None:
        try:
            owner = await self.fetch_user(user_id=int(self.channel_owner_id))
            today = datetime.now(timezone.utc).replace(
                hour=8, minute=0, second=0, microsecond=0
            )
            leaderboard = await owner.fetch_bits_leaderboard(
                period="day",
                started_at=today,
            )
            total = sum(entry.score for entry in leaderboard.leaders)
            self.tracker.bootstrap_bits(total)
            logger.info("Bootstrapped bits from API: %d", total)
        except Exception:
            logger.warning("Could not bootstrap bits (missing token or scope?)")

    async def _poll_viewers(self) -> None:
        while True:
            try:
                streams = [
                    s
                    async for s in self.fetch_streams(
                        user_ids=[self.channel_owner_id]
                    )
                ]
                self.current_viewers = streams[0].viewer_count if streams else 0
            except Exception:
                logger.debug("Viewer poll failed", exc_info=True)
            await asyncio.sleep(60)

    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        # Override default which skips messages from bot_id.
        # We use the same account for bot and chatter, so we must not skip.
        if payload.source_broadcaster is not None:
            return
        await self.process_commands(payload)

    async def close(self) -> None:
        if self._viewer_task and not self._viewer_task.done():
            self._viewer_task.cancel()
        await super().close()
