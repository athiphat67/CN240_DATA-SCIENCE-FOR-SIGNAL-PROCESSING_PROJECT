import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from datetime import datetime
from typing import Optional
from logs.logger_setup import sys_logger

# ─────────────────────────────────────────────
# Schema (PostgreSQL)
# ─────────────────────────────────────────────

_CREATE_GOLD_PRICES_TABLE = """
CREATE TABLE IF NOT EXISTS gold_prices_ig (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL UNIQUE,  -- ใส่ UNIQUE ตรงนี้เลย
    ask_96 REAL,
    bid_96 REAL,
    spot_price REAL,
    usd_thb REAL
);
"""

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS runs (
    id               SERIAL PRIMARY KEY,
    run_at           TEXT    NOT NULL,
    provider         TEXT    NOT NULL,
    interval_tf      TEXT,
    period           TEXT,
    signal           TEXT,
    confidence       REAL,
    entry_price      REAL,        -- THB/gram (ราคาจาก LLM โดยตรง — ไม่ใช่ USD)
    stop_loss        REAL,        -- THB/gram
    take_profit      REAL,        -- THB/gram
    entry_price_thb  REAL,        -- alias เหมือน entry_price (backward compat)
    stop_loss_thb    REAL,
    take_profit_thb  REAL,
    usd_thb_rate     REAL,
    rationale        TEXT,
    iterations_used  INTEGER,
    tool_calls_used  INTEGER,
    gold_price       REAL,        -- USD/oz
    gold_price_thb   REAL,        -- THB/gram (sell price จาก ออม NOW)
    rsi              REAL,
    macd_line        REAL,
    signal_line      REAL,
    trend            TEXT,
    react_trace      TEXT,        -- JSON array ของ trace steps
    market_snapshot  TEXT,        -- JSON snapshot ของ market_data + indicators
    -- ── Data Quality (GATE-2) ───────────────────────────────────────────────
    is_weekend       BOOLEAN DEFAULT FALSE,  -- TRUE = ตลาดปิด / data อาจ stale
    data_quality     TEXT,                   -- "good" | "degraded" | "unknown"
    -- ── Indicators เพิ่มเติม (GATE-2) ──────────────────────────────────────
    macd_histogram   REAL,                   -- MACD histogram (สำคัญกว่า line ในการดู cross)
    bb_pct_b         REAL,                   -- %B ของ Bollinger Band (0=lower, 1=upper)
    atr_thb          REAL                    -- ATR หลัง convert เป็น THB/baht weight (GATE-3)
);
"""

# ── LLM Logs Table ─────────────────────────────────────────────────────────────
# เก็บกระบวนการคิดทั้งหมดของ LLM ต่อ 1 run:
#   - ทุก step ของ ReAct loop (THOUGHT / ACTION / OBSERVATION / THOUGHT_FINAL)
#   - Token usage (input / output / total)
#   - Elapsed time ต่อ call
#   - Full prompt + response text
#
# TODO (react.py): ให้ ReactOrchestrator include "prompt_text" และ "response_raw"
#                  ในแต่ละ trace entry เพื่อให้ full_prompt / full_response ไม่เป็น NULL
_CREATE_LLM_LOGS_TABLE = """
CREATE TABLE IF NOT EXISTS llm_logs (
    id              SERIAL PRIMARY KEY,
    run_id          INTEGER REFERENCES runs(id) ON DELETE CASCADE,
    logged_at       TEXT    NOT NULL,
    interval_tf     TEXT,
    step_type       TEXT,           -- THOUGHT / ACTION / OBSERVATION / THOUGHT_FINAL
    iteration       INTEGER DEFAULT 0,
    provider        TEXT,
    signal          TEXT,           -- ผลตัดสิน (มีเฉพาะ THOUGHT_FINAL)
    confidence      REAL,
    rationale       TEXT,
    entry_price     REAL,           -- THB/gram
    stop_loss       REAL,           -- THB/gram
    take_profit     REAL,           -- THB/gram
    full_prompt     TEXT,           -- prompt ที่ส่งไป LLM (NULL จนกว่า react.py จะ expose)
    full_response   TEXT,           -- response ดิบจาก LLM (NULL จนกว่า react.py จะ expose)
    trace_json      TEXT,           -- JSON ของ trace steps ทั้งหมดในรอบนี้
    token_input     INTEGER,
    token_output    INTEGER,
    token_total     INTEGER,
    elapsed_ms      INTEGER,
    iterations_used INTEGER DEFAULT 0,
    tool_calls_used INTEGER DEFAULT 0,
    is_fallback     BOOLEAN DEFAULT FALSE,
    fallback_from   TEXT            -- provider ต้นทางที่ fail ก่อน fallback
);
"""

_CREATE_PORTFOLIO_TABLE = """
CREATE TABLE IF NOT EXISTS portfolio (
    id                SERIAL PRIMARY KEY,
    cash_balance      REAL    NOT NULL DEFAULT 1500.0,
    gold_grams        REAL    NOT NULL DEFAULT 0.0,
    cost_basis_thb    REAL    NOT NULL DEFAULT 0.0,
    current_value_thb REAL    NOT NULL DEFAULT 0.0,
    unrealized_pnl    REAL    NOT NULL DEFAULT 0.0,
    trades_today      INTEGER NOT NULL DEFAULT 0,
    trades_this_session INTEGER NOT NULL DEFAULT 0,
    updated_at        TEXT    NOT NULL
);
"""

# ── Trade Log Table ───────────────────────────────────────────────────────────
# เก็บทุก BUY/SELL ที่ execute จริง เพื่อให้วิเคราะห์ PnL per-trade ย้อนหลังได้
# portfolio เก็บแค่ state ปัจจุบัน — trade_log คือ history ทั้งหมด
_CREATE_TRADE_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS trade_log (
    id              SERIAL PRIMARY KEY,
    run_id          INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    action          TEXT    NOT NULL,   -- "BUY" | "SELL"
    executed_at     TEXT    NOT NULL,
    price_thb       REAL,              -- ราคาที่ execute จริง (THB/gram)
    gold_grams      REAL,              -- จำนวนกรัมที่ซื้อ/ขาย
    amount_thb      REAL,              -- เงินที่เปลี่ยนมือ (THB)
    cash_before     REAL,              -- cash ก่อน execute
    cash_after      REAL,              -- cash หลัง execute
    gold_before     REAL,              -- gold_grams ก่อน execute
    gold_after      REAL,              -- gold_grams หลัง execute
    cost_basis_thb  REAL,              -- ต้นทุนเฉลี่ย ณ เวลา execute
    pnl_thb         REAL,              -- กำไร/ขาดทุน (เฉพาะ SELL, NULL สำหรับ BUY)
    pnl_pct         REAL,              -- % กำไร/ขาดทุน (เฉพาะ SELL)
    note            TEXT               -- เหตุผลเพิ่มเติม เช่น "stop_loss triggered"
);
"""

_HISTORY_COLS = """
    id, run_at, provider, interval_tf, period,
    signal, confidence, entry_price, stop_loss, take_profit,
    iterations_used, gold_price, gold_price_thb, rsi, macd_line, trend, rationale
"""

# FIX: whitelist สำหรับ migration — ป้องกัน f-string injection ถ้า migrations list
#      เคยถูกย้ายมาจาก config ภายนอกในอนาคต
_ALLOWED_MIGRATION_TABLES = {"runs", "portfolio", "llm_logs"}
_ALLOWED_MIGRATION_TYPES = {"REAL", "INTEGER", "TEXT", "BOOLEAN"}


class RunDatabase:
    def __init__(self):
        self.db_url = os.environ.get("DATABASE_URL")
        if not self.db_url:
            raise ValueError(
                "⚠️ DATABASE_URL is not set. "
                "Please add it to your .env file or Render environment variables."
            )
        # FIX: ใช้ connection pool แทนการเปิด connection ใหม่ทุกครั้ง
        # min=1, max=5 เหมาะกับ Render free tier (ลิมิต ~10 connections)
        self._pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=self.db_url,
            cursor_factory=RealDictCursor,
            sslmode="require",
        )
        sys_logger.info("DB connection pool initialized (min=1, max=5)")
        self._init_db()

    @contextmanager
    def get_connection(self):
        """Context manager ที่ดึง connection จาก pool และคืนกลับเมื่อเสร็จ"""
        conn = self._pool.getconn()
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def close(self) -> None:
        """ปิด pool ทั้งหมด — เรียกตอน shutdown"""
        self._pool.closeall()
        sys_logger.info("DB connection pool closed")

    def _init_db(self) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(_CREATE_TABLE)
                cursor.execute(_CREATE_PORTFOLIO_TABLE)
                cursor.execute(_CREATE_LLM_LOGS_TABLE)
                cursor.execute(_CREATE_TRADE_LOG_TABLE)
                cursor.execute(_CREATE_GOLD_PRICES_TABLE)

                # ── Idempotent column migrations ───────────────────────────
                migrations = [
                    ("runs", "entry_price_thb", "REAL"),
                    ("runs", "stop_loss_thb", "REAL"),
                    ("runs", "take_profit_thb", "REAL"),
                    ("runs", "usd_thb_rate", "REAL"),
                    ("runs", "gold_price_thb", "REAL"),
                    # ── v3.4: data quality & indicators ───────────────────
                    ("runs", "is_weekend", "BOOLEAN"),
                    ("runs", "data_quality", "TEXT"),
                    ("runs", "macd_histogram", "REAL"),
                    ("runs", "bb_pct_b", "REAL"),
                    ("runs", "atr_thb", "REAL"),
                    ("portfolio", "trailing_stop_level_thb", "REAL"),
                    ("portfolio", "trades_this_session", "INTEGER"),
                ]
                for table, col, typ in migrations:
                    # FIX: whitelist ก่อน interpolate เข้า f-string
                    if table not in _ALLOWED_MIGRATION_TABLES:
                        raise ValueError(f"Migration rejected: unknown table '{table}'")
                    if typ not in _ALLOWED_MIGRATION_TYPES:
                        raise ValueError(f"Migration rejected: unknown type '{typ}'")
                    cursor.execute(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ};"
                    )
                cursor.execute(
                    "UPDATE portfolio SET trades_this_session = 0 "
                    "WHERE trades_this_session IS NULL;"
                )
                cursor.execute(
                    "ALTER TABLE portfolio "
                    "ALTER COLUMN trades_this_session SET DEFAULT 0;"
                )
                cursor.execute(
                    "ALTER TABLE portfolio "
                    "ALTER COLUMN trades_this_session SET NOT NULL;"
                )
            conn.commit()
        sys_logger.info("DB init OK — tables: runs, portfolio, llm_logs, trade_log")

    # ── runs ──────────────────────────────────────────────────────────────────

    def save_run(
        self,
        provider: str,
        result: dict,
        market_state: dict,
        interval_tf: str = "",
        period: str = "",
    ) -> int:
        """
        บันทึกผล analysis 1 ครั้งลง table runs

        FIX (v3.3): ราคา entry_price / stop_loss / take_profit จาก LLM
                    เป็น THB/gram อยู่แล้ว (เห็นจาก llm_trace.log)
                    → เก็บตรงๆ ไม่ต้องแปลงจาก USD อีก
        FIX (v3.3): ลบ @log_method decorator ออก เพื่อป้องกัน double-log
                    (decorator wrapper ใน caller เป็นคนจัดการ elapsed แล้ว)
        """
        sys_logger.debug(
            f"save_run START — provider={provider}, interval={interval_tf}, period={period}"
        )

        signal_val = result.get("signal", "HOLD")
        conf_val = result.get("confidence", 0.0)
        rationale_val = result.get("rationale", "")
        if not rationale_val:
            breakdown = result.get("voting_breakdown", {})
            if breakdown.get(signal_val):
                rationale_val = f"Weighted voting result: {signal_val}"

        md = market_state.get("market_data", {})
        ti = market_state.get("technical_indicators", {})
        dq = market_state.get("data_quality", {})

        gold_price_usd = md.get("spot_price_usd", {}).get("price_usd_per_oz")
        usd_thb = md.get("forex", {}).get("usd_thb")
        gold_price_thb = md.get("thai_gold_thb", {}).get("sell_price_thb")

        rsi_val = ti.get("rsi", {}).get("value")
        macd_line = ti.get("macd", {}).get("macd_line")
        signal_line = ti.get("macd", {}).get("signal_line")
        trend_dir = ti.get("trend", {}).get("trend")

        # ── v3.4: new fields ──────────────────────────────────────────────
        macd_histogram = ti.get("macd", {}).get("histogram")
        bb_pct_b = ti.get("bollinger", {}).get("pct_b")
        atr_thb = ti.get("atr", {}).get("value")  # Gate-3 ได้ convert เป็น THB แล้ว
        is_weekend = bool(dq.get("is_weekend", False))
        data_quality = dq.get("quality_score", "unknown")

        # ─── ราคา THB/gram จาก LLM โดยตรง (ไม่แปลง) ──────────────────────
        entry_thb = result.get("entry_price")  # THB/gram
        stop_thb = result.get("stop_loss")  # THB/gram
        take_thb = result.get("take_profit")  # THB/gram

        query = """
            INSERT INTO runs (
                run_at, provider, interval_tf, period,
                signal, confidence,
                entry_price, stop_loss, take_profit,
                entry_price_thb, stop_loss_thb, take_profit_thb,
                usd_thb_rate, gold_price_thb,
                rationale, iterations_used, tool_calls_used,
                gold_price, rsi, macd_line, signal_line, trend,
                react_trace, market_snapshot,
                is_weekend, data_quality,
                macd_histogram, bb_pct_b, atr_thb
            ) VALUES (
                %s,%s,%s,%s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,
                %s,%s,
                %s,%s,%s,
                %s,%s,%s,%s,%s,
                %s,%s,
                %s,%s,
                %s,%s,%s
            )
            RETURNING id;
        """
        values = (
            datetime.utcnow().isoformat(timespec="seconds") + "Z",
            provider,
            interval_tf,
            period,
            signal_val,
            conf_val,
            entry_thb,
            stop_thb,
            take_thb,
            entry_thb,
            stop_thb,
            take_thb,  # _thb aliases
            usd_thb,
            gold_price_thb,
            rationale_val,
            result.get("iterations_used", 0),
            result.get("tool_calls_used", 0),
            gold_price_usd,
            rsi_val,
            macd_line,
            signal_line,
            trend_dir,
            json.dumps(result.get("react_trace", []), ensure_ascii=False),
            json.dumps(
                {"market_data": md, "technical_indicators": ti},
                ensure_ascii=False,
                default=str,
            ),
            is_weekend,
            data_quality,
            macd_histogram,
            bb_pct_b,
            atr_thb,
        )

        # FIX: wrap DB write ด้วย try/except — log payload ที่ fail แล้ว re-raise
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, values)
                    new_id = cursor.fetchone()["id"]
                conn.commit()
        except Exception as e:
            sys_logger.error(
                f"save_run FAILED — provider={provider} interval={interval_tf} "
                f"signal={signal_val} error={e}"
            )
            raise

        sys_logger.info(
            f"save_run OK — ID={new_id} | {signal_val} {conf_val:.1%} | provider={provider}"
        )
        return new_id

    def get_recent_runs(self, limit: int = 50) -> list[dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_HISTORY_COLS} FROM runs ORDER BY id DESC LIMIT %s",
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def get_run_detail(self, run_id: int) -> Optional[dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM runs WHERE id = %s", (run_id,))
                row = cursor.fetchone()

        if not row:
            return None

        d = dict(row)
        for col in ("react_trace", "market_snapshot"):
            if d.get(col):
                try:
                    d[col] = json.loads(d[col])
                except json.JSONDecodeError:
                    pass
        return d

    def get_signal_stats(self) -> dict:
        # FIX: เพิ่ม try/except และ guard กรณี row เป็น None
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT
                            COUNT(*)                                         AS total,
                            SUM(CASE WHEN signal='BUY'  THEN 1 ELSE 0 END)  AS buy_count,
                            SUM(CASE WHEN signal='SELL' THEN 1 ELSE 0 END)  AS sell_count,
                            SUM(CASE WHEN signal='HOLD' THEN 1 ELSE 0 END)  AS hold_count,
                            AVG(confidence)                                  AS avg_confidence,
                            AVG(gold_price_thb)                              AS avg_price
                        FROM runs
                    """)
                    row = cursor.fetchone()
        except Exception as e:
            sys_logger.error(f"get_signal_stats FAILED: {e}")
            row = None

        if not row:
            return {
                "total": 0,
                "buy_count": 0,
                "sell_count": 0,
                "hold_count": 0,
                "avg_confidence": 0.0,
                "avg_price": 0.0,
            }

        return {
            "total": row["total"] or 0,
            "buy_count": row["buy_count"] or 0,
            "sell_count": row["sell_count"] or 0,
            "hold_count": row["hold_count"] or 0,
            "avg_confidence": round(row["avg_confidence"] or 0, 3),
            "avg_price": round(row["avg_price"] or 0, 2),  # THB/gram
        }

    def delete_run(self, run_id: int) -> bool:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM runs WHERE id = %s", (run_id,))
                deleted_count = cursor.rowcount
            conn.commit()
        return deleted_count > 0

    # ── llm_logs ──────────────────────────────────────────────────────────────

    def save_llm_log(self, run_id: int, log_data: dict) -> int:
        """
        บันทึก 1 LLM log entry ลง llm_logs

        log_data keys (ทั้งหมด optional ยกเว้น interval_tf):
            interval_tf       : str   — ชื่อ interval เช่น "1h"
            step_type         : str   — "THOUGHT_FINAL" / "THOUGHT" / "ACTION" / "OBSERVATION"
            iteration         : int   — ลำดับ iteration ใน ReAct loop
            provider          : str   — provider ที่ใช้จริง
            signal            : str   — BUY / SELL / HOLD
            confidence        : float
            rationale         : str   — เหตุผลของ LLM
            entry_price       : float — THB/gram
            stop_loss         : float — THB/gram
            take_profit       : float — THB/gram
            full_prompt       : str   — prompt ที่ส่งไป (None จนกว่า react.py จะ expose)
            full_response     : str   — response ดิบ (None จนกว่า react.py จะ expose)
            trace_json        : list  — trace steps ทั้งหมด
            token_input       : int
            token_output      : int
            token_total       : int
            elapsed_ms        : int   — milliseconds
            iterations_used   : int
            tool_calls_used   : int
            is_fallback       : bool
            fallback_from     : str   — provider ต้นทางที่ fail
        """
        trace_json = log_data.get("trace_json")
        if isinstance(trace_json, list):
            trace_json = json.dumps(trace_json, ensure_ascii=False, default=str)

        query = """
            INSERT INTO llm_logs (
                run_id, logged_at, interval_tf, step_type, iteration,
                provider, signal, confidence, rationale,
                entry_price, stop_loss, take_profit,
                full_prompt, full_response, trace_json,
                token_input, token_output, token_total,
                elapsed_ms, iterations_used, tool_calls_used,
                is_fallback, fallback_from
            ) VALUES (
                %s,%s,%s,%s,%s,
                %s,%s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,
                %s,%s
            )
            RETURNING id;
        """
        values = (
            run_id,
            datetime.utcnow().isoformat(timespec="seconds") + "Z",
            log_data.get("interval_tf", ""),
            log_data.get("step_type", "THOUGHT_FINAL"),
            log_data.get("iteration", 0),
            log_data.get("provider", ""),
            log_data.get("signal", "HOLD"),
            log_data.get("confidence", 0.0),
            log_data.get("rationale", ""),
            log_data.get("entry_price"),
            log_data.get("stop_loss"),
            log_data.get("take_profit"),
            log_data.get("full_prompt"),
            log_data.get("full_response"),
            trace_json,
            log_data.get("token_input"),
            log_data.get("token_output"),
            log_data.get("token_total"),
            log_data.get("elapsed_ms"),
            log_data.get("iterations_used", 0),
            log_data.get("tool_calls_used", 0),
            bool(log_data.get("is_fallback", False)),
            log_data.get("fallback_from"),
        )

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, values)
                new_id = cursor.fetchone()["id"]
            conn.commit()

        sys_logger.debug(
            f"save_llm_log OK — log_id={new_id} run_id={run_id} "
            f"interval={log_data.get('interval_tf')} tokens={log_data.get('token_total')}"
        )
        return new_id

    def save_llm_logs_batch(self, run_id: int, logs: list[dict]) -> list[int]:
        """บันทึก llm_logs หลาย entry (1 run = หลาย interval = หลาย logs)"""
        if not logs:
            return []

        ids = []
        errors = []
        for log_data in logs:
            try:
                log_id = self.save_llm_log(run_id, log_data)
                ids.append(log_id)
            except Exception as e:
                interval = log_data.get("interval_tf", "unknown")
                sys_logger.error(
                    f"save_llm_logs_batch: error for interval={interval}: {e}"
                )
                # FIX: เก็บ error detail ไว้เพื่อ traceability
                errors.append({"interval": interval, "error": str(e)})

        sys_logger.info(
            f"save_llm_logs_batch: {len(ids)}/{len(logs)} logs saved for run_id={run_id}"
        )
        # FIX: log summary ของที่ fail ทั้งหมด ไม่ใช่แค่นับ
        if errors:
            sys_logger.warning(
                f"save_llm_logs_batch: {len(errors)} failed entries — {errors}"
            )
        return ids

    def get_llm_logs_for_run(self, run_id: int) -> list[dict]:
        """ดึง llm_logs ทั้งหมดของ run เรียงตามเวลา"""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, logged_at, interval_tf, step_type, iteration,
                           provider, signal, confidence, rationale,
                           entry_price, stop_loss, take_profit,
                           full_prompt, full_response, trace_json,
                           token_input, token_output, token_total,
                           elapsed_ms, iterations_used, tool_calls_used,
                           is_fallback, fallback_from
                    FROM llm_logs
                    WHERE run_id = %s
                    ORDER BY logged_at ASC, id ASC
                    """,
                    (run_id,),
                )
                rows = cursor.fetchall()

        result = []
        for r in rows:
            d = dict(r)
            if d.get("trace_json"):
                try:
                    d["trace_json"] = json.loads(d["trace_json"])
                except json.JSONDecodeError:
                    pass
            result.append(d)
        return result

    def get_recent_llm_logs(self, limit: int = 20) -> list[dict]:
        """ดึง llm_logs ล่าสุด (ข้ามรอบ) สำหรับ monitoring"""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT l.id, l.run_id, l.logged_at, l.interval_tf,
                           l.provider, l.signal, l.confidence,
                           l.token_input, l.token_output, l.token_total,
                           l.elapsed_ms, l.is_fallback, l.fallback_from,
                           r.run_at
                    FROM llm_logs l
                    LEFT JOIN runs r ON r.id = l.run_id
                    ORDER BY l.id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(r) for r in rows]

    # ── portfolio ─────────────────────────────────────────────────────────────

    def save_portfolio(self, data: dict) -> None:
        """UPSERT portfolio — มีแค่ 1 row เสมอ (id = 1)"""
        sys_logger.info(
            f"save_portfolio: cash={data.get('cash_balance')}, gold={data.get('gold_grams')}"
        )
        query = """
            INSERT INTO portfolio (id, cash_balance, gold_grams, cost_basis_thb,
                                   current_value_thb, unrealized_pnl, trades_today, updated_at,
                                   trailing_stop_level_thb, trades_this_session)
            VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                cash_balance      = EXCLUDED.cash_balance,
                gold_grams        = EXCLUDED.gold_grams,
                cost_basis_thb    = EXCLUDED.cost_basis_thb,
                current_value_thb = EXCLUDED.current_value_thb,
                unrealized_pnl    = EXCLUDED.unrealized_pnl,
                trades_today      = EXCLUDED.trades_today,
                updated_at        = EXCLUDED.updated_at,
                trailing_stop_level_thb = EXCLUDED.trailing_stop_level_thb,
                trades_this_session = EXCLUDED.trades_this_session;
        """
        values = (
            data.get("cash_balance", 1500.0),
            data.get("gold_grams", 0.0),
            data.get("cost_basis_thb", 0.0),
            data.get("current_value_thb", 0.0),
            data.get("unrealized_pnl", 0.0),
            int(data.get("trades_today") or 0),
            datetime.utcnow().isoformat(timespec="seconds") + "Z",
            data.get("trailing_stop_level_thb"),
            int(data.get("trades_this_session") or 0),
        )
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, values)
            conn.commit()

    def get_portfolio(self) -> dict:
        """ดึง portfolio row (id=1) ถ้าไม่มีคืน default"""
        default = {
            "cash_balance": 1500.0,
            "gold_grams": 0.0,
            "cost_basis_thb": 0.0,
            "current_value_thb": 0.0,
            "unrealized_pnl": 0.0,
            "trades_today": 0,
            "trades_this_session": 0,
            "updated_at": "",
            "trailing_stop_level_thb": None,
        }
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM portfolio WHERE id = 1")
                    row = cursor.fetchone()
            if row:
                portfolio = dict(default)
                portfolio.update(dict(row))
                portfolio["trades_today"] = int(portfolio.get("trades_today") or 0)
                portfolio["trades_this_session"] = int(
                    portfolio.get("trades_this_session") or 0
                )
                return portfolio
        except Exception as e:
            # FIX: log ให้รู้ว่า DB fail — ไม่ใช่แค่ "ยังไม่มี portfolio"
            sys_logger.warning(f"get_portfolio failed, returning default: {e}")
        return default

    # ── trade_log ─────────────────────────────────────────────────────────────

    def save_trade(self, run_id: Optional[int], trade: dict) -> int:
        """
        บันทึก 1 trade (BUY หรือ SELL) ลง trade_log

        trade keys:
            action         : str   — "BUY" | "SELL"
            price_thb      : float — ราคา execute จริง (THB/gram)
            gold_grams     : float — จำนวนกรัม
            amount_thb     : float — เงินที่เปลี่ยนมือ
            cash_before    : float
            cash_after     : float
            gold_before    : float
            gold_after     : float
            cost_basis_thb : float — ต้นทุนเฉลี่ย ณ เวลา execute
            pnl_thb        : float — กำไร/ขาดทุน (SELL เท่านั้น)
            pnl_pct        : float — % กำไร/ขาดทุน (SELL เท่านั้น)
            note           : str   — optional
        """
        action = trade.get("action", "").upper()
        if action not in ("BUY", "SELL"):
            raise ValueError(
                f"save_trade: invalid action '{action}' — must be BUY or SELL"
            )

        query = """
            INSERT INTO trade_log (
                run_id, action, executed_at,
                price_thb, gold_grams, amount_thb,
                cash_before, cash_after,
                gold_before, gold_after,
                cost_basis_thb, pnl_thb, pnl_pct, note
            ) VALUES (
                %s,%s,%s,
                %s,%s,%s,
                %s,%s,
                %s,%s,
                %s,%s,%s,%s
            )
            RETURNING id;
        """
        values = (
            run_id,
            action,
            datetime.utcnow().isoformat(timespec="seconds") + "Z",
            trade.get("price_thb"),
            trade.get("gold_grams"),
            trade.get("amount_thb"),
            trade.get("cash_before"),
            trade.get("cash_after"),
            trade.get("gold_before"),
            trade.get("gold_after"),
            trade.get("cost_basis_thb"),
            trade.get("pnl_thb"),  # None สำหรับ BUY
            trade.get("pnl_pct"),  # None สำหรับ BUY
            trade.get("note"),
        )

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, values)
                new_id = cursor.fetchone()["id"]
            conn.commit()

        pnl_str = (
            f" | PnL={trade.get('pnl_thb'):+.2f} THB"
            if trade.get("pnl_thb") is not None
            else ""
        )
        sys_logger.info(
            f"save_trade OK — id={new_id} {action} {trade.get('gold_grams')}g "
            f"@ {trade.get('price_thb')} THB/g{pnl_str}"
        )
        return new_id

    def get_trades_count_since(self, since_iso: str) -> int:
        """นับจำนวนไม้ (BUY/SELL) ที่เกิดขึ้นตั้งแต่เวลา since_iso เป็นต้นมา"""
        if not since_iso:
            return 0
        query = """
            SELECT COUNT(*) as count
            FROM trade_log
            WHERE executed_at::timestamptz >= %s::timestamptz
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (since_iso,))
                    row = cursor.fetchone()
                    return int(row["count"] or 0)
        except Exception as e:
            sys_logger.error(f"get_trades_count_since FAILED: {e}")
            return 0

    def update_trades_this_session(self, count: int) -> None:
        """Persist the current session trade count on the portfolio singleton."""
        safe_count = max(0, int(count or 0))
        now_str = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        query = """
            INSERT INTO portfolio (id, trades_this_session, updated_at)
            VALUES (1, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                trades_this_session = EXCLUDED.trades_this_session,
                updated_at = EXCLUDED.updated_at;
        """
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (safe_count, now_str))
            conn.commit()

    def record_emergency_sell_atomic(
        self,
        grams: float,
        price_per_gram: float,
        reason: str,
        run_id: int = None,
    ) -> int:
        """
        [P0 FIX] Atomic Emergency Sell Transaction
        ─────────────────────────────────────────────
        รวม 2 operations ใน transaction เดียว:
          1. INSERT INTO trade_log (action=SELL)
          2. UPDATE portfolio (gold_grams, cost_basis, unrealized_pnl)

        ป้องกัน Phantom Gold: ถ้า step ใด fail → rollback ทั้งคู่ ไม่มีข้อมูลครึ่งๆ

        Returns:
            trade_log.id ที่เพิ่งสร้าง
        """
        from datetime import datetime

        portfolio = self.get_portfolio()

        gold_before = float(portfolio.get("gold_grams", 0.0))
        cash_before = float(portfolio.get("cash_balance", 0.0))
        cost_basis = float(portfolio.get("cost_basis_thb", 0.0))

        if gold_before <= 0:
            raise ValueError(
                f"record_emergency_sell_atomic: gold_grams={gold_before} — nothing to sell"
            )

        grams_to_sell = min(grams, gold_before)  # ขายได้ไม่เกินที่มี
        amount_thb = grams_to_sell * price_per_gram
        gold_after = round(gold_before - grams_to_sell, 6)
        cash_after = round(cash_before + amount_thb, 2)

        # PnL = (sell price - cost basis) × grams ขาย
        pnl_thb = (price_per_gram - cost_basis) * grams_to_sell
        pnl_pct = (pnl_thb / (cost_basis * grams_to_sell)) if cost_basis > 0 else 0.0

        now_str = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # ── Step 1: INSERT trade_log ──────────────────────
                    cursor.execute(
                        """
                        INSERT INTO trade_log (
                            run_id, action, executed_at,
                            price_thb, gold_grams, amount_thb,
                            cash_before, cash_after,
                            gold_before, gold_after,
                            cost_basis_thb, pnl_thb, pnl_pct, note
                        ) VALUES (
                            %s,%s,%s,
                            %s,%s,%s,
                            %s,%s,
                            %s,%s,
                            %s,%s,%s,%s
                        )
                        RETURNING id;
                        """,
                        (
                            run_id,
                            "SELL",
                            now_str,
                            round(price_per_gram, 4),
                            round(grams_to_sell, 6),
                            round(amount_thb, 2),
                            round(cash_before, 2),
                            cash_after,
                            round(gold_before, 6),
                            gold_after,
                            round(cost_basis, 4),
                            round(pnl_thb, 2),
                            round(pnl_pct, 6),
                            reason,
                        ),
                    )
                    trade_id = cursor.fetchone()["id"]

                    # ── Step 2: UPDATE portfolio (UPSERT id=1) ────────
                    new_cost_basis = cost_basis if gold_after > 0 else 0.0
                    cursor.execute(
                        """
                        INSERT INTO portfolio (
                            id, cash_balance, gold_grams, cost_basis_thb,
                            current_value_thb, unrealized_pnl, trades_today,
                            trades_this_session, updated_at, trailing_stop_level_thb
                        )
                        VALUES (1, %s, %s, %s, %s, %s,
                                COALESCE((SELECT trades_today FROM portfolio WHERE id=1), 0) + 1,
                                COALESCE((SELECT trades_this_session FROM portfolio WHERE id=1), 0) + 1,
                                %s, NULL)
                        ON CONFLICT (id) DO UPDATE SET
                            cash_balance             = EXCLUDED.cash_balance,
                            gold_grams               = EXCLUDED.gold_grams,
                            cost_basis_thb           = EXCLUDED.cost_basis_thb,
                            current_value_thb        = EXCLUDED.current_value_thb,
                            unrealized_pnl           = EXCLUDED.unrealized_pnl,
                            trades_today             = COALESCE(portfolio.trades_today, 0) + 1,
                            trades_this_session      = COALESCE(portfolio.trades_this_session, 0) + 1,
                            updated_at               = EXCLUDED.updated_at,
                            trailing_stop_level_thb  = NULL;
                        """,
                        (
                            cash_after,
                            gold_after,
                            new_cost_basis,
                            round(gold_after * price_per_gram, 2),  # current_value_thb
                            round(
                                gold_after * (price_per_gram - cost_basis), 2
                            ),  # unrealized_pnl
                            now_str,
                        ),
                    )

                # ── Commit: ทั้ง trade_log + portfolio ใน transaction เดียว ──
                conn.commit()

        except Exception as e:
            # rollback เกิดขึ้นอัตโนมัติจาก get_connection() context manager
            from logs.logger_setup import sys_logger

            sys_logger.error(
                f"record_emergency_sell_atomic FAILED — ROLLBACK | "
                f"grams={grams_to_sell} price={price_per_gram} reason={reason} | err={e}"
            )
            raise

        from logs.logger_setup import sys_logger

        sys_logger.info(
            f"record_emergency_sell_atomic OK — trade_id={trade_id} "
            f"SELL {grams_to_sell:.4f}g @ {price_per_gram:.2f} ฿/g "
            f"PnL={pnl_thb:+.2f} THB ({pnl_pct:+.2%})"
        )
        return trade_id

    def clear_trailing_stop(self) -> None:
        """
        Reset trailing_stop_level_thb = NULL ใน portfolio
        เรียกหลัง emergency sell หรือ manual clear
        """
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE portfolio SET trailing_stop_level_thb = NULL WHERE id = 1"
                )
            conn.commit()

    def get_trade_history(self, limit: int = 100) -> list[dict]:
        """ดึง trade history ทั้งหมด เรียงจากใหม่ไปเก่า"""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT t.*, r.signal, r.confidence, r.interval_tf, r.rationale
                    FROM trade_log t
                    LEFT JOIN runs r ON r.id = t.run_id
                    ORDER BY t.id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def get_pnl_summary(self) -> dict:
        """สรุป PnL รวมจาก trade_log ทั้งหมด"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT
                            COUNT(*)                                           AS total_trades,
                            SUM(CASE WHEN action='BUY'  THEN 1 ELSE 0 END)   AS buy_count,
                            SUM(CASE WHEN action='SELL' THEN 1 ELSE 0 END)    AS sell_count,
                            SUM(COALESCE(pnl_thb, 0))                         AS total_pnl_thb,
                            AVG(CASE WHEN pnl_thb IS NOT NULL
                                THEN pnl_pct END)                             AS avg_pnl_pct,
                            SUM(CASE WHEN pnl_thb > 0 THEN 1 ELSE 0 END)     AS win_count,
                            SUM(CASE WHEN pnl_thb < 0 THEN 1 ELSE 0 END)     AS loss_count
                        FROM trade_log
                    """)
                    row = cursor.fetchone()
        except Exception as e:
            sys_logger.error(f"get_pnl_summary FAILED: {e}")
            row = None

        if not row:
            return {
                "total_trades": 0,
                "buy_count": 0,
                "sell_count": 0,
                "total_pnl_thb": 0.0,
                "avg_pnl_pct": 0.0,
                "win_count": 0,
                "loss_count": 0,
                "win_rate": 0.0,
            }

        sell_count = row["sell_count"] or 0
        win_count = row["win_count"] or 0
        return {
            "total_trades": row["total_trades"] or 0,
            "buy_count": row["buy_count"] or 0,
            "sell_count": sell_count,
            "total_pnl_thb": round(row["total_pnl_thb"] or 0, 2),
            "avg_pnl_pct": round(row["avg_pnl_pct"] or 0, 4),
            "win_count": win_count,
            "loss_count": row["loss_count"] or 0,
            "win_rate": round(win_count / sell_count, 3) if sell_count > 0 else 0.0,
        }

    def get_monthly_growth(self) -> dict:
        """
        คำนวณ Growth P&L เทียบเดือนปัจจุบันกับเดือนที่แล้ว
        เพื่อนำไปโชว์ในกล่อง Total Realized P&L (+8.4% Growth)
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        WITH current_m AS (
                            SELECT SUM(COALESCE(pnl_thb, 0)) as pnl
                            FROM trade_log
                            WHERE action = 'SELL'
                              AND executed_at::timestamp >= date_trunc('month', CURRENT_DATE)
                        ),
                        last_m AS (
                            SELECT SUM(COALESCE(pnl_thb, 0)) as pnl
                            FROM trade_log
                            WHERE action = 'SELL'
                              AND executed_at::timestamp >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month')
                              AND executed_at::timestamp < date_trunc('month', CURRENT_DATE)
                        )
                        SELECT 
                            COALESCE((SELECT pnl FROM current_m), 0) as current_month_pnl,
                            COALESCE((SELECT pnl FROM last_m), 0) as last_month_pnl
                    """)
                    row = cursor.fetchone()

            curr = float(row["current_month_pnl"] or 0)
            last = float(row["last_month_pnl"] or 0)

            # คำนวณเปอร์เซ็นต์การเติบโต
            if last > 0:
                growth_pct = ((curr - last) / last) * 100
            elif curr > 0 and last <= 0:
                growth_pct = 100.0  # โตจาก 0 ถือว่าเป็น 100%
            elif curr < 0 and last <= 0:
                growth_pct = -100.0  # ติดลบเพิ่มขึ้น
            else:
                growth_pct = 0.0

            return {
                "current_month_thb": round(curr, 2),
                "last_month_thb": round(last, 2),
                "growth_pct": round(growth_pct, 2),
            }

        except Exception as e:
            from logs.logger_setup import sys_logger

            sys_logger.error(f"get_monthly_growth FAILED: {e}")
            return {"current_month_thb": 0.0, "last_month_thb": 0.0, "growth_pct": 0.0}

    def get_daily_cumulative_pnl(self, days: int = 30) -> list[dict]:
        """
        สร้างข้อมูล Time-series P&L สะสมย้อนหลัง (ค่าเริ่มต้น 30 วัน)
        สำหรับส่งให้ Recharts นำไปวาด Equity Growth Curve
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # ใช้ Window Function ของ PostgreSQL บวกสะสม (Cumulative Sum)
                    cursor.execute(
                        """
                        WITH daily_pnl AS (
                            SELECT 
                                date_trunc('day', executed_at::timestamp) as day_date,
                                SUM(COALESCE(pnl_thb, 0)) as daily_profit
                            FROM trade_log
                            WHERE action = 'SELL'
                              AND executed_at::timestamp >= CURRENT_DATE - (%s * INTERVAL '1 day')
                            GROUP BY 1
                        )
                        SELECT 
                            to_char(day_date, 'DD Mon') as display_date,
                            SUM(daily_profit) OVER (ORDER BY day_date ASC) as cumulative_profit
                        FROM daily_pnl
                        ORDER BY day_date ASC;
                    """,
                        (days,),
                    )
                    rows = cursor.fetchall()

            if not rows:
                return []

            # แปลงเป็น Format ที่ Recharts ต้องการ: [{ date: '15 Mar', profit: 4500 }, ...]
            return [
                {
                    "date": r["display_date"],
                    "profit": round(float(r["cumulative_profit"]), 2),
                }
                for r in rows
            ]

        except Exception as e:
            from logs.logger_setup import sys_logger

            sys_logger.error(f"get_daily_cumulative_pnl FAILED: {e}")
            return []
