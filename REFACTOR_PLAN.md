# แผน Refactor โปรเจค CN240 "นักขุดทอง" ให้พร้อม Show Public บน GitHub

> จัดทำจากการ audit repo จริงเมื่อ 2026-06-10
> Repo: `athiphat67/CN240_DATA-SCIENCE-FOR-SIGNAL-PROCESSING_PROJECT` — **สถานะปัจจุบัน: PUBLIC อยู่แล้ว** (233 MB บน GitHub, 967 commits, 61 remote branches)

---

## ⛔ Phase 0 — Security ต้องทำ "วันนี้" ก่อนทุกอย่าง (~1–2 ชม.)

repo เป็น public อยู่แล้ว ดังนั้นของที่เคยหลุดเข้า git history ถือว่า**รั่วไปแล้ว** การลบไฟล์ทีหลังไม่ช่วย — ต้อง **revoke/rotate ที่ต้นทาง** เป็นอันดับแรก

### สิ่งที่ตรวจพบจริง (มีหลักฐาน commit)

| # | สิ่งที่หลุด | ตำแหน่ง | ความรุนแรง | การแก้ |
|---|---|---|---|---|
| 1 | **Supabase `service_role` JWT** (project ref `wrfatuhodumugnqktqub`, role = service_role = ข้าม RLS เข้า DB ได้เต็ม, exp ปี 2090) | commit `9e617f5` ไฟล์ `HowtoTrade.md` (ลบจาก HEAD แล้ว แต่อยู่ใน history) | 🔴 วิกฤต | Supabase Dashboard → Project Settings → API → **rotate JWT secret / revoke legacy keys** (จะทำให้ anon key เก่าตายด้วย — ต้องอัปเดต `.env` ทุกเครื่อง+ทุก deployment) แล้วตรวจ DB logs ว่ามีการเข้าถึงแปลก ๆ ไหม |
| 2 | **Discord webhook จริง** (`discord.com/api/webhooks/1501443662771523614/TUS4...`) | commit `9e617f5` เดียวกัน | 🟠 สูง (คนนอกยิงข้อความเข้า channel ได้) | Discord → Server Settings → Integrations → Webhooks → **ลบ webhook นี้ สร้างใหม่** → อัปเดต `.env` |
| 3 | **OpenRouter API key จริง** `sk-or-v1-55f99...` — **ยังอยู่ที่ HEAD ตอนนี้** | `Src/agent_core/llm/test_openRouter.py:6` (เข้ามาตั้งแต่ commit `e0d9bf6`) | 🔴 วิกฤต | openrouter.ai → Settings → Keys → **revoke** + เช็ค usage ว่าโดนแอบใช้ไหม → แก้ไฟล์ให้อ่านจาก `os.environ` แล้ว commit |
| 4 | คีย์ `AIza...` / `gsk_...` ใน README เก่า | หลาย commit | ✅ ไม่เป็นไร | ตรวจแล้วเป็น **placeholder ปลอม** (`AIzaSyA1b2c3d4...`, `gsk_abcdef1234...`) |
| 5 | pattern `hf_` / `AKIA` ใน history | — | ✅ false positive | ตรวจแล้วไม่มีคีย์จริง |

### ไฟล์ส่วนตัว (ยัง untracked — ยังไม่หลุด แต่เสี่ยง `git add .` พลาด)

- `Documentation/สำเนา ใบรับรองสัดส่วน Data Science ทีมนักขุดทอง*.docx/.pdf` (4 ไฟล์ — มีลายเซ็น/ข้อมูลนักศึกษา)
- `LineChat/[LINE]CN240 - ML PROJECT.txt` (export แชททีม 561 KB — ข้อมูลส่วนตัวล้วน ๆ)

**การแก้:** ย้ายออกนอกโฟลเดอร์ repo เลย (เช่น `~/TSE35/YEAR 2/TERM2/CN240-private/`) + เพิ่มกฎใน `.gitignore` กันเหนียว:

```gitignore
LineChat/
Documentation/สำเนา*
Documentation/ใบรับรอง*
```

### ขั้นตอน Phase 0 เรียงตามลำดับ

1. Rotate Supabase keys (ข้อ 1) — ด่วนสุดเพราะเป็น service_role
2. ลบ + สร้าง Discord webhook ใหม่ (ข้อ 2)
3. Revoke OpenRouter key (ข้อ 3) แล้วแก้ `test_openRouter.py` → `os.environ["OPENROUTER_API_KEY"]` ห้าม hardcode
4. ย้ายไฟล์ส่วนตัว 2 กลุ่มข้างบนออกนอก repo
5. ยืนยันปิดท้ายด้วย gitleaks ทั้ง history:
   ```bash
   brew install gitleaks
   cd "/Users/big/TSE35/YEAR 2/TERM2/CN240"
   gitleaks git --redact -v .
   ```
6. **ตัดสินใจเรื่อง history rewrite** — คำแนะนำ: **rotate อย่างเดียว ไม่ rewrite** เพราะ
   - คีย์ที่ revoke แล้ว = ขยะ ไม่มีค่าให้ขโมย
   - rewrite จะพัง PR ทั้ง 331 อัน + ทุกคนในทีม 10 คนต้อง re-clone
   - GitHub cache commit เก่าไว้ — rewrite อย่างเดียวลบไม่หมด ต้องเปิด ticket ขอ GitHub support purge อีกชั้น
   - ถ้าจะ rewrite จริง ๆ ให้ทำตอน Phase 6 ทีเดียวพร้อมลด size

---

## Phase 1 — Repo Hygiene (~ครึ่งวัน)

### 1.1 แก้ชื่อ `.gitIgnore` → `.gitignore` (บั๊กเงียบที่ทำให้ขยะหลุดเข้า repo)

ไฟล์ tracked อยู่ในชื่อ `.gitIgnore` (I ใหญ่) — บน macOS (case-insensitive) ใช้งานได้ แต่บนเครื่อง Linux/CI/Codespaces **git จะมองไม่เห็น** → เพื่อนร่วมทีม commit ขยะเข้ามาได้

```bash
git mv .gitIgnore .gitignore.tmp && git mv .gitignore.tmp .gitignore
```

### 1.2 เขียน `.gitignore` ใหม่ — ลบกฎที่ขัดแย้งกันเอง

ปัญหาในไฟล์ปัจจุบัน:
- `*.json` ignore ทั้งโลก แต่ model config (`Src_V4/models/lambdamart_v11.json`, `roles.json`, `skills.json`) ต้อง tracked → เปลี่ยนเป็น ignore เฉพาะ path ที่เป็น runtime output
- `*.ipynb` ignore ทั้งหมด แต่ `Documentation/*.ipynb` tracked อยู่ → ลบกฎนี้
- `CLAUDE.md` อยู่ใน ignore แต่ไฟล์ tracked อยู่ → ลบกฎ (เก็บ CLAUDE.md ไว้ เป็น docs ที่ดี)
- เพิ่ม: `LineChat/`, `Documentation/สำเนา*`, `*.pkl` ใหม่ (ที่ไม่ใช่ models/ ทางการ), `venv/` ครอบทุกระดับ (มี `Src_V4/venv/` 510 MB โผล่บนดิสก์)

### 1.3 ลบไฟล์ขยะออกจาก HEAD

| ไฟล์ | เหตุผล |
|---|---|
| `Documentation/Papers/~$ase1_Discovery_Report.docx` | Word lock file (ขยะชั่วคราวของ MS Word) |
| `Src/backup_gold_bot.sql`, `Src/database/backup_gold_bot.sql`, `Src_V2/database/backup_gold_bot.sql` | ไฟล์ว่าง 0 byte ทั้ง 3 ไฟล์ |
| `Src_V4/fallback/pending_inserts.jsonl` | runtime artifact ไม่ใช่ source |
| `package.json`, `package-lock.json`, `node_modules/` (ที่ root) | stray dependency (@vercel/analytics) — ของจริงอยู่ใน `Src/frontend/` |
| `Src/agent_core/model_ai/model_buy.zip`, `model_sell.zip` | ซ้ำกับ `.pkl` ข้าง ๆ |

```bash
git rm --cached "Documentation/Papers/~\$ase1_Discovery_Report.docx" \
  Src/backup_gold_bot.sql Src/database/backup_gold_bot.sql Src_V2/database/backup_gold_bot.sql \
  Src_V4/fallback/pending_inserts.jsonl package.json package-lock.json \
  Src/agent_core/model_ai/model_buy.zip Src/agent_core/model_ai/model_sell.zip
```

### 1.4 Dedupe ไฟล์ซ้ำใน HEAD

- `master_merged_data.csv` ซ้ำ 2 ที่ (87 MB ที่ `Src/backtest/data/` + 79 MB ที่ `Src/backtest/data/merge_data/`) → เก็บที่เดียว (จัดการต่อใน Phase 2)
- `model_sell.pkl` (4.3 MB) ซ้ำ **4 ที่**: `Src/agent_core/model_ai/`, `Src/outputs/latest_model/models/`, `Src_V2/models/`, `Src_V2/models/v1_rich/` → เก็บเฉพาะที่โค้ด production โหลดจริง (`Src/agent_core/model_ai/`) ที่เหลือลบ/ย้ายไป Release

> ⚠️ หมายเหตุ: `git rm` จาก HEAD ทำให้ repo **สะอาดขึ้น** แต่**ไม่ลดขนาด clone** (blob ยังอยู่ใน history) — การลดขนาดจริงคือ Phase 6 (optional)

### 1.5 เก็บกวาดดิสก์ local (ไม่เกี่ยวกับ git แต่กิน 2 GB+)

- `venv/` ที่ root 1.1 GB, `Src_V4/venv/` 510 MB → ลบ แล้วสร้างใหม่เมื่อใช้
- `Src/frontend/node_modules/` 200 MB → `npm ci` เมื่อใช้
- `Src/backtest/data/` ส่วน untracked ~300 MB → คัดทิ้ง/อัด zip เก็บนอก repo

---

## Phase 2 — Data Strategy: เอาไฟล์ใหญ่ออกจาก git (~ครึ่งวัน)

ไฟล์ CSV ที่ tracked ใหญ่สุด (รวม ~250 MB ใน checkout):

| ไฟล์ | ขนาด | ปลายทาง |
|---|---|---|
| `Src/backtest/data/master_merged_data.csv` | 87 MB | → GitHub Release |
| `Src/backtest/data/merge_data/master_merged_data.csv` | 79 MB | → ลบ (ซ้ำ) |
| `Src/backtest/data/merge_data/merged_gold_5min_TH_TIME.csv` | 57 MB | → Release |
| `Src/backtest/data/label/gold_data_labeled_v6.csv` | 37 MB | → Release |
| `Src/backtest/data/label/sniper_data.csv` | 35 MB | → Release |
| `merged_gold_15min_TH_TIME.csv` + `MarketState_data/*.csv` + `premium_hsh/*.csv` | 5–18 MB ต่อไฟล์ | → Release |
| `Src/backtest/data/HSH965_BuySell_Clean/raw_data/GetHistoryGoldPriceList-1..49` | เล็กแต่ 49 ไฟล์ | → zip เดียว → Release |
| `Src/backtest/data/latest_data/Final_Merged_HSH_M5.csv` | 2 MB | ✅ เก็บใน repo (เป็น production input ของ backtest) |
| `Data/Raw/*.csv` (XAUUSD, USDTHB, VIX) | รวม ~1 MB | ✅ เก็บได้ + ใส่ README ระบุแหล่งที่มา |

### วิธีทำ

```bash
# 1) สร้าง Release เก็บ dataset (ไม่บวมใน clone, ฟรี)
gh release create dataset-v1 --title "Backtest Dataset v1" \
  --notes "Full HSH965/XAUUSD merged datasets for backtesting" \
  master_merged_data.csv.gz merged_gold_5min.csv.gz ...

# 2) เก็บ sample 1,000 แถวแรกไว้ใน repo แทน เพื่อให้คนอ่านโค้ดเห็นหน้าตา data
head -1001 master_merged_data.csv > Src/backtest/data/samples/master_merged_sample.csv

# 3) เขียน scripts/download_data.sh ดึงจาก Release มาวางตำแหน่งเดิม
```

### ⚠️ ข้อควรระวังเรื่องลิขสิทธิ์ data
- tick data HSH965/Intergold มาจากการ intercept WebSocket — การ redistribute แบบ public อาจขัด ToS ของผู้ให้บริการ → ใส่ disclaimer "for educational/research purposes only" ใน Release notes และพิจารณาแจกเฉพาะ derived/aggregated data (M5/M10 candle) ไม่แจก raw tick
- ข้อมูลจาก TwelveData/Investing มีเงื่อนไข redistribution เช่นกัน

---

## Phase 3 — โครงสร้างโปรเจค (~ครึ่งวัน–1 วัน)

ปัจจุบันมี source 3 เวอร์ชันวางคู่กัน: `Src/` (LLM agent — 280 ไฟล์), `Src_V2/` (75 ไฟล์ — **legacy ไม่ใช้แล้ว** ตาม README), `Src_V4/` (67 ไฟล์ — ML หลัก) ซึ่งทำให้คนนอกที่เข้ามาดู repo งงทันที

### Tier A — แนะนำ (ปลอดภัย ไม่ break import)

1. **Archive `Src_V2/`**: สร้าง branch เก็บถาวรแล้วลบออกจาก main
   ```bash
   git branch archive/src-v2 main      # history ยังอยู่ครบใน branch นี้
   git rm -r Src_V2/
   ```
   ใส่หมายเหตุใน README: "V2 (legacy ML pipeline) อยู่ที่ branch `archive/src-v2`"
2. **ย้าย dev notes ออกจาก source tree**: `Src_V4/Src_V4_purichfixed/*.md` (5 ไฟล์ fix-plan) → `docs/dev-notes/` แล้วลบโฟลเดอร์ชื่อแปลกนี้ทิ้ง
3. **รวม test ที่กระจัดกระจาย**:
   - `Src_V4/test_sell_scenarios_dryrun.py`, `Src_V4/test_tp_manager.py` (อยู่ root ของ V4) → `Src_V4/tests/`
   - `Src/agent_core/llm/test_client.py`, `test_gemini.py`, `test_groq.py`, `test_openRouter.py`, `Src/agent_core/core/test_tool.py` → `Src/tests/` (มีโฟลเดอร์ tests/ อยู่แล้ว) — ระวังอัปเดต import path
4. **จัดที่ให้ของจร**:
   - `news_api_backtest/` (3 ไฟล์) → `Src/backtest/news_api/` หรือ archive branch
   - `Data/Raw/` → `data/raw/` + `data/README.md` บอกแหล่งที่มาแต่ละไฟล์
   - `public/logo.png` → `Src/frontend/public/` (เช็คก่อนว่า Vercel config ชี้ที่ไหน)
5. **ลบ `Src_V4/result_week2/`, `Src_V4/logs/`, `Src_V4/hsh_recent.csv`, `ig_recent.csv`** ออกจากดิสก์ (เป็น runtime output — ignored อยู่แล้วบางส่วน)

### Tier B — เต็มรูปแบบ (optional ถ้ามีเวลา)

Rename เพื่อให้สื่อความหมายต่อคนนอก:

```
CN240/
├── ml-signal/        ← เดิม Src_V4 (ระบบหลัก XGBoost LambdaMART)
├── llm-agent/        ← เดิม Src (ReAct LLM agent + Gradio + FastAPI + frontend)
├── data/             ← เดิม Data
├── docs/             ← Documentation + about_*.md ที่ scatter อยู่ + dev-notes
├── scripts/          ← download_data.sh, setup helpers
└── README.md
```

ต้องตามแก้: import ภายใน, `Dockerfile`, path ใน `CLAUDE.md`, CI, เอกสารทุกจุด → ทำเป็น PR เดียวจบ + รัน `pytest` ทั้งสองระบบยืนยัน ถ้าไม่มั่นใจให้หยุดที่ Tier A ก็เพียงพอสำหรับ public showcase แล้ว

---

## Phase 4 — Docs & การนำเสนอ (~1 วัน) — ส่วนที่ "ขาย" ที่สุด

### 4.1 ปรับ README.md (โครงปัจจุบันดีแล้ว เพิ่มของที่ recruiter/คนนอกอยากเห็น)

- [ ] **Screenshot/GIF** ของ Gradio dashboard + React frontend + ตัวอย่าง Discord notification (ใส่ไว้ที่ `docs/images/`)
- [ ] **Architecture diagram** เป็น Mermaid ใน README (มี data flow เขียนไว้แล้ว แปลงเป็นภาพ)
- [ ] **Results section** — ตัวเลขจริงจาก backtest (มี `backtest/metrics/calculator.py` + deploy_gate 7-check อยู่แล้ว): win rate, PnL, max drawdown, จำนวน trade ต่อระบบ ML vs LLM
- [ ] **ภาษา**: ทำ README หลักเป็น **อังกฤษ** + ลิงก์ `README.th.md` ฉบับไทย (กลุ่มเป้าหมาย public กว้างกว่า)
- [ ] **เอา Student ID ออก** — เก็บชื่อ + ลิงก์ GitHub profile แทน (PII ไม่ควรอยู่ใน repo public; ใน history ยังมีอยู่แต่ความเสี่ยงต่ำ ไม่คุ้ม rewrite)
- [ ] Badge CI (หลังทำ Phase 5) + Python version + license

### 4.2 LICENSE

ตอนนี้ badge เขียน "Academic Use Only" แต่**ไม่มีไฟล์ LICENSE จริง** = สถานะทางกฎหมายคือ all-rights-reserved
- ตัวเลือก: **MIT** (โชว์ผลงานง่ายสุด) หรือคง all-rights-reserved พร้อมไฟล์ `LICENSE` เขียนชัด
- **ต้องได้ความยินยอมจากทีมทั้ง 10 คน** (เป็น copyright ร่วม) + เช็คนโยบายรายวิชา/อาจารย์ก่อน
- data ใน Release ใส่ license แยก (CC BY-NC หรือ "educational use only")

### 4.3 จัดบ้านเอกสาร

- `about_*.md` กระจายอยู่ทั่ว (about_src, about_aiagent, about_backtest, about_database, about_rationale, pipeline_flow/ ฯลฯ) — เนื้อหาดีมาก → ทำ `docs/INDEX.md` ลิงก์รวม หรือย้ายเข้า `docs/` แล้วใน source เหลือ README สั้น ๆ ชี้กลับ
- `Documentation/Papers/` เก็บ PDF เป็นหลัก (docx เก็บไว้ได้แต่ลบ lock file ตาม Phase 1)
- Presentation PDF 3 ไฟล์ (55 MB) — อยู่ใน history แล้ว เก็บที่เดิมได้ (ลบไปก็ไม่ลด size) แต่ไฟล์ presentation **ใหม่** ในอนาคตให้แนบกับ Release แทน

### 4.4 หน้า GitHub repo

- [ ] ใส่ **Description**: "🥇 ML + LLM gold trading signal agent for Thai gold (HSH965) — XGBoost LambdaMART + ReAct LLM agent. CN240 course project, Thammasat University"
- [ ] ใส่ **Topics**: `machine-learning`, `trading-bot`, `xgboost`, `llm-agent`, `gold-trading`, `fastapi`, `react`, `data-science`, `thailand`
- [ ] Social preview image (Settings → General → Social preview)
- [ ] พิจารณา **rename repo** → เช่น `nakkhutthong-gold-signal-agent` (จำง่าย/portfolio-friendly — GitHub ตั้ง redirect จากชื่อเก่าให้อัตโนมัติ) — optional

---

## Phase 5 — Quality Gates & ปิดงานค้าง (~ครึ่งวัน)

### 5.1 GitHub Actions CI (ไฟล์เดียวพอ)

`.github/workflows/ci.yml`: รัน 3 อย่างต่อ push/PR
1. `ruff check` (lint)
2. `cd Src && pytest -m unit` + `cd Src_V4 && pytest` (เฉพาะ test ที่ไม่ใช้ API key จริง — marker มีอยู่แล้วใน pyproject)
3. `gitleaks/gitleaks-action` กัน secret หลุดซ้ำ

### 5.2 Pre-commit hooks (กันเหตุซ้ำที่ต้นทาง)

`.pre-commit-config.yaml`: `gitleaks`, `check-added-large-files` (max 2 MB), `end-of-file-fixer`, `ruff`

### 5.3 เก็บกวาด GitHub

- ปิด/merge **PR #275** (เปิดค้างตั้งแต่ 2026-04-20)
- ลบ remote branch ที่ merge แล้ว (มี 61 branches — ชื่อรายคน เช่น `AI-Agent-purichdev`, `BACKTEST-theepopdev`): `git branch -r --merged origin/main` ดูรายการ → ตกลงกับทีมก่อนลบ → เหลือ `main`, `main_deploy`, `archive/*`
- สร้าง **tag `v1.0.0` + Release** ผูก dataset (Phase 2) และทำให้หน้า repo มี "Releases" ดูจบงานเป็นเรื่องเป็นราว

---

## Phase 6 — (Optional) ลดขนาด history ด้วย git filter-repo

ทำเฉพาะถ้าอยากให้ clone เบา (310 MB → ประมาณ 50–80 MB) **และ** ยอมรับผลข้างเคียง:

- ลบ blob CSV/PDF ใหญ่ + `HowtoTrade.md` (ที่มี webhook/JWT เก่า) ออกจากทุก commit ด้วย `git filter-repo --strip-blobs-bigger-than 5M --invert-paths --path HowtoTrade.md`
- **ผลข้างเคียง**: commit hash เปลี่ยนหมด → PR 331 อันชี้ commit ตาย, ทีมทุกคนต้อง re-clone, ต้อง force-push, และต้องเปิด ticket ให้ GitHub support purge cached commits ถึงจะหายจริง
- **คำแนะนำ**: ถ้า rotate คีย์ครบตาม Phase 0 แล้ว คุณค่าของ Phase 6 เหลือแค่ "clone เร็วขึ้น" — ทำหลังส่งเกรด/จบ collaboration แล้วเท่านั้น หรือไม่ทำเลยก็ได้

---

## ลำดับการลงมือ + เวลารวม (~3–4 วันทำงาน)

| ลำดับ | งาน | เวลา | Blocker |
|---|---|---|---|
| 1 | Phase 0 Security (rotate 3 คีย์ + ย้ายไฟล์ส่วนตัว + gitleaks) | 1–2 ชม. | ต้องมีสิทธิ์เข้า Supabase/Discord/OpenRouter dashboard |
| 2 | Phase 1 Hygiene (.gitignore + ลบขยะ) | ครึ่งวัน | — |
| 3 | Phase 2 Data → Release | ครึ่งวัน | ตกลงเรื่อง ToS data ก่อนแจก raw tick |
| 4 | Phase 3 Tier A โครงสร้าง | ครึ่ง–1 วัน | บอกทีมก่อน archive Src_V2 |
| 5 | Phase 4 README/LICENSE/หน้า repo | 1 วัน | LICENSE ต้องให้ทีม 10 คนเห็นชอบ |
| 6 | Phase 5 CI + branch cleanup + v1.0.0 | ครึ่งวัน | ตกลงทีมก่อนลบ branch |
| 7 | Phase 6 history rewrite | — | ทำหลังจบเทอม หรือข้ามไป |

## Definition of Done — เช็คลิสต์ "พร้อมโชว์"

- [ ] คีย์ทั้ง 3 ถูก revoke และระบบยังรันได้ด้วยคีย์ใหม่
- [ ] `gitleaks git .` ผ่านโดยไม่มี finding ที่เป็นคีย์จริง
- [ ] ไม่มีไฟล์ส่วนตัว (ใบรับรอง/LineChat) อยู่ในโฟลเดอร์ repo
- [ ] `.gitignore` ชื่อถูกต้อง ตัวพิมพ์เล็ก และไม่มีกฎขัดแย้ง
- [ ] root repo เหลือโฟลเดอร์ที่อธิบายได้ทุกอัน ไม่มี `Src_V2`, ไม่มี stray `package.json`
- [ ] clone ใหม่ + ทำตาม README quickstart แล้วรันได้จริง (ทดสอบบนเครื่องเปล่า/เพื่อนในทีม)
- [ ] README มี screenshot + results + architecture + team (ไม่มี student ID)
- [ ] มี LICENSE, repo description, topics, CI badge เขียว, Release v1.0.0
- [ ] PR ค้างปิดหมด, เหลือ branch หลัก ≤ 5 อัน
