"""
core/chart_renderer.py — Chart Tab HTML Renderer
Gold Trading Agent v3.2

render 2 ส่วนหลักตามรูป:
  1. TradingView Advanced Chart Widget  (candlestick + volume)
  2. Gold Spot Price Card               (USD + THB)
  3. Provider Status Table
"""


class ChartTabRenderer:
    """Render Live Chart tab — เหมือน layout ในรูป screenshot"""

    # Gradio interval string → TradingView interval string
    _TV_INTERVAL = {
        "1m": "1", "5m": "5", "15m": "15", "30m": "30",
        "1h": "60", "4h": "240", "1d": "D", "1w": "W",
    }

    # ─────────────────────────────────────────────────────────────────
    # 1. TradingView Advanced Chart
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def tradingview_widget(interval: str = "1h") -> str:
        """
        TradingView Advanced Real-Time Chart Widget
        - Symbol  : OANDA:XAUUSD  (Gold Spot/USD — เหมือนในรูป)
        - Style   : Candlestick + Volume
        - Timezone: Asia/Bangkok
        - Theme   : Dark
        """
        tv_iv = ChartTabRenderer._TV_INTERVAL.get(interval, "60")

        return f"""
                <div style="height: 600px; width: 100%; border-radius: 12px; overflow: hidden; border: 1.5px solid rgba(0,88,190,0.1);">
                    <iframe 
                        srcdoc='
                            <html>
                            <body style="margin:0;">
                                <div id="tradingview_widget" style="height:100vh;"></div>
                                <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
                                <script type="text/javascript">
                                new TradingView.widget({{
                                "autosize": true,
                                "symbol": "OANDA:XAUUSD",
                                "interval": "{tv_iv}",
                                "timezone": "Asia/Bangkok",
                                "theme": "dark",
                                "style": "1",
                                "locale": "en",
                                "enable_publishing": false,
                                "allow_symbol_change": true,
                                "container_id": "tradingview_widget"
                                }});
                                </script>
                            </body>
                            </html>
                        '
                        style="width: 100%; height: 100%; border: none;"
                    ></iframe>
                </div>
                """

    # ─────────────────────────────────────────────────────────────────
    # 2. Gold Spot Price Card  (ขวาบน)
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def gold_price_card(data: dict) -> str:
        """
        Dark card แสดง USD/oz + THB/oz + THB/gram
        data: dict จาก ChartService.fetch_price()
        """
        # ── Error state ──────────────────────────────────────────────
        if data.get("status") == "error":
            return f"""
            <div style="
                background: #1a1f2e;
                border: 1px solid #3a2020;
                border-radius: 12px;
                padding: 20px;
                font-family: 'Segoe UI', sans-serif;
                color: #ff6b6b;
            ">
                <div style="font-size:12px; font-weight:700; margin-bottom:6px;">
                    ⚠️ ไม่สามารถดึงราคาได้
                </div>
                <div style="font-size:11px; color:#888; line-height:1.6;">
                    {data.get('error', 'Unknown error')}<br>
                    {data.get('hint', '')}
                </div>
            </div>"""

        # ── Extract values ───────────────────────────────────────────
        currency    = data.get("currency", "THB")
        price_oz    = data.get("price", 0)          # per troy oz
        change      = data.get("change", 0)
        change_pct  = data.get("change_pct", 0)
        timestamp   = data.get("timestamp", "—")
        fetched_at  = data.get("fetched_at", "—")

        # คำนวณ USD ↔ THB
        # ถ้า fetch เป็น THB: price_oz คือ THB/oz → แปลงเป็น USD
        # ถ้า fetch เป็น USD: price_oz คือ USD/oz → แปลงเป็น THB
        USD_THB = 33.5   # approximate — ใช้เป็น fallback เท่านั้น
        if currency == "THB":
            price_thb_oz   = price_oz
            price_usd_oz   = round(price_oz / USD_THB, 2)
        else:
            price_usd_oz   = price_oz
            price_thb_oz   = round(price_oz * USD_THB, 2)

        price_thb_gram = round(price_thb_oz / 31.1035, 2)

        is_up      = change_pct >= 0
        chg_color  = "#4caf7d" if is_up else "#ef5350"
        chg_bg     = "rgba(76,175,125,0.10)" if is_up else "rgba(239,83,80,0.10)"
        chg_border = "rgba(76,175,125,0.30)" if is_up else "rgba(239,83,80,0.30)"
        chg_arrow  = "▲" if is_up else "▼"

        return f"""
        <div style="
            background: linear-gradient(145deg, #1a1f35, #0f1525);
            border: 1px solid #2a3550;
            border-radius: 14px;
            padding: 18px 20px;
            font-family: 'Segoe UI', sans-serif;
            color: #e2e8f0;
            box-shadow: 0 6px 24px rgba(0,0,0,0.35);
        ">
            <!-- ── Header ── -->
            <div style="display:flex; align-items:center; gap:8px; margin-bottom:3px;">
                <span style="
                    width:9px; height:9px; border-radius:50%;
                    background:#f0c040;
                    box-shadow: 0 0 7px #f0c040;
                    display:inline-block; flex-shrink:0;
                "></span>
                <span style="
                    font-size:10px; color:#8899bb; font-weight:700;
                    text-transform:uppercase; letter-spacing:1.8px;
                ">GOLD SPOT PRICE</span>
                <span style="
                    margin-left:auto; font-size:9px;
                    color:#4caf7d; display:flex; align-items:center; gap:4px;
                ">
                    <span style="width:6px;height:6px;border-radius:50%;
                                 background:#4caf7d;display:inline-block;
                                 animation:pulse 2s infinite;"></span>
                    london_fix_static
                </span>
            </div>
            <div style="font-size:10px; color:#3d4f70; margin-bottom:16px;">
                {timestamp} (TH)
            </div>

            <!-- ── Main Prices ── -->
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:14px;">
                <!-- USD -->
                <div>
                    <div style="font-size:9px; color:#8899bb; font-weight:600;
                                text-transform:uppercase; letter-spacing:1px; margin-bottom:5px;">
                        USD / troy oz
                    </div>
                    <div style="font-size:26px; font-weight:800; color:#f0c040;
                                letter-spacing:-0.5px; line-height:1;">
                        ${price_usd_oz:,.2f}
                    </div>
                </div>
                <!-- THB -->
                <div>
                    <div style="font-size:9px; color:#8899bb; font-weight:600;
                                text-transform:uppercase; letter-spacing:1px; margin-bottom:5px;">
                        THB / บาทแท้ (96.5%)
                    </div>
                    <div style="font-size:26px; font-weight:800; color:#7dd3fc;
                                letter-spacing:-0.5px; line-height:1;">
                        ฿{price_thb_oz:,.0f}
                    </div>
                </div>
            </div>

            <!-- ── THB/gram + rate ── -->
            <div style="
                display:grid; grid-template-columns:1fr 1fr; gap:10px;
                background:rgba(255,255,255,0.04);
                border-radius:8px; padding:10px 12px; margin-bottom:14px;
            ">
                <div>
                    <div style="font-size:9px; color:#8899bb; margin-bottom:3px;
                                text-transform:uppercase; letter-spacing:0.8px;">THB / กรัม</div>
                    <div style="font-size:15px; font-weight:700; color:#e2e8f0;">
                        ฿{price_thb_gram:,.2f}
                    </div>
                </div>
                <div>
                    <div style="font-size:9px; color:#8899bb; margin-bottom:3px;
                                text-transform:uppercase; letter-spacing:0.8px;">USD/THB Rate</div>
                    <div style="font-size:15px; font-weight:700; color:#e2e8f0;">
                        ~{USD_THB:.2f}
                    </div>
                </div>
            </div>

            <!-- ── Change badge + timestamp ── -->
            <div style="display:flex; align-items:center; gap:10px;">
                <div style="
                    padding:4px 14px;
                    background:{chg_bg};
                    border:1px solid {chg_border};
                    border-radius:20px;
                    font-size:13px; font-weight:800; color:{chg_color};
                ">
                    {chg_arrow} {abs(change_pct):.2f}%
                </div>
                <div style="font-size:10px; color:#3d4f70;">
                    เทียบ prev close · อัพเดท {fetched_at}
                </div>
            </div>
        </div>
        <style>
            @keyframes pulse {{
                0%, 100% {{ opacity:1; }}
                50% {{ opacity:0.3; }}
            }}
        </style>
        """

    # ─────────────────────────────────────────────────────────────────
    # 3. Provider Status Table  (ขวาล่าง)
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def provider_table(providers: list) -> str:
        """
        ตาราง Provider เหมือนในรูป
        providers: list จาก ChartService.get_providers_info()
        """
        rows = ""
        for p in providers:
            key_ok = p.get("api_key_set", False)
            key_html = (
                '<span style="color:#4caf7d; font-weight:700; font-size:12px;">✅ Set</span>'
                if key_ok else
                '<span style="color:#ef5350; font-weight:700; font-size:12px;">✗ Missing</span>'
            )
            rows += f"""
            <tr style="border-bottom:1px solid #f0f4f8;">
                <td style="padding:10px 10px; font-weight:700;
                           font-size:13px; color:#1a2a4a;">
                    {p.get('name','—')}
                </td>
                <td style="padding:10px 8px; font-family:monospace;
                           font-size:11px; color:#4a5568;">
                    {p.get('model_id','—')}
                </td>
                <td style="padding:10px 8px;">
                    <span style="
                        background:#dbeafe; color:#1d4ed8;
                        padding:2px 9px; border-radius:10px;
                        font-size:11px; font-weight:600;
                    ">{p.get('tier','Free')}</span>
                </td>
                <td style="padding:10px 8px; font-size:12px; color:#4a5568;">
                    {p.get('rate_limit','—')}
                </td>
                <td style="padding:10px 8px;">{key_html}</td>
                <td style="padding:10px 8px; font-size:11px; color:#a0aec0;">
                    ⊞
                </td>
                <td style="padding:10px 8px; font-size:11px; color:#a0aec0;">
                    ○ Not loaded
                </td>
            </tr>"""

        return f"""
        <div style="
            border-radius:10px; overflow:hidden;
            border:1px solid #e2e8f0;
            box-shadow:0 2px 10px rgba(0,0,0,0.06);
            margin-top:10px;
        ">
            <table style="width:100%; border-collapse:collapse;
                          font-family:'Segoe UI',sans-serif;">
                <thead>
                    <tr style="background:#f8fafc; border-bottom:2px solid #e2e8f0;">
                        <th style="padding:9px 10px; text-align:left; font-size:12px;
                                   color:#64748b; font-weight:600;">Provider</th>
                        <th style="padding:9px 8px; text-align:left; font-size:12px;
                                   color:#64748b; font-weight:600;">Model ID</th>
                        <th style="padding:9px 8px; text-align:left; font-size:12px;
                                   color:#64748b; font-weight:600;">Tier</th>
                        <th style="padding:9px 8px; text-align:left; font-size:12px;
                                   color:#64748b; font-weight:600;">Rate Limit</th>
                        <th style="padding:9px 8px; text-align:left; font-size:12px;
                                   color:#64748b; font-weight:600;">API Key</th>
                        <th style="padding:9px 8px; text-align:left; font-size:12px;
                                   color:#64748b; font-weight:600;">Cache</th>
                        <th style="padding:9px 8px; text-align:left; font-size:12px;
                                   color:#64748b; font-weight:600;">Loaded</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
        """