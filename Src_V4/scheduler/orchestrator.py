import logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from config.settings import TIMEZONE, DRY_RUN, STATE_EMPTY, STATE_HOLDING
from config.settings import TP_ATR_MULTIPLIER, TP_BREAKEVEN_ATR_MULT, TP_SCORE_DROP_THRESH
from core.candle_builder import build_candles
from core.feature_engine import compute_features
from core.model_inference import run_inference
from core.signal_gate import evaluate_signal_gate
from core.signal_recorder import build_signal_record
from core.state_manager import get_current_state, set_state
from core.dynamic_tp_manager import DynamicTPManager
from db.supabase_writer import insert_signal, insert_bar_log, update_state
from notifier.discord_notifier import notify_buy_signal, notify_sell_signal, notify_heartbeat, notify_error, notify_dynamic_tp
from rationale.generator import build_trade_payload

TZ = pytz.timezone(TIMEZONE)
system_log  = logging.getLogger("system")
trading_log = logging.getLogger("trading")

_last_bar_time : str   = "N/A"
_last_score    : float = 0.0
_last_state    : str   = STATE_EMPTY

tp_manager = DynamicTPManager(
    atr_multiplier=TP_ATR_MULTIPLIER,
    breakeven_atr_mult=TP_BREAKEVEN_ATR_MULT,
    score_drop_threshold=TP_SCORE_DROP_THRESH
)

def run_signal_pipeline() -> None:
    global _last_bar_time, _last_score, _last_state
    now = datetime.now(TZ)
    system_log.info(f"[Job A] Pipeline started at {now.strftime('%H:%M:%S')}")
    try:
        candles_df = build_candles()
        features_row = compute_features(candles_df)
        if features_row["session"] == "Closed":
            system_log.info("[Job A] Market closed — skipping")
            return

        inference_result = run_inference(features_row)
        _last_bar_time = features_row["bar_time"]
        _last_score    = inference_result["ranker_score"]
        gate_result    = evaluate_signal_gate(inference_result, features_row)
        _last_state    = gate_result["state_before"]

        # ─── 🆕 TP Manager: Activate / Reset ─────────────────────────────────
        if gate_result["passed"]:
            if gate_result["signal_type"] == "BUY":
                sl_price = gate_result["hsh_ask"] - (features_row["F_ATR_48"] * 1.0)
                tp_manager.activate(
                    entry_ask=gate_result["hsh_ask"],
                    entry_score=gate_result["ranker_score"],
                    initial_bid=gate_result["hsh_bid"],
                    sl_price=sl_price
                )
            elif gate_result["signal_type"] == "SELL":
                tp_manager.reset()

        # ─── 🆕 TP Manager: Evaluate every M10 bar ───────────────────────────
        tp_trigger, tp_price, trail_level = tp_manager.update(
            current_bid=features_row["hsh_close_bid"],
            atr_48=features_row["F_ATR_48"],
            current_score=inference_result["ranker_score"]
        )
        if tp_trigger != "NONE":
            notify_dynamic_tp(tp_trigger, tp_price, trail_level, inference_result["ranker_score"], features_row["F_ATR_48"])

        # 🚨 FORCED EXIT LOGIC (SL Hit หรือ Trail Hit)
        if tp_trigger in ("TRAIL_HIT", "SL_HIT"):
            reason_text = "Trailing Stop Hit" if tp_trigger == "TRAIL_HIT" else "Stop Loss Hit"
            exit_bid_price = features_row["hsh_close_bid"]  # ✅ ใช้ Bid Price เป็นจุดออก
            system_log.info(f"[TP] {reason_text} @ {exit_bid_price:.2f}. Forcing SELL signal.")

            # 1. Override State → EMPTY
            update_state(STATE_EMPTY)
            set_state(STATE_EMPTY)

            # 2. บันทึก Forced SELL Record
            forced_signal_id = f"tp_{features_row['bar_time'][:19].replace('-','').replace(':','').replace('T','_')}"
            forced_sell_record = {
                "id"            : forced_signal_id,
                "bar_time"      : features_row["bar_time"],
                "session"       : features_row["session"],
                "signal_type"   : "SELL",
                "ranker_score"  : inference_result["ranker_score"],
                "state_before"  : "HOLDING",
                "hsh_ask_price" : features_row["hsh_close_ask"],
                "hsh_bid_price" : exit_bid_price,
                "xau_price"     : features_row["xau_close"],
                "atr_at_signal" : features_row["F_ATR_48"],
                "passed"        : True,
                "reject_reason" : f"FORCED_BY_{tp_trigger}",
                "dry_run"       : DRY_RUN,
                "features_snap" : inference_result["features_snap"],
                "created_at"    : datetime.now(TZ).isoformat(),
            }
            insert_signal(forced_sell_record)

            # 3. ✅ ใช้ Template Rationale เดิม + เติมเหตุผล Auto-Exit
            rationale_payload = build_trade_payload(
                signal_type   = "SELL",
                ranker_score  = inference_result["ranker_score"],
                shap_values   = inference_result.get("shap_values", {}),
                feature_names = inference_result.get("feature_names", []),
                current_ask   = features_row["hsh_close_ask"],
                current_bid   = exit_bid_price,
            )
            rationale_payload["rationale_text"] = (
                f"🤖 **Auto-Exit Trigger:** {reason_text} @ `{exit_bid_price:,.2f}` THB\n"
                f"{rationale_payload.get('rationale_text', '')}"
            )
            rationale_payload["execution_price"] = exit_bid_price

            # 4. แจ้ง Discord ผ่านโครงสร้างเดิม
            forced_gate_result = {
                "bar_time"      : features_row["bar_time"],
                "session"       : features_row["session"],
                "ranker_score"  : inference_result["ranker_score"],
                "hsh_bid"       : exit_bid_price,
                "xau_close"     : features_row["xau_close"]
            }
            notify_sell_signal(forced_gate_result, rationale_payload)

            # 5. Reset TP Manager & จบ Pipeline (กัน Duplicate)
            tp_manager.reset()
            trading_log.info(f"FORCED SELL executed by {tp_trigger} | Bid Price: {exit_bid_price:.2f}")
            return  # 🔚 จบรอบนี้ทันที

        # ─── P5: Build Signal Record ──────────────────────────────────────────
        rationale_payload = build_trade_payload(
            signal_type   = gate_result["signal_type"],
            ranker_score  = inference_result["ranker_score"],
            shap_values   = inference_result.get("shap_values", {}),
            feature_names = inference_result.get("feature_names", []),
            current_ask   = gate_result["hsh_ask"],
            current_bid   = gate_result["hsh_bid"],
        )
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

        # ─── Action & State Update ────────────────────────────────────────────
        if gate_result["passed"] and gate_result["signal_type"]:
            signal_type = gate_result["signal_type"]
            if signal_type == "BUY":
                update_state(STATE_HOLDING)
                set_state(STATE_HOLDING)
                notify_buy_signal(gate_result, rationale_payload)
                trading_log.info(f"BUY signal sent | score={_last_score:.4f}")
            elif signal_type == "SELL":
                update_state(STATE_EMPTY)
                set_state(STATE_EMPTY)
                notify_sell_signal(gate_result, rationale_payload)
                trading_log.info(f"SELL signal sent | score={_last_score:.4f}")
        else:
            trading_log.info(f"HOLD | state={_last_state} | score={_last_score:.4f} | reject={gate_result['reject_reason']}")

    except Exception as e:
        system_log.error(f"[Job A] Pipeline error: {e}", exc_info=True)
        notify_error("Job A — signal_pipeline", str(e))

def run_heartbeat() -> None:
    try:
        state = get_current_state()
        _last_state = state
        notify_heartbeat(state, _last_bar_time, _last_score)
        system_log.info(f"[Job C] Heartbeat sent | state={state}")
    except Exception as e:
        system_log.warning(f"[Job C] Heartbeat error: {e}")

def start_scheduler() -> None:
    scheduler = BlockingScheduler(timezone=TZ)
    scheduler.add_job(run_signal_pipeline, CronTrigger(minute="0,10,20,30,40,50", hour="0,1,6-23", day_of_week="mon-fri", timezone=TZ), id="signal_pipeline", name="M10 Signal Pipeline", max_instances=1, misfire_grace_time=60)
    scheduler.add_job(run_heartbeat, CronTrigger(minute=0, hour="0,1,6-23", day_of_week="mon-fri", timezone=TZ), id="heartbeat", name="System Heartbeat")
    system_log.info(f"Scheduler started | DRY_RUN={DRY_RUN} | Coverage: 06:00-01:59 BKK")
    scheduler.start()