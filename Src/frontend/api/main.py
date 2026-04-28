from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel   
import argparse                  
import sys
import threading
import importlib.util
try:
    from cachetools import TTLCache
    _HAS_CACHETOOLS = True
except ImportError:
    _HAS_CACHETOOLS = False

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request 

from datetime import datetime, timezone
import os
from dotenv import load_dotenv
import json

app = FastAPI(title="Nakkhutthong API")

# origins = [
#     "http://localhost:5173", # ต้องเป๊ะแบบนี้ ไม่มี / ต่อท้าย
#     "http://127.0.0.1:5173",
#     "https://cn-240-data-science-for-signal-git-74908c-athiphat67s-projects.vercel.app", 
# ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. หาตำแหน่งของไฟล์ .env ให้แน่ชัด
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir)) # ย้อน 2 ชั้น
dotenv_path = os.path.join(project_root, '.env')

if project_root not in sys.path:
    sys.path.insert(0, project_root)


def _load_agent_cli():
    """โหลด Src/main.py ภายใต้ชื่อ module เฉพาะ เพื่อเลี่ยง circular import กับ uvicorn."""
    agent_main_path = os.path.join(project_root, "main.py")
    spec = importlib.util.spec_from_file_location("agent_cli_main", agent_main_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load agent main module from {agent_main_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_cli_main"] = module
    spec.loader.exec_module(module)
    return module


agent_cli = _load_agent_cli()  # Import ไฟล์ main.py หลักของคุณมาใช้งาน
# --------------------------------------------------------------------

# 2. โหลดด้วย path ที่ระบุ
load_dotenv(dotenv_path)

# 3. ลอง Print เช็คดูว่าเจอค่าไหม (กันพลาด)
db_url = os.getenv("DATABASE_URL")
if not db_url:
    print(f"❌ Error: ไม่พบ DATABASE_URL ในไฟล์ที่ {dotenv_path}")
else:
    print(f"✅ โหลด DATABASE_URL เรียบร้อยแล้ว")

# หลังจากนั้นค่อย Initialize RunDatabase()
from database.database import RunDatabase
db = RunDatabase()
from psycopg2.extras import RealDictCursor
from supabase import create_client, Client

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# ─── In-Memory TTL Cache ───────────────────────────────────────────────────────
# ใช้ cachetools.TTLCache — ถ้าไม่ได้ install ให้ fallback เป็น dict ธรรมดา (ไม่มี TTL)
# ติดตั้งด้วย: pip install cachetools
_cache_lock = threading.Lock()

def _make_cache(ttl: int):
    if _HAS_CACHETOOLS:
        return TTLCache(maxsize=1, ttl=ttl)
    return {}  # fallback: ไม่มี TTL (cache จนกว่า server จะ restart)

_cache = {
    "gold_prices":      _make_cache(30),    # สด 30 วิ
    "portfolio":        _make_cache(15),    # สด 15 วิ
    "market_bias":      _make_cache(60),    # สด 1 นาที
    "agent_health":     _make_cache(60),
    "recent_signals":   _make_cache(20),
    "active_pos":       _make_cache(15),
    "market_state":     _make_cache(30),
    "latest_signal":    _make_cache(20),
    "signal_stats":     _make_cache(60),
    "signal_analytics": _make_cache(60),
    "history_summary":  _make_cache(30),
    "market_snapshot":  _make_cache(30),
    "hsh_live":         _make_cache(20),
    "market_news":      _make_cache(120),   # ข่าวเปลี่ยนช้า cache 2 นาที
    "backtest_summary": _make_cache(300),   # backtest ไม่ค่อยเปลี่ยน cache 5 นาที
    "perf_chart":       _make_cache(30),
    "models":           _make_cache(3600),  # model list ไม่เปลี่ยน cache 1 ชม.
}

def _cache_get(key: str):
    """ดึงค่าจาก cache thread-safe — คืน (found, value)"""
    with _cache_lock:
        c = _cache.get(key, {})
        if "v" in c:
            return True, c["v"]
    return False, None

def _cache_set(key: str, value):
    """เก็บค่าลง cache thread-safe"""
    with _cache_lock:
        _cache[key]["v"] = value


def _cache_invalidate(*keys: str):
    """ล้าง cache เฉพาะ key ที่เกี่ยวข้องหลังมีการแก้ข้อมูล"""
    with _cache_lock:
        for key in keys:
            cache_bucket = _cache.get(key)
            if cache_bucket is not None:
                cache_bucket.clear()


def _build_portfolio_payload(result: dict) -> dict:
    cost_basis = float(result.get('cost_basis_thb') or 0.0)
    gold_grams = float(result.get('gold_grams') or 0.0)
    unrealized_pnl = float(result.get('unrealized_pnl') or 0.0)
    available_cash = float(result.get('cash_balance', 0))

    total_cost = cost_basis * gold_grams
    pnl_percent = round((unrealized_pnl / total_cost) * 100, 2) if total_cost > 0 else 0.0
    total_equity = available_cash + total_cost + unrealized_pnl

    return {
        "available_cash": available_cash,
        "cash_balance": available_cash,
        "gold_grams": gold_grams,
        "cost_basis_thb": cost_basis,
        "current_value_thb": float(result.get('current_value_thb') or 0.0),
        "unrealized_pnl": unrealized_pnl,
        "pnl_percent": pnl_percent,
        "trades_today": int(result.get('trades_today', 0)),
        "total_equity": total_equity,
        "updated_at": result.get("updated_at") or "",
        "trailing_stop_level_thb": (
            round(float(result.get("trailing_stop_level_thb")), 4)
            if result.get("trailing_stop_level_thb") is not None else None
        ),
    }

# ─────────────────────────────────────────────────────────────────────────────

# [🔥 ส่วนที่ต้องเพิ่มใหม่] โหลด Runtime ของ AI Agent เตรียมไว้ตอนเปิด Server
print("Loading Agent Runtime...")
runtime = agent_cli.build_runtime(no_save=False) # ใช้ no_save=False เพื่อให้มันเซฟลง DB คุณได้
print("Agent Runtime Loaded!")

# -------------------------------------------------------------
# API Endpoints (ใช้ db instance โดยตรง)
# -------------------------------------------------------------

# [🔥 ส่วนที่ต้องเพิ่มใหม่] Schema และ Endpoint สำหรับให้หน้าเว็บกดยิง Agent
class AnalyzeRequest(BaseModel):
    provider: str
    period: str = "7d"
    intervals: list[str] = ["15m"]


@app.post("/api/analyze")
def trigger_analysis(req: AnalyzeRequest): # ✅ ลบ async ออกแล้ว (เหลือแค่ def)
    args = argparse.Namespace(
        provider=req.provider,
        period=req.period,
        intervals=req.intervals,
        skip_fetch=False,
        no_save=False 
    )
    # พอไม่มี async, FastAPI จะโยนงานนี้ไปทำใน Worker Thread 
    # ทำให้ Agent ของคุณสามารถเรียก asyncio.run() ข้างในได้อย่างอิสระครับ
    result = agent_cli.run_analysis_once(args, runtime["services"], emit_logs=False)
    return result

@app.get("/api/models")
async def get_models():
    found, cached = _cache_get("models")
    if found:
        return cached
    result = {
        "models": [
            # 🟢 Google Gemini Family
            {"id": "openrouter:gemini-3-1-flash-lite-preview", "name": "Gemini 3.1 Flash Lite Preview (Default)"},
            
            
        ]
    }
    _cache_set("models", result)
    return result

# -------------------------------------------------------------
# API Endpoints (ใช้ db instance โดยตรง)
# -------------------------------------------------------------

@app.get("/api/latest-signal")
def get_latest_signal():
    found, cached = _cache_get("latest_signal")
    if found:
        return cached
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                query = "SELECT *, 'AI AGENT' as provider FROM llm_logs WHERE signal IS NOT NULL ORDER BY id DESC LIMIT 1;"
                cursor.execute(query)
                result = cursor.fetchone()
                if result:
                    _cache_set("latest_signal", result)
                    return result
                raise HTTPException(status_code=404, detail="No signals found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/signals/{signal_id}")
def get_signal_detail(signal_id: int):
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM llm_logs WHERE id = %s", (signal_id,))
                result = cursor.fetchone()
                if result:
                    return result
                raise HTTPException(status_code=404, detail="Signal not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/portfolio")
def get_portfolio_data():
    found, cached = _cache_get("portfolio")
    if found:
        return cached
    try:
        result = db.get_portfolio()
        payload = _build_portfolio_payload(result)
        _cache_set("portfolio", payload)
        return payload
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/portfolio/add-funds")
def add_portfolio_funds(amount: float = Query(...)):
    amount = float(amount or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    try:
        portfolio = db.get_portfolio()
        portfolio["cash_balance"] = round(float(portfolio.get("cash_balance", 0.0)) + amount, 2)
        db.save_portfolio(portfolio)

        payload = _build_portfolio_payload(portfolio)
        _cache_invalidate("portfolio", "history_summary", "notifications")
        _cache_set("portfolio", payload)
        return payload
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/portfolio/withdraw-funds")
def withdraw_portfolio_funds(amount: float = Query(...)):
    amount = float(amount or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    try:
        portfolio = db.get_portfolio()
        available_cash = round(float(portfolio.get("cash_balance", 0.0)), 2)
        if amount > available_cash:
            raise HTTPException(status_code=400, detail="Withdrawal amount exceeds available cash balance")

        portfolio["cash_balance"] = round(available_cash - amount, 2)
        db.save_portfolio(portfolio)

        payload = _build_portfolio_payload(portfolio)
        _cache_invalidate("portfolio", "history_summary", "notifications")
        _cache_set("portfolio", payload)
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/portfolio/manual-update")
def manual_update_portfolio(
    cash_balance: float | None = Query(None),
    gold_grams: float | None = Query(None),
    cost_basis_thb: float | None = Query(None),
    current_value_thb: float | None = Query(None),
    unrealized_pnl: float | None = Query(None),
    trades_today: int | None = Query(None),
    trailing_stop_level_thb: float | None = Query(None),
):
    updates = {
        "cash_balance": cash_balance,
        "gold_grams": gold_grams,
        "cost_basis_thb": cost_basis_thb,
        "current_value_thb": current_value_thb,
        "unrealized_pnl": unrealized_pnl,
        "trades_today": trades_today,
        "trailing_stop_level_thb": trailing_stop_level_thb,
    }
    if all(value is None for value in updates.values()):
        raise HTTPException(status_code=400, detail="At least one portfolio field must be provided")

    try:
        portfolio = db.get_portfolio()

        for key, value in updates.items():
            if value is None:
                continue
            if key == "trades_today":
                if int(value) < 0:
                    raise HTTPException(status_code=400, detail="trades_today cannot be negative")
                portfolio[key] = int(value)
            else:
                if key in {"cash_balance", "gold_grams", "current_value_thb"} and float(value) < 0:
                    raise HTTPException(status_code=400, detail=f"{key} cannot be negative")
                portfolio[key] = float(value)

        db.save_portfolio(portfolio)

        payload = _build_portfolio_payload(portfolio)
        _cache_invalidate("portfolio", "history_summary", "notifications")
        _cache_set("portfolio", payload)
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/gold-prices")
def get_gold_prices():
    try:
        # 💡 เปลี่ยนชื่อ table ตรงนี้เป็น gold_prices_hsh
        response = supabase.table("gold_prices_hsh").select("*").order("timestamp", desc=True).limit(1).execute()
        
        if response.data:
            data = response.data[0]
            result = {
                "hsh_sell": data.get("ask_96"), 
                "hsh_buy": data.get("bid_96"),
                "spot_price": data.get("spot_price"),
                "usd_thb": data.get("usd_thb"),
            }
            return result
            
        raise HTTPException(status_code=404, detail="No gold data found in Supabase")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/recent-signals")
def get_recent_signals(limit: int = 20):
    # found, cached = _cache_get("recent_signals")
    # if found:
    #     return cached
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT id, logged_at, interval_tf, entry_price, take_profit, stop_loss, signal, confidence
                    FROM llm_logs 
                    WHERE signal IS NOT NULL 
                    ORDER BY id DESC LIMIT %s;
                """, (limit,))
                result = cursor.fetchall()
                _cache_set("recent_signals", result)
                return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/market-state")
def get_market_state():
    # found, cached = _cache_get("market_state")
    # if found: return cached
        
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT market_snapshot FROM runs WHERE market_snapshot IS NOT NULL ORDER BY id DESC LIMIT 1")
                row = cursor.fetchone()
        
        if row and row.get("market_snapshot"):
            snapshot = row["market_snapshot"]
            
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)
            
            # แกะข้อมูลราคา
            market_data = snapshot.get("market_data", {})
            thai_gold = market_data.get("thai_gold_thb", {})
            spot_usd = market_data.get("spot_price_usd", {})
            
            # แกะข้อมูล Indicator
            tech = snapshot.get("technical_indicators", {})
            
            result = {
                "spot_price": spot_usd.get("price_usd_per_oz"),
                "ask_96": thai_gold.get("sell_price_thb"),
                "bid_96": thai_gold.get("buy_price_thb"),
                "rsi_14": tech.get("rsi", {}).get("value"),
                # ดึง trend ("downtrend") มาทำเป็นตัวพิมพ์ใหญ่ให้เข้ากับ UI ("DOWNTREND")
                "trend": tech.get("trend", {}).get("trend", "").upper(), 
                "macd_hist": tech.get("macd", {}).get("histogram"),
                "ema_20": tech.get("trend", {}).get("ema_20"),
                "ema_50": tech.get("trend", {}).get("ema_50"),
                "timestamp": tech.get("calculated_at") # ใช้เวลาจาก calculated_at
            }
            # _cache_set("market_state", result)
            return result
            
        raise HTTPException(status_code=404, detail="No market data found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
def sync_latest_price():
    try:
        # ดึงแค่แถวเดียวล่าสุดจาก Supabase
        response = supabase.table("gold_prices_ig").select("*").order("timestamp", desc=True).limit(1).execute()
        if response.data:
            row = response.data[0]
            with db.get_connection() as conn:
                with conn.cursor() as cursor:
                    # อัปเดตข้อมูลล่าสุดลง Render
                    cursor.execute("""
                        INSERT INTO gold_prices_ig (timestamp, ask_96, bid_96, spot_price, usd_thb)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (timestamp) DO NOTHING;
                    """, (row['timestamp'], row['ask_96'], row['bid_96'], row['spot_price'], row['usd_thb']))
                conn.commit()
    except Exception as e:
        print(f"Sync failed: {e}")
        
from datetime import datetime

@app.get("/api/performance-chart")
def get_performance_chart(limit: int = 50):
    found, cached = _cache_get("perf_chart")
    if found:
        return cached
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    WITH latest_data AS (
                        SELECT 
                            run_at as timestamp,
                            id as "signalId",
                            signal as action,
                            gold_price_thb as price
                        FROM runs
                        WHERE gold_price_thb IS NOT NULL
                        ORDER BY run_at DESC
                        LIMIT %s
                    )
                    SELECT * FROM latest_data 
                    ORDER BY timestamp ASC;
                """, (limit,))
                
                rows = cursor.fetchall()
                formatted_data = []

                for r in rows:
                    dt_str = r['timestamp'].replace('Z', '+00:00')
                    try:
                        dt = datetime.fromisoformat(dt_str)
                        time_display = dt.strftime('%d %b %H:%M')
                    except Exception:
                        time_display = r['timestamp']
                    
                    formatted_data.append({
                        "time": time_display,
                        "price": float(r['price']),
                        "signalId": r['signalId'],
                        "action": r['action'] if r['action'] in ['BUY', 'SELL', 'HOLD'] else None
                    })
                
                _cache_set("perf_chart", formatted_data)
                return formatted_data
    except Exception as e:
        print(f"Error in /api/performance-chart: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch chart data")

from datetime import datetime
@app.get("/api/active-positions")
def get_active_positions():
    found, cached = _cache_get("active_pos")
    if found:
        return cached
    try:
        # 1. ดึงข้อมูล Portfolio ของจริงว่าตอนนี้ถือทองอยู่ไหม
        portfolio = db.get_portfolio()
        gold_grams = float(portfolio.get('gold_grams') or 0.0)

        # ถ้าไม่มีทองถืออยู่เลย (gold_grams <= 0) แปลว่าพอร์ตว่าง ไม่มี Position เปิดอยู่
        if gold_grams <= 0:
            _cache_set("active_pos", [])
            return []

        cost_basis = float(portfolio.get('cost_basis_thb') or 0.0)

        # 2. ดึงราคาทองคำปัจจุบันจาก Database เพื่อเอามาคำนวณกำไร/ขาดทุน
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT bid_96 FROM gold_prices_ig ORDER BY timestamp DESC LIMIT 1")
                latest_price_row = cursor.fetchone()
                
                cursor.execute("""
                    SELECT take_profit, stop_loss, logged_at 
                    FROM llm_logs 
                    WHERE signal = 'BUY' 
                    ORDER BY id DESC LIMIT 1
                """)
                latest_signal = cursor.fetchone()

        current_price = float(latest_price_row['bid_96']) if latest_price_row else cost_basis

        # 3. คำนวณ PnL (กำไร/ขาดทุน) ของจริง
        total_cost = cost_basis * gold_grams
        current_value = current_price * gold_grams
        pnl = current_value - total_cost
        pnl_percent = round((pnl / total_cost) * 100, 2) if total_cost > 0 else 0.0

        open_time = "Active Hold"
        if latest_signal and latest_signal['logged_at']:
            dt = latest_signal['logged_at']
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            open_time = dt.strftime('%d %b, %H:%M')

        result = [{
            "id": "POS-REAL-1",
            "asset": "XAU/THB (96.5%)",
            "type": "BUY",
            "size": f"{round(gold_grams, 4)} g", 
            "entry": cost_basis,
            "current": current_price,
            "tp": float(latest_signal['take_profit'] or 0) if latest_signal else 0,
            "sl": float(latest_signal['stop_loss'] or 0) if latest_signal else 0,
            "openTime": open_time,
            "pnl": round(pnl, 2),
            "pnlPercent": pnl_percent
        }]
        _cache_set("active_pos", result)
        return result

    except Exception as e:
        print(f"Error fetching real active positions: {e}")
        return []

@app.get("/api/market-bias")
def get_market_bias():
    found, cached = _cache_get("market_bias")
    if found:
        return cached
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT signal, confidence, rationale 
                    FROM runs 
                    WHERE signal IS NOT NULL
                    ORDER BY id DESC LIMIT 1
                """)
                result = cursor.fetchone()
        
        if result:
            sig = result.get('signal', 'HOLD')
            direction = "Neutral"
            if sig == "BUY": direction = "Bullish"
            elif sig == "SELL": direction = "Bearish"

            payload = {
                "direction": direction,
                "conviction": result.get('confidence') or 0,
                "reason": result.get('rationale') or "Analysis in progress..."
            }
            _cache_set("market_bias", payload)
            return payload
        
        fallback = {"direction": "Neutral", "conviction": 0, "reason": "No recent runs found."}
        _cache_set("market_bias", fallback)
        return fallback
    except Exception as e:
        print(f"Market Bias Error: {e}")
        return {"direction": "Neutral", "conviction": 0, "reason": "System synchronization..."}

@app.get("/api/agent-health")
def get_agent_health():
    found, cached = _cache_get("agent_health")
    if found:
        return cached
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT run_at, execution_time_ms, confidence, iterations_used 
                    FROM runs 
                    ORDER BY id DESC LIMIT 1
                """)
                last_run = cursor.fetchone()
                
                cursor.execute("SELECT timestamp FROM gold_prices_ig ORDER BY timestamp DESC LIMIT 1")
                last_price = cursor.fetchone()

        now = datetime.now(timezone.utc)
        api_status = "Stable"
        last_update_str = "Just now"
        
        if last_price and last_price['timestamp']:
            p_time = last_price['timestamp']
            if isinstance(p_time, str):
                p_time = datetime.fromisoformat(p_time.replace('Z', '+00:00'))
            if p_time.tzinfo is None:
                p_time = p_time.replace(tzinfo=timezone.utc)
            
            diff = (now - p_time).total_seconds()
            if diff > 300: api_status = "Warning"
            last_update_str = f"{int(diff//60)}m ago" if diff > 60 else f"{int(diff)}s ago"

        payload = {
            "latency": last_run.get('execution_time_ms') or 0,
            "iterations": last_run.get('iterations_used') or 0,
            "api_status": api_status,
            "accuracy": last_run.get('confidence') or 0,
            "last_update": last_update_str,
            "quality_score": 95 if api_status == "Stable" else 60
        }
        _cache_set("agent_health", payload)
        return payload
    except Exception as e:
        print(f"Health API Error: {e}")
        return {"latency": 0, "iterations": 0, "api_status": "Offline", "accuracy": 0, "last_update": "-", "quality_score": 0}
    
# ─────────────────────────────────────────────────────────────────────────────
# เพิ่ม 2 endpoints นี้ลงใน main.py ต่อท้าย endpoints เดิมได้เลย
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/backtest/summary")
def get_backtest_summary(model: str = None):
    """
    ดึง backtest summary ล่าสุด (หรือ filter ตาม model_name)
    ส่งกลับ: object ที่มีทุก field จาก backtest_summary
    """
    cache_key = f"backtest_summary_{model or 'all'}"
    # backtest summary ใช้ cache dict แบบ manual เพราะ key แปรผัน
    found, cached = _cache_get("backtest_summary")
    if found and isinstance(cached, dict) and cached.get("_model") == model:
        return cached["_data"]
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cursor:
                if model:
                    cursor.execute("""
                        SELECT * FROM backtest_summary
                        WHERE model_name = %s
                        ORDER BY run_date DESC LIMIT 1
                    """, (model,))
                else:
                    cursor.execute("""
                        SELECT * FROM backtest_summary
                        ORDER BY run_date DESC LIMIT 1
                    """)
                row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="No backtest summary found")

        result = dict(row)
        _cache_set("backtest_summary", {"_model": model, "_data": result})
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── endpoint ต่อไปนี้ ───────────────────────────────────────────────────────

@app.get("/api/backtest/trades")
def get_backtest_trades(model: str = None, limit: int = 500, signal: str = None):
    """
    ดึงรายการ trade ทั้งหมดที่มี final_signal เป็น BUY หรือ SELL
    Fields: timestamp, final_signal, final_confidence, net_pnl_thb,
            position_size_thb, stop_loss, take_profit,
            llm_rationale, llm_confidence, llm_signal,
            final_correct, final_profitable, rejection_reason,
            portfolio_value, close_thai
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                conditions = ["final_signal IN ('BUY', 'SELL')"]
                params = []

                if model:
                    conditions.append("model_name = %s")
                    params.append(model)
                if signal and signal.upper() in ("BUY", "SELL"):
                    conditions.append("final_signal = %s")
                    params.append(signal.upper())

                where = " AND ".join(conditions)
                params.append(limit)

                cursor.execute(f"""
                    SELECT
                        timestamp,
                        final_signal,
                        final_confidence,
                        net_pnl_thb,
                        position_size_thb,
                        stop_loss,
                        take_profit,
                        llm_rationale,
                        llm_confidence,
                        llm_signal,
                        final_correct,
                        final_profitable,
                        rejection_reason,
                        portfolio_value,
                        close_thai
                    FROM backtest_equity_curve
                    WHERE {where}
                    ORDER BY timestamp ASC
                    LIMIT %s
                """, params)

                rows = cursor.fetchall()

        if not rows:
            return []

        result = []
        for r in rows:
            ts = r["timestamp"]
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                label = dt.strftime("%d %b %H:%M")
            except Exception:
                label = str(ts)[:16]

            result.append({
                "timestamp":         label,
                "signal":            r["final_signal"] or "HOLD",
                "confidence":        round(float(r["final_confidence"] or 0), 2),
                "pnl":               round(float(r["net_pnl_thb"] or 0), 2),
                "position_size":     round(float(r["position_size_thb"] or 0), 2),
                "stop_loss":         round(float(r["stop_loss"] or 0), 2),
                "take_profit":       round(float(r["take_profit"] or 0), 2),
                "rationale":         r["llm_rationale"] or "—",
                "llm_signal":        r["llm_signal"] or "—",
                "llm_confidence":    round(float(r["llm_confidence"] or 0), 2),
                "correct":           bool(r["final_correct"]),
                "profitable":        bool(r["final_profitable"]),
                "rejection_reason":  r["rejection_reason"] or "",
                "portfolio_value":   round(float(r["portfolio_value"] or 0), 2),
                "price":             round(float(r["close_thai"] or 0), 2),
            })

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# ─── แทนที่ endpoint /api/backtest/equity-curve เดิมใน main.py ────────────────
# เพิ่ม 3 fields ใหม่: price (close_thai), raw_ts (ISO timestamp), profitable

@app.get("/api/backtest/equity-curve")
def get_backtest_equity_curve(model: str = None, limit: int = 2000):
    """
    ดึง equity curve สำหรับวาดกราฟ
    - ส่งกลับ: list ของ { date, value, signal, pnl, price, raw_ts, profitable }
    - เพิ่ม price (close_thai), raw_ts, profitable เพื่อให้ frontend filter timeframe
      และวาดกราฟราคาทองควบคู่กับ equity curve ได้
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                if model:
                    cursor.execute("""
                        SELECT
                            timestamp,
                            portfolio_value,
                            final_signal      AS signal,
                            net_pnl_thb       AS pnl,
                            close_thai        AS price,
                            final_profitable  AS profitable
                        FROM backtest_equity_curve
                        WHERE model_name = %s
                        ORDER BY timestamp ASC
                        LIMIT %s
                    """, (model, limit))
                else:
                    cursor.execute("""
                        SELECT
                            timestamp,
                            portfolio_value,
                            final_signal      AS signal,
                            net_pnl_thb       AS pnl,
                            close_thai        AS price,
                            final_profitable  AS profitable
                        FROM backtest_equity_curve
                        ORDER BY timestamp ASC
                        LIMIT %s
                    """, (limit,))

                rows = cursor.fetchall()

        if not rows:
            return []

        result = []
        for r in rows:
            ts = r["timestamp"]
            raw_ts_str = str(ts)  # เก็บ ISO string ไว้ให้ frontend filter timeframe

            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                label = dt.strftime("%-m/%-d %H:%M")   # "9/1 14:30"
            except Exception:
                label = raw_ts_str[:16]

            result.append({
                "date":       label,
                "value":      round(float(r["portfolio_value"] or 0), 2),
                "signal":     r["signal"] or "HOLD",
                "pnl":        round(float(r["pnl"] or 0), 2),
                "price":      round(float(r["price"] or 0), 2),   # ราคาทองตอนนั้น
                "raw_ts":     raw_ts_str,                          # ISO string สำหรับ filter
                "profitable": bool(r["profitable"]),
            })

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/signal-analytics")
def get_signal_analytics():
    found, cached = _cache_get("signal_analytics")
    if found:
        return cached
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT 
                        COALESCE(AVG(pnl_pct), 0) as avg_pnl,
                        0 as avg_confidence, 
                        COUNT(*) as total_trades
                    FROM trade_log 
                    WHERE action = 'SELL'
                """)
                result = cursor.fetchone()
                _cache_set("signal_analytics", result)
                return result
    except Exception as e:
        print(f"Error in /api/signal-analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# เพิ่มใน main.py (หรือไฟล์ที่กำหนด endpoint /api/signal-stats)
@app.get("/api/signal-stats")
def get_signal_stats():
    found, cached = _cache_get("signal_stats")
    if found:
        return cached
    try:
        pnl_data = db.get_pnl_summary() 
        signal_data = db.get_signal_stats()
        
        payload = {
            "net_pnl": pnl_data.get("total_pnl_thb", 0),
            "win_rate": pnl_data.get("win_rate", 0) * 100,
            "total_signals": signal_data.get("total", 0),
            "active_signals": 0,
            "weekly_growth": 0
        }
        _cache_set("signal_stats", payload)
        return payload
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ──────────────────────────────────────────────────────────────────
# เพิ่ม endpoints เหล่านี้ต่อท้าย main.py ได้เลยครับ
# ──────────────────────────────────────────────────────────────────

def _build_history_sql(table: str, ts_col: str, tf: str, limit: int) -> tuple[str, tuple]:
    """
    สร้าง SQL สำหรับดึง time-series history ตาม timeframe
    รองรับทั้ง gold_prices_ig (timestamp), gold_prices_hsh (created_at), gold_prices (created_at)
    ไม่มี WHERE กรอง lookback — ดึงข้อมูลทั้งหมดที่มีใน DB
    """
    # bucket expression ตาม timeframe
    bucket_expr = {
        "15m": f"date_trunc('hour', {ts_col}) + (EXTRACT(MINUTE FROM {ts_col})::int / 15) * INTERVAL '15 minutes'",
        "1H":  f"date_trunc('hour', {ts_col})",
        "4H":  f"date_trunc('day', {ts_col}) + (EXTRACT(HOUR FROM {ts_col})::int / 4) * INTERVAL '4 hours'",
        "1D":  f"date_trunc('day', {ts_col})",
        "1W":  f"date_trunc('week', {ts_col})",
    }.get(tf, f"date_trunc('day', {ts_col})")

    sql = f"""
        SELECT
            {bucket_expr} AS bucket,
            MAX(ask_96)     AS high_ask,
            MIN(ask_96)     AS low_ask,
            AVG(ask_96)     AS avg_ask,
            AVG(bid_96)     AS avg_bid,
            COUNT(*)        AS data_points
        FROM {table}
        WHERE ask_96 IS NOT NULL
        GROUP BY bucket
        ORDER BY bucket ASC
        LIMIT %s
    """
    return sql, (limit,)


def _build_history_sql_with_spot(tf: str, limit: int) -> tuple[str, tuple]:
    """
    SQL สำหรับ gold_prices_ig ที่มี spot_price และ usd_thb ด้วย
    """
    ts_col = "timestamp"
    bucket_expr = {
        "15m": f"date_trunc('hour', {ts_col}) + (EXTRACT(MINUTE FROM {ts_col})::int / 15) * INTERVAL '15 minutes'",
        "1H":  f"date_trunc('hour', {ts_col})",
        "4H":  f"date_trunc('day', {ts_col}) + (EXTRACT(HOUR FROM {ts_col})::int / 4) * INTERVAL '4 hours'",
        "1D":  f"date_trunc('day', {ts_col})",
        "1W":  f"date_trunc('week', {ts_col})",
    }.get(tf, f"date_trunc('day', {ts_col})")

    sql = f"""
        SELECT
            {bucket_expr}   AS bucket,
            MAX(ask_96)     AS high_ask,
            MIN(ask_96)     AS low_ask,
            AVG(ask_96)     AS avg_ask,
            AVG(bid_96)     AS avg_bid,
            AVG(spot_price) AS avg_spot,
            AVG(usd_thb)    AS avg_usd_thb,
            COUNT(*)        AS data_points
        FROM gold_prices_ig
        WHERE ask_96 IS NOT NULL
        GROUP BY bucket
        ORDER BY bucket ASC
        LIMIT %s
    """
    return sql, (limit,)


def _rows_to_history(rows: list, has_spot: bool = False) -> list[dict]:
    """แปลง DB rows → list ของ dict สำหรับ frontend"""
    result = []
    for r in rows:
        ts = r["bucket"]
        if hasattr(ts, "timestamp"):
            ts_ms = int(ts.timestamp() * 1000)
        else:
            from datetime import datetime as _dt
            ts_ms = int(_dt.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp() * 1000)

        avg_ask = float(r["avg_ask"] or 0)
        avg_bid = float(r["avg_bid"] or 0)

        item: dict = {
            "time":     ts_ms,
            "ask_96":   round(avg_ask, 2),
            "bid_96":   round(avg_bid, 2),
            "high_ask": round(float(r["high_ask"] or 0), 2),
            "low_ask":  round(float(r["low_ask"] or 0), 2),
            "spread":   round(avg_ask - avg_bid, 2),
            "n":        int(r["data_points"] or 0),
        }
        if has_spot:
            item["spot"]    = round(float(r.get("avg_spot") or 0), 2)
            item["usd_thb"] = round(float(r.get("avg_usd_thb") or 0), 4)

        result.append(item)
    return result


# ── 1. Market History (unified) ────────────────────────────────────
@app.get("/api/market/history")
def get_market_history(
    tf: str     = "1D",
    limit: int  = 500,
    source: str = "ig",   # "ig" | "hsh" | "prices"
):
    """
    ดึง time-series ราคาทอง สำหรับวาดกราฟ — ข้อมูลทั้งหมดใน DB (ไม่ตัด lookback)

    Parameters:
      tf     : "15m" | "1H" | "4H" | "1D" | "1W"
      limit  : จำนวน bucket สูงสุด (default 500)
      source : "ig"     → gold_prices_ig     (5.3M rows, มี spot_price + usd_thb)
               "hsh"    → gold_prices_hsh    (1.4M rows, มี market_status)
               "prices" → gold_prices        (400K rows, มี assoc_bid/ask)

    Response: list[{ time, ask_96, bid_96, high_ask, low_ask, spread, n, ?spot, ?usd_thb }]
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:

                if source == "ig":
                    sql, params = _build_history_sql_with_spot(tf, limit)
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()
                    return _rows_to_history(rows, has_spot=True)

                elif source == "hsh":
                    sql, params = _build_history_sql("gold_prices_hsh", "created_at", tf, limit)
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()
                    return _rows_to_history(rows, has_spot=False)

                elif source == "prices":
                    sql, params = _build_history_sql("gold_prices", "created_at", tf, limit)
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()
                    return _rows_to_history(rows, has_spot=False)

                else:
                    raise HTTPException(status_code=400, detail=f"Unknown source: {source}. Use ig | hsh | prices")

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in /api/market/history [source={source}, tf={tf}]: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── 2. HSH Live + Market Status ────────────────────────────────────
@app.get("/api/market/hsh-live")
def get_hsh_live():
    """
    ราคา Hua Seng Heng ล่าสุดจาก gold_prices_hsh
    รวม market_status, bid_99/ask_99 (ทอง 99.99%) และ bid_96/ask_96 (96.5%)
    """
    found, cached = _cache_get("hsh_live")
    if found:
        return cached
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT
                        bid_96, ask_96,
                        bid_99, ask_99,
                        market_status,
                        created_at
                    FROM gold_prices_hsh
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="No HSH data found")

        ask_96 = float(row["ask_96"] or 0)
        bid_96 = float(row["bid_96"] or 0)
        ask_99 = float(row["ask_99"] or 0)
        bid_99 = float(row["bid_99"] or 0)

        ts = row["created_at"]
        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

        payload = {
            "ask_96":        ask_96,
            "bid_96":        bid_96,
            "ask_99":        ask_99,
            "bid_99":        bid_99,
            "spread_96":     round(ask_96 - bid_96, 2),
            "spread_99":     round(ask_99 - bid_99, 2),
            "market_status": row.get("market_status") or "UNKNOWN",
            "is_open":       (row.get("market_status") or "").upper() not in ("CLOSED", "WEEKEND", "HOLIDAY"),
            "updated_at":    ts_str,
        }
        _cache_set("hsh_live", payload)
        return payload

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in /api/market/hsh-live: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── 3. Market Snapshot (unified, ดึงจากทุก table) ─────────────────
@app.get("/api/market/snapshot")
def get_market_snapshot():
    """
    รวม live price + 24h/7d change จาก gold_prices_ig
    ส่งกลับ: ask_96, bid_96, spot_usd, usd_thb, spread,
             ask_chg_24h, ask_pct_24h, spot_chg_24h, spot_pct_24h,
             rate_chg_24h, rate_pct_24h, ask_pct_7d, spot_pct_7d
    """
    found, cached = _cache_get("market_snapshot")
    if found:
        return cached
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # ล่าสุด
                cursor.execute("""
                    SELECT ask_96, bid_96, spot_price, usd_thb, timestamp
                    FROM gold_prices_ig
                    ORDER BY timestamp DESC LIMIT 1
                """)
                latest = cursor.fetchone()

                # 24h ที่แล้ว
                cursor.execute("""
                    SELECT ask_96, bid_96, spot_price, usd_thb
                    FROM gold_prices_ig
                    WHERE timestamp <= NOW() - INTERVAL '24 hours'
                    ORDER BY timestamp DESC LIMIT 1
                """)
                prev_24h = cursor.fetchone()

                # 7d ที่แล้ว
                cursor.execute("""
                    SELECT ask_96, spot_price
                    FROM gold_prices_ig
                    WHERE timestamp <= NOW() - INTERVAL '7 days'
                    ORDER BY timestamp DESC LIMIT 1
                """)
                prev_7d = cursor.fetchone()

        if not latest:
            raise HTTPException(status_code=404, detail="No market data available")

        def pct(curr, prev):
            if not curr or not prev or prev == 0:
                return 0.0
            return round((curr - prev) / prev * 100, 3)

        ask  = float(latest["ask_96"]    or 0)
        bid  = float(latest["bid_96"]    or 0)
        spot = float(latest["spot_price"] or 0)
        rate = float(latest["usd_thb"]   or 0)

        ask_prev  = float(prev_24h["ask_96"]    or 0) if prev_24h else 0
        spot_prev = float(prev_24h["spot_price"] or 0) if prev_24h else 0
        rate_prev = float(prev_24h["usd_thb"]   or 0) if prev_24h else 0

        ts = latest["timestamp"]
        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

        payload = {
            "ask_96":       ask,
            "bid_96":       bid,
            "spot_usd":     spot,
            "usd_thb":      rate,
            "spread":       round(ask - bid, 2),
            "timestamp":    ts_str,
            # 24h delta
            "ask_chg_24h":  round(ask - ask_prev, 2),
            "ask_pct_24h":  pct(ask, ask_prev),
            "spot_chg_24h": round(spot - spot_prev, 2),
            "spot_pct_24h": pct(spot, spot_prev),
            "rate_chg_24h": round(rate - rate_prev, 4),
            "rate_pct_24h": pct(rate, rate_prev),
            # 7d delta
            "ask_pct_7d":   pct(ask,  float(prev_7d["ask_96"]    or 0)) if prev_7d else 0,
            "spot_pct_7d":  pct(spot, float(prev_7d["spot_price"] or 0)) if prev_7d else 0,
        }
        _cache_set("market_snapshot", payload)
        return payload

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in /api/market/snapshot: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── 4. News Feed ───────────────────────────────────────────────────
@app.get("/api/market/news")
def get_market_news(limit: int = 30, category: str = None, impact: str = None):
    """
    ดึงข่าวล่าสุดจาก Supabase news_sentiment
    category: "gold" | "forex" | "macro" | None (all)
    impact:   "HIGH" | "MEDIUM" | "LOW"  | None (all)
    """
    # cache key รวม filter params
    found, cached = _cache_get("market_news")
    if found and isinstance(cached, dict) and cached.get("_key") == f"{category}_{impact}_{limit}":
        return cached["_data"]
    try:
        query = (
            supabase.table("news_sentiment")
            .select("id, title, url, source, published_at, category, "
                    "impact_level, sentiment_score, impact_score, "
                    "event_type, actual_value, forecast_value, value_diff")
            .order("published_at", desc=True)
            .limit(limit)
        )
        if category:
            query = query.eq("category", category)
        if impact:
            query = query.eq("impact_level", impact)

        response = query.execute()

        result = []
        for item in (response.data or []):
            score = float(item.get("sentiment_score") or 0)
            if score >= 0.3:
                label = "BULLISH"
            elif score <= -0.3:
                label = "BEARISH"
            else:
                label = "NEUTRAL"

            result.append({
                "id":              item.get("id"),
                "title":           item.get("title") or "—",
                "url":             item.get("url") or "#",
                "source":          item.get("source") or "Unknown",
                "published_at":    item.get("published_at"),
                "category":        item.get("category") or "general",
                "impact_level":    item.get("impact_level") or "LOW",
                "sentiment":       round(score, 3),
                "sentiment_label": label,
                "impact_score":    item.get("impact_score") or 0,
                "event_type":      item.get("event_type") or "news",
                "actual":          item.get("actual_value"),
                "forecast":        item.get("forecast_value"),
                "value_diff":      item.get("value_diff"),
            })

        _cache_set("market_news", {"_key": f"{category}_{impact}_{limit}", "_data": result})
        return result

    except Exception as e:
        print(f"Error in /api/market/news: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
# ─────────────────────────────────────────────────────────────────────────────
# HISTORY SECTION — เพิ่ม 4 endpoints นี้ต่อท้าย main.py
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import Query

# ── 1. Summary (header stats รวมทุก table) ────────────────────────────────────
@app.get("/api/history/summary")
def get_history_summary():
    """
    Aggregate stats สำหรับ History section header
    Returns: total_runs, total_trades, realized_pnl, win_rate,
             avg_exec_ms, buy_count, sell_count, hold_count
    """
    found, cached = _cache_get("history_summary")
    if found:
        return cached
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:

                cursor.execute("SELECT COUNT(*) AS total FROM runs")
                total_runs = cursor.fetchone()["total"] or 0

                cursor.execute("""
                    SELECT
                        COUNT(*)                                        AS total_trades,
                        COALESCE(SUM(pnl_thb), 0)                      AS realized_pnl,
                        COALESCE(
                            SUM(CASE WHEN pnl_thb > 0 THEN 1 ELSE 0 END)
                            ::float / NULLIF(COUNT(CASE WHEN pnl_thb IS NOT NULL THEN 1 END), 0)
                        , 0)                                            AS win_rate
                    FROM trade_log
                """)
                trade_stats = cursor.fetchone()

                cursor.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE signal = 'BUY')  AS buy_count,
                        COUNT(*) FILTER (WHERE signal = 'SELL') AS sell_count,
                        COUNT(*) FILTER (WHERE signal = 'HOLD') AS hold_count,
                        COALESCE(AVG(execution_time_ms), 0)     AS avg_exec_ms
                    FROM runs
                    WHERE signal IS NOT NULL
                """)
                signal_stats = cursor.fetchone()

        payload = {
            "total_runs":    int(total_runs),
            "total_trades":  int(trade_stats["total_trades"] or 0),
            "realized_pnl":  round(float(trade_stats["realized_pnl"] or 0), 2),
            "win_rate":      round(float(trade_stats["win_rate"] or 0) * 100, 1),
            "avg_exec_ms":   round(float(signal_stats["avg_exec_ms"] or 0), 0),
            "buy_count":     int(signal_stats["buy_count"] or 0),
            "sell_count":    int(signal_stats["sell_count"] or 0),
            "hold_count":    int(signal_stats["hold_count"] or 0),
        }
        _cache_set("history_summary", payload)
        return payload
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 2. Agent Runs (runs table) ────────────────────────────────────────────────
@app.get("/api/history/runs")
def get_history_runs(
    limit:  int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    signal: str = Query(None),          # filter: BUY | SELL | HOLD
):
    """
    ดึงรายการ agent runs ทั้งหมด + optional filter ตาม signal
    Returns list ของ runs พร้อม field หลักสำหรับแสดงผล
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:

                where = "WHERE 1=1"
                params: list = []

                if signal and signal.upper() in ("BUY", "SELL", "HOLD"):
                    where += " AND signal = %s"
                    params.append(signal.upper())

                params += [limit, offset]
                cursor.execute(f"""
                    SELECT
                        id, run_at, provider, interval_tf,
                        signal, confidence,
                        gold_price_thb, entry_price_thb, stop_loss_thb, take_profit_thb,
                        usd_thb_rate, rsi, macd_line, macd_histogram,
                        bb_pct_b, atr_thb, trend, data_quality,
                        rationale, iterations_used, tool_calls_used,
                        execution_time_ms, is_weekend
                    FROM runs
                    {where}
                    ORDER BY id DESC
                    LIMIT %s OFFSET %s
                """, params)

                rows = cursor.fetchall()

        result = []
        for r in rows:
            result.append({
                "id":               r["id"],
                "run_at":           str(r["run_at"]),
                "provider":         r["provider"] or "—",
                "interval_tf":      r["interval_tf"] or "—",
                "signal":           r["signal"] or "HOLD",
                "confidence":       round(float(r["confidence"] or 0), 2),
                "gold_price_thb":   round(float(r["gold_price_thb"] or 0), 2),
                "entry_price_thb":  round(float(r["entry_price_thb"] or 0), 2),
                "stop_loss_thb":    round(float(r["stop_loss_thb"] or 0), 2),
                "take_profit_thb":  round(float(r["take_profit_thb"] or 0), 2),
                "usd_thb_rate":     round(float(r["usd_thb_rate"] or 0), 4),
                "rsi":              round(float(r["rsi"] or 0), 2),
                "macd_line":        round(float(r["macd_line"] or 0), 4),
                "macd_histogram":   round(float(r["macd_histogram"] or 0), 4),
                "bb_pct_b":         round(float(r["bb_pct_b"] or 0), 4),
                "atr_thb":          round(float(r["atr_thb"] or 0), 2),
                "trend":            r["trend"] or "—",
                "data_quality":     r["data_quality"] or "—",
                "rationale":        r["rationale"] or "",
                "iterations_used":  int(r["iterations_used"] or 0),
                "tool_calls_used":  int(r["tool_calls_used"] or 0),
                "execution_time_ms": round(float(r["execution_time_ms"] or 0), 0),
                "is_weekend":       bool(r["is_weekend"]),
            })

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 3. Trade Log (trade_log table) ────────────────────────────────────────────
@app.get("/api/history/trades")
def get_history_trades(
    limit:  int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    action: str = Query(None),          # filter: BUY | SELL
):
    """
    ดึงประวัติการ trade ทั้งหมดพร้อม portfolio movement
    Returns: action, price, grams, pnl, cash flow, gold flow
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:

                where = "WHERE 1=1"
                params: list = []

                if action and action.upper() in ("BUY", "SELL"):
                    where += " AND action = %s"
                    params.append(action.upper())

                params += [limit, offset]
                cursor.execute(f"""
                    SELECT
                        t.id, t.run_id, t.action, t.executed_at,
                        t.price_thb, t.gold_grams, t.amount_thb,
                        t.cash_before, t.cash_after,
                        t.gold_before, t.gold_after,
                        t.cost_basis_thb, t.pnl_thb, t.pnl_pct,
                        t.note,
                        r.signal         AS run_signal,
                        r.confidence     AS run_confidence,
                        r.rationale      AS run_rationale,
                        r.provider       AS run_provider
                    FROM trade_log t
                    LEFT JOIN runs r ON t.run_id = r.id
                    {where}
                    ORDER BY t.id DESC
                    LIMIT %s OFFSET %s
                """, params)

                rows = cursor.fetchall()

        result = []
        for r in rows:
            result.append({
                "id":             r["id"],
                "run_id":         r["run_id"],
                "action":         r["action"],
                "executed_at":    str(r["executed_at"]),
                "price_thb":      round(float(r["price_thb"] or 0), 2),
                "gold_grams":     round(float(r["gold_grams"] or 0), 4),
                "amount_thb":     round(float(r["amount_thb"] or 0), 2),
                "cash_before":    round(float(r["cash_before"] or 0), 2),
                "cash_after":     round(float(r["cash_after"] or 0), 2),
                "gold_before":    round(float(r["gold_before"] or 0), 4),
                "gold_after":     round(float(r["gold_after"] or 0), 4),
                "cost_basis_thb": round(float(r["cost_basis_thb"] or 0), 2),
                "pnl_thb":        round(float(r["pnl_thb"]), 2) if r["pnl_thb"] is not None else None,
                "pnl_pct":        round(float(r["pnl_pct"]), 4) if r["pnl_pct"] is not None else None,
                "note":           r["note"] or "",
                "run_signal":     r["run_signal"] or "—",
                "run_confidence": round(float(r["run_confidence"] or 0), 2),
                "run_rationale":  r["run_rationale"] or "",
                "run_provider":   r["run_provider"] or "—",
            })

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 4. LLM Interaction Logs (llm_logs table) ──────────────────────────────────
@app.get("/api/history/logs")
def get_history_logs(
    limit:     int = Query(50, le=200),
    offset:    int = Query(0, ge=0),
    step_type: str = Query(None),       # filter: THOUGHT_FINAL | TOOL_CALL | THOUGHT
    run_id:    int = Query(None),       # filter: ดึง logs ของ run เดียว
):
    """
    ดึง LLM interaction logs พร้อม token stats
    Includes: step_type, signal, confidence, elapsed_ms, token breakdown
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:

                where = "WHERE 1=1"
                params: list = []

                if step_type:
                    where += " AND step_type = %s"
                    params.append(step_type.upper())

                if run_id:
                    where += " AND run_id = %s"
                    params.append(run_id)

                params += [limit, offset]
                cursor.execute(f"""
                    SELECT
                        id, run_id, logged_at, interval_tf,
                        step_type, iteration, provider,
                        signal, confidence, rationale,
                        entry_price, stop_loss, take_profit,
                        token_input, token_output, token_total,
                        elapsed_ms, iterations_used, tool_calls_used,
                        is_fallback, fallback_from
                    FROM llm_logs
                    {where}
                    ORDER BY id DESC
                    LIMIT %s OFFSET %s
                """, params)

                rows = cursor.fetchall()

        result = []
        for r in rows:
            result.append({
                "id":              r["id"],
                "run_id":          r["run_id"],
                "logged_at":       str(r["logged_at"]),
                "interval_tf":     r["interval_tf"] or "—",
                "step_type":       r["step_type"] or "—",
                "iteration":       int(r["iteration"] or 0),
                "provider":        r["provider"] or "—",
                "signal":          r["signal"] or "—",
                "confidence":      round(float(r["confidence"] or 0), 2),
                "rationale":       r["rationale"] or "",
                "entry_price":     round(float(r["entry_price"] or 0), 2),
                "stop_loss":       round(float(r["stop_loss"] or 0), 2),
                "take_profit":     round(float(r["take_profit"] or 0), 2),
                "token_input":     int(r["token_input"] or 0),
                "token_output":    int(r["token_output"] or 0),
                "token_total":     int(r["token_total"] or 0),
                "elapsed_ms":      int(r["elapsed_ms"] or 0),
                "iterations_used": int(r["iterations_used"] or 0),
                "tool_calls_used": int(r["tool_calls_used"] or 0),
                "is_fallback":     bool(r["is_fallback"]),
                "fallback_from":   r["fallback_from"] or "",
            })

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/api/analyze")
def trigger_analysis(req: AnalyzeRequest):
    args = argparse.Namespace(
        provider=req.provider,
        period=req.period,
        intervals=req.intervals,
        skip_fetch=False,
        no_save=False  # บังคับ Save ลง DB
    )
    
    # 1. สั่งรัน AI Agent
    agent_result = agent_cli.run_analysis_once(args, runtime["services"], emit_logs=False)
    
    # 2. หา run_id ล่าสุดที่เพิ่งรันเสร็จ
    run_id = agent_result.get("run_id") if isinstance(agent_result, dict) else None

    # 3. ดึงข้อมูลแบบจัดเต็มจาก DB เพื่อส่งกลับให้หน้า Live Analysis
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # ถ้า Agent ไม่ได้คืนค่า run_id มา ให้ดึงแถวล่าสุดแทน
                if not run_id:
                    cursor.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1")
                    run_data = cursor.fetchone()
                    if run_data:
                        run_id = run_data["id"]
                else:
                    cursor.execute("SELECT * FROM runs WHERE id = %s", (run_id,))
                    run_data = cursor.fetchone()

                if not run_data:
                    return {"error": "Run completed but data not found in DB"}

                # ดึงประวัติความคิด (llm_logs) ของ run_id นี้
                cursor.execute("""
                    SELECT * FROM llm_logs 
                    WHERE run_id = %s 
                    ORDER BY iteration ASC, id ASC
                """, (run_id,))
                logs_data = cursor.fetchall()

        # Format วันที่ให้เป็น String
        if "run_at" in run_data and run_data["run_at"]:
            run_data["run_at"] = str(run_data["run_at"])
        for log in logs_data:
            if "logged_at" in log and log["logged_at"]:
                log["logged_at"] = str(log["logged_at"])

        # ส่งกลับไปให้ React แบบจัดเต็ม
        return {
            "run": run_data,
            "llm_logs": logs_data
        }

    except Exception as e:
        print(f"Error fetching Live Run DB: {e}")
        raise HTTPException(status_code=500, detail="Analysis completed, but failed to fetch DB records.")
    
@app.get("/api/notifications")
def get_notifications(limit: int = 15):
    """
    ดึงรายการแจ้งเตือนล่าสุด โดยรวมข้อมูลจาก trade_log (การซื้อขาย) และ runs (สัญญาณ AI)
    นำมาเรียงลำดับตามเวลาล่าสุด
    """
    try:
        notifications = []
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                
                # 1. ดึงประวัติการเทรด (Trade Executions)
                cursor.execute("""
                    SELECT id, action, executed_at as timestamp, price_thb, pnl_thb 
                    FROM trade_log 
                    ORDER BY executed_at DESC LIMIT %s
                """, (limit,))
                trades = cursor.fetchall()
                
                for t in trades:
                    action = t['action']
                    pnl = float(t['pnl_thb']) if t['pnl_thb'] is not None else 0
                    
                    notif_type = "info"
                    title = f"Order Executed: {action}"
                    desc = f"XAU/THB {action} order executed at {t['price_thb']:,.2f} ฿"
                    
                    # ตรวจสอบว่าเป็น Take Profit หรือ Stop Loss
                    if action == "SELL":
                        if pnl > 0:
                            notif_type = "success"
                            title = "Take Profit Hit 🎯"
                            desc = f"Closed SELL with +{pnl:,.2f} ฿ profit."
                        elif pnl < 0:
                            notif_type = "warning"
                            title = "Stop Loss Hit 🛡️"
                            desc = f"Closed SELL with {pnl:,.2f} ฿ loss."

                    notifications.append({
                        "id": f"trade_{t['id']}",
                        "title": title,
                        "desc": desc,
                        "raw_time": t['timestamp'],
                        "type": notif_type
                    })

                # 2. ดึงประวัติสัญญาณ AI (New Signals)
                cursor.execute("""
                    SELECT id, signal, confidence, run_at as timestamp, rationale 
                    FROM runs 
                    WHERE signal IN ('BUY', 'SELL') 
                    ORDER BY run_at DESC LIMIT %s
                """, (limit,))
                runs = cursor.fetchall()
                
                for r in runs:
                    conf = float(r['confidence'] or 0)
                    if conf <= 1: conf *= 100
                    
                    # ตัด Rationale ให้ไม่ยาวเกินไป
                    rationale_short = (r['rationale'][:75] + '...') if r['rationale'] and len(r['rationale']) > 75 else r['rationale']
                    
                    notif_type = "success" if r['signal'] == 'BUY' else "warning"

                    notifications.append({
                        "id": f"signal_{r['id']}",
                        "title": f"New Signal: {r['signal']} 🤖",
                        "desc": f"{rationale_short} (Conf: {conf:.1f}%)",
                        "raw_time": r['timestamp'],
                        "type": notif_type
                    })

        # นำทั้ง 2 แหล่งมาเรียงลำดับเวลาจากใหม่ไปเก่า
        notifications.sort(key=lambda x: x['raw_time'], reverse=True)
        final_notifications = notifications[:limit]
        
        # แปลงเวลาเป็น String สำหรับ JSON
        for n in final_notifications:
            ts = n['raw_time']
            n['time'] = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
            del n['raw_time'] # ลบ raw_time ออก เพราะส่งผ่าน JSON ไม่ได้

        return final_notifications

    except Exception as e:
        print(f"Error in /api/notifications: {e}")
        raise HTTPException(status_code=500, detail=str(e))
