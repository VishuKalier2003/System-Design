# Uber System Design Atlas

A phase-wise, component-wise and subcomponent-wise architecture knowledge base for an Uber-like ride-hailing platform, delivered as **one self-contained HTML file**:

**[`uber-system-design-atlas.html`](uber-system-design-atlas.html)**

## How to open it

GitHub shows `.html` files as source code, not as a rendered page. Use one of these:

1. **Download** the file (open it on GitHub → *Download raw file*) and open it in any modern browser. It works fully offline, because the diagram renderer (Mermaid 10.9.1, MIT) is inlined.
2. Or enable **GitHub Pages** on this repository and open `/uber-system-design-atlas.html`.

## What is inside

| | |
|---|---|
| Domains | 17 (Identity → Global infrastructure & privacy) |
| Components | 47, each with sections 5.1–5.15 (problem, requirements, derivation, boundaries, subcomponents, HLD, data, reliability, security, ADRs, questions, implementation, tests, phase evolution, completion criteria) |
| Subcomponents | 113, each with sections 6.1–6.16 (problem, derivation, architecture, 5–6 diagrams, schema, interfaces, mechanisms, code, failure analysis, alternatives, ADRs, questions, tests, assignment, final spec) |
| Phases | 6 (0–1K users → 10M+), each with workload assumptions, system HLD, transition analysis, ADRs and questions |
| End-to-end workflows | 29 |
| Diagrams | 932 Mermaid diagrams, all render-checked in headless Chromium |
| ADRs / answered questions | 167 / 1,074 |

The page has phase filtering, full-text search (`/`), a per-chapter completion tracker (stored in your browser), click-to-zoom diagrams, light and dark themes, and a generated **quality audit** that lists coverage and the known deviations from the original specification.

## Source and rebuild

Content is plain data, kept separate from presentation:

```
atlas/
├── model.py              # content model (domain/comp/sub/workflow/glossary helpers)
├── content/              # all architecture content, one module per domain
├── build.py              # renderer + coverage audit → uber-system-design-atlas.html
├── template.html         # page shell, styles, navigation/search/tracker JS
├── vendor/mermaid.min.js # inlined at build time (MIT, see MERMAID_LICENSE)
└── validation/
    ├── coverage.json     # generated coverage manifest
    └── render_check.js   # renders every diagram in headless Chromium, checks links
```

```bash
python3 atlas/build.py --audit
```

```bash
node atlas/validation/render_check.js
```
