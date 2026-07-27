# Europe SFA Data Load Copilot — Presentation

A self-contained HTML slide deck for leadership and stakeholder presentations (15 minutes per person).

## Files

| File | Purpose |
|------|---------|
| `final_project_presentation.html` | **Final project deck** — self-contained, leadership-focused (12 slides) |
| `index.html` | Extended slide deck (13 slides, external CSS) |
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

## Slide Overview (12 slides)

| # | Title | ~Time |
|---|-------|-------|
| 1 | Title / Hook | — |
| 2 | The Problem | 2 min |
| 3 | Who It Helps | — |
| 4 | Our Approach | 2 min |
| 5 | Key Decisions & Tradeoffs | — |
| 6 | Solution Overview (Architecture) | 2 min |
| 7 | Unified Prepare & Validate Flow | — |
| 8 | Key Features Built | 2 min |
| 9 | Demo Script (2–3 min) | 2–3 min |
| 10 | Impact & Value | — |
| 11 | What's Next / Roadmap | 1 min |
| 12 | Q&A | 5 min |

## Live Demo Setup

Before presenting slide 9, start the Streamlit app:

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
