"""
core/dashboard_css.py
=====================
Global CSS override สำหรับ Gradio
Design system: High-End Financial Intelligence
Theme: Purple × Gold (brand) + Semantic colors (green/red/amber)
"""

DASHBOARD_CSS = """
/* ── Google Fonts ── */
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif:wght@700&family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@400;500;600&display=swap');

/* ── Design tokens ── */
:root {
    --surface:              #f6fafe;
    --surface-low:          #f0f4f8;
    --surface-high:         #e4e9ed;
    --surface-highest:      #dfe3e7;
    --surface-lowest:       #ffffff;
    --surface-container:    #eaeef2;

    /* Purple-Gold brand */
    --brand-purple:         #6D28D9;
    --brand-purple-light:   #8B5CF6;
    --brand-gold:           #D97706;
    --brand-gold-light:     #F59E0B;

    /* Semantic (keep blue for links/focus) */
    --primary:              #6D28D9;
    --primary-container:    #D97706;

    --success:              #10b981;
    --error:                #ef4444;
    --warning:              #f59e0b;
    --on-surface:           #171c1f;
    --on-surface-var:       #424754;
    --outline-var:          #c2c6d6;
    --inverse-surface:      #1e293b;
    --shadow-ambient:       0px 12px 32px rgba(109,40,217,0.06);
    --shadow-float:         0px 24px 48px rgba(109,40,217,0.10);
    --font-body:            'Inter', sans-serif;
    --font-mono:            'IBM Plex Mono', monospace;
    --font-headline:        'Noto Serif', serif;
}

/* ── Page background ── */
body, .gradio-container {
    background: var(--surface) !important;
    font-family: var(--font-body) !important;
    color: var(--on-surface) !important;
}

.gradio-container > .main {
    background: transparent !important;
}
.block {
    background: transparent !important;
    border: none !important;
}

/* ── Tab navigation ── */
.tab-nav {
    background: #ffffff !important;
    border-bottom: 2px solid #ede9fe !important;
    padding: 0 8px !important;
    gap: 0 !important;
    box-shadow: 0 2px 8px rgba(109,40,217,0.06) !important;
}
.tab-nav button {
    font-family: var(--font-body) !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    color: var(--on-surface-var) !important;
    background: transparent !important;
    border: none !important;
    border-bottom: 3px solid transparent !important;
    border-radius: 0 !important;
    padding: 11px 18px !important;
    transition: color 0.15s, border-color 0.15s !important;
    margin-bottom: -2px !important;
}
.tab-nav button.selected {
    color: var(--brand-purple) !important;
    border-bottom-color: var(--brand-purple) !important;
    font-weight: 700 !important;
    background: linear-gradient(180deg, rgba(109,40,217,0.04) 0%, transparent 100%) !important;
}
.tab-nav button:hover:not(.selected) {
    color: var(--on-surface) !important;
    background: rgba(109,40,217,0.03) !important;
}

/* ── Input / Textbox ── */
.gr-box, .gr-text-input, textarea, input[type="text"],
input[type="number"], .gr-input {
    font-family: var(--font-body) !important;
    font-size: 13px !important;
    background: var(--surface-low) !important;
    border: 1px solid #e5e7eb !important;
    border-radius: 8px !important;
    color: var(--on-surface) !important;
    transition: border-color 0.15s, background 0.15s !important;
}
.gr-box:focus-within, textarea:focus, input:focus {
    background: var(--surface-lowest) !important;
    border-color: var(--brand-purple) !important;
    outline: 3px solid rgba(109,40,217,0.12) !important;
    outline-offset: 0 !important;
}

/* Label above inputs */
label > span, .gr-label span {
    font-family: var(--font-body) !important;
    font-size: 10px !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 1.2px !important;
    color: var(--on-surface-var) !important;
}

/* ── Dropdown ── */
.gr-dropdown select, select {
    font-family: var(--font-body) !important;
    font-size: 13px !important;
    background: var(--surface-low) !important;
    border: 1px solid #e5e7eb !important;
    border-radius: 8px !important;
    color: var(--on-surface) !important;
}

/* ── Checkbox ── */
.gr-checkbox-group label, .gr-checkbox label {
    font-family: var(--font-body) !important;
    font-size: 12px !important;
    color: var(--on-surface) !important;
}
input[type="checkbox"]:checked {
    accent-color: var(--brand-purple) !important;
}

/* ══════════════════════════════════════════════
   ██████╗ ██╗   ██╗████████╗████████╗ ██████╗ ███╗   ██╗███████╗
   ██╔══██╗██║   ██║╚══██╔══╝╚══██╔══╝██╔═══██╗████╗  ██║██╔════╝
   ██████╔╝██║   ██║   ██║      ██║   ██║   ██║██╔██╗ ██║███████╗
   ██╔══██╗██║   ██║   ██║      ██║   ██║   ██║██║╚██╗██║╚════██║
   ██████╔╝╚██████╔╝   ██║      ██║   ╚██████╔╝██║ ╚████║███████║
   Purple × Gold Theme
   ══════════════════════════════════════════════ */

/* Primary button — Purple → Gold gradient */
.gr-button-primary, button.primary, button[data-testid*="primary"] {
    font-family: var(--font-body) !important;
    font-size: 13px !important;
    font-weight: 700 !important;
    letter-spacing: 0.5px !important;
    background: linear-gradient(135deg, #6D28D9 0%, #D97706 100%) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 11px 24px !important;
    box-shadow: 0 4px 18px rgba(109,40,217,0.30) !important;
    transition: opacity 0.15s, transform 0.1s, box-shadow 0.15s !important;
    cursor: pointer !important;
    position: relative !important;
    overflow: hidden !important;
}
.gr-button-primary::before, button.primary::before {
    content: '' !important;
    position: absolute !important;
    inset: 0 !important;
    background: linear-gradient(135deg, rgba(255,255,255,0.15) 0%, transparent 60%) !important;
    pointer-events: none !important;
}
.gr-button-primary:hover, button.primary:hover {
    opacity: 0.92 !important;
    box-shadow: 0 6px 24px rgba(109,40,217,0.40) !important;
    transform: translateY(-1px) !important;
}
.gr-button-primary:active, button.primary:active {
    transform: scale(0.97) translateY(0) !important;
    box-shadow: 0 2px 10px rgba(109,40,217,0.25) !important;
}

/* Large primary button (Run Analysis) */
button.primary[data-size="lg"], .run-btn-large {
    padding: 14px 28px !important;
    font-size: 14px !important;
    border-radius: 12px !important;
    box-shadow: 0 6px 22px rgba(109,40,217,0.35) !important;
}

/* Secondary button */
.gr-button-secondary, button.secondary {
    font-family: var(--font-body) !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    background: var(--surface-high) !important;
    color: var(--on-surface) !important;
    border: 1px solid #e5e7eb !important;
    border-radius: 10px !important;
    padding: 10px 20px !important;
    transition: background 0.15s, border-color 0.15s !important;
}
.gr-button-secondary:hover, button.secondary:hover {
    background: var(--surface-highest) !important;
    border-color: #d1d5db !important;
}

/* Small secondary button */
button.secondary[data-size="sm"] {
    padding: 6px 14px !important;
    font-size: 12px !important;
    border-radius: 8px !important;
}

/* ── Markdown headings ── */
.gr-markdown h1, .gr-markdown h2 {
    font-family: var(--font-headline) !important;
    color: var(--on-surface) !important;
}
.gr-markdown h3 {
    font-family: var(--font-body) !important;
    font-size: 12px !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 1.4px !important;
    color: var(--brand-purple) !important;
    margin: 16px 0 8px !important;
    padding-bottom: 4px !important;
    border-bottom: 2px solid #ede9fe !important;
}
.gr-markdown h4 {
    font-family: var(--font-body) !important;
    font-size: 11px !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 1.2px !important;
    color: var(--on-surface-var) !important;
}
.gr-markdown p {
    font-family: var(--font-body) !important;
    font-size: 13px !important;
    color: var(--on-surface-var) !important;
}

/* ── Code / mono ── */
.gr-markdown code, code, pre {
    font-family: var(--font-mono) !important;
    font-size: 12px !important;
    background: #f3f0ff !important;
    color: var(--brand-purple) !important;
    border-radius: 4px !important;
    padding: 2px 6px !important;
}

/* ── Row spacing ── */
.gr-row { gap: 14px !important; }

/* ── Stats bar ── */
#stats-bar {
    padding: 10px 14px !important;
    background: var(--surface-low) !important;
    border-radius: 10px !important;
    font-family: var(--font-mono) !important;
    font-size: 12px !important;
}

/* ── Scrollbars ── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: #d8b4fe;
    border-radius: 99px;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--brand-purple);
}

/* ── Accordion ── */
.gr-accordion {
    border: 1px solid #ede9fe !important;
    border-radius: 10px !important;
    overflow: hidden !important;
}
.gr-accordion > .label-wrap {
    background: linear-gradient(135deg, #faf5ff, #fffbeb) !important;
    padding: 10px 16px !important;
    font-family: var(--font-body) !important;
    font-size: 12px !important;
    font-weight: 700 !important;
    color: var(--brand-purple) !important;
}

/* ── Analysis page specific ── */
#analysis-status-bar {
    margin-bottom: 12px !important;
}

.controls-col {
    border-right: 1px solid #f3f0ff !important;
    padding-right: 16px !important;
}

.controls-col .gr-markdown h3 {
    margin-top: 20px !important;
}
.controls-col .gr-markdown h3:first-child {
    margin-top: 0 !important;
}

/* ── Log page specific ── */
#logs-status-bar {
    margin-bottom: 12px !important;
}

.log-panel {
    background: #0d1117 !important;
    border-radius: 12px !important;
    overflow: hidden !important;
}

/* ── General cards ── */
.card {
    background: white;
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0px 10px 30px rgba(109,40,217,0.06);
    border: 1px solid #f3f0ff;
}

/* ── Navbar ── */
#navbar {
    background: #ffffff;
    padding: 12px 24px;
    border-bottom: 1px solid #ede9fe;
}

/* ── Purple-Gold gradient utility ── */
.pg-gradient {
    background: linear-gradient(135deg, #6D28D9, #D97706) !important;
}
.pg-text {
    background: linear-gradient(135deg, #6D28D9, #D97706);
    -webkit-background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
    background-clip: text !important;
}

/* 1. Hide the Light/Dark/System buttons in the settings modal */
input[value="light"], input[value="dark"], input[value="system"] {
    display: none !important;
}
label:has(input[value="dark"]), label:has(input[value="light"]), label:has(input[value="system"]) {
    display: none !important;
}

/* 2. Force Dark Mode to render exactly like Light Mode */
.dark {
    --background-fill-primary: #ffffff !important;
    --background-fill-secondary: #f6fafe !important;
    --body-background-fill: #f6fafe !important;
    --body-text-color: #171c1f !important;
    --color-accent-soft: #eaeef2 !important;
    --border-color-primary: #eaeef2 !important;
    --block-background-fill: #ffffff !important;
}
body.dark {
    background-color: #f6fafe !important;
    color: #171c1f !important;
}

/* ── Gr.Group styling ── */
.gr-group {
    background: white !important;
    border: 1px solid #f3f0ff !important;
    border-radius: 12px !important;
    padding: 16px !important;
    margin-bottom: 12px !important;
    box-shadow: 0 2px 8px rgba(109,40,217,0.05) !important;
}
"""