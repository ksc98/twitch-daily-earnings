from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import twitchio
from twitchio.ext import commands

if TYPE_CHECKING:
    from twitch_earnings.bot import EarningsBot
    from twitch_earnings.tracker import RevenueTracker

logger = logging.getLogger(__name__)


class EarningsComponent(commands.Component):
    def __init__(self, bot: EarningsBot, tracker: RevenueTracker) -> None:
        self.bot = bot
        self.tracker = tracker

    @commands.command(name="todaysearnings", aliases=("earnings", "revenue"))
    async def todaysearnings(self, ctx: commands.Context, *, channel: str = "") -> None:
        logger.info("Command triggered by %s", ctx.chatter.name)
        try:
            channel = channel.strip().lower()
            if not channel or channel == self.bot.channel.lower():
                await ctx.send(self.tracker.format_chat_message())
                return

            # Estimate another channel's earnings from viewer count
            users = await self.bot.fetch_users(logins=[channel])
            if not users:
                await ctx.send(f"Channel '{channel}' not found.")
                return

            user = users[0]
            streams = [
                s async for s in self.bot.fetch_streams(user_ids=[user.id])
            ]

            if not streams:
                await ctx.send(f"{user.display_name} is offline — can't estimate earnings.")
                return

            viewers = streams[0].viewer_count

            # Industry estimates based on viewer count:
            # Subs: ~1% of concurrent viewers are active subs (conservative)
            # Bits: ~$0.50 per 1k viewers per hour
            # Ads: ~4 ad breaks/hr, 60s each, $3.50 CPM
            est_subs = int(viewers * 0.01)
            sub_rev = est_subs * 2.50  # tier 1 avg, 50% split
            bit_rev = (viewers / 1000) * 0.50 * 6  # ~6hr stream
            ad_breaks = 4 * 6  # 4/hr over 6hr stream
            ad_rev = self.bot.settings.ad_cpm * (viewers / 1000) * (60 / 30) * ad_breaks
            total = sub_rev + bit_rev + ad_rev

            await ctx.send(
                f"{user.display_name} estimated daily earnings: ${total:,.0f} | "
                f"Subs: ~${sub_rev:,.0f} (~{est_subs:,} subs) | "
                f"Bits: ~${bit_rev:,.0f} | "
                f"Ads: ~${ad_rev:,.0f} | "
                f"Viewers: {viewers:,} | "
                f"⚠ Rough estimate based on viewer count"
            )
        except Exception:
            logger.exception("Failed to respond to !todaysearnings")

    @commands.Component.listener()
    async def event_subscription(self, payload: twitchio.ChannelSubscribe) -> None:
        if not payload.gift:
            self.tracker.record_sub(payload.tier)

    @commands.Component.listener()
    async def event_subscription_gift(
        self, payload: twitchio.ChannelSubscriptionGift
    ) -> None:
        self.tracker.record_sub(payload.tier, payload.total)

    @commands.Component.listener()
    async def event_subscription_message(
        self, payload: twitchio.ChannelSubscriptionMessage
    ) -> None:
        self.tracker.record_sub(payload.tier)

    @commands.Component.listener()
    async def event_cheer(self, payload: twitchio.ChannelCheer) -> None:
        self.tracker.record_cheer(payload.bits)

    @commands.Component.listener()
    async def event_ad_break(self, payload: twitchio.ChannelAdBreakBegin) -> None:
        self.tracker.record_ad_break(payload.duration, self.bot.current_viewers)

    @commands.Component.listener()
    async def event_stream_online(self, payload: twitchio.StreamOnline) -> None:
        self.tracker.reset()
        await self.bot.bootstrap_bits()
