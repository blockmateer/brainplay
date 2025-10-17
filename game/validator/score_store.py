from __future__ import annotations

import os
import sqlite3
import time
import threading
from collections import defaultdict
from typing import Dict, Iterable, Optional

import aiohttp
import bittensor as bt


class ScoreStore:
    """SQLite-backed store for finished game snapshots and backend synchronisation."""

    def __init__(self, db_path: str, backend_url: str, signer=None):
        self.db_path = db_path
        self.backend_url = backend_url
        self.signer = signer
        folder = os.path.dirname(db_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            with self._lock:
                if self._conn is None:
                    self._conn = sqlite3.connect(
                        self.db_path,
                        isolation_level=None,
                        check_same_thread=False,
                    )
                    self._conn.execute("PRAGMA journal_mode=WAL;")
                    self._conn.execute("PRAGMA synchronous=NORMAL;")
        return self._conn

    def init(self):
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT NOT NULL UNIQUE,
                rs TEXT NOT NULL,
                ro TEXT NOT NULL,
                bs TEXT NOT NULL,
                bo TEXT NOT NULL,
                winner TEXT,
                started_at INTEGER NOT NULL,
                ended_at INTEGER NOT NULL,
                score_rs REAL NOT NULL,
                score_ro REAL NOT NULL,
                score_bs REAL NOT NULL,
                score_bo REAL NOT NULL,
                reason TEXT,
                synced_at INTEGER
            );
            """
        )
        cur.close()

    def record_game(
        self,
        *,
        room_id: str,
        rs: str,
        ro: str,
        bs: str,
        bo: str,
        winner: Optional[str],
        started_at: float,
        ended_at: float,
        score_rs: float,
        score_ro: float,
        score_bs: float,
        score_bo: float,
        reason: Optional[str],
    ) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO scores(
                    room_id, rs, ro, bs, bo, winner,
                    started_at, ended_at,
                    score_rs, score_ro, score_bs, score_bo,
                    reason, synced_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
                ON CONFLICT(room_id) DO UPDATE SET
                    rs=excluded.rs,
                    ro=excluded.ro,
                    bs=excluded.bs,
                    bo=excluded.bo,
                    winner=excluded.winner,
                    started_at=excluded.started_at,
                    ended_at=excluded.ended_at,
                    score_rs=excluded.score_rs,
                    score_ro=excluded.score_ro,
                    score_bs=excluded.score_bs,
                    score_bo=excluded.score_bo,
                    reason=excluded.reason,
                    synced_at=NULL
                ;
                """,
                (
                    room_id,
                    rs,
                    ro,
                    bs,
                    bo,
                    winner,
                    int(started_at),
                    int(ended_at),
                    float(score_rs),
                    float(score_ro),
                    float(score_bs),
                    float(score_bo),
                    reason,
                ),
            )
            cur.close()

    def pending(self) -> Iterable[Dict[str, object]]:
        columns = [
            "room_id",
            "rs",
            "ro",
            "bs",
            "bo",
            "winner",
            "started_at",
            "ended_at",
            "score_rs",
            "score_ro",
            "score_bs",
            "score_bo",
            "reason",
        ]
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT {} FROM scores WHERE synced_at IS NULL ORDER BY ended_at ASC".format(
                    ", ".join(columns)
                )
            )
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
            cur.close()
        return rows

    def window_scores_by_hotkey(self, since_ts: float) -> Dict[str, float]:
        totals: Dict[str, float] = defaultdict(float)
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                SELECT rs, ro, bs, bo,
                       score_rs, score_ro, score_bs, score_bo
                FROM scores
                WHERE ended_at >= ?
                """,
                (int(since_ts),),
            )
            for row in cur.fetchall():
                rs, ro, bs, bo, score_rs, score_ro, score_bs, score_bo = row
                if rs:
                    totals[rs] += float(score_rs or 0.0)
                if ro:
                    totals[ro] += float(score_ro or 0.0)
                if bs:
                    totals[bs] += float(score_bs or 0.0)
                if bo:
                    totals[bo] += float(score_bo or 0.0)
            cur.close()
        return dict(totals)

    def mark_synced(self, room_id: str) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE scores SET synced_at=? WHERE room_id=?",
                (int(time.time()), room_id),
            )
            cur.close()

    async def sync_pending(self) -> int:
        """Pushes unsynced rows to the backend API.

        Returns the number of rows marked as synced.
        """

        if not self.backend_url:
            bt.logging.warning("No backend URL configured for score syncing.")
            return 0

        to_sync = list(self.pending())
        if not to_sync:
            return 0

        synced = 0
        async with aiohttp.ClientSession() as session:
            for row in to_sync:
                payload = {
                    "red": {
                        "spymaster": {
                            "hotkey": row["rs"],
                            "score": row["score_rs"],
                        },
                        "operative": {
                            "hotkey": row["ro"],
                            "score": row["score_ro"],
                        },
                    },
                    "blue": {
                        "spymaster": {
                            "hotkey": row["bs"],
                            "score": row["score_bs"],
                        },
                        "operative": {
                            "hotkey": row["bo"],
                            "score": row["score_bo"],
                        },
                    },
                    "reason": row["reason"],
                }
                headers = self.signer() if self.signer else {}
                try:
                    async with session.patch(
                        self.backend_url + "/" + row["room_id"],
                        json=payload,
                        headers=headers,
                        timeout=10,
                    ) as resp:
                        if resp.status in (200, 201, 202, 204):
                            self.mark_synced(row["room_id"])
                            synced += 1
                        else:
                            text = await resp.text()
                            bt.logging.error(
                                f"Failed to sync score {row['room_id']}: {resp.status} {text}"
                            )
                except Exception as err:  # noqa: BLE001
                    bt.logging.error(f"Exception syncing score {row['room_id']}: {err}")
        return synced

    def close(self):
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None
