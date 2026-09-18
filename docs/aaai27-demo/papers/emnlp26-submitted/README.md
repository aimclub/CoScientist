# Alembic — EMNLP 2026 System Demonstrations paper

LaTeX source for the Alembic demo-track submission, built on the official
[acl-style-files](https://github.com/acl-org/acl-style-files) template
(`acl.sty` / `acl_natbib.bst`, unmodified per ACL policy).

## Key dates (2026 System Demonstrations track)
- Submission: **2026-07-10, 11:59 PM UTC-12h**
- Notification: 2026-08-20
- Camera-ready: 2026-08-30

## Format rules that apply
- Main content: **max 6 pages** (longer → desk reject)
- Appendix: **max 2 pages**
- Ethics/broader-impact statement and references: unlimited extra space
- **Single-blind**: authors are not anonymized, self-citation is fine
- A submission with **no reported evaluation risks desk rejection**
- Demo package: a working link (repo/video) is required, or a note on why
  hardware prevents sharing it
- Screencast: ≤ 2.5 minutes, YouTube or MPEG4 supplementary file

Full call: <https://2026.emnlp.org/calls/demos/>

## Layout
`emnlp2026_demo.tex` is preamble + wiring only (`\title`, `\author`, package
loads, and one `\input{sections/...}` per section). **Edit the section
content in `sections/`, not the top-level file:**

| File | Maps to |
|---|---|
| `sections/abstract.tex` | Abstract |
| `sections/intro.tex` | §1 Introduction |
| `sections/system.tex` | §2 System Overview (incl. pipeline figure) |
| `sections/demo.tex` | §3 Demonstration |
| `sections/comparison.tex` | §4 Comparison with Existing Systems (incl. table) |
| `sections/availability.tex` | §5 Availability |
| `sections/evaluation.tex` | Evaluation |
| `sections/limitations.tex` | Limitations |
| `sections/ethics.tex` | Ethics Statement |
| `sections/acknowledgments.tex` | Acknowledgments |
| `sections/appendix.tex` | Appendix A |

Add a new section by creating a file in `sections/` and adding one
`\input{sections/<name>}` line at the right spot in `emnlp2026_demo.tex`.

## Building
```bash
pdflatex emnlp2026_demo.tex
bibtex emnlp2026_demo
pdflatex emnlp2026_demo.tex
pdflatex emnlp2026_demo.tex
```

## Before submitting — outstanding TODOs
- [ ] Real author names/affiliations/emails (`emnlp2026_demo.tex`)
- [ ] `\repourl` / `\demourl` — public repo link + screencast link (`emnlp2026_demo.tex`)
- [ ] **Evaluation section** (`sections/evaluation.tex`) — replace the placeholder
      with the actual `run_benchmark.py` results table (this is required, not optional)
- [ ] Trim `docs/TOOLMAKER_COMPARISON.md` / `docs/TOOLROSELLA_COMPARISON.md`
      into `sections/appendix.tex` (2-page limit)
- [ ] Acknowledgments (`sections/acknowledgments.tex`, funding if any)
- [ ] Switch `\usepackage[preprint]{acl}` → `\usepackage{acl}` in `emnlp2026_demo.tex`
      for camera-ready
