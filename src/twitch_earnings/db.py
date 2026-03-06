from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path("twitch_earnings.db")


def get_db(path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_stats (
            channel TEXT NOT NULL,
            date TEXT NOT NULL,
            subs_t1 INTEGER DEFAULT 0,
            subs_t2 INTEGER DEFAULT 0,
            subs_t3 INTEGER DEFAULT 0,
            subs_prime INTEGER DEFAULT 0,
            gift_subs INTEGER DEFAULT 0,
            bits INTEGER DEFAULT 0,
            messages INTEGER DEFAULT 0,
            PRIMARY KEY (channel, date)
        )
    """)
    conn.commit()
    return conn


def load_stats(conn: sqlite3.Connection, channel: str, date: str) -> dict:
    row = conn.execute(
        "SELECT subs_t1, subs_t2, subs_t3, subs_prime, gift_subs, bits, messages "
        "FROM channel_stats WHERE channel = ? AND date = ?",
        (channel, date),
    ).fetchone()
    if row:
        return {
            "subs_t1": row[0],
            "subs_t2": row[1],
            "subs_t3": row[2],
            "subs_prime": row[3],
            "gift_subs": row[4],
            "bits": row[5],
            "messages": row[6],
        }
    return {}


def save_stats(
    conn: sqlite3.Connection,
    channel: str,
    date: str,
    *,
    subs_t1: int,
    subs_t2: int,
    subs_t3: int,
    subs_prime: int,
    gift_subs: int,
    bits: int,
    messages: int,
) -> None:
    conn.execute(
        """
        INSERT INTO channel_stats (channel, date, subs_t1, subs_t2, subs_t3, subs_prime, gift_subs, bits, messages)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(channel, date) DO UPDATE SET
            subs_t1 = excluded.subs_t1,
            subs_t2 = excluded.subs_t2,
            subs_t3 = excluded.subs_t3,
            subs_prime = excluded.subs_prime,
            gift_subs = excluded.gift_subs,
            bits = excluded.bits,
            messages = excluded.messages
        """,
        (channel, date, subs_t1, subs_t2, subs_t3, subs_prime, gift_subs, bits, messages),
    )
    conn.commit()
