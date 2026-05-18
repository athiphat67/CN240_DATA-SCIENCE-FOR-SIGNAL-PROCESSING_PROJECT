import json

from dotenv import load_dotenv

from data_engine.hsh_supabase_provider import HshSupabaseMarketDataProvider


def main() -> None:
    load_dotenv()

    provider = HshSupabaseMarketDataProvider()
    market_state = provider.build_market_state(interval="5m")

    data_quality = market_state.get("data_quality", {})
    thai_gold = market_state.get("market_data", {}).get("thai_gold_thb", {})
    indicators = market_state.get("technical_indicators", {})
    rsi = indicators.get("rsi", {})
    macd = indicators.get("macd", {})
    bollinger = indicators.get("bollinger", {})

    print("source=supabase_hsh_ig")
    print("data_quality:")
    print(json.dumps(data_quality, indent=2, ensure_ascii=False, default=str))
    print("latest thai_gold_thb:")
    print(json.dumps(thai_gold, indent=2, ensure_ascii=False, default=str))
    print("latest technical indicators:")
    print(
        json.dumps(
            {
                "rsi": rsi.get("value"),
                "macd_histogram": macd.get("histogram"),
                "bollinger_signal": bollinger.get("signal"),
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )

    raw_ohlcv = market_state.get("_raw_ohlcv")
    if data_quality.get("status") == "ok":
        assert raw_ohlcv is not None, "_raw_ohlcv is missing"
        assert len(raw_ohlcv) >= 50, f"_raw_ohlcv has only {len(raw_ohlcv)} rows"


if __name__ == "__main__":
    main()
