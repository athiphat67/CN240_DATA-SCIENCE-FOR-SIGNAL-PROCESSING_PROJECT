"""One-shot script to patch orchestrator.py with Gate SELL banner and improved HOLD log."""
import sys

path = "scheduler/orchestrator.py"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# The exact block to find (use a unique anchor that avoids emoji matching issues)
ANCHOR = 'tp_manager.reset()  # \u2705 I-1: Clear TP state so stale trail/SL doesn\'t fire on next bar\n                notify_sell_signal(gate_result, rationale_payload)\n                trading_log.info(f"SELL signal sent | score={_last_score:.4f}")\n        else:\n            trading_log.info(f"HOLD | state={_last_state} | score={_last_score:.4f} | reject={gate_result[\'reject_reason\']}")'

REPLACEMENT = ('tp_manager.reset()  # \u2705 I-1: Clear TP state so stale trail/SL doesn\'t fire on next bar\n'
               '                notify_sell_signal(gate_result, rationale_payload)\n'
               '\n'
               '                # \u2500\u2500 LOG 3b: High-Visibility Gate SELL Banner \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n'
               '                trading_log.warning(\n'
               '                    "\\n" + "="*60 + "\\n"\n'
               '                    "  \ud83d\udea8 [EXIT] ORGANIC GATE SELL\\n"\n'
               "                    f\"  Bid Price : {gate_result['hsh_bid']:,.2f} THB\\n\"\n"
               '                    f"  Score     : {_last_score:.4f} (dropped below sell threshold)\\n"\n'
               '                    f"  Bar Time  : {_last_bar_time}\\n"\n'
               '                    + "="*60\n'
               '                )\n'
               '        else:\n'
               '            # \u2500\u2500 HOLD log \u2014 shows exactly WHY the gate rejected a SELL \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n'
               '            if _last_state == STATE_HOLDING:\n'
               '                trading_log.info(\n'
               "                    f\"[HOLD] Still holding. \"\n"
               "                    f\"Gate blocked SELL -> reason: '{gate_result['reject_reason']}' \"\n"
               "                    f\"| Score: {_last_score:.4f} | Bid: {features_row['hsh_close_bid']:,.2f}\"\n"
               '                )\n'
               '            else:\n'
               '                trading_log.info(\n'
               '                    f"[HOLD] state={_last_state} "\n'
               '                    f"| score={_last_score:.4f} "\n'
               "                    f\"| reject={gate_result['reject_reason']}\"\n"
               '                )')

if ANCHOR in content:
    content = content.replace(ANCHOR, REPLACEMENT, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("SUCCESS: Gate SELL banner and improved HOLD log injected.")
else:
    print("FAIL: anchor block not found in file.")
    idx = content.find("SELL signal sent")
    print("Context around 'SELL signal sent':", repr(content[max(0,idx-200):idx+200]))
    sys.exit(1)
