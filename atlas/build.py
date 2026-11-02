#!/usr/bin/env python3
"""Build the Uber System Design Atlas into one self-contained HTML file.

Usage: python3 atlas/build.py            -> writes uber-system-design-atlas.html
       python3 atlas/build.py --audit    -> also prints the coverage audit
"""
import html
import importlib
import json
import os
import pkgutil
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from model import REG, PHASES, STATE  # noqa: E402
import content  # noqa: E402

for m in sorted(pkgutil.iter_modules(content.__path__), key=lambda x: x.name):
    importlib.import_module("content." + m.name)

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "uber-system-design-atlas.html")
DOM = {d["id"]: d for d in REG["domains"]}
COMP = {c["id"]: c for c in REG["comps"]}
SUB = {s["id"]: s for s in REG["subs"]}
for s in REG["subs"]:
    COMP[s["comp"]]["subs"].append(s)
PH_IDX = {p: i for i, p in enumerate(PHASES)}

# ---------------------------------------------------------------- text helpers
e = lambda s: html.escape(str(s), quote=True)  # noqa: E731


def inline(s):
    s = e(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[\[(c|s|w|g|phase|p):([a-zA-Z0-9_\-]+)\]\]", lambda m: link(m.group(1), m.group(2)), s)
    return s


def link(kind, id_):
    if kind == "c" and id_ in COMP:
        return f'<a href="#/c/{id_}">{e(COMP[id_]["name"])}</a>'
    if kind == "s" and id_ in SUB:
        return f'<a href="#/s/{id_}">{e(SUB[id_]["name"])}</a>'
    if kind == "phase":
        return f'<a href="#/phase/{id_}">Phase {id_}</a>'
    if kind == "w":
        return f'<a href="#/w/{id_}">workflow {id_}</a>'
    if kind == "p":
        t = next((x["title"] for x in REG["pages"] if x["id"] == id_), id_)
        return f'<a href="#/p/{id_}">{e(t)}</a>'
    return e(id_)


def md(s):
    """Tiny markdown: paragraphs, '- ' bullets, '1. ' lists, inline code/bold/links."""
    if s is None:
        return ""
    if isinstance(s, (list, tuple)):
        return "<ul>" + "".join(f"<li>{inline(x)}</li>" for x in s) + "</ul>"
    out = []
    for block in str(s).strip().split("\n\n"):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if lines and all(ln.lstrip().startswith("- ") for ln in lines):
            out.append("<ul>" + "".join(f"<li>{inline(ln.lstrip()[2:])}</li>" for ln in lines) + "</ul>")
        elif lines and all(re.match(r"\s*\d+\. ", ln) for ln in lines):
            out.append("<ol>" + "".join(f"<li>{inline(re.sub(r'^\s*\d+\. ', '', ln))}</li>" for ln in lines) + "</ol>")
        else:
            out.append("<p>" + inline(" ".join(lines)) + "</p>")
    return "".join(out)


def table(headers, rows, cls=""):
    h = "".join(f"<th>{e(x)}</th>" for x in headers)
    b = "".join("<tr>" + "".join(f"<td>{md(c) if isinstance(c, list) else inline(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def kv(rows):
    return '<div class="tw"><table class="kv"><tbody>' + "".join(
        f"<tr><th>{e(k)}</th><td>{md(v) if isinstance(v, list) else inline(v)}</td></tr>" for k, v in rows if v not in (None, "", [])) + "</tbody></table></div>"


def code(src, lang=""):
    if not src:
        return ""
    return f'<div class="code"><span class="lang">{e(lang)}</span><pre><code>{e(src.strip())}</code></pre></div>'


DIAG_COUNT = [0]


def mermaid_safe(src):
    """Normalize authored Mermaid: ';' ends a statement in sequence diagrams, and '(' in unquoted edge labels breaks flowcharts."""
    src = src.strip()
    if src.startswith("sequenceDiagram"):
        src = "\n".join(ln if ln.strip().startswith(("Note", "participant")) else ln.replace(";", ",") for ln in src.split("\n"))
    elif src.startswith(("flowchart", "graph")):
        src = re.sub(r'\|([^|"\n]*[()][^|"\n]*)\|', lambda m: '|"' + m.group(1) + '"|', src)
    return src


def diagram(d, title):
    if not d:
        return ""
    src, expl = d if isinstance(d, (list, tuple)) else (d, "")
    src = mermaid_safe(src)
    DIAG_COUNT[0] += 1
    return (f'<figure class="dg"><figcaption>{e(title)}</figcaption>'
            f'<pre class="mermaid">{e(src.strip())}</pre>'
            f'<details class="src"><summary>Diagram source</summary><pre><code>{e(src.strip())}</code></pre></details>'
            f'<div class="dx">{md(expl)}</div></figure>')


def H(n, text, anchor=""):
    a = f' id="{anchor}"' if anchor else ""
    return f"<h{n}{a}>{inline(text)}</h{n}>"


def chip(text, cls=""):
    return f'<span class="chip {cls}">{e(text)}</span>'


def state_of(entry):
    m = re.match(r"\s*([NIUERPX])\s*[:|]\s*(.*)", entry, re.S)
    return (m.group(1), m.group(2)) if m else ("E", entry)


def evo_diagram(name, evo):
    lines = ["flowchart LR"]
    prev = None
    for i, p in enumerate(PHASES):
        st, txt = state_of(evo[i]) if isinstance(evo[i], str) else (evo[i][0], evo[i][1])
        short = re.sub(r"[\"\[\]{}()<>|#;`]", " ", txt)
        short = (short[:70] + "…") if len(short) > 70 else short
        nid = f"P{i+1}"
        cls = {"N": "na", "I": "intro", "U": "same", "E": "ext", "R": "rearch", "P": "repl", "X": "ret"}[st]
        lines.append(f'  {nid}["Phase {p} · {STATE[st]}<br/>{short}"]:::{cls}')
        if prev:
            lines.append(f"  {prev} --> {nid}")
        prev = nid
    lines += ["  classDef na fill:#FFFFFF,stroke:#CBCBCB,color:#757575",
              "  classDef intro fill:#EFF3FE,stroke:#276EF1,color:#000000,stroke-width:2px",
              "  classDef same fill:#F6F6F6,stroke:#757575,color:#000000",
              "  classDef ext fill:#E6F7EE,stroke:#06C167,color:#000000,stroke-width:2px",
              "  classDef rearch fill:#FFF2D9,stroke:#FFC043,color:#000000,stroke-width:2px",
              "  classDef repl fill:#FFEFED,stroke:#E11900,color:#000000",
              "  classDef ret fill:#EEEEEE,stroke:#545454,color:#545454"]
    return "\n".join(lines)


def context_diagram(c):
    lines = ["flowchart LR", f'  SELF["{c["name"]}"]:::self']
    for i, u in enumerate(c.get("up", [])):
        lbl = COMP[u]["name"] if u in COMP else SUB[u]["name"] if u in SUB else u
        lines.append(f'  SELF -->|calls / reads| U{i}["{lbl}"]')
    for i, d in enumerate(c.get("down", [])):
        lbl = COMP[d]["name"] if d in COMP else SUB[d]["name"] if d in SUB else d
        lines.append(f'  D{i}["{lbl}"] -->|consumes| SELF')
    for i, x in enumerate(c.get("ext", [])):
        lines.append(f'  SELF -.->|external| X{i}(["{x}"])')
    lines.append("  classDef self fill:#000000,stroke:#000000,color:#FFFFFF")
    return "\n".join(lines)


def tracker(key):
    states = ["Knowledge understood", "Architecture designed", "HLD completed", "LLD completed",
              "Implementation completed", "Tests passed", "Failure scenarios validated", "Operational readiness"]
    boxes = "".join(f'<label><input type="checkbox" data-track="{e(key)}" data-i="{i}"> {s}</label>' for i, s in enumerate(states))
    return f'<div class="tracker"><div class="tracker-h">Your completion tracking (stored in this browser only)</div>{boxes}</div>'


# ---------------------------------------------------------------- renderers
def r_adrs(adrs, prefix):
    out = []
    for i, a in enumerate(adrs, 1):
        aid = f"ADR-{prefix}-{i:02d}"
        a["_id"] = aid
        opts = table(["Option", "Assessment"], [[o, v] for o, v in a["options"]])
        out.append(f'<details class="adr" open><summary><b>{aid}</b> · {inline(a["title"])} {chip("Phase " + a["phase"])}</summary>'
                   + kv([("Context, problem & constraints", a["context"])]) + "<h5>Options considered</h5>" + opts
                   + kv([("Decision", a["decision"]), ("Reasoning", a["why"]),
                         ("Trade-offs, risks & operational consequences", a["tradeoffs"]),
                         ("Revisit when", a["revisit"])]) + "</details>")
    return "".join(out) or "<p class='gap'>No ADRs recorded.</p>"


def r_qa(qas):
    out = []
    for i, q in enumerate(qas, 1):
        out.append(f'<details class="qa"><summary><span class="qn">Q{i}</span> {chip(q["cat"])} {inline(q["q"])}</summary>'
                   f'<div class="ans"><h6>Recommended answer</h6>{md(q["a"])}'
                   + (f"<h6>Alternatives &amp; trade-offs</h6>{md(q['alt'])}" if q.get("alt") else "")
                   + (f"<h6>Across phases</h6>{md(q['phases'])}" if q.get("phases") else "")
                   + "</div></details>")
    return "".join(out)


def r_fail(fails):
    return table(["Failure case", "Detection", "Impact & containment", "Recovery", "Data consistency"],
                 [[f["case"], f["detect"], f["impact"], f["recover"], f["consistency"]] for f in fails])


def r_tests(tests):
    return table(["Test type", "Scenario", "Expected outcome"], [[t["kind"], t["scenario"], t["expected"]] for t in tests])


def r_ideas(ideas):
    if not ideas:
        return ""
    names = [("now", "Recommended now"), ("next", "Potential next-phase evolution"),
             ("adv", "Advanced alternatives"), ("rej", "Rejected ideas")]
    return '<div class="ideas">' + "".join(
        f'<div class="idea {k}"><h5>{t}</h5>{md(ideas.get(k, []))}</div>' for k, t in names) + "</div>"


def r_evo_table(evo):
    rows = []
    for i, p in enumerate(PHASES):
        st, txt = state_of(evo[i])
        rows.append(f'<tr data-ph="{p}"><td><a href="#/phase/{p}">Phase {p}</a></td><td>{chip(STATE[st], "st-" + st)}</td><td>{md(txt)}</td></tr>')
    return '<div class="tw"><table class="evo"><thead><tr><th>Phase</th><th>State</th><th>Design at this phase</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"


def r_comp_evo(evo):
    dims = ["Architecture & deployment", "Data, storage & communication", "Reliability, consistency & security", "What forces the change"]
    head = "<th>Dimension</th>" + "".join(f'<th data-ph="{p}">Phase {p}</th>' for p in PHASES)
    body = ""
    body += "<tr><th>State</th>" + "".join(f'<td data-ph="{p}">{chip(STATE[evo[i][0]], "st-" + evo[i][0])}</td>' for i, p in enumerate(PHASES)) + "</tr>"
    for d in range(4):
        body += f"<tr><th>{dims[d]}</th>" + "".join(f'<td data-ph="{p}">{inline(evo[i][d + 1])}</td>' for i, p in enumerate(PHASES)) + "</tr>"
    return f'<div class="tw"><table class="evo wide"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def std_questions(s):
    """Standard question bank (§6.13) answered from this subcomponent's own authored design."""
    first_fail = s["fail"][0] if s.get("fail") else None
    dep_fail = next((f for f in s.get("fail", []) if re.search(r"unavailab|outage|down|timeout|degrad", f["case"], re.I)), first_fail)
    revisit = s["adrs"][0]["revisit"] if s.get("adrs") else ""
    qs = [
        Qd("Concurrency", f"How does {s['name']} prevent conflicting concurrent modifications?", s["conc"]),
        Qd("Idempotency", "How does the design behave under duplicate requests or duplicate events?", s["idem"]),
        Qd("Consistency", "What consistency guarantees are necessary, and which are deliberately not provided?", s["consistency"]),
        Qd("Ordering", "What happens if an input message is delayed or arrives out of order?", s["order"]),
        Qd("Recovery", "What happens after a crash and restart?", s["restart"]),
        Qd("Scale", "What becomes the bottleneck, how is throughput increased and how is it partitioned?", s["scale"]),
    ]
    if dep_fail:
        qs.append(Qd("Reliability", f"What happens when this fails: {dep_fail['case']}?",
                     f"Detection: {dep_fail['detect']} Impact and containment: {dep_fail['impact']} Recovery: {dep_fail['recover']} Consistency consequence: {dep_fail['consistency']}"))
    if revisit:
        qs.append(Qd("Evolution", "When should this design be changed?", revisit + " " + "The phase table below lists the concrete next design."))
    return qs


def Qd(cat, q, a):
    return dict(cat=cat, q=q, a=a, alt="", phases="")


def sub_page(s):
    c = COMP[s["comp"]]
    d = DOM[c["domain"]]
    p = []
    p.append(f'<div class="crumbs"><a href="#/d/{d["id"]}">{e(d["name"])}</a> › <a href="#/c/{c["id"]}">{e(c["name"])}</a> › Subcomponent</div>')
    p.append(f'<h1>{e(s["name"])}</h1><div class="meta">{chip("Subcomponent")} {chip(s["cat"])} {chip("Introduced in Phase " + s["phase"], "ph")}</div>')
    p.append(f'<p class="lede">{inline(s["resp"])}</p>')
    p.append(tracker("s:" + s["id"]))
    p.append(H(2, "6.1 Overview", "ov"))
    p.append(kv([("Parent component", f"[[c:{c['id']}]]"), ("Domain", d["name"]), ("Category", s["cat"]),
                 ("Introduction phase", "Phase " + s["phase"]), ("Responsibility", s["resp"]), ("Inputs", s["inp"]),
                 ("Outputs", s["out"]), ("Dependencies", s["deps"]), ("Consumers", s["cons"]), ("Data ownership", s["own"])]))
    p.append(H(2, "6.2 Problem and design motivation"))
    p.append(kv([("Exact problem", s["problem"]), ("Without it", s["without"]), ("Must guarantee", s["guar"]),
                 ("Must not / does not guarantee", s["nong"]), ("Constraints", s.get("constraints", "")), ("Realistic use case", s["usecase"])]))
    p.append(H(2, "6.3 First-principles derivation"))
    p.append(md(s["derive"]))
    p.append(kv([("Concurrency model", s["conc"]), ("Consistency model", s["consistency"]), ("Idempotency & deduplication", s["idem"]),
                 ("Ordering & delayed inputs", s["order"]), ("Restart & recovery requirement", s["restart"]), ("Scaling constraint", s["scale"])]))
    p.append(H(2, "6.4 Recommended feasible architecture"))
    p.append(md(s["arch"]))
    p.append(table(["Internal module", "Responsibility"], s["modules"]))
    p.append(H(2, "6.5 Diagrams"))
    p.append(diagram(s.get("d_arch"), "A. Architecture"))
    p.append(diagram(s.get("d_seq"), "B. Sequence"))
    if s.get("d_state"):
        p.append(diagram(s["d_state"], "C. State"))
    else:
        p.append(f'<p class="na"><b>C. State diagram — not applicable:</b> {inline(s.get("nostate", ""))}</p>')
    p.append(diagram(s.get("d_flow"), "D. Data flow"))
    p.append(diagram(s.get("d_fail"), "E. Failure and recovery"))
    p.append(diagram((evo_diagram(s["name"], s["evo"]), "Generated from the phase-evolution table in §Evolution: each box is this subcomponent's state and design at that phase."), "F. Phase evolution"))
    p.append(H(2, "6.6 Database and data model"))
    p.append(md(s.get("data", "")))
    p.append(code(s.get("sql", ""), "SQL"))
    p.append(H(2, "6.7 API, event and interface design"))
    p.append(code(s.get("api", ""), "Interface"))
    p.append(md(s.get("api_notes", "")))
    p.append(H(2, "6.8 Internal mechanisms and algorithms"))
    p.append("".join(f'<div class="mech"><h5>{inline(n)}</h5>{md(t)}</div>' for n, t in s["mech"]))
    p.append(H(2, "6.9 Code-level implementation"))
    p.append(code(s.get("code", ""), "Java / Spring Boot"))
    p.append(md(s.get("cx", "")))
    p.append(H(2, "6.10 Failure and recovery design"))
    p.append(r_fail(s["fail"]))
    p.append(H(2, "6.11 Alternatives and trade-offs"))
    p.append(table(["Alternative", "Verdict", "Reasoning", "Becomes preferable when"], s["alts"]))
    p.append(H(2, "6.12 Subcomponent architecture decisions"))
    p.append(r_adrs(s["adrs"], s["id"].upper()))
    p.append(H(2, "6.13 Open-ended questions with solutions"))
    p.append("<h4>Standard engineering questions (answered from this design)</h4>" + r_qa(std_questions(s)))
    p.append("<h4>Subcomponent-specific questions</h4>" + r_qa(s["qa"]))
    p.append(H(2, "6.14 Testing strategy"))
    p.append(r_tests(s["tests"]))
    p.append(H(2, "6.15 Independent implementation assignment"))
    p.append(kv([("Objective", f"Build {s['name']} as a standalone module that solves: {s['problem']}"),
                 ("Scope", s["resp"]),
                 ("Requirements (guarantees to deliver)", s["guar"]),
                 ("Package structure", "`com.atlas." + c["id"].replace("-", "") + "." + s["id"].replace("-", "") + "` → " + ", ".join(m[0] for m in s["modules"])),
                 ("Database requirements", "Implement the schema in §6.6 with a migration tool (Flyway), including every constraint and index listed." if s.get("sql") else "No owned database; implement the in-memory/stream state described in §6.6."),
                 ("API requirements", "Implement every operation in §6.7 with the stated error codes and idempotency semantics."),
                 ("Algorithms & mechanisms", [m[0] for m in s["mech"]]),
                 ("Failure scenarios to simulate", [f["case"] for f in s["fail"]]),
                 ("Test cases", [t["scenario"] for t in s["tests"]]),
                 ("Acceptance criteria", [t["expected"] for t in s["tests"]]),
                 ("Advanced extensions", s.get("ideas", {}).get("next", []))]))
    p.append(H(2, "6.16 Final engineering specification"))
    ev_rows = [f"Phase {PHASES[i]} ({STATE[state_of(x)[0]]}): {state_of(x)[1]}" for i, x in enumerate(s["evo"])]
    p.append(kv([("Final recommended design", s["arch"].split("\n\n")[0]), ("Guarantees", s["guar"]), ("Non-guarantees", s["nong"]),
                 ("Assumptions", s.get("assume", s.get("constraints", ""))), ("Dependencies", s["deps"]),
                 ("Phase-specific behaviour", ev_rows),
                 ("Completion checklist", ["Schema migrated with constraints", "All §6.7 operations implemented", "Every §6.10 failure case reproduced in a test",
                                           "Every §6.14 test passing", "Standard + specific questions answerable without notes", "Metrics and alerts for the failure detections in §6.10"])]))
    p.append(H(2, "Phase evolution (introduction → Phase VI)", "evo"))
    p.append(r_evo_table(s["evo"]))
    p.append(H(2, "Design ideas and alternative solutions"))
    p.append(r_ideas(s.get("ideas")))
    return "".join(p)


def comp_page(c):
    d = DOM[c["domain"]]
    p = []
    p.append(f'<div class="crumbs"><a href="#/d/{d["id"]}">{e(d["name"])}</a> › Component</div>')
    p.append(f'<h1>{e(c["name"])}</h1><div class="meta">{chip("Component")} {chip(c["tag"])} {chip("Introduced in Phase " + c["phase"], "ph")} {chip(c["kind"])}</div>')
    p.append(f'<p class="lede">{inline(c["biz"])}</p>')
    p.append(tracker("c:" + c["id"]))
    p.append(H(2, "5.1 Identity and context"))
    p.append(kv([("Domain", d["name"]), ("Category / tag", c["tag"]), ("Classification", c["kind"]), ("Business purpose", c["biz"]),
                 ("Engineering purpose", c["eng"]), ("First introduction", "Phase " + c["phase"]), ("Deployment boundary", c["deploy"]),
                 ("Data ownership", c["data_own"]),
                 ("Upstream dependencies", ", ".join(f"[[c:{u}]]" if u in COMP else f"[[s:{u}]]" if u in SUB else u for u in c.get("up", [])) or "None"),
                 ("Downstream consumers", ", ".join(f"[[c:{u}]]" if u in COMP else f"[[s:{u}]]" if u in SUB else u for u in c.get("down", [])) or "None"),
                 ("External integrations", ", ".join(c.get("ext", [])) or "None"), ("Interfaces", c["interfaces"])]))
    p.append(diagram((context_diagram(c), "System context generated from the dependency lists above: arrows out of the component are calls/reads it makes; arrows in are consumers; dashed arrows are external providers."), "System context"))
    p.append(H(2, "5.2 Problem definition and requirements"))
    p.append(kv([("Problem", c["problem"]), ("Functional requirements", c["fr"]), ("Non-functional requirements & targets", c["nfr"]),
                 ("Expected workload", c["workload"]), ("Success means", c["success"]), ("Failure means", c["failure"])]))
    p.append(H(2, "5.3 First-principles architecture derivation"))
    p.append(md(c["derive"]))
    p.append(H(2, "5.4 Responsibility and boundary design"))
    rows = [["Owns", c["owns"]], ["Does not own", c["not_owns"]], ["Synchronous operations", c["sync"]], ["Asynchronous operations", c["async"]]]
    p.append(table(["Responsibility", "Items"], rows))
    p.append(md(c["boundary_why"]))
    p.append(H(2, "5.5 Subcomponent decomposition"))
    p.append(table(["Subcomponent", "Phase", "Responsibility", "Inputs → Outputs", "Why it exists"],
                   [[f"[[s:{s['id']}]]", s["phase"], s["resp"], f"{s['inp']} → {s['out']}", s["problem"]] for s in c["subs"]]))
    p.append("<p>Every subcomponent above links to its full solution chapter (§6.1–6.16).</p>")
    p.append(H(2, "5.6 Integrated component architecture"))
    p.append(diagram(c["hld"], "Component HLD"))
    p.append(diagram(c["seq"], "Primary request sequence"))
    if c.get("state"):
        p.append(diagram(c["state"], "Component state model"))
    dep = ["flowchart TB"]
    for s in c["subs"]:
        dep.append(f'  {s["id"].replace("-", "_")}["{s["name"]} · P{s["phase"]}"]')
    for a, b in c.get("subdeps", []):
        dep.append(f'  {a.replace("-", "_")} --> {b.replace("-", "_")}')
    p.append(diagram(("\n".join(dep), "Subcomponent dependency graph: an arrow A → B means A calls or reads B. Labels show the phase each subcomponent is introduced."), "Subcomponent dependency graph"))
    p.append(md(c["flow"]))
    p.append(H(2, "5.7 Component-level data architecture"))
    p.append(md(c["data"]))
    if c.get("er"):
        p.append(diagram(c["er"], "Entity relationships"))
    p.append(H(2, "5.8 Reliability architecture"))
    p.append(table(["Concern", "Design"], c["rel"]))
    p.append(H(2, "5.9 Security"))
    p.append(table(["Aspect", "Design"], c["sec"]))
    p.append(H(2, "5.10 Architecture decision records"))
    p.append(r_adrs(c["adrs"], c["id"].upper()))
    p.append(H(2, "5.11 Open-ended architecture questions"))
    p.append(r_qa(c["qa"]))
    p.append(H(2, "5.12 Implementation guide"))
    p.append(kv([("Implementation order", c["impl_order"])]))
    p.append(code(c.get("pkg", ""), "Package structure"))
    p.append(md(c.get("impl_notes", "")))
    p.append(H(2, "5.13 Testing and validation"))
    p.append(r_tests(c["tests"]))
    p.append(H(2, "5.14 Phase evolution", "evo"))
    p.append(r_comp_evo(c["evo"]))
    p.append(diagram((evo_diagram(c["name"], [f"{x[0]}: {x[1]}" for x in c["evo"]]), "Generated from the evolution matrix above."), "Phase evolution"))
    sm = []
    for s in c["subs"]:
        sm.append([f"[[s:{s['id']}]]"] + [STATE[state_of(x)[0]] for x in s["evo"]])
    p.append(table(["Subcomponent"] + [f"Phase {x}" for x in PHASES], sm, "matrix"))
    p.append(H(2, "5.15 Completion criteria"))
    p.append(kv([("Knowledge understood", "You can answer every question in §5.11 and in each subcomponent's §6.13 without notes."),
                 ("Architecture designed", "You can redraw the HLD and justify each ADR's decision against its rejected options."),
                 ("HLD completed", "Context, HLD, sequence and dependency diagrams exist for your implementation."),
                 ("LLD completed", "Schemas, interfaces and algorithms of all subcomponents are specified."),
                 ("Implementation completed", "Every subcomponent assignment (§6.15) is implemented in the order of §5.12."),
                 ("Tests passed", "All §5.13 and subcomponent §6.14 tests pass in CI."),
                 ("Failure scenarios validated", "Each §6.10 failure case was injected and recovered as documented."),
                 ("Operational readiness", "Dashboards and alerts exist for every detection signal named in the failure tables; runbooks link to them.")]))
    p.append(H(2, "Design ideas and alternative solutions"))
    p.append(r_ideas(c.get("ideas")))
    return "".join(p)


def domain_page(d):
    comps = [c for c in REG["comps"] if c["domain"] == d["id"]]
    p = [f'<h1>{e(d["letter"])}. {e(d["name"])}</h1><p class="lede">{inline(d["summary"])}</p>']
    p.append(table(["Item", "Classification"], d["kinds"]))
    p.append(table(["Component", "Phase", "Classification", "Purpose", "Subcomponents"],
                   [[f"[[c:{c['id']}]]", c["phase"], c["kind"], c["eng"], ", ".join(f"[[s:{s['id']}]]" for s in c["subs"])] for c in comps]))
    g = ["flowchart LR"]
    for c in comps:
        g.append(f'  {c["id"].replace("-", "_")}["{c["name"]}"]')
        for u in c.get("up", []):
            if u in COMP:
                g.append(f'  {c["id"].replace("-", "_")} --> {u.replace("-", "_")}["{COMP[u]["name"]}"]')
    p.append(diagram(("\n".join(g), "Components of this domain and their outbound dependencies (including into other domains)."), "Domain dependency map"))
    return "".join(p)


def phase_page(ph):
    p = [f'<h1>Phase {ph["id"]} — {e(ph["title"])}</h1><p class="lede">{inline(ph["focus"])}</p>']
    p.append(H(2, "Workload assumptions"))
    p.append(kv(ph["workload"]))
    p.append(H(2, "Phase architecture"))
    p.append(diagram(ph["hld"], f"Phase {ph['id']} system HLD"))
    p.append(md(ph["arch"]))
    p.append(H(2, "Transition from the previous phase"))
    p.append(kv(ph["transition"]))
    p.append(H(2, "Mechanisms introduced in this phase"))
    p.append(table(["Mechanism", "Why it is justified now"], ph["mechs"]))
    p.append(H(2, "Component changes in this phase"))
    rows = []
    i = PH_IDX[ph["id"]]
    for c in REG["comps"]:
        st, *_ = c["evo"][i]
        if st != "N":
            rows.append([f"[[c:{c['id']}]]", STATE[st], c["evo"][i][1]])
    p.append(table(["Component", "State", "Architecture at this phase"], rows))
    srows = []
    for s in REG["subs"]:
        st, txt = state_of(s["evo"][i])
        if st in "IERPX":
            srows.append([f"[[s:{s['id']}]]", STATE[st], txt])
    p.append(H(3, "Subcomponents introduced, extended, re-architected, replaced or retired"))
    p.append(table(["Subcomponent", "State", "Change"], srows))
    p.append(H(2, "Phase-level ADRs"))
    p.append(r_adrs(ph["adrs"], "PH" + ph["id"]))
    p.append(H(2, "Phase-level questions"))
    p.append(r_qa(ph["qa"]))
    p.append(H(2, "Testing requirements and completion criteria"))
    p.append(kv([("Testing", ph["testing"]), ("Phase complete when", ph["done"])]))
    return "".join(p)


def workflow_page(w):
    p = [f'<h1>Workflow {w["n"]}: {e(w["title"])}</h1><p class="lede">{inline(w["summary"])}</p>']
    p.append(kv([("Actors", w["actors"]), ("Participating components", ", ".join(f"[[c:{x}]]" for x in w["comps"])),
                 ("Owner of each operation", w["owners"])]))
    p.append(diagram(w["seq"], "Sequence"))
    p.append(kv([("State transitions", w["states"]), ("Database modifications", w["db"]), ("Events", w["events"]),
                 ("Synchronous boundary", w["sync"]), ("Asynchronous boundary", w["async"]), ("Consistency requirements", w["consistency"])]))
    p.append(code(w.get("msg", ""), "Message format"))
    p.append(H(2, "Failure cases and recovery"))
    p.append(r_fail(w["fail"]))
    return "".join(p)


def glossary_page():
    out = ["<h1>Glossary and concept knowledge base</h1><p class='lede'>Every concept used in the Atlas, grounded in the component where it is used.</p>"]
    for g in sorted(REG["glossary"], key=lambda x: x["term"].lower()):
        out.append(f'<details class="gl"><summary><b>{inline(g["term"])}</b> — {inline(g["definition"])}</summary>'
                   + kv([("Fundamental problem", g["problem"]), ("Internal working", g["internals"]), ("Example", g["example"]),
                         ("Used in", g["used"]), ("Phase of introduction", g["phase"]), ("Related concepts", g["related"]),
                         ("Common mistakes", g["mistakes"]), ("Implementation implications", g["impl"])]) + "</details>")
    return "".join(out)


# ---------------------------------------------------------------- block pages
def nid(x):
    return x.replace("-", "_")


def auto_block(name):
    if name == "component_dependency_graph":
        g = ["flowchart LR"]
        for d in REG["domains"]:
            g.append(f'  subgraph {d["id"]}_g["{d["letter"]}. {d["name"]}"]')
            for c in [c for c in REG["comps"] if c["domain"] == d["id"]]:
                g.append(f'    {nid(c["id"])}["{c["name"].split(" (")[0]}"]')
            g.append("  end")
        for c in REG["comps"]:
            for u in c.get("up", []):
                if u in COMP:
                    g.append(f"  {nid(c['id'])} --> {nid(u)}")
        return diagram(("\n".join(g), "Generated from every component's upstream dependency list. An arrow A → B means A calls, reads or consumes B. Domains are grouped as subgraphs."), "Global component dependency graph")
    if name == "domain_map":
        g = ["flowchart TB"]
        doms = REG["domains"]
        W_ = 4
        for d in doms:
            cs = [c for c in REG["comps"] if c["domain"] == d["id"]]
            g.append(f'  {d["id"]}_d["<b>{d["letter"]}. {d["name"]}</b><br/>' + "<br/>".join(c["name"].split(" (")[0] for c in cs) + '"]')
        for i in range(len(doms) - W_):
            g.append(f'  {doms[i]["id"]}_d ~~~ {doms[i + W_]["id"]}_d')
        return diagram(("\n".join(g), "Every domain (A–Q) with its components, read left to right, top to bottom."), "Domain map")
    if name == "data_ownership":
        return table(["Component", "Domain", "Owns data", "Deployment boundary"], [[f"[[c:{c['id']}]]", DOM[c["domain"]]["name"], c["data_own"], c["deploy"]] for c in REG["comps"]])
    if name == "event_catalog":
        rows = []
        for w in REG["workflows"]:
            rows.append([w["events"], f"[[w:{w['n']}]] {w['title']}", w["owners"], w["consistency"]])
        return table(["Events", "Workflow", "Ownership", "Consistency"], rows)
    if name == "phase_counts":
        rows = []
        for i, p in enumerate(PHASES):
            cs = {k: 0 for k in STATE}
            ss = {k: 0 for k in STATE}
            for c in REG["comps"]:
                cs[c["evo"][i][0]] += 1
            for x in REG["subs"]:
                ss[state_of(x["evo"][i])[0]] += 1
            rows.append([f"[[phase:{p}]]"] + [f"{cs[k]} / {ss[k]}" for k in STATE])
        return table(["Phase"] + [f"{v} (comp / sub)" for v in STATE.values()], rows)
    if name == "roadmap":
        out = []
        for i, p in enumerate(PHASES):
            items = [s for s in REG["subs"] if s["phase"] == p]
            g = ["flowchart LR"]
            ids = {s["id"] for s in items}
            for s in items:
                g.append(f'  {nid(s["id"])}["{s["name"].split(" (")[0]}"]')
            for c in REG["comps"]:
                for a, b in c.get("subdeps", []):
                    if a in ids and b in ids:
                        g.append(f"  {nid(b)} --> {nid(a)}")
            out.append(H(3, f"Phase {p}: {len(items)} subcomponents introduced"))
            out.append(table(["Order", "Subcomponent", "Component", "Why now"], [[str(k + 1), f"[[s:{s['id']}]]", f"[[c:{s['comp']}]]", state_of(s["evo"][i])[1]] for k, s in enumerate(items)]))
            if len(items) > 1:
                out.append(diagram(("\n".join(g), "Implementation dependency graph for this phase: B → A means implement B before A (A depends on B). Unconnected items can be built in parallel."), f"Phase {p} implementation dependencies"))
        return "".join(out)
    return f"<p class='gap'>Unknown block {e(name)}</p>"


def render_blocks(blocks):
    out = []
    for b in blocks:
        kind = b[0]
        if kind == "md":
            out.append(md(b[1]))
        elif kind == "h":
            out.append(H(b[1], b[2]))
        elif kind == "diagram":
            out.append(diagram(b[1], b[2]))
        elif kind == "table":
            out.append(table(b[1], b[2]))
        elif kind == "kv":
            out.append(kv(b[1]))
        elif kind == "code":
            out.append(code(b[1], b[2] if len(b) > 2 else ""))
        elif kind == "auto":
            out.append(auto_block(b[1]))
        elif kind == "qa":
            out.append(r_qa(b[1]))
        elif kind == "adrs":
            out.append(r_adrs(b[1], b[2]))
    return "".join(out)


# ---------------------------------------------------------------- audit
SUB_REQ = [("problem", "Problem definition"), ("derive", "First-principles derivation"), ("arch", "Recommended architecture"),
           ("modules", "Internal modules"), ("d_arch", "Architecture diagram"), ("d_seq", "Sequence diagram"),
           ("d_state|nostate", "State diagram or N/A justification"), ("d_flow", "Data-flow diagram"), ("d_fail", "Failure & recovery diagram"),
           ("sql|data", "Schema / data model"), ("api", "Interfaces"), ("mech", "Internal mechanisms"), ("code", "Code"),
           ("fail", "Failure analysis"), ("alts", "Alternatives & trade-offs"), ("adrs", "ADRs"), ("qa", "Specific Q&A"),
           ("tests", "Testing"), ("evo", "Phase evolution (6 phases)"), ("ideas", "Design ideas"),
           ("conc", "Concurrency model"), ("consistency", "Consistency model"), ("idem", "Idempotency"), ("order", "Ordering"),
           ("restart", "Restart"), ("scale", "Scaling")]
COMP_REQ = [("problem", "Problem definition"), ("fr", "Functional requirements"), ("nfr", "Non-functional requirements"),
            ("owns", "Boundaries"), ("subs", "Subcomponent inventory"), ("hld", "HLD"), ("seq", "Sequence"), ("data", "Data architecture"),
            ("interfaces", "Interface architecture"), ("rel", "Reliability"), ("sec", "Security"), ("adrs", "ADRs"), ("qa", "Q&A"),
            ("impl_order", "Implementation guide"), ("tests", "Testing"), ("evo", "Phase evolution"), ("ideas", "Design ideas"),
            ("derive", "First-principles derivation")]


def present(obj, key):
    for k in key.split("|"):
        v = obj.get(k)
        if v is None:
            continue
        if isinstance(v, str) and len(v.strip()) >= 15:
            return True
        if isinstance(v, (list, tuple, dict)) and len(v) > 0:
            if k == "evo" and len(v) != 6:
                return False
            if k == "qa" and any(not q.get("a") or len(q["a"]) < 40 for q in v):
                return False
            return True
    return False


def audit():
    res = {"components": {}, "subcomponents": {}, "phases": {}, "workflows": {}, "summary": {}}
    for c in REG["comps"]:
        res["components"][c["id"]] = {lbl: present(c, k) for k, lbl in COMP_REQ}
        res["components"][c["id"]]["All subcomponents have solutions"] = all(s["id"] in SUB for s in c["subs"]) and len(c["subs"]) > 0
    for s in REG["subs"]:
        res["subcomponents"][s["id"]] = {lbl: present(s, k) for k, lbl in SUB_REQ}
    for ph in REG["phases"]:
        res["phases"][ph["id"]] = {k: present(ph, k) for k in ["workload", "hld", "arch", "transition", "mechs", "adrs", "qa", "testing", "done"]}
    for w in REG["workflows"]:
        res["workflows"][w["n"]] = {k: present(w, k) for k in ["seq", "states", "db", "events", "sync", "async", "consistency", "fail"]}
    def tally(d):
        tot = sum(len(v) for v in d.values()); ok = sum(sum(1 for x in v.values() if x) for v in d.values())
        return ok, tot
    for k in ["components", "subcomponents", "phases", "workflows"]:
        ok, tot = tally(res[k])
        res["summary"][k] = {"count": len(res[k]), "sections_complete": ok, "sections_required": tot}
    res["summary"]["diagrams"] = sum(1 for s in REG["subs"] for k in ["d_arch", "d_seq", "d_state", "d_flow", "d_fail"] if s.get(k)) + \
        len(REG["subs"]) + 3 * len(REG["comps"]) + len(REG["phases"]) + len(REG["workflows"])
    res["summary"]["questions_answered"] = sum(len(s["qa"]) + len(std_questions(s)) for s in REG["subs"]) + sum(len(c["qa"]) for c in REG["comps"]) + sum(len(p["qa"]) for p in REG["phases"])
    res["summary"]["adrs"] = sum(len(s["adrs"]) for s in REG["subs"]) + sum(len(c["adrs"]) for c in REG["comps"]) + sum(len(p["adrs"]) for p in REG["phases"])
    return res


def audit_page(res):
    out = ["<h1>Quality audit and coverage manifest</h1>",
           "<p class='lede'>Computed at build time from the content data. A section only counts as complete if it exists with substantive content (≥15 characters of text, a non-empty list, six phase entries, and every question has an answer of ≥40 characters). Headings never count by themselves.</p>"]
    sm = res["summary"]
    out.append(table(["Area", "Items", "Sections complete", "Sections required"],
                     [[k, v["count"], v["sections_complete"], v["sections_required"]] for k, v in sm.items() if isinstance(v, dict)]))
    out.append(kv([("Diagrams (source-based Mermaid)", str(sm["diagrams"])), ("Questions with answers", str(sm["questions_answered"])), ("ADRs", str(sm["adrs"]))]))
    for area, label, link_kind in [("components", "Component coverage", "c"), ("subcomponents", "Subcomponent coverage", "s")]:
        cols = list(next(iter(res[area].values())).keys())
        rows = []
        for k, v in res[area].items():
            rows.append([f"[[{link_kind}:{k}]]"] + ["✔" if v[c] else "✘ incomplete" for c in cols])
        out.append(H(2, label) + table(["Item"] + cols, rows, "matrix audit"))
    out.append(H(2, "Known deviations from the master prompt (stated, not hidden)"))
    out.append(md(DEVIATIONS))
    return "".join(out)


DEVIATIONS = """- **Component phase evolution uses four folded dimensions** (architecture & deployment; data, storage & communication; reliability, consistency & security; transition driver) instead of the fifteen separate rows in §7. Observability and concurrency changes are written inside those cells and inside each subcomponent's per-phase entry.
- **Per-component phase diagrams** are a generated phase-evolution diagram plus one HLD annotated with phase labels, not six separate hand-drawn HLDs per component. Each system phase page does have its own HLD.
- **Subcomponent question banks are smaller than the specification asks.** Each has eight standard questions answered from that subcomponent's own concurrency, idempotency, consistency, ordering, restart, scaling, failure and ADR fields, plus one to three hand-written subcomponent-specific questions. They are not 15-category banks.
- **The implementation assignment (§6.15) and final specification (§6.16)** are assembled from the subcomponent's own authored fields, not written as separate prose.
- **Depth is dense, not textbook length.** Each section gives the decision, the mechanism and the reasoning in a few sentences rather than pages. Uniformity is held by the same required fields for every item, checked by the audit above. The audit checks that content is present and non-trivial, not that it is correct.
- **Interactive features:** phase filter, full-text search, completion tracking and click-to-zoom diagrams are implemented. There is no separate *category* filter. Use search on the tag (e.g. "Money ·") or the inventory page instead.
- **Code samples are illustrative and near-runnable**, aligned with the design. They are not a compiled reference implementation."""


# ---------------------------------------------------------------- assemble
def coverage_matrix_page():
    rows = []
    for d in REG["domains"]:
        for c in [c for c in REG["comps"] if c["domain"] == d["id"]]:
            rows.append([d["name"], f"[[c:{c['id']}]]", "—"] + [STATE[x[0]] for x in c["evo"]])
            for s in c["subs"]:
                rows.append([d["name"], c["name"], f"[[s:{s['id']}]]"] + [STATE[state_of(x)[0]] for x in s["evo"]])
    return ("<h1>Inventory and coverage matrix</h1><p class='lede'>Every domain, component and subcomponent, with its state in each phase. "
            "Every cell links (via the item) to the phase-specific explanation in that item's evolution table.</p>"
            + table(["Domain", "Component", "Subcomponent"] + [f"Phase {p}" for p in PHASES], rows, "matrix"))


def nav():
    out = ['<div class="navsec"><div class="navh">Atlas</div>']
    for pg in [x for x in REG["pages"] if x["group"] == "top"]:
        out.append(f'<a class="nl" href="#/p/{pg["id"]}">{"Home" if pg["id"] == "home" else e(pg["title"])}</a>')
    out.append('<a class="nl" href="#/p/inventory">Inventory &amp; coverage matrix</a><a class="nl" href="#/p/glossary">Glossary</a><a class="nl" href="#/p/audit">Quality audit</a></div>')
    out.append('<div class="navsec"><div class="navh">Phases</div>' + "".join(
        f'<a class="nl" href="#/phase/{ph["id"]}">Phase {ph["id"]} · {e(ph["title"])}</a>' for ph in REG["phases"]) + "</div>")
    out.append('<div class="navsec"><div class="navh">Domains → components → subcomponents</div>')
    for d in REG["domains"]:
        out.append(f'<details class="nd"><summary><a href="#/d/{d["id"]}">{e(d["letter"])}. {e(d["name"])}</a></summary>')
        for c in [c for c in REG["comps"] if c["domain"] == d["id"]]:
            out.append(f'<details class="nc" data-ph="{c["phase"]}"><summary><a class="nl" data-key="c:{c["id"]}" href="#/c/{c["id"]}">{e(c["name"])}</a></summary>')
            for s in c["subs"]:
                out.append(f'<a class="nl ns" data-ph="{s["phase"]}" data-key="s:{s["id"]}" href="#/s/{s["id"]}">{e(s["name"])} <small>P{s["phase"]}</small></a>')
            out.append("</details>")
        out.append("</details>")
    out.append("</div>")
    out.append('<div class="navsec"><div class="navh">End-to-end workflows</div>' + "".join(
        f'<a class="nl" href="#/w/{w["n"]}">{w["n"]}. {e(w["title"])}</a>' for w in REG["workflows"]) + "</div>")
    out.append('<div class="navsec"><div class="navh">Cross-cutting architecture</div>' + "".join(
        f'<a class="nl" href="#/p/{pg["id"]}">{e(pg["title"])}</a>' for pg in REG["pages"] if pg["group"] == "cross") + "</div>")
    return "".join(out)


def main():
    res = audit()
    arts = []
    def art(route, body, title):
        arts.append(f'<article data-route="{e(route)}" data-title="{e(title)}" hidden>{body}</article>')
    for pg in REG["pages"]:
        body = render_blocks(pg["body"]) if isinstance(pg["body"], list) else md(pg["body"])
        art("/p/" + pg["id"], f"<h1>{e(pg['title'])}</h1>" + body, pg["title"])
    art("/p/inventory", coverage_matrix_page(), "Inventory")
    art("/p/glossary", glossary_page(), "Glossary")
    for ph in REG["phases"]:
        art("/phase/" + ph["id"], phase_page(ph), "Phase " + ph["id"])
    for d in REG["domains"]:
        art("/d/" + d["id"], domain_page(d), d["name"])
    for c in REG["comps"]:
        art("/c/" + c["id"], comp_page(c), c["name"])
    for s in REG["subs"]:
        art("/s/" + s["id"], sub_page(s), s["name"])
    for w in REG["workflows"]:
        art("/w/" + str(w["n"]), workflow_page(w), w["title"])
    res["summary"]["diagrams"] = DIAG_COUNT[0]  # every diagram actually emitted into the page
    art("/p/audit", audit_page(res), "Quality audit")
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        tpl = f.read()
    with open(os.path.join(HERE, "vendor", "mermaid.min.js"), encoding="utf-8") as f:
        mermaid_js = f.read().replace("</script", "<\\/script")
    stats = res["summary"]
    tpl = (tpl.replace("{{NAV}}", nav()).replace("{{ARTICLES}}", "\n".join(arts))
           .replace("{{MERMAID}}", mermaid_js)
           .replace("{{STATS}}", e(f'{len(REG["domains"])} domains · {len(REG["comps"])} components · {len(REG["subs"])} subcomponents · {len(REG["workflows"])} workflows · {stats["adrs"]} ADRs · {stats["questions_answered"]} answered questions')))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(tpl)
    os.makedirs(os.path.join(HERE, "validation"), exist_ok=True)
    with open(os.path.join(HERE, "validation", "coverage.json"), "w") as f:
        json.dump(res, f, indent=1)
    print(f"wrote {OUT} ({os.path.getsize(OUT)/1e6:.1f} MB)")
    print(json.dumps(res["summary"], indent=1))
    if "--audit" in sys.argv:
        for area in ["components", "subcomponents", "phases", "workflows"]:
            for k, v in res[area].items():
                miss = [x for x, ok in v.items() if not ok]
                if miss:
                    print(f"INCOMPLETE {area}/{k}: {miss}")


if __name__ == "__main__":
    main()
