import sys
import os
import csv
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from database.database import RunDatabase

load_dotenv()

CSV_FILE_PATH = os.path.join(
    parent_dir,
    "backtest", "output", "BIGtest", "backtest_results_main",
    "main_gemini-3_1-flash-lite-preview_30m_Noned_20260419_181603.csv"
)
MODEL_NAME = "gemini-3.1-flash-lite-preview"

SUMMARY_COLUMNS = [
    ("llm_directional_accuracy_pct",    "REAL"),
    ("llm_signal_sensitivity_pct",      "REAL"),
    ("llm_total_signals",               "INTEGER"),
    ("llm_buy_signals",                 "INTEGER"),
    ("llm_sell_signals",                "INTEGER"),
    ("llm_correct_signals",             "INTEGER"),
    ("llm_correct_profitable",          "INTEGER"),
    ("llm_avg_net_pnl_thb",             "REAL"),
    ("llm_rejected_by_risk",            "INTEGER"),
    ("llm_avg_confidence",              "REAL"),
    ("final_directional_accuracy_pct",  "REAL"),
    ("final_signal_sensitivity_pct",    "REAL"),
    ("final_total_signals",             "INTEGER"),
    ("final_buy_signals",               "INTEGER"),
    ("final_sell_signals",              "INTEGER"),
    ("final_correct_signals",           "INTEGER"),
    ("final_correct_profitable",        "INTEGER"),
    ("final_avg_net_pnl_thb",           "REAL"),
    ("final_rejected_by_risk",          "INTEGER"),
    ("final_avg_confidence",            "REAL"),
    ("risk_initial_portfolio_thb",      "REAL"),
    ("risk_final_portfolio_thb",        "REAL"),
    ("risk_total_return_pct",           "REAL"),
    ("risk_annualized_return_pct",      "REAL"),
    ("risk_annualized_reliable",        "BOOLEAN"),
    ("risk_annualized_volatility_pct",  "REAL"),
    ("risk_mdd_pct",                    "REAL"),
    ("risk_mdd_peak_timestamp",         "TEXT"),
    ("risk_mdd_trough_timestamp",       "TEXT"),
    ("risk_sharpe_ratio",               "REAL"),
    ("risk_sortino_ratio",              "REAL"),
    ("risk_candles_total",              "INTEGER"),
    ("risk_periods_per_year",           "INTEGER"),
    ("risk_risk_free_rate_pct",         "REAL"),
    ("session_compliance_total_sessions",    "INTEGER"),
    ("session_compliance_passed_sessions",   "INTEGER"),
    ("session_compliance_failed_sessions",   "INTEGER"),
    ("session_compliance_no_data_sessions",  "INTEGER"),
    ("session_compliance_compliance_pct",    "REAL"),
    ("session_compliance_session_fail_flag", "BOOLEAN"),
    ("trade_total_trades",              "INTEGER"),
    ("trade_winning_trades",            "INTEGER"),
    ("trade_losing_trades",             "INTEGER"),
    ("trade_win_rate_pct",              "REAL"),
    ("trade_profit_factor",             "REAL"),
    ("trade_avg_win_thb",               "REAL"),
    ("trade_avg_loss_thb",              "REAL"),
    ("trade_expectancy_thb",            "REAL"),
    ("trade_max_consec_wins",           "INTEGER"),
    ("trade_max_consec_losses",         "INTEGER"),
    ("trade_gross_profit_thb",          "REAL"),
    ("trade_gross_loss_thb",            "REAL"),
    ("trade_net_pnl_thb",               "REAL"),
    ("trade_unrealized_pnl_thb",        "REAL"),
    ("trade_total_cost_thb",            "REAL"),
    ("trade_largest_win_thb",           "REAL"),
    ("trade_largest_loss_thb",          "REAL"),
    ("trade_best_annualized_trade_pct", "REAL"),
    ("trade_worst_annualized_trade_pct","REAL"),
    ("trade_median_annualized_pct",     "REAL"),
    ("trade_top10_annualized_trade_pct","REAL"),
    ("trade_bottom10_annualized_trade_pct", "REAL"),
    ("trade_xirr_pct",                  "REAL"),
    ("trade_avg_capital_per_year_thb",  "REAL"),
    ("trade_calmar_ratio",              "REAL"),
]

EQUITY_COLUMNS = [
    ("close_thai",        "REAL"),
    ("actual_direction",  "TEXT"),
    ("price_change",      "REAL"),
    ("news_sentiment",    "REAL"),
    ("llm_signal",        "TEXT"),
    ("llm_confidence",    "REAL"),
    ("llm_rationale",     "TEXT"),
    ("llm_correct",       "BOOLEAN"),
    ("llm_profitable",    "BOOLEAN"),
    ("final_signal",      "TEXT"),
    ("final_confidence",  "REAL"),
    ("final_correct",     "BOOLEAN"),
    ("final_profitable",  "BOOLEAN"),
    ("rejection_reason",  "TEXT"),
    ("position_size_thb", "REAL"),
    ("stop_loss",         "REAL"),
    ("take_profit",       "REAL"),
    ("iterations_used",   "INTEGER"),
    ("from_cache",        "BOOLEAN"),
    ("session_id",        "TEXT"),
    ("can_execute",       "BOOLEAN"),
]


def migrate_table(cursor, table_name, required_columns):
    cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table_name,)
    )
    rows = cursor.fetchall()
    # รองรับทั้ง tuple-rows และ dict-rows (RealDictCursor)
    existing = {
        (row['column_name'] if isinstance(row, dict) else row[0])
        for row in rows
    }
    added = []
    for col_name, col_type in required_columns:
        if col_name not in existing:
            cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN "{col_name}" {col_type}')
            added.append(col_name)
    if added:
        print(f"   ➕ เพิ่ม {len(added)} column ใหม่ใน {table_name}: {', '.join(added)}")
    else:
        print(f"   ✔  {table_name} schema ครบแล้ว")


def setup_backtest_tables(db):
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS backtest_summary (
                    id SERIAL PRIMARY KEY,
                    model_name TEXT NOT NULL,
                    run_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS backtest_equity_curve (
                    id SERIAL PRIMARY KEY,
                    model_name TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    portfolio_value REAL NOT NULL,
                    cash REAL,
                    gold_grams REAL,
                    net_pnl_thb REAL,
                    signal TEXT
                )
            """)
            migrate_table(cursor, "backtest_summary",      SUMMARY_COLUMNS)
            migrate_table(cursor, "backtest_equity_curve", EQUITY_COLUMNS)
        conn.commit()
    print("✅ Schema พร้อม")


def safe_float(val, default=0.0):
    try:
        return float(val) if val not in (None, '', 'None') else default
    except (ValueError, TypeError):
        return default

def safe_int(val, default=0):
    try:
        return int(float(val)) if val not in (None, '', 'None') else default
    except (ValueError, TypeError):
        return default

def safe_bool(val, default=False):
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ('true', '1', 'yes')
    return default


def parse_and_import(filepath):
    db = RunDatabase()
    setup_backtest_tables(db)

    summary_data = {}
    detailed_lines = []

    print(f"\nกำลังอ่านไฟล์: {filepath}")

    with open(filepath, 'r', encoding='utf-8') as f:
        state = "SEARCHING"
        for line in f:
            clean_line = line.strip()
            if not clean_line:
                continue

            # ใช้ 'in' แทน startswith — รับมือ em-dash / BOM / whitespace
            if "MAIN PIPELINE BACKTEST" in clean_line and "SUMMARY" in clean_line:
                state = "READ_SUMMARY"
                continue
            elif "DETAILED SIGNAL LOG" in clean_line:
                state = "READ_DETAILED"
                continue

            if state == "READ_SUMMARY":
                parts = clean_line.split(",", 1)
                if len(parts) == 2:
                    summary_data[parts[0].strip()] = parts[1].strip()
            elif state == "READ_DETAILED":
                detailed_lines.append(clean_line)

    print(f"✅ อ่าน Summary ได้ {len(summary_data)} fields | Detailed {max(0, len(detailed_lines)-1)} rows")

    if not summary_data:
        print("⚠️  ไม่พบข้อมูล Summary — ตรวจสอบ encoding หรือ header ในไฟล์ CSV")
        return

    # --- บันทึก Summary ---
    try:
        col_names  = [c[0] for c in SUMMARY_COLUMNS]
        col_types  = dict(SUMMARY_COLUMNS)
        col_list   = ", ".join(col_names)
        placeholders = ", ".join(["%s"] * len(col_names))

        def cast(col, val):
            t = col_types[col]
            if t == "REAL":    return safe_float(val)
            if t == "INTEGER": return safe_int(val)
            if t == "BOOLEAN": return safe_bool(val)
            return val  # TEXT

        values = [MODEL_NAME] + [cast(c, summary_data.get(c)) for c in col_names]

        with db.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO backtest_summary (model_name, {col_list}) VALUES (%s, {placeholders})",
                    values
                )
            conn.commit()
        print(f"✅ บันทึก Summary สำเร็จ ({len(col_names)} fields)")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดตอนบันทึก Summary: {e}")

    # --- บันทึก Equity Curve ---
    try:
        reader = csv.DictReader(detailed_lines)
        count = 0
        with db.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM backtest_equity_curve WHERE model_name = %s",
                    (MODEL_NAME,)
                )
                insert_query = """
                    INSERT INTO backtest_equity_curve (
                        model_name, timestamp, close_thai,
                        portfolio_value, cash, gold_grams,
                        actual_direction, price_change, net_pnl_thb,
                        news_sentiment, llm_signal, llm_confidence, llm_rationale,
                        llm_correct, llm_profitable,
                        final_signal, final_confidence, final_correct, final_profitable,
                        rejection_reason, position_size_thb, stop_loss, take_profit,
                        iterations_used, from_cache, session_id, can_execute
                    ) VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                    )
                """
                for row in reader:
                    cursor.execute(insert_query, (
                        MODEL_NAME,
                        row.get('timestamp', ''),
                        safe_float(row.get('close_thai')),
                        safe_float(row.get('portfolio_total_value')),
                        safe_float(row.get('portfolio_cash')),
                        safe_float(row.get('portfolio_gold_grams')),
                        row.get('actual_direction', ''),
                        safe_float(row.get('price_change')),
                        safe_float(row.get('net_pnl_thb')),
                        safe_float(row.get('news_sentiment')),
                        row.get('llm_signal', ''),
                        safe_float(row.get('llm_confidence')),
                        row.get('llm_rationale', ''),
                        safe_bool(row.get('llm_correct')),
                        safe_bool(row.get('llm_profitable')),
                        row.get('final_signal', ''),
                        safe_float(row.get('final_confidence')),
                        safe_bool(row.get('final_correct')),
                        safe_bool(row.get('final_profitable')),
                        row.get('rejection_reason', ''),
                        safe_float(row.get('position_size_thb')),
                        safe_float(row.get('stop_loss')),
                        safe_float(row.get('take_profit')),
                        safe_int(row.get('iterations_used')),
                        safe_bool(row.get('from_cache')),
                        row.get('session_id', ''),
                        safe_bool(row.get('can_execute')),
                    ))
                    count += 1
            conn.commit()
        print(f"✅ บันทึก Equity Curve สำเร็จ {count} records")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดตอนบันทึก Equity Curve: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    if os.path.exists(CSV_FILE_PATH):
        parse_and_import(CSV_FILE_PATH)
    else:
        print(f"❌ ไม่พบไฟล์: {CSV_FILE_PATH}")
