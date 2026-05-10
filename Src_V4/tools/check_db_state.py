"""
tools/check_db_state.py
Pre-deployment check: verifies v3_system_state has a valid row (id=1).
If the row is missing, it initializes it to EMPTY.
Run from Src_V4/ with: python -m tools.check_db_state
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from core.state_manager import get_current_state, init_state
from config.settings import DRY_RUN, STATE_EMPTY

def main():
    print("=" * 55)
    print("  PRE-DEPLOYMENT: Supabase State Table Check")
    print("=" * 55)

    if DRY_RUN:
        print("[WARNING] DRY_RUN=true — skipping live DB check.")
        print("          Set DRY_RUN=false in .env before deploying.")
        return

    try:
        state = get_current_state()
        print(f"\n✅ v3_system_state OK — current_position = '{state}'")
        print(f"   (Valid values: EMPTY | HOLDING)")
    except RuntimeError as e:
        if "empty" in str(e).lower():
            print("\n⚠️  v3_system_state table is empty — initializing to EMPTY...")
            init_state(STATE_EMPTY)
            state = get_current_state()
            print(f"✅ Initialized — current_position = '{state}'")
        else:
            print(f"\n❌ Unexpected error reading state: {e}")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ DB connection failed: {e}")
        print("   Check SUPABASE_URL and SUPABASE_KEY in .env")
        sys.exit(1)

    print("\n✅ Database state check PASSED — ready for deployment.")
    print("=" * 55)

if __name__ == "__main__":
    main()
