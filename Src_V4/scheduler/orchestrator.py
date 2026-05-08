# scheduler/orchestrator.py
import logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config.settings import TIMEZONE, DRY_RUN, STATE_EMPTY, STATE_HOLDING
from core.candle_builder import build_candles
from core.feature_engine import compute_features
from core.model_inference import run_inference
from core.signal_gate import evaluate_signal_gate
from core.signal_recorder import build_signal_record
from core.state_manager import get_current_state, set_state
from db.supabase_writer import insert_signal, insert_bar_log, update_state
from notifier.discord_notifier import notify_buy_signal, notify_sell_signal, notify_heartbeat, notify_error
from rationale.generator import build_trade_payload
from notifier.trade_log_api import send_trade_log

# ─── Logging & Timezone ──────────────────────────────────────────────────────
TZ = pytz.timezone(TIMEZONE)
system_log  = logging.getLogger("system")
trading_log = logging.getLogger("trading")

# ─── In-Memory State for Heartbeat ───────────────────────────────────────────
_last_bar_time : str   = "N/A"
_last_score    : float = 0.0
_last_state    : str   = STATE_EMPTY


def run_signal_pipeline() -> None:
    """
    Job A — รันทุก 10 นาที
    ลำดับ: Candle → Feature → Inference(+SHAP) → Gate → Rationale → APIอาจารย์ → DB → Notify
    """
    global _last_bar_time, _last_score, _last_state
    now = datetime.now(TZ)
    system_log.info(f"[Job A] Pipeline started at {now.strftime('%H:%M:%S')}")

    try:
        # ─── P1: Build M10 Candles ────────────────────────────────────────────
        candles_df = build_candles()

        # ─── P2: Compute Features ─────────────────────────────────────────────
        features_row = compute_features(candles_df)

        # Early exit ถ้าตลาดปิด
        if features_row["session"] == "Closed":
            system_log.info("[Job A] Market closed — skipping")
            return

        # ─── P3: Model Inference (รวม SHAP Values) ────────────────────────────
        inference_result = run_inference(features_row)
        _last_bar_time = features_row["bar_time"]
        _last_score    = inference_result["ranker_score"]

        # ─── P4: Signal Gate & State Check ────────────────────────────────────
        gate_result = evaluate_signal_gate(inference_result, features_row)
        _last_state  = gate_result["state_before"]

        # ─── Rationale Generation (SHAP → Human-Readable Reason) ──────────────
        rationale_payload = build_trade_payload(
            signal_type   = gate_result["signal_type"],
            ranker_score  = inference_result["ranker_score"],
            shap_values   = inference_result["shap_values"],
            feature_names = inference_result["feature_names"],
            current_ask   = gate_result["hsh_ask"],
            current_bid   = gate_result["hsh_bid"],
        )

        # ─── เตรียมข้อมูลสำหรับ API อาจารย์ ───────────────────────────────────
        api_action = rationale_payload["signal_type"]  # BUY / SELL / HOLD
        api_price  = rationale_payload["execution_price"] if rationale_payload["execution_price"] is not None else "MARKET"
        api_reason = rationale_payload["rationale_text"]

        # ─── ยิง Trade Log API อาจารย์ (ทุกสัญญาณ รวม HOLD) ──────────────────
        # send_trade_log(action=api_action, price=api_price, reason=api_reason)

        # ─── P5: Build Signal Record (แนบ Rationale) ──────────────────────────
        signal_record = build_signal_record(gate_result, rationale_payload)

        # ─── P6: Write to Supabase ────────────────────────────────────────────
        insert_signal(signal_record)
        insert_bar_log({
            "bar_time"      : features_row["bar_time"],
            "session"       : features_row["session"],
            "state_at_bar"  : gate_result["state_before"],
            "ranker_score"  : inference_result["ranker_score"],
            "signal_passed" : gate_result["passed"],
            "signal_type"   : gate_result["signal_type"],
            "hsh_close_ask" : features_row["hsh_close_ask"],
            "hsh_close_bid" : features_row["hsh_close_bid"],
            "atr_48"        : features_row["F_ATR_48"],
            "features_snap" : signal_record["features_snap"],
        })

        # ─── Action & State Update (เฉพาะเมื่อผ่าน Gate) ─────────────────────
        if gate_result["passed"]:
            signal_type = gate_result["signal_type"]
            if signal_type == "BUY":
                # ✅ แจ้งเตือนอย่างเดียว — คุณตัดสินใจเอง
                notify_buy_signal(gate_result, rationale_payload)
                trading_log.info(
                    f"BUY signal sent (PENDING MANUAL) | "
                    f"score={_last_score:.4f} | ask={features_row['hsh_close_ask']:.2f}"
                )

            elif signal_type == "SELL":
                # ✅ แจ้งเตือนอย่างเดียว — คุณตัดสินใจเอง
                notify_sell_signal(gate_result, rationale_payload)
                trading_log.info(
                    f"SELL signal sent (PENDING MANUAL) | "
                    f"score={_last_score:.4f} | bid={features_row['hsh_close_bid']:.2f}"
                )
        else:
            # HOLD / Reject → ไม่เปลี่ยน State, ไม่แจ้ง Discord (กันสแปม)
            trading_log.info(
                f"HOLD | state={gate_result['state_before']} | "
                f"score={_last_score:.4f} | reason={gate_result['reject_reason']}"
            )

    except Exception as e:
        system_log.error(f"[Job A] Pipeline error: {e}", exc_info=True)
        notify_error("Job A — signal_pipeline", str(e))


def run_heartbeat() -> None:
    """
    Job C — รันทุก 1 ชั่วโมง (ตอนตลาดเปิด)
    แจ้งสถานะระบบ + แท่งล่าสุด + Score ล่าสุด
    """
    try:
        state = get_current_state()
        _last_state = state  # sync in-memory
        notify_heartbeat(state, _last_bar_time, _last_score)
        system_log.info(f"[Job C] Heartbeat sent | state={state}")
    except Exception as e:
        system_log.warning(f"[Job C] Heartbeat error: {e}")


def start_scheduler() -> None:
    """
    เริ่มต้น APScheduler
    - Job A: ทุก 10 นาที ครอบคลุม 06:00–01:59 (Cross-Midnight)
    - Job C: ทุก 1 ชั่วโมง ช่วงตลาดเปิด
    """
    scheduler = BlockingScheduler(timezone=TZ)

    # Job A — Signal Pipeline (M10)
    # ชั่วโมง 0,1 = 00:00-01:50 (Night session ข้ามเที่ยงคืน)
    # ชั่วโมง 6-23 = 06:00-23:50 (Morning + Afternoon + Night เริ่ม)
    scheduler.add_job(
        run_signal_pipeline,
        CronTrigger(
            minute="0,10,20,30,40,50",
            hour="0,1,6-23",
            day_of_week="mon-fri",
            timezone=TZ,
        ),
        id="signal_pipeline",
        name="M10 Signal Pipeline",
        max_instances=1,       # ป้องกัน job ทับกัน
        misfire_grace_time=60, # ยอม delay ได้ 60 วินาที
    )

    # Job C — Heartbeat (ทุกชั่วโมงตอนตลาดเปิด)
    scheduler.add_job(
        run_heartbeat,
        CronTrigger(
            minute=0,
            hour="0,1,6-23",
            day_of_week="mon-fri",
            timezone=TZ,
        ),
        id="heartbeat",
        name="System Heartbeat",
    )

    system_log.info(
        f"Scheduler started | DRY_RUN={DRY_RUN} | "
        f"Jobs: signal_pipeline (10min), heartbeat (1h) | "
        f"Coverage: 06:00-01:59 BKK (Mon-Fri)"
    )
    scheduler.start()