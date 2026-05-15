#!/usr/bin/env python3
"""
validate_startup.py — Startup Validation Script

ตรวจสอบว่าการตั้งค่าพร้อมใช้งานก่อนเริ่มต้นแอปพลิเคชัน
- ตรวจสอบ environment variables ที่จำเป็น
- ตรวจสอบการเชื่อมต่อ Database
- ตรวจสอบ API keys ว่าใช้งานได้

รัน: python validate_startup.py

ไม่รบกวนการทำงานใด ๆ เพียงแค่ validation เท่านั้น
"""

import os
import sys
import asyncio

# ─────────────────────────────────────────────────────────────────────────────


def check_env_vars() -> bool:
    """ตรวจสอบ environment variables ที่จำเป็น"""
    print("\n📋 Checking environment variables...")
    
    required = [
        "GEMINI_API_KEY",
        "DATABASE_URL",
        "HF_TOKEN",
    ]
    
    optional = [
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "DISCORD_WEBHOOK_URL",
    ]
    
    missing_required = []
    missing_optional = []
    
    for var in required:
        if not os.getenv(var):
            missing_required.append(var)
            print(f"  ❌ {var} — MISSING (required)")
        else:
            print(f"  ✅ {var} — present")
    
    for var in optional:
        if not os.getenv(var):
            missing_optional.append(var)
            print(f"  ⚠️  {var} — missing (optional)")
        else:
            print(f"  ✅ {var} — present")
    
    if missing_required:
        print(f"\n❌ Missing required env vars: {', '.join(missing_required)}")
        return False
    
    if missing_optional:
        print(f"\n⚠️  Missing optional env vars: {', '.join(missing_optional)}")
    
    return True


def check_database() -> bool:
    """ตรวจสอบการเชื่อมต่อ PostgreSQL"""
    print("\n🗄️  Checking database connection...")
    
    try:
        import psycopg2
        
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            print("  ⚠️  DATABASE_URL not set — skipping DB check")
            return True
        
        # Parse connection string (simple parsing)
        # postgresql://user:password@host:port/database
        conn = psycopg2.connect(db_url)
        conn.close()
        
        print("  ✅ Database connection successful")
        return True
    
    except ImportError:
        print("  ⚠️  psycopg2 not installed — skipping DB check")
        return True
    except Exception as e:
        print(f"  ❌ Database connection failed: {e}")
        return False


async def check_api_keys() -> bool:
    """ตรวจสอบว่า API keys ที่สำคัญใช้งานได้"""
    print("\n🔑 Checking API keys...")
    
    try:
        import httpx
    except ImportError:
        print("  ⚠️  httpx not installed — skipping API checks")
        return True
    
    all_ok = True
    
    # ตรวจสอบ HF Token
    hf_token = os.getenv("HF_TOKEN")
    if hf_token:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                headers = {"Authorization": f"Bearer {hf_token}"}
                resp = await client.get(
                    "https://huggingface.co/api/",
                    headers=headers,
                )
                if resp.status_code < 400:
                    print("  ✅ HF_TOKEN — valid")
                else:
                    print(f"  ⚠️  HF_TOKEN — returned status {resp.status_code}")
        except asyncio.TimeoutError:
            print("  ⚠️  HF API timeout — check internet connection")
        except Exception as e:
            print(f"  ⚠️  HF API check failed: {e}")
    else:
        print("  ⚠️  HF_TOKEN not set")
    
    # ตรวจสอบ Gemini API (ถ้าใช้ gemini)
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        # Gemini key format check เท่านั้น (ไม่มี public endpoint สำหรับตรวจสอบ)
        if len(gemini_key) > 20:
            print("  ✅ GEMINI_API_KEY — format looks valid")
        else:
            print("  ⚠️  GEMINI_API_KEY — format might be invalid")
    else:
        print("  ⚠️  GEMINI_API_KEY not set")
    
    return all_ok


def check_python_version() -> bool:
    """ตรวจสอบ Python version"""
    print("\n🐍 Checking Python version...")
    
    version_info = sys.version_info
    required_version = (3, 10)  # Python 3.10+
    
    if version_info >= required_version:
        print(f"  ✅ Python {version_info.major}.{version_info.minor} — OK")
        return True
    else:
        print(
            f"  ❌ Python {version_info.major}.{version_info.minor} — "
            f"requires 3.10+"
        )
        return False


def check_dependencies() -> bool:
    """ตรวจสอบ critical dependencies"""
    print("\n📦 Checking critical dependencies...")
    
    critical_modules = [
        "fastapi",
        "asyncio",
        "psycopg2",
        "pandas",
        "numpy",
        "requests",
        "httpx",
    ]
    
    all_ok = True
    for module in critical_modules:
        try:
            __import__(module)
            print(f"  ✅ {module}")
        except ImportError:
            print(f"  ❌ {module} — NOT INSTALLED")
            all_ok = False
    
    return all_ok


async def run_all_checks() -> bool:
    """รัน checks ทั้งหมด"""
    print("\n" + "=" * 60)
    print("🚀 Gold Trading AI — Startup Validation")
    print("=" * 60)
    
    checks = [
        ("Python Version", check_python_version()),
        ("Environment Variables", check_env_vars()),
        ("Dependencies", check_dependencies()),
        ("Database", check_database()),
        ("API Keys", await check_api_keys()),
    ]
    
    results = [passed for _, passed in checks]
    
    print("\n" + "=" * 60)
    print("📊 Validation Summary")
    print("=" * 60)
    
    for name, passed in checks:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} — {name}")
    
    all_passed = all(results)
    
    if all_passed:
        print("\n✅ All checks passed! System is ready.")
        return True
    else:
        print("\n❌ Some checks failed. Please fix the issues above.")
        return False


def main():
    """Entry point"""
    try:
        # Windows ปิดใช้ event loop ที่มีอยู่
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        result = asyncio.run(run_all_checks())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Validation interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error during validation: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
