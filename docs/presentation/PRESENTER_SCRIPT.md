# Europe SFA Data Load Copilot — Presenter Script & Demo Guide

**Audience:** Leadership  
**Total time:** ~15 minutes (7–8 min talk · 2–3 min live demo · 5 min Q&A)  
**Deck:** `docs/presentation/final_project_presentation.html` (12 slides)  
**Demo file:** `test_data/retail_promotion/RO_Promotion_Faulty_Validation_Test.csv`  
**Demo path:** Data Import Tool → Retail Promotion → Prepare & Validate File

---

## Part 1: Full Presenter Script (~7–8 minutes)

Read naturally — these are talking points, not a word-for-word teleprompter. Pause briefly after each slide transition.

---

### Slide 1 — Title / Hook (~45 sec)

**Europe SFA Data Load Copilot**

> Good [morning/afternoon], everyone. Thank you for the time.
>
> I want to start with a question most of us have lived through: *How many hours have we lost fixing a CSV that Salesforce still rejects at upload?*
>
> That gap — between a business spreadsheet and a file Workbench or the Data Import Tool will accept — is exactly what the **Europe SFA Data Load Copilot** addresses.
>
> It's a Streamlit application that prepares and validates data *before* upload: faster, safer, and with fewer errors. This is my final project, built against our local EUSFA Salesforce metadata.

*Leadership should notice:* Clear problem framing, not a feature tour yet.

---

### Slide 2 — The Problem (~60 sec)

**Manual data prep slows every SFA load**

> Every load cycle, teams juggle Excel, template PDFs, and tribal knowledge. The same checks get repeated by hand.
>
> Picklist labels, date formats, header names — none of that is validated until someone tries to upload. And when Workbench or DIT rejects the file, the team goes back to square one.
>
> The pain point isn't Salesforce itself. It's the **preparation gap**: turning a market spreadsheet into something the platform will actually accept, without finding out at the last minute.

*Leadership should notice:* This is an operational workflow problem, not an IT tooling complaint.

---

### Slide 3 — Why It Matters (~50 sec)

**Bad data has real deployment cost**

> When loads fail, the cost is real. Invalid picklists, wrong date formats, malformed rows — Salesforce rejects the whole file.
>
> Each failure sends teams back to Excel and delays SFA deployment timelines across markets. Loaders end up guessing API values and hoping the upload succeeds.
>
> And as Europe SFA expands templates and markets, **manual review simply doesn't scale**. This is operational risk and wasted capacity — not just an inconvenience for admins.

*Leadership should notice:* Business impact — delays, rework, scale risk — tied to data quality.

---

### Slide 4 — My Approach (~60 sec)

**A guided path from upload to corrected CSV**

> The Copilot is a **preparation layer**, not a replacement for Salesforce upload tools. Workbench and DIT remain the upload path.
>
> Walk through the flow on screen: upload a file → the app detects the template and upload method → validates against EUSFA metadata → proposes fixes → the user approves → downloads a ready CSV.
>
> Importantly, it supports **both Workbench and the Data Import Tool** — API field names and YYYY-MM-DD for Workbench; friendly headers and DD/MM/YYYY for DIT — all validated against the same metadata source.

*Leadership should notice:* Complements existing tools; doesn't bypass Salesforce governance.

---

### Slide 5 — Key Decisions (~60 sec)

**Design choices that keep the Copilot trustworthy**

> Four decisions shaped the architecture.
>
> First, **data preparation, not Salesforce replacement** — we prepare CSVs before upload; we don't write to Salesforce.
>
> Second, **EUSFA metadata is the single source of truth** — picklists, field types, required fields come from our local Salesforce DX clone, read-only.
>
> Third, **users stay in control** — safe fixes are proposed for approval; risky changes like picklists and duplicates require explicit action. The Copilot **never auto-guesses** picklist values.
>
> Fourth, **action-based fixes** — validation results become clear, approvable corrections through **Fix Issues in Copilot**, so loaders can edit inline without leaving the workflow.

*Leadership should notice:* Trust and control are deliberate design choices, not afterthoughts.

---

### Slide 6 — What the Copilot Does (~60 sec)

**Capabilities overview**

> Quick tour — I won't read every card.
>
> Header and template checks map uploaded columns to EUSFA config. Date formatting catches ambiguous and invalid dates per upload method. Picklist validation shows allowed values but never invents replacements.
>
> Whitespace cleanup, leading-zero protection for EANs and SKUs, duplicate detection — all the things that silently break in Excel.
>
> The app surfaces **blocking vs. review items** with a clear readiness status, and offers two downloads: a **Tool-Ready CSV** for upload and a **Review CSV** with audit context. Over 140 automated tests cover the core validators.

*Leadership should notice:* Breadth of validation; dual download model; test coverage for credibility.

---

### Slide 7 — Demo Flow (~45 sec)

**Three steps — faulty file to upload-ready CSV**

> Before we go live, here's the story we'll walk through in about two minutes.
>
> Step one: upload a **Retail Promotion** test file with intentional errors — dates, picklists, whitespace, formatting.
>
> Step two: the Copilot identifies issues. We'll use **Fix Issues in Copilot** for manual corrections and approve safe cleanup changes.
>
> Step three: when readiness passes, download the **Tool-Ready CSV** for DIT upload — or the **Review CSV** for audit.
>
> The test file is `RO_Promotion_Faulty_Validation_Test.csv` — a fault-injection file designed to show the full workflow.

*Leadership should notice:* Demo is scripted and repeatable; not a happy-path-only demo.

---

### Slide 8 — Impact (~50 sec)

**Value delivered to data loading teams**

> Let me lead with outcomes, not features.
>
> The Copilot **reduces manual review time** — validation runs against metadata before anyone touches Workbench or DIT.
>
> It **prevents common upload failures** — dates, picklists, headers, formatting — caught early, not at upload.
>
> It **improves data quality** with user-approved corrections and download gating: you can't get a tool-ready file while blockers remain.
>
> It **makes loading easier for non-technical users** — guided workflow, plain-language fixes.
>
> And it creates a **reusable foundation** for future markets and templates across Europe SFA.

*Leadership should notice:* Time saved, failures prevented, accessibility for loaders, extensibility.

---

### Slide 9 — Final Outcome (~50 sec)

**A working Copilot — ready for pilot use**

> What was built: a working Streamlit app connected to local EUSFA metadata, full prepare → validate → approve → download workflow, both Workbench and DIT paths.
>
> It runs on Python 3.11+ with a local EUSFA SFDX clone. There's a metadata refresh panel — fetch, compare, pull updates — and session metadata version lock with change warnings.
>
> Critical point for security and governance: the Copilot **reads metadata from the local repo only**. It never modifies Salesforce repository files and never writes data to Salesforce. It's suitable for pilot use with ops teams now.

*Leadership should notice:* Deliverable is real and pilot-ready; clear security boundary.

---

### Slide 10 — Next Steps (~40 sec)

**Where the Copilot goes next**

> This isn't a dead end — there's a clear roadmap.
>
> **Expand business rules** — template-specific validation and dependency checks beyond current stubs.
>
> **Improve metadata refresh** — streamline fetch/pull and CI-ready metadata sync for teams.
>
> **Batch upload planning** — multi-file preparation and load sequencing for large deployments.
>
> **UI refinement** — continue improving layout and Fix Issues UX based on loader feedback.
>
> These are natural extensions of the foundation we've built.

*Leadership should notice:* Forward-looking roadmap; investment already de-risked.

---

### Slide 11 — Live Demo Transition (~15 sec)

**Let's see it in action**

> **Now let's test the Copilot.**
>
> *[Exit fullscreen if needed — Alt+F11 — and switch to the Streamlit app tab. The app should already be running at localhost:8501 or your hosted URL.]*
>
> I'll walk through the Retail Promotion validation test we just described.

*Then proceed to Part 2 below. After the demo, advance to Slide 12 for Q&A.*

---

## Part 2: Live Demo Script (2–3 minutes)

**Setup:** App running · test CSV path ready · browser tab pre-opened  
**Path:** Data Import Tool → Retail Promotion → Prepare & Validate File

| Step | Action | Say (short) | Leadership should notice |
|------|--------|-------------|--------------------------|
| **1** | Switch to Streamlit app (`localhost:8501` or hosted URL) | "Here's the Copilot — same workflow our loaders would use." | Clean, guided UI with labeled steps |
| **2** | **Step 1:** Select **Data Import Tool** from "Select Target Tool" | "We're using the Data Import Tool path — friendly headers, DD/MM/YYYY dates." | Tool-specific validation rules |
| **3** | **Step 2:** Select **Retail Promotion** from "Select Business Template" | "Retail Promotion for Romania — one of our active SFA templates." | Template tied to EUSFA metadata |
| **4** | **Step 3:** Click **🛠️ Prepare & Validate File (Recommended)** | "Full prepare and validate — not just formatting." | Task selection before upload |
| **5** | **Step 4:** Upload `RO_Promotion_Faulty_Validation_Test.csv` | "This is a fault-injection test file — intentional errors built in." | File overview + 10-row preview appear |
| **6** | **Header Review:** Review template match status → click **Continue to Data Validation** (or **Approve All High-Confidence Header Changes** if prompted, then Continue) | "Headers are checked against the DIT template first. Original file is never modified." | "Needs User Action" or match % banner; user approves before row validation |
| **7** | **Data Cleanup:** In the 🧹 **Data Cleanup** card → click **Apply All Safe Changes** | "Safe fixes — whitespace trim, formatting — applied with one click." | Category breakdown (whitespace, punctuation, etc.); success message |
| **8** | **Fix Issues in Copilot:** Scroll to **Fix Issues in Copilot** → expand **Row 5 — *Start Date(dd/mm/yyyy)** (Invalid Calendar Date, `31/02/2026`) → enter a valid date e.g. `06/07/2026` → click **Save Correction** | "Invalid dates can't be auto-guessed — the loader fixes them inline with metadata-aware validation." | Issue count decreases; expander shows row, field, problem; correction saved to working copy |
| **9** | **Picklist Review:** Scroll to **Picklist Review** → on **\*Market** or **\*Promotion Type** card → click **Review N Values** → in inline editor, select a valid allowed value (e.g. change `NOT_A_MARKET` → `RO`, or `INVALID_TYPE` → `Leaflet`) → click **Apply Selected Picklist Replacements** | "Picklists show allowed values from metadata — we choose, the Copilot never guesses." | Allowed values expander; valid options only; no invented replacements |
| **10** | Scroll to **Upload Readiness** and download section | "Readiness is explicit — we're not ready for tool upload yet." | **Upload Readiness: NOT READY** status with explanation |
| **11** | Click **Download Review CSV** | "Even when not tool-ready, teams get an audit file with approved changes and issue notes." | Review CSV always available; Tool-Ready button disabled or shows gating message |
| **12** *(optional, ~30 sec)* | Fix one more issue in **Fix Issues in Copilot** (e.g. Row 6 — Text Date) or approve another picklist trim | "Each fix improves readiness — watch the status update." | Issue count drops; readiness explanation shortens |
| **13** | Point to **Download Tool-Ready CSV** (disabled if blockers remain) | "Tool-Ready CSV unlocks only when all blocking issues are resolved — that's the file that goes straight to DIT." | Gating message: "Tool-ready download will become available after blocking issues are resolved." |
| **Close** | Return to Slide 12 (Q&A) | "That's the full loop — upload, validate, fix with approval, download when ready." | End-to-end workflow in under three minutes |

### Demo highlights to call out (if time allows)

- **Metadata source panel** at top — shows connected EUSFA repo (read-only).
- **Original file never modified** — all changes on a working copy.
- **Fix Issues vs. Picklist Review** — dates/duplicates in Fix Issues; picklists in Picklist Review (by design).
- **Review CSV vs. Tool-Ready CSV** — audit trail vs. upload file.

---

## Part 3: Q&A Prep (~5 minutes)

*Speaker backup only — not on slides.*

### Q1: "Why not just use Excel? Our teams already know Excel."

- Excel is great for editing; it is **not metadata-aware**. It strips leading zeros, misreads dates, and has no picklist validation.
- The Copilot **doesn't replace Excel** — it sits between Excel and Salesforce, catching errors Excel cannot see.
- Loaders still work in familiar CSV format; the app adds **guided validation and approval**, not a new data entry tool.
- Review CSV gives an audit trail Excel macros cannot replicate against live Salesforce metadata.

### Q2: "How is this different from Salesforce's native Data Import Tool or Workbench?"

- Workbench and DIT **upload** data; they reject bad files at upload time — after hours of prep.
- The Copilot **prepares and validates before upload** — same metadata rules, but errors surface early with plain-language fixes.
- It supports **both upload paths** with method-specific date formats and header conventions.
- It is complementary: download Tool-Ready CSV → upload via DIT or Workbench as today.

### Q3: "What's the deployment timeline? When can teams use this?"

- The app is **working today** for local/pilot use (`streamlit run app.py` + local EUSFA SFDX clone).
- Phase 1 demo deployment docs exist (`docs/deployment/PHASE1_DEMO_DEPLOYMENT.md`) for hosted pilot.
- Production rollout depends on hosting decision (internal Streamlit server, container, etc.) and ops onboarding — **weeks, not months**, for a controlled pilot.
- 140+ automated tests reduce regression risk during rollout.

### Q4: "What about security? Does this touch production Salesforce?"

- **No writes to Salesforce** — read-only access to local EUSFA metadata repo (`EUSFA_SFDX_REPO_PATH`).
- User CSVs are processed **in-session**; no data persisted to external services in the default local setup.
- Metadata refresh (fetch/pull) is **user-initiated** and targets the local clone, not production orgs directly.
- SSO can be enabled via Streamlit auth when hosted (`is_sso_required()` in app config).
- Suitable for review by InfoSec as a **pre-upload preparation utility**, not a data integration platform.

### Q5: "Can this work for other markets and templates beyond Retail Promotion?"

- **Yes — by design.** Template configs and validators are metadata-driven from EUSFA.
- Workbench and DIT paths already support multiple templates (Customers, Products, Routing, etc.).
- Retail Promotion is the demo because the fault-injection test file is comprehensive and Romania-specific.
- Adding a new template is primarily **metadata + template config**, not a rebuild — the roadmap includes expanding business rules per template.

### Q6: "Who maintains this after the project? What's the ongoing cost?"

- Built in **Python / Streamlit** — standard stack, no proprietary runtime.
- Validators and template configs are **modular**; metadata sync follows existing SFDX workflows teams already use.
- Maintenance = metadata refresh when EUSFA org changes + adding template rules as new markets onboard.
- Automated test suite (140+ tests) catches regressions when metadata or templates change.
- Low hosting footprint for Streamlit; no Salesforce license consumption beyond existing DX clone.

---

## Part 4: Presenter Tips

### Deck controls

| Action | How |
|--------|-----|
| Fullscreen | **F11** (recommended for projector) |
| Next / previous slide | **→** / **←**, Space, Page Down/Up |
| Presenter notes | **N** or click **Notes (N)** — shows `data-notes` for current slide |
| Jump to slide | Click dots in nav bar, or **Home** / **End** |
| Open deck | Double-click `final_project_presentation.html` or `start docs\presentation\final_project_presentation.html` |

### Pre-demo checklist (complete before Slide 11)

- [ ] Streamlit app running: `cd C:\Users\cwangz162\Europe-SFA-Data-Load-Copilot` → `.\venv\Scripts\Activate.ps1` → `streamlit run app.py`
- [ ] Browser tab open to `http://localhost:8501` (or hosted URL)
- [ ] Metadata connected — green status in **Metadata Source** panel; no startup validation error
- [ ] Test file ready: `test_data\retail_promotion\RO_Promotion_Faulty_Validation_Test.csv`
- [ ] Deck open in separate browser window/tab; Slide 11 ready
- [ ] Close unrelated tabs; disable notifications
- [ ] Optional: run through demo once the morning of the presentation

### Backup if the demo fails

If the app won't start, metadata is disconnected, or upload errors:

1. **Stay on Slide 7 (Demo Flow)** or Slide 11 and ** narrate the workflow** using the three-step cards on screen.
2. Describe what leadership **would** see:
   - Upload faulty CSV → template match banner → Header Review → Data Cleanup with "Apply All Safe Changes"
   - Fix Issues in Copilot: Row 5 invalid date `31/02/2026` corrected inline
   - Picklist Review: `NOT_A_MARKET` flagged; user selects `RO` from allowed values
   - Upload Readiness: **NOT READY** until blockers cleared → Review CSV available → Tool-Ready CSV gated
3. Reference the test file intentionally contains **26 rows of fault injections** (dates, picklists, whitespace, scientific notation, duplicates, blanks).
4. Offer to share a **screen recording** or schedule a follow-up walkthrough.
5. Pivot to Slide 8 (Impact) and Slide 9 (Final Outcome) — the deliverable exists regardless of live demo.

### Timing guardrails

| Segment | Target | If running long… |
|---------|--------|-------------------|
| Slides 1–10 | 7–8 min | Shorten Slide 6 (capabilities) and Slide 10 (next steps) |
| Live demo | 2–3 min | Skip optional Step 12; show NOT READY + Review CSV only |
| Q&A | 5 min | Prioritize security and deployment questions |

### Professional delivery notes

- Stand slightly to the side of the screen; face the audience, not the monitor.
- On Slide 5, emphasize **"never auto-guesses picklist values"** — leadership cares about trust.
- On demo Step 10, pause on **NOT READY** — it proves the gating works.
- End demo with confidence: "The file we started with would have failed in DIT. We caught it here."

---

*Document version: July 2026 · Aligned with `final_project_presentation.html` (12 slides)*
