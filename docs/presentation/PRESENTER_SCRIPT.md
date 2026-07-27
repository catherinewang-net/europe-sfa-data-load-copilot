# PepFlow AI — Presenter Script & Demo Guide

**Audience:** Leadership and team members who are NOT on Europe SFA — plain-language context throughout  
**Total time:** ~15 minutes (7–8 min talk · 2–3 min live demo · 5 min Q&A)  
**Deck:** `docs/presentation/final_project_presentation.html` (17 slides)  
**Demo file:** `test_data/retail_promotion/RO_Promotion_Faulty_Validation_Test.csv`  
**Demo path:** Data Import Tool → Retail Promotion → Prepare & Validate File

---

## Part 1: Full Presenter Script (~7–8 minutes)

Read naturally — talking points, not a teleprompter. Pause briefly after each slide transition.

---

### Slide 1 — Title / Hook (~45 sec)

**PepFlow AI · Prepare. Validate. Load.**

> Good [morning/afternoon], everyone. Thank you for the time.
>
> I want to start with a question most of us have lived through: *How many hours have we lost fixing a CSV that Salesforce still rejects at upload?*
>
> That's the gap **PepFlow AI** addresses — the Europe SFA Data Load Copilot. It prepares and validates data *before* upload to Workbench or the Data Import Tool: faster, safer, fewer errors.
>
> Tagline: **Prepare. Validate. Load.**

*Audience should notice:* Clear problem framing; PepFlow AI branding.

---

### Slide 2 — What is Europe SFA? (~60 sec)

**Context for non-SFA audience**

> If you're not on the Europe SFA team, here's the context.
>
> **SFA — Sales Force Automation** — is PepsiCo's Salesforce deployment for European markets: promotions, customers, products, routing.
>
> When a market launches or updates data, teams don't type row-by-row. They prepare **CSV spreadsheet exports** with hundreds or thousands of rows and bulk-upload them.
>
> Imagine shipping a product catalog to 20 countries — each fills an Excel template, and every file must match Salesforce's exact rules or the whole upload fails.

*Audience should notice:* Plain-language SFA explanation; why CSV uploads matter at scale.

---

### Slide 3 — The Problem (~50 sec)

**The preparation gap**

> Read the quote on screen — this story is familiar on every deployment.
>
> Teams juggle Excel, template PDFs, and tribal knowledge. The same checks get repeated by hand.
>
> Picklist labels, date formats, header names — none validated until someone tries to upload. One bad row can reject the entire file.
>
> The pain isn't Salesforce itself. It's the **preparation gap** between a market spreadsheet and a file the platform will accept.

*Audience should notice:* Operational workflow problem, not an IT complaint.

---

### Slide 4 — Two Upload Paths (~50 sec)

**DIT vs Workbench intro**

> There are **two ways** to bulk-load data into Salesforce for Europe SFA.
>
> **Data Import Tool (DIT)** — PepsiCo's spreadsheet template tool. Friendly headers like `*Promotion Name`, dates as DD/MM/YYYY. Used by market ops.
>
> **Salesforce Workbench** — alternative path with API field names like `Name`, `Market__c`, dates as YYYY-MM-DD. Often used by admins.
>
> Both validate against the same org — but expect **different column names and date formats**. PepFlow supports both.

*Audience should notice:* Two paths, two rule sets — loaders must know their target tool.

---

### Slide 5 — DIT vs Workbench Comparison (~45 sec)

**Same data, two formats**

> Walk through the comparison table. Same Retail Promotion row — different headers and date formats depending on upload path.
>
> DIT: `*Promotion Name`, `*Market`, `06/07/2026`. Workbench: `Name`, `Market__c`, `2026-07-06`.
>
> PepFlow detects which tool you're targeting from your headers and applies the right validation rules.

*Audience should notice:* Concrete side-by-side difference; not abstract.

---

### Slide 6 — Broken Data: Dates (~45 sec)

**Malformed dates**

> Point to the red cells. These look fine in Excel but fail validation.
>
> Row 3: `6/7/2026` — ambiguous US vs EU. Row 5: `31/02/2026` — impossible date. Row 6: `46209` — Excel serial number. Row 7: `July 6, 2026` — text, not DD/MM/YYYY.
>
> All from our fault-injection test file — real patterns loaders hit every cycle.

*Audience should notice:* Visual proof; issues are subtle in Excel, obvious to Salesforce.

---

### Slide 7 — Missing + Picklists (~45 sec)

**Required fields and picklist mismatches**

> Left table: blank Promotion Name, blank Market — required fields marked with `*` in DIT templates.
>
> `NOT_A_MARKET` isn't a valid picklist value. `leaflet` vs `Leaflet` — case matters. Salesforce is exact-match.
>
> Loaders often guess from a PDF template. PepFlow shows allowed values from org metadata — but never auto-guesses replacements.

*Audience should notice:* Required fields and picklist precision.

---

### Slide 8 — IDs & Formatting (~40 sec)

**Silent Excel damage**

> Scientific notation: Material ID `3.40061E+08` — Excel destroyed the number. Whitespace in promotion names. Duplicate External IDs on rows 12 and 14.
>
> These pass visual Excel review but break at upload.

*Audience should notice:* Excel is part of the problem, not the solution.

---

### Slide 9 — LIVE DEMO (~15 sec transition → 2–3 min demo)

**Let's see PepFlow catch these issues**

> **Now let's test PepFlow.** Switch to the Streamlit app.
>
> We'll upload the Retail Promotion validation test file and walk through the full workflow.

*Then proceed to Part 2 below. After demo, advance to Slide 10.*

---

### Slide 10 — Workbench Errors vs PepFlow (~45 sec)

**Before vs after upload**

> Back to the deck. Left panel: typical Workbench failure messages — cryptic, after upload, file rejected.
>
> Right panel: PepFlow catches the same issues *before* upload — plain language, row numbers, suggested fixes.
>
> This is the value prop: **shift data quality left** — fix before upload, not after failure.

*Audience should notice:* Contrast is stark; PepFlow complements existing tools.

---

### Slide 11 — How PepFlow Fixes It (~50 sec)

**Granular fixes**

> Quick tour — won't read every card.
>
> **Whitespace trim** — automatic safe fix. **Date conversion** — per upload method. **Picklist selection** — user picks from allowed values, never auto-guessed. **Leading zeros** — EAN codes only. **Duplicate IDs** flagged. **Scientific notation** detected.
>
> Two downloads: **Review CSV** for audit, **Tool-Ready CSV** gated until blockers cleared.

*Audience should notice:* Safe automation vs. manual control where it matters.

---

### Slide 12 — Process Walkthrough (~45 sec)

**Upload to tool-ready CSV**

> Walk the timeline: Upload → Header Review → Data Cleanup → Fix Issues → Picklist Review → Review CSV → Tool-Ready CSV.
>
> PepFlow is a **preparation layer** — loaders download the Tool-Ready CSV and upload via DIT or Workbench as they do today. Original file is never modified.

*Audience should notice:* Concrete, repeatable workflow.

---

### Slide 13 — Salesforce OAuth (~40 sec)

**Connect Salesforce — brief**

> Primary auth: **Connect Salesforce** via OAuth PKCE — not Microsoft Entra.
>
> Live org pulls current field types and picklists. Fallback: **Approved Snapshot** for Streamlit Cloud demo.
>
> **Read-only** — PepFlow never writes to Salesforce. Entra is optional app gate for hosted deployments only.

*Audience should notice:* Security boundary; flexible deployment.

---

### Slide 14 — Impact (~40 sec)

**Outcomes, not features**

> Less manual review. Fewer upload failures. Better data quality with user-approved corrections. Easier for non-technical loaders. Reusable foundation for new markets.

*Audience should notice:* Business value tied to each outcome.

---

### Slide 15 — Final Outcome (~40 sec)

**Ready for pilot**

> Working Streamlit app, OAuth, hybrid metadata, both upload paths, 140+ tests. Phase 1 on Streamlit Cloud. Next steps: expand rules, production OAuth, batch uploads, UI refinement.

*Audience should notice:* Deliverable is real and pilot-ready.

---

### Slide 16 — Recap (~30 sec)

**Tie back to opening hook**

> The file we started with would have failed in DIT. We caught it in PepFlow — before upload, with plain-language fixes and user approval.
>
> **Prepare. Validate. Load.**

*Audience should notice:* Full-circle narrative.

---

### Slide 17 — Q&A (~5 min)

**Time for Q&A**

> Open the floor. Sources on screen for reference.

*See Part 3 for backup answers.*

---

## Part 2: Live Demo Script (2–3 minutes)

**Setup:** App running (Streamlit Cloud or localhost) · test CSV ready · browser tab pre-opened  
**Trigger:** Slide 9 — demo is in the **middle** of the deck  
**Path:** Data Import Tool → Retail Promotion → Prepare & Validate File

| Step | Action | Say (short) | Audience should notice |
|------|--------|-------------|--------------------------|
| **1** | Switch to Streamlit app | "Here's PepFlow — same workflow our loaders use." | Clean, guided UI |
| **2** | Point to **Salesforce Connection** card | "Phase 1 uses Approved Snapshot. Devs can Connect Salesforce for live metadata." | Metadata source labeled |
| **3** | Select **Data Import Tool** | "DIT path — friendly headers, DD/MM/YYYY dates." | Tool-specific rules |
| **4** | Select **Retail Promotion** | "Romania Retail Promotion — one of our active templates." | Template tied to EUSFA |
| **5** | Click **Prepare & Validate File** | "Full prepare and validate — not just formatting." | Task before upload |
| **6** | Upload `RO_Promotion_Faulty_Validation_Test.csv` | "Fault-injection test file — 26 rows of intentional errors." | Preview + file overview |
| **7** | **Header Review** → Continue | "Headers checked first. Original file never modified." | Match % banner |
| **8** | **Data Cleanup** → Apply All Safe Changes | "Whitespace trim — one click." | Category breakdown |
| **9** | **Fix Issues:** Row 5 invalid date → Save | "Ambiguous dates need loader input — inline fix." | Issue count drops |
| **10** | **Picklist Review:** NOT_A_MARKET → select RO → Apply | "Allowed values only — we choose, PepFlow never guesses." | No invented replacements |
| **11** | Scroll to **Upload Readiness** | "NOT READY until blockers cleared." | Gating works |
| **12** | **Download Review CSV** | "Audit file even when not tool-ready." | Review CSV always available |
| **13** | Point to **Tool-Ready CSV** (disabled if blockers) | "Unlocks only when all blocking issues resolved." | Download gating |
| **Close** | Return to Slide 10 | "That's the loop — upload, validate, fix, download when ready." | End-to-end in under 3 min |

### Demo highlights (if time allows)

- **Salesforce Connection card** — Approved Snapshot or live org.
- **Fix Issues vs Picklist Review** — dates/duplicates vs picklists (by design).
- **Review CSV vs Tool-Ready CSV** — audit vs upload file.

---

## Part 3: Q&A Prep (~5 minutes)

*Speaker backup — not on slides.*

### Q1: "Why not just use Excel?"

- Excel isn't metadata-aware — strips leading zeros, misreads dates, no picklist validation.
- PepFlow sits **between Excel and Salesforce**, not replacing Excel.
- Review CSV gives an audit trail Excel macros can't replicate against live metadata.

### Q2: "How is this different from DIT or Workbench?"

- DIT and Workbench **upload** data; they reject bad files at upload time.
- PepFlow **prepares before upload** — same rules, errors surface early with plain-language fixes.
- Complementary: download Tool-Ready CSV → upload via DIT or Workbench as today.

### Q3: "What's the deployment timeline?"

- Phase 1 demo live on Streamlit Community Cloud with bundled snapshot.
- Local dev: `streamlit run app.py` + SFDX clone or Connect Salesforce.
- Controlled pilot: **weeks, not months**. 140+ tests reduce regression risk.

### Q4: "What about security?"

- **No writes to Salesforce** — read-only metadata via OAuth or snapshot.
- OAuth tokens in session state only — not persisted.
- CSVs processed in-session. Optional Entra OIDC is app-level gate only.

### Q5: "Other markets and templates?"

- **Yes — by design.** Metadata-driven from EUSFA.
- Retail Promotion is the demo because the fault-injection file is comprehensive.
- New template = metadata + config, not a rebuild.

### Q6: "Who maintains this?"

- Python / Streamlit — standard stack.
- Modular validators; metadata sync via SFDX or Connect Salesforce.
- 140+ automated tests catch regressions.

---

## Part 4: Presenter Tips

### Deck controls

| Action | How |
|--------|-----|
| Fullscreen | **F11** |
| Next / previous | **→** / **←**, Space, Page Down/Up |
| Presenter notes | **N** or **Notes (N)** button |
| Jump to slide | Click dots, or **Home** / **End** |
| Open deck | `start docs\presentation\final_project_presentation.html` |

### Pre-demo checklist (before Slide 9)

- [ ] Streamlit app running (Cloud URL or `localhost:8501`)
- [ ] Browser tab open to app
- [ ] Metadata source visible (Snapshot or Connected)
- [ ] Test file: `test_data\retail_promotion\RO_Promotion_Faulty_Validation_Test.csv`
- [ ] Deck open; Slide 9 ready
- [ ] Close unrelated tabs; disable notifications

### Backup if demo fails

1. Stay on **Slide 9** and narrate the three-step cards.
2. Describe what audience would see (upload → Header Review → Fix Issues → Picklist Review → NOT READY → Review CSV).
3. Reference **26 rows of fault injections** in test file.
4. Offer screen recording or follow-up walkthrough.
5. Pivot to Slides 10–15 — deliverable exists regardless.

### Timing guardrails

| Segment | Target | If running long… |
|---------|--------|-------------------|
| Slides 1–8 | 5–6 min | Shorten Slides 2, 5 |
| Live demo (Slide 9) | 2–3 min | Skip optional fix; show NOT READY + Review CSV |
| Slides 10–16 | 2–3 min | Shorten Slide 11 (capabilities) |
| Q&A (Slide 17) | 5 min | Prioritize security and deployment |

### Delivery notes

- Slide 2: pause for non-SFA audience — this is their context slide.
- Slide 9: demo is **mid-deck** — don't rush the broken-data slides before it.
- Slide 10: pause on Workbench vs PepFlow contrast — leadership cares about shift-left.
- Slide 11: emphasize **"never auto-guesses picklist values."**
- End demo: "The file we started with would have failed in DIT. We caught it here."

---

*Document version: July 2026 · Aligned with `final_project_presentation.html` (17 slides)*
