"""
One-shot pipeline test — run from terminal with valid SUPABASE_KEY in env:
    python run_pipeline_once.py
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from logger_setup import setup_logging
setup_logging()

from core.candle_builder import build_candles
from core.feature_engine import compute_features
from core.model_inference import run_inference
from core.signal_gate import evaluate_signal_gate
from core.state_manager import get_current_state
import monitoring.pipeline_monitor as pm

run = pm.new_run()

# L1
t0 = time.monotonic()
try:
    candles = build_candles()
    ms = int((time.monotonic()-t0)*1000)
    pm.record_l1(run, candles, ms)
except Exception as e:
    pm.record_l1_error(run, int((time.monotonic()-t0)*1000), str(e))
    pm.finalize(run); pm.print_terminal(run); sys.exit(1)

# L2
t0 = time.monotonic()
try:
    features = compute_features(candles)
    ms = int((time.monotonic()-t0)*1000)
    pm.record_l2(run, features, ms)
except Exception as e:
    pm.record_l2_error(run, int((time.monotonic()-t0)*1000), str(e))
    pm.finalize(run); pm.print_terminal(run); sys.exit(1)

# L3
t0 = time.monotonic()
try:
    result = run_inference(features)
    ms = int((time.monotonic()-t0)*1000)
    pm.record_l3(run, result, ms)
except Exception as e:
    pm.record_l3_error(run, int((time.monotonic()-t0)*1000), str(e))
    pm.finalize(run); pm.print_terminal(run); sys.exit(1)

# L4
t0 = time.monotonic()
try:
    state = get_current_state()
    gate = evaluate_signal_gate(result, features)
    ms = int((time.monotonic()-t0)*1000)
    pm.record_l4(run, gate, ms)
except Exception as e:
    pm.record_l4_error(run, int((time.monotonic()-t0)*1000), str(e))

pm.finalize(run)
pm.print_terminal(run)
