# PepFlow AI — Presentation

A self-contained HTML slide deck for leadership and stakeholder presentations (~15 minutes). Includes plain-language Europe SFA context for audiences not on the SFA team.

## Files

| File | Purpose |
|------|---------|
| `final_project_presentation.html` | **Final project deck** — self-contained, PepFlow AI branding (17 slides) |
| `PRESENTER_SCRIPT.md` | Full presenter script, demo steps, Q&A backup |
| `IMAGE_PLACEHOLDER_GUIDE.md` | Where to insert your own screenshots |
| `index.html` | Extended slide deck (external CSS) |
| `styles.css` | PepsiCo-branded styles (linked from `index.html`) |
| `README.md` | This file |

## How to Open

### Final project presentation (recommended)

1. **Double-click** `final_project_presentation.html` in File Explorer.
2. **Or** from the project root:

   ```powershell
   start docs\presentation\final_project_presentation.html
   ```

3. **Or** drag `final_project_presentation.html` into Chrome, Edge, or Firefox.

This file is fully self-contained (embedded CSS + JS). No server required. Works offline after first font load.

### Extended deck (`index.html`)

1. **Double-click** `index.html` in File Explorer — opens in your default browser.
2. **Or** from the project root:

   ```powershell
   start docs\presentation\index.html
   ```

No server or internet connection required after download. Works fully offline.

## Presenting

1. Press **F11** for fullscreen (recommended for projector).
2. Use **→** / **←** arrow keys (or Space / Page Down) to navigate slides.
3. Press **N** to toggle presenter notes (bottom panel).
4. Click the **dots** in the navigation bar to jump to any slide.
5. **Home** / **End** jump to first / last slide.

## Slide Overview (17 slides)

| # | Title | Notes |
|---|-------|-------|
| 1 | PepFlow AI — Title / Hook | Prepare. Validate. Load. |
| 2 | What is Europe SFA? | Context for non-SFA audience |
| 3 | The Problem | Quote callout |
| 4 | Two Upload Paths | DIT vs Workbench split |
| 5 | DIT vs Workbench comparison | Side-by-side table |
| 6 | Broken Data: Dates | CSS spreadsheet mock |
| 7 | Missing + Picklists | Split panel |
| 8 | IDs & Formatting | Scientific notation, duplicates |
| 9 | **Live Demo** | **Mid-deck — switch to Streamlit** |
| 10 | Workbench errors vs PepFlow | Before/after panels |
| 11 | How PepFlow Fixes It | Granular fix cards |
| 12 | Process Walkthrough | Timeline |
| 13 | Salesforce OAuth | Brief connection story |
| 14 | Impact | Outcomes list |
| 15 | Final Outcome + Next Steps | Split panel |
| 16 | Recap | Problem/solution pair |
| 17 | Q&A + Sources | 5 min |

See `PRESENTER_SCRIPT.md` for full talking points and demo script.

## Live Demo Setup

Before presenting **slide 9** (mid-deck), start the Streamlit app:

```powershell
cd C:\Users\cwangz162\Europe-SFA-Data-Load-Copilot
.\venv\Scripts\Activate.ps1
streamlit run app.py
```

Demo test file:

```
test_data/retail_promotion/RO_Promotion_Faulty_Validation_Test.csv
```

**Demo path:** Data Import Tool → Retail Promotion → Prepare & Validate → upload test CSV.

## Printing / PDF

Use browser Print (Ctrl+P) — each slide prints on a separate page. Navigation and notes panels are hidden in print layout.

## Customization

- Edit slide content in `index.html` (each `<section class="slide">` block).
- Presenter notes are in the `data-notes` attribute on each slide.
- Colors and typography are in `styles.css` (PepsiCo palette: `#004B93`, `#E32934`).
