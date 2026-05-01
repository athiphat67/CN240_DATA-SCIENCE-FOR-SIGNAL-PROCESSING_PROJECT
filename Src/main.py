import json
import argparse
import os
import sys
import time
from logs.api_logger import send_trade_log
from dotenv import load_dotenv
import requests

load_dotenv()

# ── Path Setup ──────────────────────────────────────────────
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.join(current_dir, "data_engine"))

from agent_core.core.prompt import SkillRegistry, RoleRegistry
from agent_core.llm.client import OpenRouterClient
from data_engine.orchestrator import GoldTradingOrchestrator
from database.database import RunDatabase
from ui.core.services import init_services
from data_engine.extract_features import get_xgboost_feature
# ─────────────────────────────────────────────────────────────
# xgboost
# ─────────────────────────────────────────────────────────────

def get_xgboost_signal(raw_data: dict) -> str:
    """
    รับข้อมูลดิบ (Raw Data) -> สกัด Features -> ตัดข้อมูลที่ไม่เกี่ยวข้องออก -> ส่งให้โมเดล XGBoost บน Hugging Face ประมวลผล
    และรับค่ากลับมาเป็น 'BUY', 'SELL', หรือ 'HOLD'
    """
    # 1. สกัด Features ออกมาเป็น Dictionary ด้วยฟังก์ชันที่คุณเขียนไว้
    features = get_xgboost_feature(raw_data, as_dataframe=False)
    
    # 2. นำตัวแปรกลุ่ม Forex ออกจาก Features เพื่อโฟกัสที่ข้อมูลทองคำโดยตรง
    if "usd_thb" in features:
        del features["usd_thb"]

    # ดึงค่า API Config จากไฟล์ .env
    hf_token = os.getenv("HF_TOKEN")
    hf_api_url = os.getenv("HF_XGBOOST_URL") 

    if not hf_token or not hf_api_url:
        print("⚠️ [XGBoost] ข้ามการทำงาน: ไม่พบ HF_TOKEN หรือ HF_XGBOOST_URL ใน .env")
        return "HOLD"

    headers = {
        "Authorization": f"Bearer {hf_token}",
        "Content-Type": "application/json"
    }

    # จัดรูปแบบ Payload ตามที่ Hugging Face Inference API ต้องการ
    payload = {
        "inputs": features 
    }

    try:
        # กำหนด Timeout สั้นๆ ไว้ที่ 10 วินาที เพื่อรักษาความเร็วในการออกไม้เทรด
        response = requests.post(hf_api_url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        
        signal = "HOLD"
        # จัดการโครงสร้าง Response ที่อาจแตกต่างกันตามการตั้งค่าบน Hugging Face
        if isinstance(result, list) and len(result) > 0:
            if isinstance(result[0], dict):
                signal = result[0].get("label", "HOLD")
            else:
                signal = str(result[0])
        elif isinstance(result, dict):
            signal = result.get("label", result.get("prediction", "HOLD"))
            
        signal = signal.upper()
        
        if signal in ["BUY", "SELL", "HOLD"]:
            print(f"🌲 [XGBoost] ประมวลผลสำเร็จ ได้รับสัญญาณชี้เป้า: {signal}")
            return signal
        else:
            print(f"⚠️ [XGBoost] สัญญาณที่ได้ไม่ตรงรูปแบบ (ได้ '{signal}'), ใช้ HOLD แทน")
            return "HOLD"

    except requests.exceptions.Timeout:
        print("❌ [XGBoost] API Timeout: Hugging Face ตอบสนองช้าเกินไป ข้ามไปใช้ HOLD")
        return "HOLD"
    except Exception as e:
        print(f"❌ [XGBoost] API Error: {e}")
        return "HOLD"
    
# ─────────────────────────────────────────────────────────────
# Print helpers  (เหมือน main.py ทุกอย่าง)
# ─────────────────────────────────────────────────────────────

def _sep(char="=", n=62): print(char * n)


def print_voting(voting_result: dict) -> None:
    _sep()
    breakdown = voting_result.get("voting_breakdown", {})
    for sig in ["BUY", "SELL", "HOLD"]:
        v = breakdown.get(sig, {})
        if v.get("count", 0) == 0:
            continue
        icon = {"BUY": "🟢", "SELL": "🔴"}.get(sig, "🟡")
        ivs  = ", ".join(v.get("intervals", []))
        print(f"  {icon} {sig:4s}  votes:{v['count']}  "
              f"avg_conf:{v['avg_conf']:.0%}  "
              f"w_score:{v['weighted_score']:.0%}  [{ivs}]")
    _sep("-")
    icon = {"BUY": "🟢", "SELL": "🔴"}.get(voting_result["final_signal"], "🟡")
    print(f"  {icon} FINAL : {voting_result['final_signal']}  "
          f"({voting_result['weighted_confidence']:.0%} confidence)")
    _sep()


def print_interval_details(interval_results: dict) -> None:
    print("\n  Per-Interval Breakdown:")
    for iv, ir in interval_results.items():
        icon = {"BUY": "🟢", "SELL": "🔴"}.get(ir["signal"], "🟡")
        fb   = f"  ⚠ fallback←{ir['fallback_from']}" if ir.get("is_fallback") else ""
        print(f"    {iv:5s}  {icon} {ir['signal']:4s}  "
              f"conf:{ir['confidence']:.0%}  "
              f"via:{ir.get('provider_used','?')}{fb}")


def print_result(result: dict) -> None:
    if result["status"] == "error":
        _sep()
        print(f"  ❌ FAILED: {result['error']}")
        _sep()
        return

    voting = result["voting_result"]
    ivr    = result["data"]["interval_results"]

    print_voting(voting)
    print_interval_details(ivr)

    best_iv = max(ivr.items(), key=lambda x: x[1]["confidence"])[0]
    best    = ivr[best_iv]
    print(f"\n  Best Interval  : {best_iv}")
    print(f"  Entry Price    : {best.get('entry_price', 'N/A')}")
    print(f"  Stop Loss      : {best.get('stop_loss',  'N/A')}")
    print(f"  Take Profit    : {best.get('take_profit','N/A')}")
    print(f"  Rationale      : {(best.get('rationale') or '')[:200]}")

    run_id = result.get("run_id")
    if run_id:
        print(f"\n  ✅ Saved to DB  : run_id={run_id}")
    else:
        print("\n  ℹ  DB save skipped (--no-save)")

    market_open = result.get("market_open", True)
    if not market_open:
        print("\n  ⚠  ตลาดทองไทยปิดอยู่ (weekend/holiday) — ราคาอาจล่าช้า")

    attempt = result.get("attempt", 1)
    if attempt > 1:
        print(f"\n  ⚠  Used attempt {attempt} (retried {attempt-1} time(s))")
    _sep()


# ─────────────────────────────────────────────────────────────
# Provider helpers  (ส่วนที่เพิ่มใหม่)
# ─────────────────────────────────────────────────────────────

def _resolve_provider_label(provider_str: str) -> str:
    """
    แปลง provider string → label สำหรับ print
    "openrouter:claude-haiku" → "openrouter [anthropic/claude-haiku-4-5]"
    """
    if provider_str.startswith("openrouter:"):
        _, model_part = provider_str.split(":", 1)
        full = OpenRouterClient.resolve_model(model_part)
        return f"openrouter [{full}]"
    if provider_str == "openrouter":
        return f"openrouter [{OpenRouterClient.DEFAULT_MODEL}]"
    return provider_str


def build_runtime(*, no_save: bool = False) -> dict:
    """Build registries/orchestrator/services shared by CLI and Dashboard."""
    skill_registry = SkillRegistry()
    skill_registry.load_from_json(
        os.path.join(current_dir, "agent_core", "config", "skills.json")
    )
    role_registry = RoleRegistry(skill_registry)
    role_registry.load_from_json(
        os.path.join(current_dir, "agent_core", "config", "roles.json")
    )

    orchestrator = GoldTradingOrchestrator()
    db = None if no_save else RunDatabase()
    services = init_services(skill_registry, role_registry, orchestrator, db)

    return {
        "skill_registry": skill_registry,
        "role_registry": role_registry,
        "orchestrator": orchestrator,
        "db": db,
        "services": services,
    }


def run_analysis_once(
    args: argparse.Namespace,
    services: dict,
    *,
    emit_logs: bool = True,
) -> dict:
    """Run one analysis cycle using the same logic as CLI main loop."""
    provider_label = _resolve_provider_label(args.provider)
    if emit_logs:
        print(f"\n[goldtrader] provider={provider_label}  period={args.period}  "
              f"intervals={args.intervals}  skip_fetch={args.skip_fetch}  "
              f"save_db={not args.no_save}")

        if args.skip_fetch:
            print("[goldtrader] Skipping data fetch — using existing data.\n")

        print("[goldtrader] Running analysis...\n")

    return services["analysis"].run_analysis(
        provider=args.provider,
        period=args.period,
        intervals=args.intervals,
        bypass_session_gate=getattr(args, "bypass_session_gate", False),
    )


def send_trade_log_from_result(result: dict, *, emit_logs: bool = True) -> None:
    """Send trade log with the same policy/fields as CLI main loop."""
    if result.get("status") != "success":
        return

    action = result["voting_result"]["final_signal"]
    ivr = result["data"]["interval_results"]
    best_iv = max(ivr.items(), key=lambda x: x[1]["confidence"])[0]
    best_result = ivr[best_iv]

    price = best_result.get("entry_price") or "MARKET"
    rationale = best_result.get("rationale") or f"Auto-generated signal based on {action} decision"
    confidence = result["voting_result"]["weighted_confidence"]
    stop_loss = best_result.get("stop_loss", 0.0)
    take_profit = best_result.get("take_profit", 0.0)

    team_api_key = os.getenv("TEAM_API_KEY")
    if not team_api_key:
        if emit_logs:
            print("\n❌ [ERROR] ไม่พบ TEAM_API_KEY กรุณาตรวจสอบไฟล์ .env ของคุณ")
        return

    if emit_logs:
        print("\n[goldtrader] Sending customized Trade Log to API...")
        
    print(f"Action: {action}")
    print(f"Price:  {price}")
    print(f"Reason: {rationale}")

    send_trade_log(
        action=action,
        price=price,
        reason=reason,
        api_key=team_api_key,
    )


# ─────────────────────────────────────────────────────────────
# Arg parser
# ─────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="goldtrader v3.4 — ReAct LLM trading agent",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--provider",
        default="gemini",
        metavar="PROVIDER",
        help=(
            "LLM provider (default: gemini-3.1-flash-lite-preview)\n"
            "\n"
            "Direct providers:\n"
            "  gemini | openai | claude | groq | deepseek | ollama | mock\n"
            "\n"
            "OpenRouter (ต้องมี OPENROUTER_API_KEY ใน .env):\n"
            "  openrouter                  — ใช้ default model\n"
            "  openrouter:<shortcut>       — ใช้ shortcut\n"
            "  openrouter:<full/model-id>  — ระบุ full model name\n"
            "\n"
            "OpenRouter shortcuts:\n"
            "  gpt-5o-mini      → openai/gpt-5o-mini\n"
            "  claude-haiku-3-5 → anthropic/claude-3-5-haiku-20241022\n"
            "  nemotron-super   → nvidia/llama-3.1-nemotron-ultra-253b-v1:free\n"
            "  claude-haiku     → anthropic/claude-haiku-4-5\n"
            "  gpt-5-mini       → openai/gpt-5-mini\n"
            "  llama-70b        → meta-llama/llama-3.3-70b-instruct\n"
            "  grok-mini        → x-ai/grok-3-mini\n"
            "  mistral-small    → mistralai/mistral-small-3.2-24b-instruct-2506\n"
            "\n"
            "Examples:\n"
            "  --provider gemini-3.1-flash-lite-preview\n"
            "  --provider openrouter\n"
            "  --provider openrouter:claude-haiku\n"
            "  --provider openrouter:llama-70b\n"
            "  --provider openrouter:anthropic/claude-haiku-4-5\n"
        ),
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="แสดง OpenRouter model shortcuts ทั้งหมด แล้วออก",
    )
    parser.add_argument("--period",     default="7d",
                        help="Data period: 1d 3d 5d 7d 14d 1mo 2mo 3mo")
    parser.add_argument("--intervals",  nargs="+", default=["15m"],
                        help="Candle intervals: 1m 5m 15m 30m 1h 4h 1d 1w")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip fetching new market data (ใช้ข้อมูลเดิม)")
    parser.add_argument("--no-save",    action="store_true",
                        help="Do not save result to database")
    parser.add_argument("--output",     default="Output/result_output.json",
                        help="Path to save JSON result")
    return parser


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    interval_seconds = 300  # ตั้งค่า 10 นาที (600 วินาที), = 0 ปิด auto run

    # parse args ครั้งเดียวนอก loop — ไม่ re-parse ทุก cycle
    parser = _build_parser()
    args   = parser.parse_args()

    # --list-models: แสดงรายการแล้วออกเลย ไม่ต้อง loop
    if args.list_models:
        OpenRouterClient.list_models()
        return

    # ── WatcherEngine: สร้างครั้งเดียวก่อน loop ─────────────────────────
    # (import ที่นี่เพื่อไม่ให้ crash ถ้า engine ยังไม่มี — graceful fallback)
    _watcher = None
    try:
         from engine.engine import WatcherEngine

         # สร้าง orchestrator + db ชั่วคราวสำหรับ watcher init
         # (watcher ใช้ analysis_service ที่สร้างใน loop แรก ไม่ได้ ต้องสร้างก่อน)
         _w_skill = SkillRegistry()
         _w_skill.load_from_json(os.path.join(current_dir, "agent_core", "config", "skills.json"))
         _w_role  = RoleRegistry(_w_skill)
         _w_role.load_from_json(os.path.join(current_dir, "agent_core", "config", "roles.json"))
         _w_orch  = GoldTradingOrchestrator()
         _w_db    = RunDatabase()
         _w_svc   = init_services(_w_skill, _w_role, _w_orch, _w_db)

         _watcher = WatcherEngine(
             analysis_service  = _w_svc["analysis"],
             data_orchestrator = _w_orch,
             watcher_config    = {
                 "provider":  args.provider,
                 "period":    args.period,
                 "interval":  '5m',
             },
         )
         _watcher.start()
         print("🔭 WatcherEngine started (background thread)")
    except Exception as _we:
         print(f"⚠️  WatcherEngine not started: {_we}")

    while True:
        try:
            print(f"\n🚀 Starting cycle at {time.strftime('%Y-%m-%d %H:%M:%S')}")

            runtime = build_runtime(no_save=args.no_save)
            services = runtime["services"]
            result = run_analysis_once(args, services, emit_logs=True)

            # ── 6. Print result ────────────────────────────────────────
            print_result(result)
            send_trade_log_from_result(result, emit_logs=True)

            # ── 7. Save JSON output ────────────────────────────────────
            # if args.output and result["status"] == "success":
            #     out_path = os.path.abspath(args.output)
            #     os.makedirs(os.path.dirname(out_path), exist_ok=True)
            #     safe = {
            #         "status":           result["status"],
            #         "final_signal":     result["voting_result"]["final_signal"],
            #         "confidence":       result["voting_result"]["weighted_confidence"],
            #         "voting_breakdown": result["voting_result"]["voting_breakdown"],
            #         "interval_details": result["voting_result"]["interval_details"],
            #         "run_id":           result.get("run_id"),
            #         "attempt":          result.get("attempt"),
            #         "market_open":      result.get("market_open"),
            #     }
            #     with open(out_path, "w", encoding="utf-8") as f:
            #         json.dump(safe, f, ensure_ascii=False, indent=2)
            #     print(f"\n✅ Saved JSON result → {out_path}")

            if interval_seconds == 0:
                break

            print(f"\n😴 Sleeping for {interval_seconds // 60} minutes...")
            time.sleep(interval_seconds)

        except KeyboardInterrupt:
            print("\n👋 Stopped by user")
            break
        except Exception as e:
            print(f"❌ Error in loop: {e}")
            time.sleep(60)  # พัก 1 นาทีแล้วลองใหม่ถ้า error


if __name__ == "__main__":
    main()
    
    
# --- Anthropic Models ---
# python main.py --provider openrouter:claude-haiku-4-5
# python main.py --provider openrouter:claude-haiku-3-5
# python main.py --provider openrouter:claude-sonnet-4-6

# --- OpenAI Models ---
# python main.py --provider openrouter:gpt-5-3-codex
# python main.py --provider openrouter:gpt-5-mini
# python main.py --provider openrouter:gpt-5-2-chat
# python main.py --provider openrouter:gpt-4o-mini

# --- Google Gemini Models ---
# python main.py --provider openrouter:gemini-3-1-flash-preview
# python main.py --provider openrouter:gemini-2-5-flash-lite
# python main.py --provider openrouter:gemini-2-0-flash-lite

# --- Other Models ---
# python main.py --provider openrouter:llama-70b
# python main.py --provider openrouter:grok-mini
# python main.py --provider openrouter:mistral-small
# python main.py --provider openrouter:nemotron-super
# python main.py --provider openrouter:deepseek-v-3-2

# --- Utility ---
# รันตัว Default (Gemini 3.1 Flash Lite Preview)
# python main.py

# ดูรายชื่อโมเดลทั้งหมด
# python main.py --list-models

# ------- docker run ----------
# docker run -it --env-file .env ghcr.io/athiphat67/gold-trading-agent:latest python main.py --provider openrouter:gemini-3-1-flash-lite-preview