from model import comp, sub, A, Q, F, T

# ======================================================================= Support
comp(id="support", domain="support", name="Customer Support & Disputes", tag="Operations · Human workflows", phase="I", kind="Logical component + internal application",
     biz="Resolves rider and driver problems (lost items, fare disputes, account issues) quickly and consistently, with self-service first and humans when needed.",
     eng="Ticket intake from in-app help, routing by type and priority, agent tooling over other domains' read APIs, and audited actions through owning domains' commands.",
     deploy="Third-party helpdesk + internal tools (I–II); Support service + agent console (IV).", data_own="tickets, ticket_events, macros, dispute decisions.",
     up=["trip", "fare-finalization", "payments", "wallet", "identity", "authz", "safety"], down=["admin-policy", "risk-fraud"], ext=["Helpdesk (Zendesk-like) in early phases"],
     interfaces="`POST /v1/support/tickets` from app (with trip context); agent console APIs; events `TicketResolved`.",
     problem="Support needs data from many domains and must act (refund, adjust, unblock) without becoming a backdoor that bypasses domain rules.",
     fr=["In-app help with trip context", "Self-service flows (fare review, lost item)", "Routing & SLAs", "Agent actions via domain commands", "Dispute resolution with evidence"], nfr=["First response by SLA per priority", "All agent actions audited", "Agent console reads p95 < 500 ms"],
     workload="≈ 2–5% of trips create a ticket.", success="Fast fair resolutions, low repeat contacts.", failure="Slow responses; agents bypassing controls; fraud via support.",
     derive="Tickets reference domain objects (trip, payment) but never copy authoritative state. Agents act via owning domains' APIs with RBAC limits, never direct DB writes. Self-service automations reduce load.",
     owns=["Tickets", "Routing", "Dispute decisions"], not_owns=["Refunds/adjustments (Payments/Fare)", "Account restrictions (Identity/Rider)"], sync=["Ticket CRUD", "Agent views"], **{"async": ["Routing", "SLA timers", "Automated resolutions"]},
     boundary_why="Support orchestrates humans over domain APIs. It owns the conversation, not the business state.",
     hld=("""flowchart LR
  APP["In-app help"] --> TK["Ticket intake & triage"]
  TK --> AUTO["Self-service automations"]
  TK --> Q["Routing queues"] --> AG["Agent console"]
  AG -->|read| TRIP["Trip"] & PAY["Payments"] & ID["Identity"]
  AG -->|commands, RBAC-limited| REF["Refunds"] & ADJ["Fare adjustments"]
  DR["Dispute resolution"] --> ADJ
  AG --> AUD["Audit log"]""", "Tickets are routed to agents who act through domain commands."),
     seq=("""sequenceDiagram
  participant R as Rider
  participant S as Support
  participant F as Fare
  R->>S: "Charged too much" (trip 77)
  S->>S: auto-check: route deviation 2.1 km
  S->>F: adjust(trip 77, −₹45, reason ROUTE)
  S-->>R: We have refunded ₹45""", "Automated resolution."),
     subdeps=[("dispute-resolution", "support-ticketing")],
     flow="Intake attaches context, automation resolves common cases, and others are routed by priority and skill. Agents act via commands with limits, and everything is audited.",
     data="`tickets(id, requester, role, category, trip_id, priority, state, assignee, sla_due)`, `ticket_events(ticket_id, seq, type, actor, payload)`.",
     rel=[["SLA timers", "Durable scheduler."], ["Dependency degradation", "Console shows partial data when a domain is down."]], sec=[["RBAC", "Per-action limits; JIT elevation."], ["Audit", "Every view of PII and every action logged."]],
     adrs=[A("Actions via domain commands only", "I", "Prevent backdoors.", [("Direct DB tools", "Rejected"), ("Domain APIs", "Chosen")], "Commands.", "Domain invariants hold.", "APIs needed for each action.", "N/A")],
     qa=[Q("Security", "Support agents are a social-engineering target. How is account takeover via support prevented?", "Agents cannot change contact points or payout details directly. Those go through Identity's recovery flow with factor checks. Agents see masked PII by default and must justify unmasking. Actions have limits and anomaly monitoring.", "")],
     impl_order=["support-ticketing", "dispute-resolution"], pkg="""com.atlas.support
├── tickets  (TicketService, Triage, Routing, SlaTimers)
├── console  (AgentQueryFacade)
└── disputes (DisputeService, EvidenceCollector)""",
     tests=[T("Security", "Agent tries refund above limit", "Denied"), T("Failure", "Payments down", "Console degrades, ticket proceeds")],
     evo=[("I", "Helpdesk SaaS + manual actions via admin", "SaaS", "Audit via admin", "Pilot"), ("E", "In-app help with context", "—", "SLA timers", "Volume"), ("E", "Automations from events", "—", "—", "Events"),
          ("R", "Support service + console", "Own DB", "RBAC limits", "Scale"), ("E", "ML triage, auto-resolution", "—", "—", "Volume"), ("E", "Regional teams and data", "—", "Residency", "Global")],
     ideas={"now": ["Context attachment"], "next": ["Automations"], "adv": ["LLM-assisted agent replies with human review"], "rej": ["Direct DB edits"]})

sub(id="support-ticketing", comp="support", name="Ticket Intake, Triage & Routing", phase="I", cat="Workflow · Queues",
    resp="Create tickets with full context, categorize and prioritize them, attempt automated resolution, and route the rest to the right agent queue with SLAs.",
    inp="help requests, safety escalations, events", out="tickets, assignments, SLA timers", deps="Trip/Payments read APIs, ML classifier (V)", cons="Agents, riders/drivers", own="tickets, ticket_events",
    problem="Many low-information requests must become actionable, prioritized work.", without="Slow, misrouted support.",
    guar=["Each request becomes one ticket (dedupe by requester+trip+category within 24 h)", "Safety-tagged tickets routed to safety queue within 1 min", "SLA timers fire"], nong=["Resolution quality"],
    usecase="Driver reports 'rider left a phone'. Category LOST_ITEM goes to the lost-items flow (masked contact session) with no agent needed.",
    derive="- Structured help flows produce category + trip context at intake.\n- Priority = f(category, user tier, safety keywords).\n- Work queue with claim (SKIP LOCKED).",
    conc="Agent claim via conditional update.", consistency="Strong: ticket rows and events are in one database, and claims are conditional updates.", idem="dedupe_key = requester + trip + category + day, unique, so a repeated submission returns the existing ticket.", order="Ticket events sequenced per ticket.",
    restart="SLA timers durable.", scale="Partition tickets by month; queues by skill.", arch="Intake API → triage (rules, later ML) → automation attempt → queue with SLA → agent claim/resolve.",
    modules=[["Intake", "Context capture"], ["Triage", "Category/priority"], ["Automations", "Self-serve resolvers"], ["Router", "Skill queues, claim"], ["SlaTimers", "Escalation"]],
    d_arch=("""flowchart LR
  IN["Intake"] --> TR["Triage"] --> AU["Automations"]
  AU -->|unresolved| RT["Router"] --> Q[("queues")] --> AG["Agents"]
  ST["SlaTimers"] --> Q""", "Pipeline."),
    d_seq=("""sequenceDiagram
  participant U as User
  participant I as Intake
  participant A as Automations
  participant Q as Queue
  U->>I: help(trip, FARE_REVIEW)
  I->>A: try auto-resolve
  A-->>I: needs agent
  I->>Q: enqueue P2, SLA 24h""", "Intake path."),
    d_state=("""stateDiagram-v2
  [*] --> New
  New --> AutoResolved
  New --> Queued
  Queued --> InProgress: claimed
  InProgress --> PendingUser
  PendingUser --> InProgress
  InProgress --> Resolved
  Resolved --> Reopened""", "Ticket lifecycle."),
    d_flow=("""flowchart LR
  REQ["request + trip ctx"] --> CAT["category, priority"] --> Q["queue"]""", "Triage."),
    d_fail=("""flowchart TB
  D["domain read API down"] --> P["ticket created with partial context; refresh later"]""", "Partial context is acceptable."),
    sql="""CREATE TABLE support.tickets (id uuid PRIMARY KEY, requester uuid, role text, category text, trip_id uuid, priority int, state text, assignee uuid,
  sla_due timestamptz, dedupe_key text UNIQUE, created_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 0);""",
    data="Retention 3 years.", api="""POST /v1/support/tickets {category, trip_id?, message} -> 201 {ticket_id, eta}
POST /internal/tickets/claim?queue=FARE -> ticket""",
    mech=[("SKIP LOCKED work queue", "Agents claim the next ticket with `FOR UPDATE SKIP LOCKED ORDER BY priority, sla_due LIMIT 1`, so there is no double assignment and no blocking.")],
    code="""SELECT id FROM support.tickets WHERE state='Queued' AND queue=:q ORDER BY priority, sla_due FOR UPDATE SKIP LOCKED LIMIT 1;""", cx="O(log n).",
    fail=[F("Duplicate submissions", "Dedupe", "None", "Existing ticket", "One ticket")],
    alts=[["Helpdesk SaaS", "Phase I–III", "Fast", "Early"]],
    adrs=[A("Build in-house at Phase IV", "IV", "Deep integration needs.", [("SaaS forever", "Integration limits"), ("In-house", "Chosen")], "Own service.", "Context and automation.", "Build cost.", "N/A")],
    qa=[Q("Operations", "How do you prevent safety-critical tickets from waiting behind fare complaints?", "Triage tags safety keywords and categories, assigning P0 and routing to a dedicated safety queue staffed 24/7 with a 1-minute SLA and paging on breach. Queues never mix P0 with others.", "")],
    tests=[T("Concurrency", "Two agents claim", "Different tickets"), T("Unit", "Safety keyword", "P0 safety queue")],
    evo=["I: SaaS helpdesk", "E: In-app intake with context", "E: Event automations", "R: In-house service", "E: ML triage", "E: Regional queues"],
    ideas={"now": ["Context"], "next": ["Automations"], "adv": ["ML triage"], "rej": ["Email-only support"]})

sub(id="dispute-resolution", comp="support", name="Dispute Resolution", phase="II", cat="Workflow · Money",
    resp="Decide fare and charge disputes (and chargebacks) using trip evidence, apply outcomes through Fare/Payments, and feed results to risk.",
    inp="dispute tickets, chargeback notifications", out="decisions, adjustments/refunds, chargeback representments", deps="Fare, Location history, Pricing audit, Payments, Risk", cons="Support, Finance", own="dispute_decisions",
    problem="Consistent, evidence-based decisions that are fair to riders and drivers.", without="Inconsistent refunds, fraud via disputes.",
    guar=["Every decision references evidence", "Outcome applied via idempotent domain commands", "Chargeback evidence submitted before deadline"], nong=["Customer satisfaction"],
    usecase="Rider disputes a long route. Evidence shows the matched route was 2.1 km longer than the optimal route with no traffic reason, so a partial refund is auto-approved and driver earnings are adjusted per policy.",
    derive="- Evidence bundle assembled automatically (route vs optimal, pricing audit, timeline).\n- Policy rules → recommended outcome → agent confirm or auto-approve below threshold.",
    conc="One open dispute per (trip, type).", consistency="Decision row + outbox commands.", idem="Decision id used as command idempotency key.", order="Chargeback lifecycle follows PSP events.",
    restart="Deadlines tracked by scheduler.", scale="Disputes are about 1% of trips. Evidence collection is the cost (reads from several domains), parallelized per dispute.", arch="EvidenceCollector → PolicyRecommender → decision (auto/agent) → commands (adjust fare, refund, earnings clawback) → risk label.",
    modules=[["EvidenceCollector", "Bundle"], ["PolicyRecommender", "Outcome"], ["DecisionService", "Persist + commands"], ["ChargebackHandler", "Representment"]],
    d_arch=("""flowchart LR
  T["dispute"] --> EC["EvidenceCollector"] --> LH["Location"] & PA["Pricing audit"] & TR["Trip"]
  EC --> PR["PolicyRecommender"] --> DS["DecisionService"] --> FA["Fare adjust"] & RF["Refund"] & RK["Risk label"]""", "Evidence-driven."),
    d_seq=("""sequenceDiagram
  participant S as Support
  participant D as Disputes
  participant F as Fare
  S->>D: open(trip 77, ROUTE)
  D->>D: evidence + recommend −₹45
  D->>F: adjust (key = decision id)
  D-->>S: resolved""", "Auto-approved dispute."),
    d_state=("""stateDiagram-v2
  [*] --> Open
  Open --> EvidenceReady
  EvidenceReady --> Decided
  Decided --> Applied""", "Dispute lifecycle."),
    d_flow=("""flowchart LR
  A["actual route"] --> C["compare optimal"] --> X["excess km"] --> O["outcome"]""", "Route evidence."),
    d_fail=("""flowchart TB
  E["evidence unavailable"] --> M["manual review"]""", "Escalation."),
    sql="CREATE TABLE support.dispute_decisions (id uuid PRIMARY KEY, trip_id uuid NOT NULL, type text NOT NULL, outcome text, amount_minor bigint, evidence jsonb, decided_by text, at timestamptz, UNIQUE(trip_id, type));",
    data="7 years.", api="""POST /internal/disputes {trip_id, type} -> {recommendation}""",
    mech=[("Decision id as idempotency key", "Downstream adjustments and refunds keyed by decision id can't be applied twice.")],
    code="""var ev = evidence.collect(trip); var rec = policy.recommend(ev); if (rec.amount() <= autoLimit) apply(decisions.save(trip, rec, "AUTO"));""", cx="O(1).",
    fail=[F("Double apply", "Idempotency key", "None", "No-op", "Exact")],
    alts=[["Refund on request", "Rejected", "Abuse", "VIP low amounts"]],
    adrs=[A("Auto-approve below threshold with evidence", "III", "Volume.", [("Manual all", "Slow"), ("Auto below limit", "Chosen")], "Threshold.", "Speed.", "Tuning.", "N/A")],
    qa=[Q("Fraud", "Riders dispute every trip hoping for refunds. Defence?", "Track dispute rate and outcomes per rider. Repeated unfounded disputes lower the auto-approval threshold for that rider to zero and feed risk scoring. Evidence-based decisions are consistent regardless of complaint persistence.", "")],
    tests=[T("Idempotency", "Apply twice", "One adjustment")],
    evo=["N: Phase I agents decide manually in helpdesk", "I: Evidence bundles", "E: Auto-approval", "E: Chargeback automation", "E: ML recommendations", "E: Regional"],
    ideas={"now": ["Evidence"], "next": ["Auto"], "adv": ["ML"], "rej": ["Refund without evidence"]})

# ======================================================================= Admin & Policy
comp(id="admin-policy", domain="support", name="Admin, Policy & Manual Intervention", tag="Operations · Control plane", phase="I", kind="Internal application + configuration plane",
     biz="Gives operations teams safe tools to configure cities (products, zones, policies), intervene in live operations, and see what's happening.",
     eng="A control plane: versioned, validated, audited configuration with staged rollout, plus an admin portal that performs interventions only via domain commands.",
     deploy="Admin module in monolith (I); separate admin app + config service (IV); global control plane (VI).", data_own="config documents, config versions, admin audit log.",
     up=["authz", "identity"], down=["product-catalog", "pricing", "cancellation", "geo-index", "dispatch", "global-regions"], ext=[],
     interfaces="Admin UI; config API `GET /config/{namespace}?version`; change events `ConfigPublished`.",
     problem="Operational changes (surge caps, new zones, policies) are as risky as code deploys but made by non-engineers, often under time pressure.",
     fr=["Edit city configs with validation", "Staged rollout and rollback", "Manual interventions (force driver offline, cancel trip, block account)", "Ops dashboards", "Full audit"], nfr=["Config propagation ≤ 60 s", "Rollback ≤ 1 min", "Every change attributable"],
     workload="Low write volume; high read (cached config).", success="Fast, safe ops changes.", failure="Bad config takes down a city; untraceable changes.",
     derive="Config is code-like, so it is versioned, reviewed, validated, rolled out gradually and rolled back. Interventions must respect invariants, so they go through domain commands with reasons.",
     owns=["Config store", "Admin portal", "Audit log"], not_owns=["Config semantics (owning domains validate)"], sync=["Admin actions"], **{"async": ["Config distribution"]},
     boundary_why="A single control plane gives consistent safety mechanisms (validation, staging, audit) for every domain's configuration.",
     hld=("""flowchart LR
  OPS["Ops"] --> AP["Admin portal"]
  AP --> PC["Policy & config management"] --> VS[("versioned config")]
  PC -->|validate| DOM["Domain validators"]
  PC -->|ConfigPublished| SUB["Services (cache)"]
  AP --> MI["Manual intervention"] -->|commands| DOMS["Domain APIs"]
  AP & PC & MI --> AUD["Audit log"]""", "Configuration and interventions both pass through validation, domain APIs and audit."),
     seq=("""sequenceDiagram
  participant O as Ops
  participant P as Config
  participant V as Pricing validator
  participant S as Services
  O->>P: surge cap PUN 2.5→2.0 (draft)
  P->>V: validate
  V-->>P: ok
  O->>P: publish (canary 10%)
  P->>S: ConfigPublished v42 (canary)
  O->>P: promote 100%""", "Staged config change."),
     subdeps=[("manual-intervention", "policy-config")],
     flow="Drafts are validated by domain-provided validators, published to canary scopes, then promoted. Services poll or subscribe and cache with last-known-good. Interventions call domain commands with reason codes.",
     data="`config_documents(namespace, key, version, body, state, author, approver)`, `admin_audit(id, actor, action, target, reason, at, before, after)`.",
     rel=[["Last-known-good", "Services keep last valid config on fetch failure."], ["Rollback", "Previous version republish."]], sec=[["Approval", "Four-eyes for high-impact namespaces."], ["Audit", "Immutable audit log."]],
     adrs=[A("Config as versioned documents with staged rollout", "II", "Config incidents.", [("Direct DB edits", "Rejected"), ("Versioned + staged", "Chosen")], "Control plane.", "Safety.", "Process overhead.", "N/A")],
     qa=[Q("Reliability", "An ops change set surge cap to 0.2 (typo) in a major city. How is damage limited?", "Validation: domain validators enforce sane ranges (cap ≥ 1.0) and reject the change. If a semantically valid but harmful change passes, a canary scope (10% of cells) plus automatic metric guards (conversion drop, completion drop) halt promotion and roll back automatically.", "")],
     impl_order=["policy-config", "manual-intervention"], pkg="""com.atlas.admin
├── config       (ConfigService, Validators, Rollout)
├── intervention (InterventionService)
└── audit        (AdminAudit)""",
     tests=[T("Validation", "Out-of-range value", "Rejected"), T("Rollback", "Promote then rollback", "Previous version live < 1 min")],
     evo=[("I", "Admin pages in monolith", "Config tables", "Audit table", "Pilot"), ("E", "Validation + versions", "—", "—", "Safety"), ("E", "ConfigPublished events", "—", "—", "Distribution"),
          ("R", "Config service + admin app", "Own DB", "Four-eyes", "Many services"), ("E", "Metric-guarded rollout", "—", "Auto rollback", "Scale"), ("R", "Global control plane with regional caches", "—", "Last-known-good", "Global")],
     ideas={"now": ["Audit"], "next": ["Staged rollout"], "adv": ["Policy simulation before publish"], "rej": ["Direct DB edits"]})

sub(id="policy-config", comp="admin-policy", name="Policy & Configuration Management", phase="I", cat="Control plane · Configuration",
    resp="Store versioned configuration documents per namespace and scope, validate them with domain validators, roll them out in stages, and distribute them to services.",
    inp="drafts from admin, validator results", out="published versions, ConfigPublished events, config reads", deps="Domain validators, Authorization", cons="All configurable services", own="config_documents",
    problem="Safe, fast, auditable configuration changes across many services.", without="Config-induced outages.",
    guar=["Only validated versions published", "Monotonic versions per namespace", "Services fall back to last-known-good"], nong=["Semantic correctness beyond validators"],
    usecase="New airport zone fee: draft, validator checks geofence exists, canary at one terminal, then promoted.",
    derive="- Immutable versions + pointer to active version per scope.\n- Distribution: pull with ETag (simple, resilient) plus push notification for speed.",
    conc="Publish = compare-and-set on active pointer.", consistency="Eventual distribution (≤ 60 s).", idem="Publishing the same version twice is a no-op.", order="Monotonic versions; services ignore older.",
    restart="Services boot from local cache file + fetch.", scale="Reads cached; CDN for global (VI).", arch="Documents (JSON + JSON Schema) in PG; validators via gRPC per domain; rollout scopes (city, cell set, percentage); client library with poll + push + disk cache.",
    modules=[["DocumentStore", "Versions"], ["ValidatorRegistry", "Domain validators"], ["Rollout", "Scopes"], ["ClientLib", "Poll/push/cache"]],
    d_arch=("""flowchart LR
  AD["Admin"] --> DS["DocumentStore"] --> VR["ValidatorRegistry"] --> DV["Domain validators"]
  DS --> RO["Rollout"] --> EV["ConfigPublished"]
  CL["ClientLib in services"] -->|poll ETag| DS
  EV --> CL""", "Store, validate, roll out, distribute."),
    d_seq=("""sequenceDiagram
  participant C as ClientLib
  participant S as ConfigService
  loop 30s
    C->>S: GET ns (If-None-Match v41)
    S-->>C: 304 or v42
  end""", "Polling with ETag."),
    d_state=("""stateDiagram-v2
  [*] --> Draft
  Draft --> Validated
  Validated --> Canary
  Canary --> Active
  Canary --> RolledBack
  Active --> Superseded""", "Version lifecycle."),
    d_flow=("""flowchart LR
  D["doc v42"] --> SC["scope: PUN cells 10%"] --> SV["services in scope"]""", "Scoped rollout."),
    d_fail=("""flowchart TB
  F["config service down"] --> L["last-known-good from disk"]""", "Resilient reads."),
    sql="CREATE TABLE admin.config_documents (namespace text, version int, scope jsonb, body jsonb NOT NULL, state text NOT NULL, author uuid, approver uuid, created_at timestamptz, PRIMARY KEY(namespace, version));",
    data="All versions kept.", api="""GET /config/{namespace}  If-None-Match -> 200 {version, body} | 304
event ConfigPublished{namespace, version, scope}""",
    mech=[("Last-known-good caching", "Clients persist the last valid config to disk and use it if the config service is unreachable at boot or runtime, so config outages don't cascade.")],
    code="""public <T> T get(String ns, Class<T> type) { return cache.computeIfAbsent(ns, k -> disk.load(k).orElseThrow()).as(type); }""", cx="O(1) reads.",
    fail=[F("Invalid config", "Validator", "Rejected", "Fix draft", "None"), F("Bad but valid config", "Guard metrics", "Partial impact", "Auto-rollback", "None")],
    alts=[["Feature flag SaaS", "Viable", "Flags/rollouts", "Simple toggles"], ["Git-based config (GitOps)", "Viable", "Review via PRs", "Engineering-owned config"]],
    adrs=[A("Domain-owned validators", "II", "Only domains know semantics.", [("Central schema only", "Shallow"), ("Domain validators", "Chosen")], "gRPC validators.", "Deep validation.", "Coupling at publish.", "N/A")],
    qa=[Q("Global", "In Phase VI, is config global or regional?", "Both. Namespaces are tagged global (product catalog definitions) or regional (city policies). The global control plane stores everything and replicates regional namespaces to regional caches, and regions run on cached config if the global plane is unreachable.", "")],
    tests=[T("Resilience", "Config service down at boot", "Service starts from disk cache")],
    evo=["I: Tables + cache", "E: Versions + validation", "E: Events", "R: Config service + client lib", "E: Guarded rollouts", "R: Global control plane"],
    ideas={"now": ["Versions"], "next": ["Validators"], "adv": ["Simulation"], "rej": ["Unversioned edits"]})

sub(id="manual-intervention", comp="admin-policy", name="Manual Intervention & Admin Audit", phase="I", cat="Operations · Safety valve",
    resp="Give ops staff a small set of powerful, audited actions (force offline, cancel trip, restrict account, pause product in a city) executed through domain commands.",
    inp="admin actions with reason codes", out="domain commands, audit records", deps="Domain APIs, Authorization (JIT roles)", cons="Ops, Safety, Support", own="admin_audit",
    problem="Humans must be able to intervene during incidents without bypassing invariants or leaving no trace.", without="DB hand-edits during incidents.",
    guar=["Every action audited with actor, reason, before/after", "Actions go through domain commands (invariants hold)", "High-impact actions need approval"], nong=["Correctness of human judgment"],
    usecase="Severe flooding: ops pauses all products in 12 cells for 2 hours. Catalog config is scoped with expiry, and the audit records an incident ticket reference.",
    derive="- A whitelist of actions mapped to domain commands.\n- Reason codes + ticket ids required.\n- Bulk actions as jobs with progress.",
    conc="Commands inherit domain concurrency control.", consistency="Domain-consistent.", idem="Action id passed as idempotency key.", order="Bulk jobs process sequentially with checkpoints.",
    restart="Bulk jobs resumable.", scale="Human-initiated, so tens per hour. Bulk actions are chunked jobs to avoid overloading domain APIs.", arch="Admin UI → InterventionService (authz, approvals) → domain command → audit append.",
    modules=[["ActionCatalog", "Allowed actions"], ["Approvals", "Four-eyes"], ["Executor", "Commands, bulk jobs"], ["Audit", "Immutable log"]],
    d_arch=("""flowchart LR
  UI["Admin UI"] --> IS["InterventionService"] --> AZ["Authz + approvals"]
  IS --> EX["Executor"] --> DOM["Domain commands"]
  IS --> AU[("admin_audit")]""", "Audited command execution."),
    d_seq=("""sequenceDiagram
  participant O as Ops
  participant I as Intervention
  participant S as Supply
  O->>I: force offline driver d (reason SAFETY, ticket T)
  I->>I: authz ok
  I->>S: forceOffline(d, action id)
  I->>I: audit append""", "Single action."),
    nostate="Actions are one-shot commands. Bulk job progress is tracked by the job framework.",
    d_flow=("""flowchart LR
  A["action"] --> C["command"] --> R["result"] --> AU["audit(before, after)"]""", "Audit."),
    d_fail=("""flowchart TB
  D["domain API fails"] --> E["error shown, audit records failure"]""", "Failures are audited too."),
    sql="CREATE TABLE admin.admin_audit (id uuid PRIMARY KEY, actor uuid NOT NULL, action text NOT NULL, target text NOT NULL, reason text NOT NULL, ticket text, before jsonb, after jsonb, result text, at timestamptz NOT NULL DEFAULT now());",
    data="Retained 7 years; append-only.", api="""POST /admin/actions {action, target, reason, ticket} -> {result}""",
    mech=[("Allow-listed actions", "A fixed catalog of reviewed actions prevents arbitrary data edits during stressful incidents.")],
    code="""public Result execute(Actor a, AdminAction act) { authz.require(a, act); var r = executor.run(act); audit.append(a, act, r); return r; }""", cx="O(1).",
    fail=[F("Abuse by insider", "Audit + anomaly alerts", "Harm", "Approvals for high-impact", "Traceable")],
    alts=[["DB console access", "Rejected", "No invariants", "Never in production"]],
    adrs=[A("No production DB write access for humans", "II", "Safety.", [("Allow DBA edits", "Rejected"), ("Commands only", "Chosen")], "Break-glass only for DBAs with audit.", "Invariants hold.", "Need many command APIs.", "N/A")],
    qa=[Q("Operations", "What if an action you need isn't in the catalog during an incident?", "Break-glass: time-boxed elevated access with incident id, session recording and a mandatory post-incident review that adds the missing action to the catalog.", "")],
    tests=[T("Security", "Action without reason", "Rejected"), T("Audit", "Every action", "Audit row present")],
    evo=["I: Admin endpoints + audit", "E: Approvals", "U: No change needed", "E: Separate admin app", "E: Bulk jobs", "E: Regional ops scopes"],
    ideas={"now": ["Reason codes"], "next": ["Approvals"], "adv": ["Runbook automation"], "rej": ["DB edits"]})

# ======================================================================= Event Pipeline
comp(id="event-pipeline", domain="analytics", name="Event Pipeline & Data Platform", tag="Data · Platform", phase="I", kind="Platform capability",
     biz="Makes every business and app event available for analytics, reporting, ML and auditing, reliably and with known quality.",
     eng="Collection of client and server events, schema governance, streaming to a lake (open table format), and modeled warehouse tables, batch and streaming.",
     deploy="Nightly DB extracts (I); event logging + batch (II); Kafka → lake (III); warehouse + stream processing (IV–V); regional lakes (VI).", data_own="Lake tables, schemas, warehouse models.",
     up=["messaging"], down=["experimentation", "feature-store", "ml-platform", "data-governance", "tax-reporting"], ext=["Object storage", "Warehouse (BigQuery/Snowflake/Trino)"],
     interfaces="Client SDK `track(event)`; server events via Kafka; schema registry; SQL access to warehouse.",
     problem="Analytics on OLTP replicas breaks at scale and couples schemas. Events must be complete, deduplicated, schema-valid and privacy-compliant.",
     fr=["Client event collection (batched, offline-tolerant)", "Server domain events", "Schema validation", "Lake ingestion", "Warehouse models", "Backfills/replays"], nfr=["Lake freshness < 15 min (IV), < 2 min (V)", "Completeness ≥ 99.9% for business events", "PII tagged and governed"],
     workload="Phase V ≈ 20 TB/month raw.", success="Trusted, fresh data.", failure="Missing or wrong metrics leading to wrong decisions.",
     derive="Producers are many and evolve independently, so a schema registry with compatibility rules. The lake must support upserts and time travel (dedup, GDPR deletes), so an open table format (Iceberg). Business metrics need modeled tables, so a transformation layer (dbt).",
     owns=["Collection", "Schemas", "Lake", "Warehouse models"], not_owns=["Business semantics of events (producers)"], sync=["Collection endpoint ack"], **{"async": ["Everything else"]},
     boundary_why="Analytics reads from events, not OLTP, which decouples schemas and protects production.",
     hld=("""flowchart LR
  APP["Apps SDK"] --> COL["Event collection"] --> K[["Kafka raw topics"]]
  SVC["Services outbox/CDC"] --> K
  SR["Schema registry"] -.-> COL & K
  K --> ING["Lake ingestion (stream → Iceberg)"] --> LAKE[("Lake: Iceberg on object storage")]
  LAKE --> DBT["Transformations (dbt)"] --> WH[("Warehouse models")]
  K --> SP["Stream processing (Flink)"] --> RT[("Real-time tables")]""", "Collection, schema registry, lake, warehouse and stream processing."),
     seq=("""sequenceDiagram
  participant A as App
  participant C as Collector
  participant K as Kafka
  participant I as Ingestion
  A->>C: batch [e1..e50] (event ids)
  C->>C: validate schema, enrich
  C->>K: produce
  C-->>A: ack
  K->>I: consume
  I->>I: MERGE into Iceberg (dedupe by event_id)""", "Client event path."),
     subdeps=[("lake-ingestion", "event-collection")],
     flow="Events are validated against registered schemas at collection, deduplicated during lake merge, transformed into models, and governed by data-quality checks.",
     data="Lake tables partitioned by event date + hour; warehouse star schemas (fact_trips, dim_city...).",
     rel=[["Replay", "Kafka retention 7 days + lake raw tables allow reprocessing."], ["Dedupe", "MERGE on event_id."]], sec=[["PII", "Field-level tags; tokenization of identifiers in analytics zone."], ["Access", "Role-based datasets."]],
     adrs=[A("Iceberg lake + warehouse", "IV", "Scale and GDPR deletes.", [("Warehouse only", "Cost at raw scale"), ("Plain Parquet", "No deletes/upserts"), ("Iceberg", "Chosen")], "Iceberg.", "ACID tables on object storage.", "Ops complexity.", "N/A")],
     qa=[Q("Data quality", "Trip counts in the dashboard differ from finance. Why, and how to prevent?", "Different sources and definitions: analytics counted TripCompleted events (including later-cancelled corrections), and finance counted ledger entries. Fix by defining metrics once in a semantic layer (metric 'completed_trips' = trips with FareFinalized and no reversal), with reconciliation checks between warehouse models and ledger totals daily.", "")],
     impl_order=["event-collection", "lake-ingestion"], pkg="""com.atlas.data
├── collect  (CollectorController, SchemaValidator)
└── ingest   (IcebergSink, Compaction)""",
     tests=[T("Completeness", "Count events produced vs landed", "≥ 99.9%"), T("Schema", "Incompatible schema change", "Rejected by registry")],
     evo=[("I", "Nightly replica extracts", "CSV/warehouse", "—", "Basic BI"), ("E", "Event logging tables + batch", "—", "—", "Product analytics"), ("R", "Kafka → lake", "Iceberg", "Schema registry", "Scale"),
          ("E", "Warehouse models + streaming", "dbt, Flink", "Quality checks", "Many consumers"), ("E", "Real-time tables, tiered storage", "—", "Cost controls", "20 TB/month"), ("E", "Regional lakes + federated queries", "—", "Residency", "Global")],
     ideas={"now": ["Event ids everywhere"], "next": ["Schema registry"], "adv": ["Data mesh ownership"], "rej": ["Analytics on primary DB"]})

sub(id="event-collection", comp="event-pipeline", name="Event Collection & Schema Registry", phase="II", cat="Data · Ingestion",
    resp="Accept client analytics events in batches, validate them against registered schemas, enrich and publish to Kafka; govern schema evolution for all events.",
    inp="client batches, server events, schema submissions", out="validated events on topics; registered schemas", deps="Kafka, Schema registry", cons="Lake ingestion, Stream processing", own="schemas, raw topics",
    problem="Hundreds of event types from many app versions must arrive valid, deduplicable and evolvable.", without="Broken dashboards from silent schema changes.",
    guar=["Every event has event_id, schema id/version, client timestamp, server receive time", "Incompatible schema changes rejected", "Invalid events quarantined, not dropped"], nong=["Client delivery (offline clients may lose events after cap)"],
    usecase="App v5.2 renames a field. The registry rejects it as backward-incompatible, so the team adds a new field and deprecates the old one.",
    derive="- Client batches with retry, so events carry ids for dedupe.\n- Compatibility mode BACKWARD per subject.\n- Quarantine topic for invalid events.",
    conc="Stateless collectors.", consistency="At-least-once to Kafka.", idem="event_id; dedupe downstream.", order="Not guaranteed; consumers use timestamps.",
    restart="Stateless collectors. Unacknowledged client batches are retried by the SDK with the same event ids.", scale="Horizontal; Kafka partitions by event type/user.", arch="HTTP collector (batches ≤ 500) → validate (cached schemas) → enrich (geo from IP, app version) → produce (acks=all) → 200. Invalid go to the quarantine topic.",
    modules=[["Collector", "Batch endpoint"], ["Validator", "Schema checks"], ["Enricher", "Server metadata"], ["Registry", "Compatibility enforcement"]],
    d_arch=("""flowchart LR
  APP["SDK"] --> CO["Collector"] --> VA["Validator"] --> SR[("Schema registry")]
  VA --> EN["Enricher"] --> K[["raw.events"]]
  VA -->|invalid| QT[["quarantine"]]""", "Validate at the edge."),
    d_seq=("""sequenceDiagram
  participant A as App
  participant C as Collector
  participant R as Registry
  participant K as Kafka
  A->>C: POST /events batch
  C->>R: schema (cached)
  C->>K: produce valid
  C->>K: quarantine invalid
  C-->>A: 200 {accepted, rejected}""", "Collection."),
    nostate="Events are immutable records.",
    d_flow=("""flowchart LR
  E["event"] --> V["valid?"] -->|yes| R["raw"]
  V -->|no| Q["quarantine"]""", "Routing."),
    d_fail=("""flowchart TB
  K["Kafka down"] --> C["client retries with backoff; local cap 10K events"]""", "Client buffering."),
    sql="-- Registry stores Avro/Protobuf schemas by subject+version (Confluent-compatible API).",
    data="Raw topics 7 days; quarantine 30 days.", api="""POST /v1/events {events:[{event_id, name, schema_version, ts, props:{…}}]} -> 200 {accepted:48, rejected:2}""",
    mech=[("Backward compatibility", "New schema versions can read data written with older versions (only optional fields added, no renames), so consumers upgrade at their own pace.")],
    code="""for (Event e : batch) { if (validator.valid(e)) producer.send(raw(e)); else producer.send(quarantine(e)); }""", cx="O(batch).",
    fail=[F("Bad app release spams invalid events", "Quarantine spike", "Data gap", "Fix forward + backfill from quarantine", "Recoverable")],
    alts=[["Third-party analytics SDK", "Phase II option", "Fast", "Early"]],
    adrs=[A("Validate at collection", "II", "Garbage downstream.", [("Validate in lake", "Late"), ("At collection", "Chosen")], "Edge validation.", "Clean data.", "Collector depends on registry.", "N/A")],
    qa=[Q("Privacy", "How do you stop PII from leaking into analytics events?", "Schemas declare field classifications (PII, sensitive). The collector rejects undeclared fields, the SDK has no free-text fields, and identifiers are pseudonymized (keyed hash) in the analytics zone. CI linting flags PII-looking field names.", "")],
    tests=[T("Schema", "Breaking change", "Rejected"), T("Load", "50K events/s", "Stable")],
    evo=["N: Phase I uses DB extracts for analytics", "I: Collector + event table", "R: Kafka + registry", "E: Enrichment, quarantine", "E: Edge collectors", "E: Regional collectors"],
    ideas={"now": ["event_id"], "next": ["Registry"], "adv": ["Data contracts"], "rej": ["Free-text props"]})

sub(id="lake-ingestion", comp="event-pipeline", name="Lake Ingestion & Warehouse Modeling", phase="III", cat="Data · Storage",
    resp="Land events from Kafka into Iceberg tables with dedupe and compaction, and build modeled warehouse tables and metrics.",
    inp="Kafka topics", out="raw and modeled tables", deps="Object storage, Iceberg catalog, dbt, query engine", cons="Analysts, ML, Finance", own="lake tables, models",
    problem="Turn streams into queryable, correct, cost-efficient tables supporting deletes and replays.", without="Unqueryable data swamp.",
    guar=["Exactly one row per event_id in raw tables (MERGE dedupe)", "Freshness SLO per table", "Erasure deletes applied within 30 days"], nong=["Real-time (seconds) analytics (stream tables do that)"],
    usecase="Daily trips dashboard: fact_trips built from TripCompleted + FareFinalized + cancellations, with completeness checks vs Trip service counts.",
    derive="- Streaming writer (Flink/Spark) commits files every N minutes.\n- MERGE on event_id dedupes.\n- Compaction merges small files.\n- dbt models are versioned SQL.",
    conc="Iceberg optimistic commits; single writer per table partition.", consistency="Snapshot isolation for readers.", idem="MERGE by event_id.", order="Partitioned by event time; late events land in older partitions.",
    restart="Checkpointed consumer offsets with Iceberg commits.", scale="Object storage scales; compaction jobs scale by partition.", arch="Flink → Iceberg (5-min commits) → compaction → dbt models hourly/daily → semantic layer metrics.",
    modules=[["StreamWriter", "Kafka → Iceberg"], ["Compactor", "Small-file merges"], ["Models", "dbt"], ["ErasureApplier", "Row-level deletes"]],
    d_arch=("""flowchart LR
  K[["topics"]] --> SW["StreamWriter"] --> RAW[("raw Iceberg")] --> DBT["dbt models"] --> MART[("marts")]
  CP["Compactor"] --> RAW
  ER["ErasureApplier"] --> RAW & MART""", "Raw to marts."),
    d_seq=("""sequenceDiagram
  participant K as Kafka
  participant W as Writer
  participant I as Iceberg
  K->>W: events
  W->>I: commit snapshot (5 min) with offsets
  Note over I: readers see consistent snapshot""", "Commits."),
    nostate="Tables are versioned by snapshots, not entity lifecycles.",
    d_flow=("""flowchart LR
  E["events"] --> R["raw"] --> S["staging"] --> F["facts/dims"] --> M["metrics"]""", "Layers."),
    d_fail=("""flowchart TB
  W["writer crash"] --> RC["restart from committed offsets; no dup thanks to MERGE"]""", "Recovery."),
    sql="""MERGE INTO lake.raw_trip_events t USING staged s ON t.event_id = s.event_id
WHEN NOT MATCHED THEN INSERT *;""",
    data="Raw 2 years; marts per need; erasure applied.", api="SQL (Trino/warehouse); semantic layer metric definitions",
    mech=[("Iceberg snapshots", "Each commit creates an immutable snapshot, and readers query a snapshot, so writes never expose partial data. Time travel supports reproducible ML training sets.")],
    code="-- dbt model fact_trips.sql\nselect t.trip_id, t.city, f.amount_minor, t.started_at from {{ ref('stg_trips') }} t join {{ ref('stg_fares') }} f using (trip_id)", cx="Batch.",
    fail=[F("Small files explosion", "File count metric", "Slow queries", "Compaction", "None")],
    alts=[["Delta Lake / Hudi", "Viable", "Similar", "Ecosystem choice"]],
    adrs=[A("MERGE dedupe", "III", "At-least-once inputs.", [("Append and dedupe at query", "Costly"), ("MERGE", "Chosen")], "MERGE.", "Clean raw.", "Write cost.", "N/A")],
    qa=[Q("Privacy", "How is GDPR erasure done in an immutable lake?", "Iceberg supports row-level deletes (delete files / copy-on-write). The erasure pipeline issues deletes by pseudonymous user key across tables, then expires old snapshots after the retention window so deleted data is physically removed.", "")],
    tests=[T("Idempotency", "Replay topic", "No duplicates"), T("Freshness", "SLO", "< 15 min")],
    evo=["N: No lake in Phase I", "N: Batch extracts into the warehouse", "I: Kafka → Iceberg", "E: dbt models + semantic layer", "E: Streaming tables, compaction tuning", "E: Regional lakes"],
    ideas={"now": ["n/a"], "next": ["Semantic layer"], "adv": ["Lakehouse ML"], "rej": ["Raw JSON dumps without schema"]})

# ======================================================================= Experimentation
comp(id="experimentation", domain="analytics", name="Experimentation Platform", tag="Data · Decision science", phase="II", kind="Platform capability",
     biz="Lets teams test changes (UI, pricing, dispatch) on a subset of users or markets and decide based on measured impact.",
     eng="Deterministic assignment (users, sessions or time/space units), exposure logging and statistical analysis, including switchback designs for marketplace interference.",
     deploy="Library + service (II); analysis on warehouse (III+).", data_own="experiments, assignments config, exposure logs, results.",
     up=["event-pipeline"], down=["pricing", "dispatch", "promotions", "ml-platform"], ext=[],
     interfaces="`variant(experiment, unit) → variant` (in-process SDK); exposure events; results UI.",
     problem="Marketplace experiments interfere (treated riders take drivers from control riders), so naive A/B tests are biased. Assignment must be fast and consistent.",
     fr=["Define experiments with units and allocation", "Deterministic assignment", "Exposure logging", "Analysis with guardrail metrics", "Switchback and geo experiments"], nfr=["Assignment < 1 ms in-process", "Consistent assignment across services"],
     workload="Assignment on every relevant request.", success="Trusted decisions.", failure="Wrong conclusions from biased designs.",
     derive="Assignment = hash(experiment salt, unit id) mod 10,000, which is stateless and consistent. Interference requires choosing the unit (rider vs city-time-slice).",
     owns=["Experiment definitions", "Assignment", "Analysis"], not_owns=["Product logic per variant"], sync=["Assignment (local)"], **{"async": ["Exposure logs", "Analysis jobs"]},
     boundary_why="A shared platform ensures consistent statistics and avoids each team building biased tooling.",
     hld=("""flowchart LR
  CFG["Experiment config"] --> SDK["Assignment SDK (in services)"]
  SDK -->|exposure| K[["exposures"]] --> LAKE[("lake")]
  LAKE --> AN["Analysis engine"] --> RES["Results + guardrails"]""", "Config to SDK, exposure to analysis."),
     seq=("""sequenceDiagram
  participant P as Pricing
  participant S as SDK
  participant K as Kafka
  P->>S: variant(surge_curve_v2, city:PUN:slot:14)
  S-->>P: treatment
  S->>K: exposure""", "Switchback assignment."),
     subdeps=[("experiment-analysis", "experiment-assignment")],
     flow="Configs are distributed to the SDK. Assignment is a pure hash. Exposures are logged on use and joined with metrics in the warehouse for analysis.",
     data="`experiments(id, salt, unit_type, allocation, variants, status)`; exposures in lake.",
     rel=[["Fallback", "Config unavailable → control variant."]], sec=[["Ethics", "Pricing experiments reviewed; no protected-attribute targeting."]],
     adrs=[A("Hash-based stateless assignment", "II", "Speed and consistency.", [("Stored assignments", "Lookup cost"), ("Hashing", "Chosen")], "Hash.", "Consistent.", "Re-salting changes groups.", "N/A")],
     qa=[Q("Statistics", "Why can't you A/B test a new dispatch algorithm by rider?", "Treatment and control riders share the same drivers. If treatment grabs better drivers, control gets worse ones, which inflates the measured effect. The fix is switchback: alternate the algorithm for an entire city or zone in time slices (e.g. 30 min), randomizing slices, and analyse at slice level with carryover buffers.", "")],
     impl_order=["experiment-assignment", "experiment-analysis"], pkg="""com.atlas.exp
├── sdk      (Assigner, ConfigCache, ExposureLogger)
└── analysis (Jobs, Stats)""",
     tests=[T("Unit", "Same unit", "Same variant across services"), T("Statistics", "A/A test", "No significant difference at expected rate")],
     evo=[("N", "No experiments in pilot", "—", "—", "—"), ("I", "SDK + simple A/B", "Config table", "—", "Product iteration"), ("E", "Warehouse analysis", "Lake", "—", "Data"),
          ("E", "Switchbacks for marketplace", "—", "Guardrails", "Dispatch/pricing tests"), ("E", "Variance reduction (CUPED)", "—", "—", "Sensitivity"), ("E", "Regional experiments", "—", "—", "Global")],
     ideas={"now": ["Hash assignment"], "next": ["Switchbacks"], "adv": ["Bandits"], "rej": ["Rider-level dispatch A/B"]})

sub(id="experiment-assignment", comp="experimentation", name="Experiment Assignment & Exposure", phase="II", cat="Data · Randomization",
    resp="Assign units (user, session, city-time-slice) to variants deterministically and log exposures when a variant actually affects behaviour.",
    inp="experiment configs, unit ids", out="variant, exposure events", deps="Config distribution, Kafka", cons="All experimenting services", own="experiment configs",
    problem="Consistent, fast, unbiased assignment across many services.", without="Inconsistent experiences and biased results.",
    guar=["Same unit → same variant for an experiment's lifetime", "Exposure logged once per unit per experiment per day", "Mutually exclusive layers respected"], nong=["Analysis validity (design responsibility)"],
    usecase="Experiment 'new_pickup_ui' 50/50 by rider. Rider r1 hashes to bucket 3,812 → treatment on iOS and Android consistently.",
    derive="- bucket = murmur3(salt + unit) mod 10,000.\n- Layers: experiments in the same layer use disjoint bucket ranges.\n- Switchback unit = city + floor(time/slot).",
    conc="Pure function with immutable config snapshots, so concurrent calls share nothing mutable.", consistency="Config versions; assignments stable unless salt changes.", idem="Exposure dedupe per (exp, unit, day) in SDK cache + downstream.", order="Exposures are independent facts with timestamps; analysis doesn't depend on arrival order.",
    restart="Config from cache.", scale="CPU-only hashing, nanoseconds per call. Exposure logging is batched and sampled for very hot paths.", arch="SDK in each service with config cache; `variant()` is a pure function; exposure logger batches to Kafka.",
    modules=[["Assigner", "Hash buckets"], ["Layers", "Mutual exclusion"], ["ExposureLogger", "Batched, deduped"]],
    d_arch=("""flowchart LR
  CFG["config"] --> AS["Assigner"] --> V["variant"]
  AS --> EL["ExposureLogger"] --> K[["exposures"]]""", "SDK internals."),
    d_seq=("""sequenceDiagram
  participant S as Service
  participant A as Assigner
  S->>A: variant(exp, rider r1)
  A->>A: murmur3(salt+r1)%10000=3812
  A-->>S: treatment""", "Assignment."),
    nostate="Pure function of config and unit id.",
    d_flow=("""flowchart LR
  U["unit"] --> H["hash"] --> B["bucket"] --> V["variant range"]""", "Hashing."),
    d_fail=("""flowchart TB
  C["config missing"] --> CTRL["control variant"]""", "Safe default."),
    sql="CREATE TABLE exp.experiments (id text PRIMARY KEY, salt text NOT NULL, unit_type text NOT NULL, layer text, ranges jsonb NOT NULL, status text NOT NULL, starts_at timestamptz, ends_at timestamptz);",
    data="Configs retained.", api="""String variant(String experiment, String unitId)  // logs exposure lazily""",
    mech=[("Salted hashing", "Each experiment's salt decorrelates bucketing across experiments, so being in treatment for one doesn't predict another.")],
    code="""int bucket = Math.floorMod(Hashing.murmur3_32_fixed().hashString(exp.salt() + unitId, UTF_8).asInt(), 10_000);
return exp.ranges().stream().filter(r -> r.contains(bucket)).map(Range::variant).findFirst().orElse("control");""", cx="O(variants).",
    fail=[F("Salt changed mid-test", "Config diff", "Reshuffle", "Prevent salt edits on running tests", "N/A")],
    alts=[["Vendor (LaunchDarkly/Statsig)", "Viable", "Fast", "Product UI experiments"]],
    adrs=[A("Exposure logged on use", "II", "Dilution.", [("Log on assignment", "Dilutes effects"), ("On use", "Chosen")], "On use.", "Sensitive analysis.", "SDK discipline.", "N/A")],
    qa=[Q("Statistics", "What is sample ratio mismatch and how is it detected?", "If a 50/50 test shows 52/48 exposures with significance (chi-square), something biases exposure (bugs, crashes in one variant). Automated SRM checks block result readouts until resolved.", "")],
    tests=[T("Unit", "Distribution of buckets", "Uniform (chi-square)"), T("Unit", "Same unit across processes", "Same variant")],
    evo=["N: No experiments in pilot", "I: SDK", "E: Exposure stream", "E: Switchback units", "E: Layers at scale", "E: Regional"],
    ideas={"now": ["SRM checks"], "next": ["Layers"], "adv": ["Bandits"], "rej": ["Random() per request"]})

sub(id="experiment-analysis", comp="experimentation", name="Experiment Analysis & Guardrails", phase="III", cat="Data · Statistics",
    resp="Compute treatment effects with confidence intervals for primary and guardrail metrics, with variance reduction and design-appropriate estimators.",
    inp="exposures, metric events", out="results, guardrail alerts", deps="Lake/warehouse", cons="Product teams, Pricing, Dispatch", own="results",
    problem="Correct inference in a two-sided marketplace.", without="Shipping harmful changes.",
    guar=["SRM checked", "Guardrails (cancellations, wait time, driver earnings) always reported", "Design-aware variance (clustered SEs for switchbacks)"], nong=["Causal truth beyond design"],
    usecase="Surge curve v2 switchback over 4 weeks: completed trips +1.2% (CI 0.4–2.0), rider wait −4%, driver earnings/hour +0.8%. Ship.",
    derive="- Unit-level aggregation then difference in means.\n- CUPED uses pre-period covariates to reduce variance.\n- Switchbacks: cluster by slice.",
    conc="One analysis job per experiment per day, scheduled by the orchestrator with a lock.", consistency="Snapshot-based (Iceberg snapshot id recorded).", idem="Re-running the same snapshot gives the same result.", order="Not applicable: batch over a fixed snapshot.",
    restart="Jobs are idempotent over a pinned snapshot, so a failed run is simply re-run.", scale="Warehouse compute.", arch="Daily jobs per experiment: join exposures (first exposure time) with metrics after exposure, aggregate per unit, estimate effects, write results.",
    modules=[["MetricLibrary", "Semantic definitions"], ["Estimators", "t-test, CUPED, clustered"], ["Guardrails", "Auto-alerts"], ["SrmCheck", "Chi-square"]],
    d_arch=("""flowchart LR
  EXP["exposures"] --> J["join"] --> AGG["unit aggregates"] --> EST["estimators"] --> RES["results"]
  MET["metrics"] --> J
  RES --> GR["guardrails"]""", "Analysis pipeline."),
    d_seq=("""sequenceDiagram
  participant J as Job
  participant W as Warehouse
  J->>W: unit-level aggregates
  J->>J: SRM check, CUPED, CI
  J-->>J: write results""", "Daily run."),
    nostate="Batch computation.",
    d_flow=("""flowchart LR
  Y["metric"] --> C["Y − θ(X − mean X)"] --> D["diff in means"]""", "CUPED."),
    d_fail=("""flowchart TB
  SRM["SRM detected"] --> B["block readout"]""", "Validity gate."),
    sql="""SELECT variant, count(*) n, avg(trips) m, var_samp(trips) v FROM unit_metrics WHERE exp_id=:e GROUP BY variant;""",
    data="Results retained.", api="Results UI + API",
    mech=[("CUPED", "Adjust each unit's metric by θ·(pre-period metric − its mean), where θ = cov(Y,X)/var(X). This reduces variance without bias when X is unaffected by treatment.")],
    code="""double theta = cov(y, x) / var(x); double[] adj = IntStream.range(0, y.length).mapToDouble(i -> y[i] - theta * (x[i] - mean(x))).toArray();""", cx="O(units).",
    fail=[F("Peeking", "Repeated looks", "False positives", "Sequential testing", "N/A")],
    alts=[["Bayesian analysis", "Viable", "Intuitive", "Team preference"]],
    adrs=[A("Guardrails mandatory", "III", "Harm.", [("Optional", "Risky"), ("Mandatory", "Chosen")], "Always reported.", "Safety.", "More metrics.", "N/A")],
    qa=[Q("Statistics", "How do you handle novelty effects in UI experiments?", "Plot the effect by days since first exposure, run long enough to see stabilization (≥ 2 weeks), and use holdbacks after launch to measure long-term effect.", "")],
    tests=[T("Statistics", "Synthetic known effect", "CI covers truth ~95%")],
    evo=["N: No experiments in pilot", "N: Simple dashboards", "I: Warehouse jobs", "E: Switchback estimators", "E: CUPED, sequential", "U: No change needed"],
    ideas={"now": ["n/a"], "next": ["CUPED"], "adv": ["Synthetic control for geo tests"], "rej": ["Peeking without correction"]})

# ======================================================================= Data Governance
comp(id="data-governance", domain="analytics", name="Data Governance & Quality", tag="Data · Trust", phase="III", kind="Platform capability",
     biz="Ensures data used for decisions, finance and ML is accurate, documented, access-controlled and compliant.",
     eng="Automated data-quality checks, a catalog with lineage and ownership, classification of sensitive fields, and access policies.",
     deploy="Checks in pipelines (III); catalog + lineage service (IV).", data_own="quality rules/results, catalog metadata, classifications.",
     up=["event-pipeline", "ledger"], down=["privacy", "ml-platform"], ext=["Catalog tool (DataHub/OpenMetadata)"],
     interfaces="Quality checks as code; catalog UI/API; lineage from dbt/Flink metadata.",
     problem="As datasets multiply, nobody knows which table is correct, who owns it, or whether PII is inside.",
     fr=["Freshness/volume/schema/value checks", "Ownership and docs", "Lineage", "PII classification", "Access policies"], nfr=["Critical tables checked every load", "Alerts routed to owners"],
     workload="Thousands of tables at Phase V.", success="Trusted data with known owners.", failure="Wrong metrics; PII leaks.",
     derive="Quality must be checked where data is produced (pipelines), so checks as code. Lineage is derivable from transformation code. Classification flows from schemas.",
     owns=["Quality checks", "Catalog", "Classifications"], not_owns=["Data contents"], sync=["Catalog queries"], **{"async": ["Checks", "Lineage extraction"]},
     boundary_why="Governance is cross-cutting and is best enforced as tooling in pipelines rather than manual review.",
     hld=("""flowchart LR
  PIPE["Pipelines (dbt/Flink)"] --> DQ["Data quality checks"] --> AL["Owner alerts"]
  PIPE -->|metadata| CAT["Catalog & lineage"]
  SR["Schema classifications"] --> CAT
  CAT --> POL["Access policies"]""", "Checks and catalog fed from pipelines."),
     seq=("""sequenceDiagram
  participant P as Pipeline
  participant Q as DQ
  participant O as Owner
  P->>Q: run checks fact_trips
  Q-->>P: row count −40% vs 7-day avg
  Q->>O: alert + block downstream""", "Circuit-breaking bad data."),
     subdeps=[("catalog-lineage", "data-quality")],
     flow="Checks run per load and can block downstream models. The catalog aggregates ownership, docs, lineage and classifications.",
     data="`dq_results(table, check, status, value, at)`, catalog metadata store.",
     rel=[["Blocking", "Critical checks block publication of downstream tables."]], sec=[["Classification", "PII columns tagged; masked by default."]],
     adrs=[A("Checks as code in pipelines", "III", "Scale.", [("Manual QA", "Unscalable"), ("Code", "Chosen")], "dbt tests / Great Expectations.", "Automated.", "Maintenance.", "N/A")],
     qa=[Q("Data quality", "Which checks matter most for a revenue table?", "Freshness (latest partition age), completeness (row count vs trips service), uniqueness (trip_id), reconciliation (Σ revenue vs ledger), and value ranges (no negative fares). Critical ones block downstream publication.", "")],
     impl_order=["data-quality", "catalog-lineage"], pkg="""data/quality (dbt tests, expectations)
data/catalog (ingestion recipes)""",
     tests=[T("Integration", "Inject duplicate trip ids", "Check fails, downstream blocked")],
     evo=[("N", "Not needed in pilot", "—", "—", "—"), ("N", "Ad-hoc checks", "—", "—", "—"), ("I", "Checks in pipelines", "—", "Blocking", "Lake"), ("E", "Catalog + lineage", "—", "Access policies", "Many tables"), ("E", "Anomaly-detection checks", "—", "—", "Scale"), ("E", "Regional catalogs", "—", "Residency", "Global")],
     ideas={"now": ["Ownership"], "next": ["Lineage"], "adv": ["Data contracts enforced in CI"], "rej": ["Unowned tables"]})

sub(id="data-quality", comp="data-governance", name="Data Quality Checks", phase="III", cat="Data · Validation",
    resp="Run declarative checks on every critical dataset load and block or alert on failures.",
    inp="tables after load", out="check results, blocks, alerts", deps="Warehouse, Orchestrator", cons="Data owners, Pipelines", own="dq_results",
    problem="Detect bad data before it reaches dashboards and models.", without="Silent wrong decisions.",
    guar=["Critical checks run every load", "Failures alert owners and block dependents"], nong=["Detecting all semantic errors"],
    usecase="fact_trips load has 0 rows for Pune (upstream bug). The volume anomaly check fails, the dashboard refresh is blocked and the owner is paged.",
    derive="- Checks types: schema, freshness, volume, uniqueness, referential, ranges, reconciliation.\n- Orchestrator dependency gating.",
    conc="Checks for a load run as orchestrator tasks. Concurrent loads of the same table are prevented by the DAG.", consistency="Checks run on a specific snapshot.", idem="Same snapshot gives same results.", order="Downstream waits on upstream checks.",
    restart="Checks are stateless queries and are re-run for the same snapshot after failure.", scale="Warehouse compute.", arch="dbt tests + custom anomaly checks in the orchestrator DAG, with results stored and alerts routed via catalog ownership.",
    modules=[["CheckLibrary", "Reusable checks"], ["Runner", "Orchestrator tasks"], ["Gate", "Block dependents"], ["Alerting", "Owner routing"]],
    d_arch=("""flowchart LR
  L["load"] --> R["Runner"] --> W[("warehouse")]
  R --> G["Gate"] --> D["downstream tasks"]
  R --> A["Alerts"]""", "Gate in the DAG."),
    d_seq=("""sequenceDiagram
  participant O as Orchestrator
  participant R as Runner
  O->>R: run checks(fact_trips, snapshot 991)
  R-->>O: fail (volume)
  O->>O: skip downstream; alert""", "Gating."),
    nostate="Results are per run.",
    d_flow=("""flowchart LR
  T["table"] --> C["checks"] --> RS[("dq_results")]""", "Results."),
    d_fail=("""flowchart TB
  F["flaky check"] --> T["tune thresholds; severity levels"]""", "Severity management."),
    sql="""-- uniqueness
SELECT trip_id, count(*) FROM marts.fact_trips GROUP BY trip_id HAVING count(*) > 1;""",
    data="Results 1 year.", api="dbt test definitions; results API",
    mech=[("Volume anomaly detection", "Compare row count to a seasonal baseline (same weekday, last 4 weeks) and flag |z| > 3.")],
    code="""double z = (today - mean(baseline)) / sd(baseline); if (Math.abs(z) > 3) fail("VOLUME_ANOMALY");""", cx="O(1) per check.",
    fail=[F("Check infra down", "Runner errors", "Unknown quality", "Block critical by default", "Safe")],
    alts=[["Great Expectations", "Viable", "Rich", "Python stack"]],
    adrs=[A("Block on critical failures", "III", "Bad data spreads.", [("Alert only", "Spreads"), ("Block", "Chosen")], "Block.", "Contained.", "Delays.", "N/A")],
    qa=[Q("Operations", "How do you avoid alert fatigue from data checks?", "Severity tiers (block, warn, info), ownership routing, anomaly thresholds tuned per table, and weekly review of noisy checks with an SLO on false alerts.", "")],
    tests=[T("Integration", "Inject anomaly", "Blocked")],
    evo=["N: Not needed in pilot", "N: Manual dashboard sanity checks", "I: dbt tests", "E: Anomaly checks", "E: Contract checks in CI", "U: No change needed"],
    ideas={"now": ["n/a"], "next": ["Anomaly checks"], "adv": ["Data contracts"], "rej": ["No checks"]})

sub(id="catalog-lineage", comp="data-governance", name="Data Catalog, Lineage & Classification", phase="IV", cat="Data · Metadata",
    resp="Document datasets with owners and descriptions, extract lineage from pipelines, and classify sensitive fields to drive access policies and erasure.",
    inp="dbt manifests, Flink job metadata, schema classifications", out="catalog entries, lineage graph, policy tags", deps="Catalog tool", cons="Analysts, Privacy, Security", own="catalog metadata",
    problem="Know what data exists, where it came from and whether it's sensitive.", without="Can't do erasure or impact analysis.",
    guar=["Every production dataset has an owner", "PII columns tagged and propagated through lineage"], nong=["Perfect lineage for ad-hoc notebooks"],
    usecase="Privacy asks 'where does rider phone number flow?'. Lineage shows identity → events (hashed) → marts, so the erasure pipeline knows every table to delete from.",
    derive="- Lineage from code (dbt manifest).\n- Tags propagate along lineage edges (a derived column from PII is PII unless transformed by an approved function).",
    conc="Metadata ingestion jobs.", consistency="Eventual (daily).", idem="Ingestion upserts.", order="Upserts keyed by dataset URN, so the latest ingestion run wins.",
    restart="Ingestion recipes are re-runnable and the catalog converges on the next run.", scale="Metadata volume (thousands of datasets) is small, and ingestion runs incrementally per source.", arch="DataHub/OpenMetadata with ingestion recipes for dbt, Kafka, Iceberg and PostgreSQL, plus tag propagation rules.",
    modules=[["Ingestion", "Recipes"], ["Lineage", "Graph"], ["Tagging", "Classification propagation"]],
    d_arch=("""flowchart LR
  DBT["dbt manifest"] & K["Kafka schemas"] & PG["PG schemas"] --> ING["Ingestion"] --> CAT[("catalog")]
  CAT --> LIN["Lineage graph"] --> TAG["Tag propagation"]""", "Metadata ingestion."),
    d_seq=("""sequenceDiagram
  participant J as Ingestion job
  participant C as Catalog
  J->>C: upsert datasets + edges
  C->>C: propagate PII tags""", "Daily ingestion."),
    nostate="Metadata records.",
    d_flow=("""flowchart LR
  PII["identity.phone (PII)"] --> EV["events.phone_hash (pseudonymous)"] --> M["marts.rider_dim (pseudonymous)"]""", "Tag propagation."),
    d_fail=("""flowchart TB
  M["missing owner"] --> B["CI blocks new dataset"]""", "Ownership enforcement."),
    sql="-- Catalog tool's own store; classification tags in schema registry and dbt meta.",
    data="Metadata only.", api="Catalog UI / GraphQL",
    mech=[("Tag propagation along lineage", "A downstream column inherits sensitivity unless the transformation is on an approved list (hashing, aggregation with k ≥ 20).")],
    code="# dbt meta\ncolumns:\n  - name: phone_hash\n    meta: {classification: pseudonymous, source: identity.phone}", cx="Metadata.",
    fail=[F("Untracked notebook copies", "Scans", "Shadow data", "Restrict exports", "N/A")],
    alts=[["Spreadsheet catalog", "Rejected", "Stale", "Never"]],
    adrs=[A("Catalog at Phase IV", "IV", "Dataset count.", [("Earlier", "Overhead"), ("IV", "Chosen")], "Adopt.", "Discoverability.", "Tool ops.", "N/A")],
    qa=[Q("Privacy", "How does lineage help with erasure?", "The erasure orchestrator queries the catalog for all datasets containing user-linked identifiers (directly or derived) and their key columns, generating per-dataset delete tasks. New datasets with PII tags are automatically included.", "")],
    tests=[T("Governance", "New PII column without tag", "CI fails")],
    evo=["N: Not needed in pilot", "N: Not needed", "N: Checks only", "I: Catalog + lineage", "E: Tag-driven access", "E: Regional"],
    ideas={"now": ["n/a"], "next": ["Tag-driven masking"], "adv": ["Automated PII discovery"], "rej": ["Manual catalogs"]})
