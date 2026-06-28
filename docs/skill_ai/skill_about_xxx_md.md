ฉันจะจัดระเบียบความคิดทั้งหมดเป็น **Blueprint ที่ครบถ้วน** สำหรับสร้าง skill.md นี้:

---

# 📋 BLUEPRINT: Skill.md for Creating about_xxx.md Across GoldTrader Project

## 🎯 SKILL OVERVIEW

**Name**: `document-folder-architecture`  
**Purpose**: Generate comprehensive `about_[folder].md` files for each major folder in GoldTrader project  
**Output Type**: Markdown documentation (15+ KB per file)  
**Use Case**: Document project structure, architecture, and usage patterns hierarchically from root to leaf folders

---

## 📊 SCOPE & CONSTRAINTS

### What This Skill Does
1. **Generates** `about_xxx.md` files for individual folders (not just root)
2. **Follows** consistent 6-section structure across all files
3. **Handles** both fresh creation and editing/improving existing drafts
4. **Maintains** cross-references between related about_xxx.md files
5. **Includes** code examples, usage patterns, and extension points
6. **Documents** dependencies and relationships to other folders

### What This Skill Does NOT Do
- ❌ Replace inline code comments
- ❌ Generate API reference docs (those are in docstrings)
- ❌ Create change logs or commit history
- ❌ Generate from raw code alone (user provides context/structure)

### Target Folders (Priority Order)
```
TIER 1 (Core Intelligence - Large files, 15+ KB)
├── about_agent_core.md          ← ReAct, LLMClient, PromptBuilder, RiskManager
└── about_backtest.md            ← SimPortfolio, SessionManager, MetricsCalculator, DeployGate

TIER 2 (Data & Infrastructure - Medium/Large, 10-15 KB)
├── about_data_engine.md         ← Orchestrators, Indicators, News, Fetchers
├── about_database.md            ← PostgreSQL schema, RunDatabase, migrations
└── about_ui.md                  ← Dashboard, Services, Renderers, NavBar

TIER 3 (Supporting - Medium, 8-12 KB)
├── about_notification.md        ← Discord, Telegram notifiers
└── about_logs.md                ← Logger setup, decorators

TIER 4 (Root/Config)
└── about_src.md (EXISTING - maintain parity)
```

---

## 📐 UNIVERSAL 6-SECTION STRUCTURE

### Section 1: Folder Purpose (1-2 KB)
**What to include:**
- **1-sentence mission statement** of the folder
- **Why it exists** in the architecture
- **What problem it solves**
- **Key responsibility** (not files, but roles)
- **Scope & boundaries** (what it does vs doesn't)

**Example for agent_core:**
```
## 1. Folder Purpose

**agent_core/** is the 🧠 brain of GoldTrader — it houses all AI/LLM orchestration, 
prompt engineering, and trading risk validation logic.

### 1.1 Mission
Translate raw market data + technical indicators into structured trading decisions 
(BUY/SELL/HOLD) using multi-step ReAct reasoning loops, while enforcing hard rules 
for take-profit, stop-loss, and position sizing.

### 1.2 Core Responsibilities
- **ReAct Loop Orchestration** → Thought → Action → Observation → Decision
- **Prompt Engineering** → Role/Skill definitions + market state formatting
- **LLM Provider Management** → 8+ providers with fallback chain support
- **Risk Validation** → Daily loss limits + portfolio bust detection
- **Trading Rules Enforcement** → TP/SL rules from system prompt

### 1.3 Scope
✅ What this folder handles:
  - LLM coordination (call, parse JSON, handle errors)
  - Prompt construction (system + user prompts per role)
  - Trading logic (signal generation, rule checking)
  - Fallback chains (if one LLM fails, try next)

❌ What it does NOT handle:
  - Data fetching (that's data_engine/)
  - UI rendering (that's ui/)
  - Database persistence (that's database/)
  - Portfolio simulation (that's backtest/)
```

---

### Section 2: Key Files & Responsibilities (2-3 KB)

**What to include:**
- **File tree** with brief 1-line descriptions
- **Grouping by responsibility** (not alphabetical)
- **Dependencies** (e.g., "imports from data_engine/")
- **Size/complexity indicator** (📄 simple, 📋 medium, 📚 complex)

**Format:**
```
## 2. Key Files & Responsibilities

### agent_core/
├── config/
│   ├── roles.json                    📄 Role definitions + system prompts (TP/SL rules)
│   └── skills.json                   📄 Skill registry (tools + constraints)
│
├── core/
│   ├── prompt.py                     📚 PromptBuilder, RoleRegistry, SkillRegistry
│   │                                 • Builds user prompts per ReAct step
│   │                                 • Injects market state + portfolio status
│   │                                 • Formats technical indicators
│   │                                 • Handles timestamp for time-based exit rules
│   │
│   ├── react.py                      📚 ReactOrchestrator — main ReAct loop
│   │                                 • Thought → Action → Observation iteration
│   │                                 • Calls LLM, parses JSON, detects errors
│   │                                 • Enforces max iterations + tool call limits
│   │                                 • Aggregates token usage across steps
│   │
│   └── risk.py                       📋 RiskManager — hard rule enforcement
│                                     • TP1/TP2/TP3, SL1/SL2/SL3 checks
│                                     • Dead zone (02:00-06:14) detection
│                                     • Daily loss limit tracking
│                                     • Position sizing validation
│
└── llm/
    └── client.py                     📚 LLMClientFactory + 8 provider implementations
                                      • Gemini, Groq, Claude, OpenAI, Ollama, etc.
                                      • FallbackChainClient (primary → fallback → mock)
                                      • Token counting + LLMResponse struct
                                      • Provider-specific error handling
```

**File Statistics Table:**
```
| File | Lines | Imports From | Exports To |
|------|-------|--------------|-----------|
| prompt.py | ~450 | skills.json, roles.json | react.py, dashboard.py |
| react.py | ~600 | client.py, prompt.py, risk.py | services.py, backtest/ |
| risk.py | ~280 | portfolio.py | react.py |
| client.py | ~1200 | (external APIs) | react.py, backtest/ |
```

---

### Section 3: Architecture & Design Patterns (3-4 KB)

**What to include:**
- **Class hierarchy** (inheritance/composition)
- **Data flow** (how data moves through folder)
- **Design patterns used** (Factory, Chain of Responsibility, Strategy, etc.)
- **Key interfaces/protocols**
- **Why decisions were made** (architectural reasoning)

**Example structure:**
```
## 3. Architecture & Design Patterns

### 3.1 Class Hierarchy

PromptBuilder
├── RoleRegistry
│   └── RoleDefinition
│       ├── AIRole (enum: ANALYST, RISK_MANAGER, TRADER)
│       └── available_skills: List[str]
└── SkillRegistry
    └── Skill (name, description, tools, constraints)

ReactOrchestrator
├── LLMClient (abstract base)
│   ├── GeminiClient
│   ├── GroqClient
│   ├── ClaudeClient
│   ├── OllamaClient
│   └── ...
└── FallbackChainClient(list[LLMClient])
    └── active_provider (tracks which succeeded)

RiskManager
├── evaluate(llm_decision, market_state)
└── Hard rules (TP1/TP2/TP3, SL1/SL2/SL3)
```

### 3.2 Data Flow Diagram

```
Market State Dict
    ↓
PromptBuilder._format_market_state()
    ↓
LLM Prompt (system + user)
    ↓
ReactOrchestrator.run()
    → LLMClient.call()
    → extract_json(response)
    → _build_decision(parsed)
    ↓
RiskManager.evaluate()
    → Check TP/SL triggers
    → Validate confidence
    → Enforce position size
    ↓
Final Decision (signal + confidence + TP/SL)
```

### 3.3 Design Patterns

**Factory Pattern:**
```
LLMClientFactory.create("gemini") → GeminiClient instance
LLMClientFactory.create("groq") → GroqClient instance
```

**Chain of Responsibility:**
```
FallbackChainClient([("gemini", client1), ("groq", client2), ("mock", client3)])
├── Try gemini → if fails
├── Try groq → if fails
└── Try mock → always succeeds (hardcoded HOLD)
```

**Strategy Pattern:**
```
RiskManager implements different TP/SL strategies:
  - TP1: Simple threshold (PnL >= 300)
  - TP2: Combined (PnL >= 150 AND RSI > 65)
  - TP3: Multi-indicator (PnL >= 100 AND MACD < 0)
```

### 3.4 Architectural Decisions & Rationale

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| Separate RiskManager from ReAct | Hard rules != LLM reasoning | Adds 1 extra validation step |
| FallbackChainClient | Resilience if primary LLM fails | Extra code complexity |
| System prompt as JSON rule list | Easy to maintain trading rules | LLM must parse + follow format |
| Token counting per call | Monitor API costs | ~10% overhead per call |
```

---

### Section 4: Usage Examples (3-4 KB)

**What to include:**
- **Concrete code examples** (not pseudocode)
- **Common use cases** (not exhaustive)
- **Step-by-step flow** for typical operations
- **Error handling patterns**
- **Configuration examples**

**Format:**

```
## 4. Usage Examples

### 4.1 Running ReAct Loop (Most Common)

```python
from agent_core.core.prompt import PromptBuilder, RoleRegistry, SkillRegistry
from agent_core.core.react import ReactOrchestrator, ReactConfig
from agent_core.llm.client import LLMClientFactory

# 1. Load registries
skill_registry = SkillRegistry()
skill_registry.load_from_json("agent_core/config/skills.json")

role_registry = RoleRegistry(skill_registry)
role_registry.load_from_json("agent_core/config/roles.json")

# 2. Create LLM client (with fallback)
llm = LLMClientFactory.create("gemini")

# 3. Build prompt
prompt_builder = PromptBuilder(role_registry, AIRole.ANALYST)

# 4. Create ReAct orchestrator
config = ReactConfig(max_iterations=5, max_tool_calls=0)
react = ReactOrchestrator(
    llm_client=llm,
    prompt_builder=prompt_builder,
    tool_registry={},
    config=config,
)

# 5. Run analysis
result = react.run(market_state={...})
final_decision = result["final_decision"]
print(f"Signal: {final_decision['signal']}, Confidence: {final_decision['confidence']}")
```

### 4.2 Switching LLM Providers

```python
# Primary → Groq → Ollama → Mock fallback chain
from agent_core.llm.client import FallbackChainClient

clients = [
    ("groq", LLMClientFactory.create("groq")),
    ("ollama", LLMClientFactory.create("ollama", model="qwen3.5:9b")),
    ("mock", LLMClientFactory.create("mock")),
]
chain = FallbackChainClient(clients)

react = ReactOrchestrator(..., llm_client=chain, ...)
result = react.run(market_state)
print(f"Used provider: {chain.active_provider}")
```

### 4.3 Custom Role with Different System Prompt

```python
# Modify roles.json or create programmatically
custom_role = RoleDefinition(
    name=AIRole.ANALYST,
    title="Conservative Trader",
    system_prompt_template="""
    You are a CONSERVATIVE gold trader.
    - Only recommend BUY if confidence >= 0.80 (strict!)
    - Always enforce TP/SL rules
    - Prefer HOLD over risky signals
    """,
    available_skills=["market_analysis", "risk_assessment"],
)
role_registry.register(custom_role)
```

### 4.4 Risk Manager Direct Usage (for validation)

```python
from agent_core.core.risk import RiskManager

risk_mgr = RiskManager(
    atr_multiplier=2.0,
    risk_reward_ratio=1.5,
    min_confidence=0.6,
    max_daily_loss_thb=500.0,
)

# Validate LLM decision
llm_decision = {"signal": "BUY", "confidence": 0.65, "entry_price": 72000}
final = risk_mgr.evaluate(llm_decision, market_state)

if final["signal"] == "HOLD":
    print(f"Rejected: {final['rejection_reason']}")
else:
    print(f"Approved: {final['position_size_thb']} THB, TP={final['take_profit']}")
```

### 4.5 Error Handling Patterns

```python
from agent_core.llm.client import LLMProviderError, LLMUnavailableError

try:
    result = react.run(market_state)
except LLMUnavailableError as e:
    print(f"LLM unavailable: {e} — falling back to HOLD")
except LLMProviderError as e:
    print(f"API error: {e} — FallbackChain will retry")
except Exception as e:
    print(f"Unexpected error: {type(e).__name__}: {e}")
```

---

### Section 5: Extension Points & How to Add More (3-4 KB)

**What to include:**
- **How to add new LLM provider**
- **How to add new skill**
- **How to modify trading rules**
- **How to add new indicator to market state**
- **Code templates/patterns for each**

**Format:**

```
## 5. Extension Points & How to Add More

### 5.1 Adding a New LLM Provider

**Step 1:** Create class in `agent_core/llm/client.py`

```python
class MyCustomLLMClient(LLMClient):
    PROVIDER_NAME = "mycustom"
    DEFAULT_MODEL = "my-model-v1"
    
    def __init__(self, api_key=None, model=None, **kwargs):
        self.api_key = api_key or os.environ.get("MY_API_KEY")
        self.model = model or self.DEFAULT_MODEL
        if not self.api_key:
            raise LLMUnavailableError("MY_API_KEY not set")
    
    def call(self, prompt_package: PromptPackage) -> LLMResponse:
        # 1. Build payload
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt_package.system},
                {"role": "user", "content": prompt_package.user},
            ]
        }
        
        # 2. Call API
        response = requests.post(
            "https://api.mycustom.com/chat",
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        response.raise_for_status()
        
        # 3. Parse response
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        
        # 4. Return LLMResponse (MUST include all fields!)
        return LLMResponse(
            text=text,
            prompt_text=f"SYSTEM:\n{prompt_package.system}\n\nUSER:\n{prompt_package.user}",
            token_input=data.get("usage", {}).get("prompt_tokens", 0),
            token_output=data.get("usage", {}).get("completion_tokens", 0),
            token_total=data.get("usage", {}).get("total_tokens", 0),
            model=self.model,
            provider=self.PROVIDER_NAME,
        )
    
    def is_available(self) -> bool:
        return self.api_key is not None
```

**Step 2:** Register in factory

```python
LLMClientFactory.register("mycustom", MyCustomLLMClient)
```

**Step 3:** Add to UI config

```python
# ui/core/config.py
PROVIDER_CHOICES.append(("My Custom LLM", "mycustom"))
PROVIDER_FALLBACK_CHAIN["mycustom"] = ["mycustom", "gemini", "mock"]
```

### 5.2 Modifying Trading Rules (TP/SL)

**Rules are in `agent_core/config/roles.json` → system_prompt → `### Take-Profit` section**

**Current Example:**
```json
"TP1: Unrealized PnL >= +300 THB → auto-sell (target met)"
```

**To Add New Rule:**
1. Edit `roles.json` system_prompt
2. Add line like: `TP4: Unrealized PnL >= +250 THB AND Bollinger Band breakout → SELL (momentum)`
3. RiskManager will check it automatically (if properly formatted)

**Template:**
```
TP[N]: Condition1 AND Condition2 → Action (reasoning)
SL[N]: Condition1 OR Condition2 → Action (reasoning)
```

### 5.3 Adding New Technical Indicator to Market State

**Indicators are calculated in `data_engine/indicators.py` → TechnicalIndicators class**

```python
# Add to TechnicalIndicators.to_dict() return:

def calculate_stochastic(self) -> dict:
    """Stochastic oscillator %K"""
    lowest_low = self.df['low'].rolling(window=14).min()
    highest_high = self.df['high'].rolling(window=14).max()
    k = 100 * (self.df['close'] - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(window=3).mean()
    return {
        "k_value": round(k.iloc[-1], 2),
        "d_value": round(d.iloc[-1], 2),
        "signal": "overbought" if k.iloc[-1] > 80 else "oversold" if k.iloc[-1] < 20 else "neutral",
    }

# Then in to_dict():
indicators_dict["stochastic"] = self.calculate_stochastic()
```

Then update `roles.json` system_prompt to mention stochastic in decision logic.

### 5.4 Adding New Skill

**Skills are in `agent_core/config/skills.json`**

```json
{
  "skills": [
    {
      "name": "gold_specific_analysis",
      "description": "Analyze gold-specific factors like geopolitical risk, mining news, central bank activity",
      "tools": ["fetch_geopolitical_risk", "fetch_mining_news", "fetch_central_bank_decisions"],
      "constraints": {
        "max_calls_per_step": 2,
        "required_data": ["geopolitical_sentiment", "mining_disruption_risk"]
      }
    }
  ]
}
```

Then reference in `roles.json`:
```json
"available_skills": ["market_analysis", "risk_assessment", "gold_specific_analysis"]
```

### 5.5 Checklist for Adding Features to agent_core/

- [ ] Define in `roles.json` or `skills.json`
- [ ] Add code to `core/` or `llm/`
- [ ] Update `PromptBuilder._format_market_state()` if data structure changes
- [ ] Add test cases (if backtest)
- [ ] Update this about_agent_core.md Section 5
- [ ] Update `about_src.md` Changelog if major change

---

### Section 6: Related Folders & Dependencies (2-3 KB)

**What to include:**
- **Map of dependencies** (what this folder imports from)
- **Map of dependents** (what imports from this folder)
- **Data structure contracts** (what format market_state must be, etc.)
- **Integration points** (where this folder plugs into others)

**Format:**

```
## 6. Related Folders & Dependencies

### 6.1 Dependency Graph

```
agent_core/
    ├── imports FROM:
    │   ├── agent_core/config/roles.json (system prompts)
    │   ├── agent_core/config/skills.json (skill definitions)
    │   └── (nothing else — no internal imports outside agent_core!)
    │
    └── imported BY:
        ├── ui/core/services.py (AnalysisService calls ReactOrchestrator)
        ├── backtest/run_main_backtest.py (backtests with ReactOrchestrator)
        └── main.py (CLI uses ReactOrchestrator)
```

### 6.2 Data Contracts

**market_state dict structure (MUST match):**
```python
{
    "market_data": {
        "thai_gold_thb": {
            "sell_price_thb": float,  # ราคาขายออม NOW
            "buy_price_thb": float,   # ราคาซื้อออม NOW
        },
        "spot_price_usd": {
            "price_usd_per_oz": float,  # XAU/USD
        },
        "forex": {
            "usd_thb": float,  # exchange rate
        },
    },
    "technical_indicators": {
        "rsi": {"value": float, "signal": str},
        "macd": {"macd_line": float, "histogram": float, "signal": str},
        "trend": {"ema_20": float, "ema_50": float, "trend": str},
        "bollinger": {"upper": float, "lower": float, "mid": float},
        "atr": {"value": float},
    },
    "portfolio": {
        "cash_balance": float,
        "gold_grams": float,
        "unrealized_pnl": float,
        "trades_today": int,
    },
    "timestamp": str,  # ISO format
}
```

**final_decision dict structure (output of react.run()):**
```python
{
    "signal": "BUY" | "SELL" | "HOLD",
    "confidence": float,  # 0.0 to 1.0
    "entry_price": float | None,  # THB/gram
    "stop_loss": float | None,
    "take_profit": float | None,
    "rationale": str,  # max 200 chars
}
```

### 6.3 Integration Points

| Folder | How it uses agent_core | When |
|--------|------------------------|------|
| **ui/core/services.py** | Instantiates ReactOrchestrator, calls .run() | Every analysis run |
| **backtest/run_main_backtest.py** | Calls ReactOrchestrator per candle | Backtesting |
| **main.py** | CLI instantiates ReactOrchestrator | CLI mode |

### 6.4 API Boundaries

**What agent_core exposes (public):**
- `ReactOrchestrator.run(market_state) → dict`
- `RiskManager.evaluate(llm_decision, market_state) → dict`
- `PromptBuilder.build_thought(...), build_final_decision(...)`
- `LLMClientFactory.create(provider) → LLMClient`

**What agent_core hides (private):**
- Internal LLM error handling
- Token parsing logic
- Registry internals

**What calls agent_core MUST provide:**
- Valid `market_state` dict matching data contract (Section 6.2)
- `llm_client` that implements LLMClient interface
- Valid `prompt_package` with system + user fields

---

## 🛠️ OPERATION GUIDELINES FOR SKILL.MD

### When to Use This Skill

**Use THIS skill when:**
- ✅ You want to create `about_[folder].md` for first time
- ✅ You have a partial `about_[folder].md` and want to expand/improve it
- ✅ You want to ensure consistency across multiple about_xxx.md files
- ✅ You're doing major refactor and need to update documentation

**DON'T use this skill for:**
- ❌ Inline code comments (use code comments directly)
- ❌ API reference (use docstrings in code)
- ❌ Quick bug fixes (not documentation-scope)
- ❌ Creating architecture diagrams (use draw.io, not markdown)

### Input/Output Specification

**Input:**
```
Skill Request:
  folder_path: str                    # e.g., "agent_core"
  existing_file: str | None           # e.g., partial about_agent_core.md (optional)
  depth_level: "full" | "summary"     # "full" = 15+ KB, "summary" = 8-10 KB
  include_code_examples: bool         # Default: True
  include_diagrams: bool              # Default: True (ASCII/Mermaid)
  target_audience: str                # "developers" | "maintainers" | "contributors"
```

**Output:**
```
Result:
  about_[folder].md                   # 15+ KB comprehensive guide
  integration_checklist.txt           # Dependencies to verify
  examples.py                         # Copy-paste code snippets (optional)
```

### Quality Checklist

Before finalizing any `about_xxx.md`, verify:

- [ ] **Section 1 (Purpose):** Clear mission statement + scope boundaries
- [ ] **Section 2 (Files):** All files listed, dependencies shown
- [ ] **Section 3 (Architecture):** Design patterns explained, data flow clear
- [ ] **Section 4 (Examples):** All 5+ examples are runnable code
- [ ] **Section 5 (Extension):** At least 3-4 extension points with templates
- [ ] **Section 6 (Dependencies):** Imports/exports clearly mapped
- [ ] **Cross-references:** Links to other about_xxx.md where relevant
- [ ] **Code accuracy:** Examples match current codebase (no outdated API calls)
- [ ] **Length:** 15+ KB (aim for 18-22 KB for detailed folders)
- [ ] **Tone:** Professional but readable, mix of bullet points + prose

---

## 📝 EXAMPLE FOLDER PROGRESSION

### How Folders Relate

```
about_src.md (ROOT - master doc)
    ├── about_agent_core.md (intelligent decision-making)
    │   ├── mentions about_backtest.md (testing agent_core)
    │   └── mentions about_ui.md (calls agent_core)
    │
    ├── about_data_engine.md (data fetching)
    │   ├── mentions about_backtest.md (uses CSV loader)
    │   └── mentions about_agent_core.md (provides market_state)
    │
    ├── about_backtest.md (testing framework)
    │   ├── uses about_agent_core.md (ReactOrchestrator)
    │   ├── uses about_data_engine.md (CSV loader)
    │   └── uses about_database.md (saves results)
    │
    ├── about_ui.md (dashboard/CLI)
    │   ├── uses about_agent_core.md (ReAct loop)
    │   ├── uses about_database.md (load/save)
    │   └── uses about_notification.md (Discord alerts)
    │
    ├── about_database.md (PostgreSQL)
    │   └── stores results from agent_core, backtest, ui
    │
    └── about_notification.md (Discord, Telegram)
        └── notifies from ui or backtest
```

---

## 🎓 BEST PRACTICES FOR ABOUT_XXX.MD

### Writing Style
- **Technical but accessible:** Assume reader knows Python but not necessarily your architecture
- **Example-driven:** Show, don't just tell
- **Narrative flow:** Tell a story of how folder fits into bigger picture
- **Avoid jargon:** Define terms first time used

### Code Examples
- **Copy-paste ready:** Import statements must be complete
- **Current codebase:** Examples reflect actual API (not wishes)
- **Error handling:** Show both happy path + error case
- **Runnable:** Could theoretically `python -c` them

### Section Sizing
- **Section 1:** 1-2 KB (crisp mission)
- **Section 2:** 2-3 KB (file inventory)
- **Section 3:** 3-4 KB (architectural deep dive)
- **Section 4:** 3-4 KB (5+ practical examples)
- **Section 5:** 3-4 KB (extension templates)
- **Section 6:** 2-3 KB (dependency maps)
- **Total:** 15-23 KB per file

### Maintenance
- **Version number:** Mark each about_xxx.md with version (e.g., v3.4)
- **Update frequency:** When major refactor or new feature in folder
- **Responsibility:** Whoever commits major changes should update about_xxx.md
- **Review:** Before merging PR with agent_core/ changes, verify about_agent_core.md is current

---

## 📚 REFERENCE: about_src.md Structure (Your Template)

Your existing `about_src.md` has these sections:
1. Overview & Goal (mission + why)
2. Project Structure (tree view)
3. Architecture Layers (dependency diagram)
4. Component Deep Dives (per folder)
5. ReAct Flow Walkthrough (execution flow)
6. Prompt Engineering Guide (how prompts work)
7. Risk Manager Validation Rules (TP/SL matrix)
8. LLM Provider Ecosystem (how providers work)
9. Dashboard Architecture (UI flow)
10. Database Schema & Migrations (DB structure)
11. Backtest Architecture (testing flow)
12. Event Loop & Session Management (trading hours)
13. Error Handling & Resilience (failure modes)
14. Configuration & Secrets (env vars)
15. How to Run (commands)
16. Extensibility (add providers, indicators, skills)
17. Risk Matrix (mitigation strategies)

**For about_xxx.md, simplify to 6 sections** but keep similar level of detail.

---

# ✅ SUMMARY: WHAT I'M RECOMMENDING

Create **skill.md** with these elements:

1. **Skill Meta** (name, purpose, outputs)
2. **Scope & Constraints** (what it does/doesn't)
3. **Universal 6-Section Template** (with real examples)
4. **Folder Priority List** (4 tiers)
5. **Quality Checklist** (before finalizing)
6. **Best Practices** (style, examples, maintenance)
7. **Reference to existing about_src.md** (maintain consistency)

This skill.md will be a **guide for creating/improving about_xxx.md across your project** — ensuring every folder gets documented consistently and thoroughly.

---

**Ready for me to create the actual skill.md file now?** 🚀