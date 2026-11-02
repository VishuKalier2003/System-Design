"""Content model for the Uber System Design Atlas.

Content modules call domain(), comp() and sub() to register architecture
content. build.py renders the registry into one self-contained HTML file.
Content is plain data; presentation lives only in build.py.
"""

REG = {"domains": [], "comps": [], "subs": [], "workflows": [], "glossary": [], "phases": [], "pages": []}

PHASES = ["I", "II", "III", "IV", "V", "VI"]
STATE = {
    "N": "Not introduced",
    "I": "Introduced",
    "U": "Exists and unchanged",
    "E": "Extended",
    "R": "Re-architected",
    "P": "Replaced",
    "X": "Retired",
}


def domain(id, name, letter, summary, kinds):
    REG["domains"].append(dict(id=id, name=name, letter=letter, summary=summary, kinds=kinds))


def comp(**k):
    k.setdefault("subs", [])
    REG["comps"].append(k)
    return k


def sub(**k):
    REG["subs"].append(k)
    return k


def A(title, phase, context, options, decision, why, tradeoffs, revisit):
    """Architecture Decision Record.

    context  : context + problem + constraints
    options  : list of (option, reason-rejected-or-'chosen')
    tradeoffs: trade-offs, risks and operational consequences
    """
    return dict(title=title, phase=phase, context=context, options=options,
                decision=decision, why=why, tradeoffs=tradeoffs, revisit=revisit)


def Q(cat, q, a, alt="", phases=""):
    """Open-ended question with a complete answer.

    a      : recommended approach, why it is correct, how it works, failure behaviour
    alt    : alternatives and trade-offs
    phases : how the answer changes across phases
    """
    return dict(cat=cat, q=q, a=a, alt=alt, phases=phases)


def F(case, detect, impact, recover, consistency):
    """Failure analysis row: trigger/case, detection, impact+containment, recovery, consistency."""
    return dict(case=case, detect=detect, impact=impact, recover=recover, consistency=consistency)


def T(kind, scenario, expected):
    return dict(kind=kind, scenario=scenario, expected=expected)


def W(**k):
    REG["workflows"].append(k)


def G(term, definition, problem, internals, example, used, phase, related, mistakes, impl):
    REG["glossary"].append(dict(term=term, definition=definition, problem=problem, internals=internals,
                                example=example, used=used, phase=phase, related=related,
                                mistakes=mistakes, impl=impl))


def phase(**k):
    REG["phases"].append(k)


def page(id, title, group, body):
    REG["pages"].append(dict(id=id, title=title, group=group, body=body))
