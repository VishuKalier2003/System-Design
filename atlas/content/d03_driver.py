from model import comp, sub, A, Q, F, T

# ======================================================================= Driver Onboarding
comp(id="driver-onboarding", domain="driver", name="Driver Onboarding & Verification", tag="Supply · Compliance", phase="I", kind="Logical component → deployable service (Phase IV)",
     biz="Turns an applicant into a legally permitted, verified driver: application, documents, background check, vehicle, training, approval.",
     eng="A long-running, multi-step, partially human and vendor-driven workflow with per-city regulatory rules and document expiry that must later gate who can go online.",
     deploy="Module in monolith (Phase I); runs on workflow engine (Phase III); service with own DB (Phase IV).",
     data_own="driver_applications, driver_documents, background_checks, driver_profiles (licence, eligibility snapshot).",
     up=["identity", "maps-gateway", "notifications", "workflow"], down=["driver-supply", "fleet-vehicle", "driver-earnings", "support"], ext=["Background-check vendors (Checkr etc.)", "OCR / document AI", "Government licence registries"],
     interfaces="REST `/v1/driver-applications`, `/v1/driver-documents`; vendor webhooks; event `DriverApproved`, `DriverEligibilityChanged`, `DocumentExpiring`.",
     problem="Cities legally require verified licences, insurance, vehicle inspections and background checks. Vendors take hours to days. Documents expire. Rules differ per city. A driver who is not eligible must never go online.",
     fr=["Multi-step application with resumable progress", "Upload, OCR and verify documents", "Run background checks via vendor with consent", "Per-city requirement sets", "Approve/reject with reasons", "Track expiry and re-verification"],
     nfr=["Application step save p95 < 300 ms", "No approved driver with expired mandatory document", "Workflow survives restarts and vendor delays of days", "PII (licence, SSN) encrypted and access-audited"],
     workload="Phase I: ≈10 applications/day. Phase V: ≈20K/day with 5× seasonal spikes.", success="Fast approvals for legitimate applicants; zero ineligible drivers online.", failure="Ineligible driver online (regulatory + safety failure); applicants stuck for weeks.",
     derive="The process has waiting states (vendor, human review) that last days, so it needs a durable state machine, not request threads. Requirements vary by city and change over time, so they are data (requirement sets with versions), not code. Eligibility must be computed from current document validity and pushed to the supply gate, and Driver Supply must not recompute it.",
     owns=["Application state", "Documents and verification outcomes", "Background-check results", "Eligibility computation"], not_owns=["Online/offline state (Driver Supply)", "Vehicle registry (Fleet & Vehicle)", "Payout bank details (Earnings)"],
     sync=["Save step", "Upload document", "Get status"], **{"async": ["OCR/verification", "Background-check vendor calls and webhooks", "Expiry scanning", "Eligibility change events"]},
     boundary_why="Onboarding decides *whether a person may drive*. Supply decides *whether they are driving right now*. Keeping the eligibility decision here and enforcing it in Supply via a published snapshot avoids two sources of truth.",
     hld=("""flowchart LR
  APP["Driver app"] --> AW["Application workflow"]
  AW --> DV["Document verification"] --> OCR["OCR/Doc AI"]
  AW --> BC["Background check"] --> VEND["Vendor"]
  VEND -->|webhook| BC
  AW --> ELG["Eligibility snapshot"] -->|DriverEligibilityChanged| SUP["Driver supply gate"]
  EXP["Expiry scanner"] --> ELG
  AW --> DB[("onboarding schema")]""", "Application workflow orchestrates document verification and background checks, then computes an eligibility snapshot that Driver Supply enforces. The expiry scanner keeps that snapshot correct over time."),
     seq=("""sequenceDiagram
  participant D as Driver
  participant W as Workflow
  participant V as DocVerify
  participant B as BGCheck
  participant S as Supply
  D->>W: submit application (city=PUN)
  W->>V: verify licence + insurance
  V-->>W: verified
  W->>B: start check (consent id)
  B-->>W: CLEAR (webhook, 2 days later)
  W->>W: all requirements met → APPROVED
  W->>S: DriverEligibilityChanged(eligible=true, valid_until)""", "End-to-end approval, with a days-long wait in the middle."),
     state=("""stateDiagram-v2
  [*] --> Draft
  Draft --> Submitted
  Submitted --> DocumentsInReview
  DocumentsInReview --> BackgroundCheck
  BackgroundCheck --> Approved
  BackgroundCheck --> Rejected
  DocumentsInReview --> NeedsResubmission
  NeedsResubmission --> DocumentsInReview
  Approved --> Suspended: document expired / check revoked
  Suspended --> Approved: re-verified""", "Application lifecycle."),
     subdeps=[("application-workflow", "document-verification"), ("application-workflow", "background-check")],
     flow="The applicant drives the early steps synchronously. Everything after submission is asynchronous and durable. Outcome events update the eligibility snapshot, which is the only thing Driver Supply reads.",
     data="`driver_applications(id, user_id, city, requirement_set_version, state, version)`, `driver_documents(id, driver_id, type, status, expires_at, file_key, extracted jsonb)`, `background_checks(id, driver_id, vendor_ref, status, completed_at)`, `driver_eligibility(driver_id, eligible, reasons[], valid_until, computed_at)`. Documents in encrypted object storage with 7-year retention where law requires.",
     er="""erDiagram
  DRIVER_APPLICATIONS ||--o{ DRIVER_DOCUMENTS : requires
  DRIVER_APPLICATIONS ||--o{ BACKGROUND_CHECKS : runs
  DRIVER_APPLICATIONS ||--|| DRIVER_ELIGIBILITY : yields
  REQUIREMENT_SETS ||--o{ DRIVER_APPLICATIONS : governs""",
     rel=[["Durability", "Workflow state persisted per step; Phase III Temporal workflows with timers."], ["Vendor failure", "Breakers + retries; webhook + polling fallback."], ["Idempotency", "Vendor calls keyed by check id; webhooks deduped by vendor event id."], ["Reconciliation", "Daily: all approved drivers have valid documents per current requirement set."]],
     sec=[["PII", "Licence numbers/SSN encrypted with per-record data keys; access only for onboarding reviewers, logged."], ["Consent", "Background-check consent recorded (FCRA)."], ["Fraud", "Document tampering detection; selfie-to-licence face match."]],
     adrs=[A("Requirement sets as versioned data", "I", "Rules per city change frequently.", [("Code per city", "Rejected"), ("Versioned requirement sets", "Chosen")], "Applications pin a requirement-set version; re-evaluation on version change.", "Ops can change rules without deploy; audit of what applied.", "Need migration logic when rules tighten.", "N/A")],
     qa=[Q("Correctness", "A city adds a new mandatory training module. What happens to 5,000 already-approved drivers?", "Publish requirement set v+1 with an effective date and a grace period. A migration job evaluates every approved driver against v+1 and creates a pending requirement with a deadline. Eligibility stays true until the deadline, then flips to false for non-compliant drivers (event to Supply). Drivers are notified at T-14, T-3 and T-1 days.", "Immediate enforcement would take thousands of drivers offline at once.")],
     impl_order=["application-workflow", "document-verification", "background-check", "eligibility snapshot + expiry scanner"],
     pkg="""com.atlas.driver.onboarding
├── application (ApplicationService, RequirementSet, ApplicationState)
├── documents   (DocumentService, OcrClient, ReviewQueue)
├── bgcheck     (BackgroundCheckService, VendorClient, WebhookController)
└── eligibility (EligibilityCalculator, ExpiryScanner)""",
     tests=[T("Integration", "Vendor webhook duplicated", "Single result"), T("Failure", "Vendor down 2 days", "Applications wait, then resume"), T("Correctness", "Licence expires at midnight", "Eligibility false at 00:00; driver forced offline")],
     evo=[("I", "Module with DB state machine", "onboarding schema; manual review", "Scheduled expiry job", "Pilot needs compliance"), ("E", "Same", "Vendor calls via queue", "Breakers; webhook dedup", "Vendor latency"),
          ("R", "Temporal workflows", "Events to Supply via outbox", "Durable timers", "Multi-day waits, many steps"), ("R", "Onboarding service", "Own DB; doc store", "SLO on approval latency", "Team ownership; PII isolation"),
          ("E", "Doc AI auto-approval", "ML fraud scores", "Human-in-loop sampling", "20K/day volume"), ("E", "Regional; per-country requirement sets", "Docs stored in-country", "Residency", "Data residency")],
     ideas={"now": ["Resumable application with progress bar"], "next": ["Auto-approval for high-confidence OCR + registry match"], "adv": ["Government eID integration"], "rej": ["Approving before background check completes"]})

sub(id="application-workflow", comp="driver-onboarding", name="Application Workflow & Eligibility", phase="I", cat="Workflow · Compliance",
    resp="Drive an application through its steps against a versioned city requirement set, and compute and publish the driver's eligibility snapshot.",
    inp="applicant steps, document/check outcomes, requirement sets, clock", out="application state, DriverEligibilityChanged", deps="Document verification, Background check, Notifications", cons="Driver Supply, Support", own="driver_applications, driver_eligibility, requirement_sets",
    problem="Coordinate a multi-day process with partial results and changing rules, and produce one authoritative eligible/not-eligible answer at every moment.",
    without="Drivers online with expired insurance, or approved drivers stuck because no one noticed a vendor result.", guar=["Eligibility = all mandatory requirements satisfied and unexpired", "Every eligibility change is published", "Applications resume after any crash"], nong=["Real-time online status"],
    usecase="Insurance for driver D expires 2026-12-01. On that date the expiry scanner recomputes eligibility to false, publishes the event, Supply forces D offline after the current trip, and D gets an upload prompt.",
    derive="- Eligibility is a pure function of (requirement set, document states, check states, now). Make it a pure function, recompute on any input change, and store the snapshot with `valid_until` = earliest expiry.\n- The clock is an input, so a scheduled scan at `valid_until` is needed.\n- Outcomes arrive asynchronously and possibly duplicated, so transitions must be idempotent.",
    conc="Application row versioned; each outcome handler loads, applies a transition and saves with version check (retry on conflict).", consistency="Snapshot strongly consistent with application state (same transaction); Supply eventually consistent (events, < 5 s).",
    idem="Outcome events carry ids; applying the same outcome twice yields the same state. Recompute is pure.", order="Outcomes for different requirements commute. For the same document, a newer upload version supersedes older outcomes (version on document).",
    restart="State in DB (Phase I–II), Temporal history (Phase III+).", scale="Low write volume; the expiry scan is index-driven on `valid_until`.",
    arch="Phase I: a DB state machine and a scheduled `ExpiryScanner` (`SELECT ... WHERE valid_until <= now() FOR UPDATE SKIP LOCKED`). Phase III: each application is a Temporal workflow whose code calls activities (verify docs, start check) and waits for signals (webhook outcomes) with timers.",
    modules=[["RequirementSetStore", "Versioned per-city requirements"], ["ApplicationStateMachine", "Transitions + version check"], ["EligibilityCalculator", "Pure function → snapshot"], ["ExpiryScanner", "Recompute at valid_until"], ["EligibilityPublisher", "Outbox event"]],
    d_arch=("""flowchart LR
  OUT["outcomes (docs, checks)"] --> SM["ApplicationStateMachine"]
  SM --> EC["EligibilityCalculator"]
  RS["RequirementSetStore"] --> EC
  EC --> SNAP[("driver_eligibility")]
  SC["ExpiryScanner"] --> EC
  SNAP --> PUB["outbox → DriverEligibilityChanged"]""", "Eligibility is recomputed from inputs whenever any input changes, including time."),
    d_seq=("""sequenceDiagram
  participant S as ExpiryScanner
  participant DB
  participant E as Calculator
  participant P as Supply
  S->>DB: SELECT due snapshots FOR UPDATE SKIP LOCKED
  S->>E: recompute(driver)
  E-->>S: eligible=false (insurance expired)
  S->>DB: update snapshot + outbox (tx)
  DB-->>P: DriverEligibilityChanged""", "Time-driven ineligibility."),
    d_state=("""stateDiagram-v2
  [*] --> Eligible: all satisfied
  Eligible --> Ineligible: expiry / revoked check / new requirement deadline
  Ineligible --> Eligible: re-verified""", "The eligibility snapshot state. The application states are on the parent component page."),
    d_flow=("""flowchart LR
  RS["requirements v7"] --> F["eligibility(rs, docs, checks, now)"]
  D["doc states"] --> F
  C["check states"] --> F
  F --> S["{eligible, reasons[], valid_until}"]""", "A pure function with explicit inputs is easy to test and safe to recompute."),
    d_fail=("""flowchart TB
  SC["scanner crashed"] --> NX["next run picks due rows (valid_until <= now)"]
  PUB["event relay lag"] --> SUP["Supply also checks valid_until locally at go-online"]""", "Supply double-checks `valid_until`, so a lagging event cannot keep an expired driver online at login."),
    sql="""CREATE TABLE onboarding.driver_eligibility (
  driver_id uuid PRIMARY KEY, eligible boolean NOT NULL, reasons text[] NOT NULL DEFAULT '{}',
  valid_until timestamptz, requirement_set_version int NOT NULL, computed_at timestamptz NOT NULL);
CREATE INDEX elig_due ON onboarding.driver_eligibility(valid_until) WHERE eligible;""",
    data="One snapshot per driver, overwritten. History of changes kept in an append-only `eligibility_history` for audits (7 years).",
    api="""event DriverEligibilityChanged{driver_id, eligible, reasons[], valid_until, version, occurred_at}
GET /v1/driver-applications/me -> {state, steps:[{requirement, status, action}]}
POST /v1/driver-applications/me/steps/{requirement} {...}""",
    mech=[("Pure eligibility function", "Recomputing from all inputs avoids incremental-update bugs (forgetting a case)."), ("SKIP LOCKED scanning", "Multiple scanner instances take disjoint due rows without a coordinator."), ("Durable timers (Temporal, Phase III)", "`Workflow.sleep(until valid_until)` survives restarts. The engine persists the timer.")],
    code="""public Eligibility compute(RequirementSet rs, Docs docs, Checks checks, Instant now) {
    List<String> missing = rs.mandatory().stream()
        .filter(r -> !r.satisfiedBy(docs, checks, now)).map(Requirement::code).toList();
    Instant validUntil = rs.mandatory().stream().map(r -> r.expiry(docs, checks)).filter(Objects::nonNull).min(naturalOrder()).orElse(null);
    return new Eligibility(missing.isEmpty(), missing, validUntil, rs.version());
}""", cx="O(requirements).",
    fail=[F("Scanner down", "Due-rows age metric", "Expired drivers remain eligible in snapshot", "Supply checks valid_until locally; scanner restarts", "Supply guard covers gap"), F("Duplicate outcome", "Same outcome id", "None", "Idempotent apply", "Same state")],
    alts=[["Supply computes eligibility", "Rejected", "Two sources of truth", "Never"], ["Cron daily expiry check", "Rejected", "Up to 24h late", "Never for mandatory docs"]],
    adrs=[A("Snapshot with valid_until", "I", "Expiry is time-driven.", [("Check documents on every go-online", "Rejected: cross-domain reads"), ("Snapshot + valid_until", "Chosen")], "Publish snapshot including earliest expiry.", "Supply can guard locally.", "Snapshot must be recomputed on any rule change.", "N/A")],
    qa=[Q("Distributed systems", "Supply receives Eligible=true (v5) after Ineligible (v6) due to reordering. Is the driver allowed online?", "No. Events carry a per-driver monotonic version, and Supply stores the highest version applied and ignores older ones. Kafka partitioning by driver_id also preserves order in Phase III+, but the version check protects against replays and redeliveries.", "")],
    tests=[T("Unit", "Doc expired 1 ms ago", "Ineligible"), T("Integration", "Requirement set v+1 with grace", "Pending requirement; eligible until deadline"), T("Recovery", "Kill scanner mid-batch", "Rows reprocessed; single event per change")],
    evo=["I: DB state machine + scheduled scanner", "E: Queue-driven outcome handling", "R: Temporal workflow per application; events via outbox", "E: In Onboarding service", "E: Auto-approval rules", "E: Regional requirement sets"],
    ideas={"now": ["Reasons array for UX"], "next": ["Predictive expiry reminders"], "adv": ["Rule engine DSL for requirements"], "rej": ["Manual-only expiry tracking"]})

sub(id="document-verification", comp="driver-onboarding", name="Document Verification", phase="I", cat="Compliance · Vendor/AI",
    resp="Accept document uploads, extract fields, detect tampering, verify against registries where available, and route uncertain cases to human review.",
    inp="images/PDFs, document type, city", out="document status + extracted fields + expiry", deps="Object storage, OCR/Doc AI, registry APIs, review queue", cons="Application workflow", own="driver_documents, review tasks",
    problem="Licences and insurance certificates must be authentic, readable, belong to the applicant and be unexpired, at volume and with fraud attempts.",
    without="Fraudulent or expired documents get through, or reviewers are overloaded.", guar=["Every approved document has extracted expiry and reviewer/automation provenance", "Files encrypted at rest; access logged"], nong=["Absolute fraud detection (sampling + audits)"],
    usecase="A licence photo is uploaded. OCR extracts number and expiry with 0.97 confidence and the state registry confirms it is valid, so it is auto-approved. A blurry insurance PDF at 0.6 confidence goes to the review queue.",
    derive="- Uploads are large, so direct-to-object-storage with pre-signed URLs keeps the API light.\n- Extraction is slow and flaky, so it runs asynchronously.\n- Confidence varies, so use thresholds for auto-approve, review and reject.\n- Reviewers are a scarce resource, so a priority queue with SLA.",
    conc="Document versions: a new upload creates version n+1. Outcomes for older versions are ignored (`WHERE version = ?`). Review tasks are claimed with `SKIP LOCKED`.", consistency="Strong per document row.", idem="Upload completion keyed by object key. OCR jobs keyed by (document_id, version).",
    order="Outcome for version n arriving after version n+1 upload is discarded.", restart="Jobs in queue; review claims time out after 15 min and return to the queue.", scale="OCR throughput via vendor concurrency limits; reviewer capacity is the human bottleneck.",
    arch="Pre-signed upload → `DocumentUploaded` → OCR worker → confidence policy → (auto-approve | review task | reject) → outcome to application workflow.",
    modules=[["UploadBroker", "Pre-signed URL, size/type limits, malware scan"], ["Extractor", "OCR/Doc AI client"], ["Verifier", "Registry checks, face match"], ["ConfidencePolicy", "Thresholds per doc type/city"], ["ReviewQueue", "Human tasks with SLA"]],
    d_arch=("""flowchart LR
  APP["Driver app"] -->|PUT presigned| OBJ[("encrypted object storage")]
  APP --> UB["UploadBroker"] --> Q[["ocr jobs"]] --> EX["Extractor"] --> VER["Verifier"] --> CP["ConfidencePolicy"]
  CP -->|auto| OUT["outcome"]
  CP -->|uncertain| RQ["ReviewQueue"] --> OUT
  OUT --> WF["Application workflow"]""", "Large files bypass the API. Processing is queue-driven, and uncertain cases go to humans."),
    d_seq=("""sequenceDiagram
  participant A as App
  participant U as UploadBroker
  participant O as ObjectStore
  participant X as Extractor
  participant P as Policy
  A->>U: request upload URL (type=licence)
  U-->>A: presigned PUT (5 min)
  A->>O: PUT file
  A->>U: complete(doc_id)
  U->>X: job(doc_id, v1)
  X->>P: fields + confidence 0.97
  P-->>U: APPROVED""", "Upload and automatic approval."),
    d_state=("""stateDiagram-v2
  [*] --> Uploaded
  Uploaded --> Extracting
  Extracting --> Approved: high confidence + registry ok
  Extracting --> InReview: uncertain
  InReview --> Approved
  InReview --> Rejected
  Extracting --> Rejected: unreadable
  Approved --> Expired: expiry date""", "Per-document-version lifecycle."),
    d_flow=("""flowchart LR
  IMG["image"] --> MAL["malware scan"] --> OCR["OCR"] --> FIELDS["number, name, expiry"] --> MATCH["name match vs applicant"] --> DB[("driver_documents.extracted")]""", "Extracted fields are matched against the applicant's identity before acceptance."),
    d_fail=("""flowchart TB
  V["OCR vendor down"] --> B["breaker"] --> RQ["route to manual review (degraded SLA)"]
  R["registry down"] --> W["approve on OCR only if city allows; flag for re-check"]""", "Degradation shifts load to humans or to later re-checks, never to blind approval where the law forbids it."),
    sql="""CREATE TABLE onboarding.driver_documents (
  id uuid, version int, driver_id uuid NOT NULL, doc_type text NOT NULL, file_key text NOT NULL,
  status text NOT NULL, confidence numeric(4,3), extracted jsonb, expires_at date, decided_by text,
  created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (id, version));
CREATE TABLE onboarding.review_tasks (id uuid PRIMARY KEY, document_id uuid, version int, priority int, claimed_by uuid, claimed_until timestamptz, due_at timestamptz);""",
    data="Files retained per legal requirement (e.g. 7 years after deactivation) then deleted. `extracted` contains PII, encrypted column-level.",
    api="""POST /v1/driver-documents {type} -> {doc_id, upload_url, expires_in}
POST /v1/driver-documents/{id}/complete -> 202
GET  /v1/driver-documents -> [{type, status, expires_at, action?}]
event DocumentVerified{driver_id, doc_type, version, status, expires_at}""",
    mech=[("Pre-signed uploads", "The API issues a short-lived, single-object write URL. The client uploads directly to storage, so the API never handles large bodies."), ("Confidence thresholds", "Per-type thresholds tuned on labelled data, plus random 2% sampling of auto-approvals to human audit to measure drift.")],
    code="""public Outcome decide(Extraction x, RegistryResult r, Policy p) {
    if (!x.nameMatches(applicant) ) return Outcome.review("NAME_MISMATCH");
    if (x.confidence() >= p.autoApprove() && r.valid()) return Outcome.approved(x.expiry());
    if (x.confidence() < p.reject()) return Outcome.rejected("UNREADABLE");
    return Outcome.review("LOW_CONFIDENCE");
}""", cx="O(1) per document plus vendor latency.",
    fail=[F("Stale OCR result for replaced doc", "Version mismatch", "None", "Discard", "Latest version wins"), F("Reviewer abandons task", "claimed_until passed", "SLA risk", "Task returns to queue", "None")],
    alts=[["All manual review", "Phase I default", "Accurate but slow", "Pilot volumes"], ["Fully automated", "Rejected", "Fraud + legal", "Never for regulated docs"]],
    adrs=[A("Human-in-the-loop with thresholds", "III", "Volume grows; reviewers costly.", [("Manual only", "Unscalable"), ("Auto with thresholds + sampling", "Chosen")], "Thresholds per doc type; 2% audit sampling.", "Scales reviewers to uncertain cases.", "Threshold tuning needed.", "When audit error rate > 0.5%.")],
    qa=[Q("Security", "How do you detect a photoshopped licence?", "Layered checks: document-AI tamper signals (font inconsistency, compression artefacts), registry verification of the number and expiry, a face match between the licence photo and a live selfie with liveness detection, and cross-account duplicate detection (same licence number on two accounts). Any signal routes to review.", "")],
    tests=[T("Integration", "Upload v2 while v1 OCR running", "v1 result discarded"), T("Failure", "OCR vendor 500s", "Tasks routed to review"), T("Security", "Executable disguised as PDF", "Rejected by scan")],
    evo=["I: Manual review of uploaded files", "E: OCR via queue; review queue SLA", "E: Events to workflow", "E: Registry integrations per country", "E: Doc AI auto-approval + sampling", "E: In-country storage"],
    ideas={"now": ["Client-side blur/glare detection before upload"], "next": ["Registry APIs"], "adv": ["Verifiable digital credentials (mDL)"], "rej": ["Storing documents in DB blobs"]})

sub(id="background-check", comp="driver-onboarding", name="Background Check Integration", phase="II", cat="Compliance · External integration",
    resp="Run consented criminal and driving-record checks through vendors, handle asynchronous results, adverse-action flows and periodic re-checks.",
    inp="driver identity data + consent", out="check result (CLEAR/CONSIDER/SUSPENDED)", deps="Vendor API, consent record", cons="Application workflow", own="background_checks",
    problem="Checks take hours to days, are delivered by webhook, sometimes duplicated or lost, and legally require consent and an adverse-action process.",
    without="Stuck applications or unlawful rejections.", guar=["No check without recorded consent", "Every check reaches a terminal state or escalates", "Adverse action follows legal waiting periods"], nong=["Vendor result correctness"],
    usecase="Check returns CONSIDER for a minor traffic offence. The policy engine evaluates per city rules: allowed, so APPROVED. A serious offence triggers pre-adverse notice, a 7-day wait, then final adverse action.",
    derive="- Asynchronous vendor with webhooks, so a stored check record with vendor_ref and status.\n- Webhooks can be lost, so poll for checks with no update after an SLA.\n- Webhooks can be forged, so verify signatures.\n- Legal process includes waiting periods, so durable timers.",
    conc="One active check per driver (partial unique index). Webhook processing does a conditional status update.", consistency="Strong for check record.", idem="Create keyed by (driver, cycle) idempotency key sent to vendor. Webhooks deduped by vendor event id.",
    order="Vendor statuses are monotonic (pending → complete). Lower-rank updates are ignored.", restart="Poller and timers durable (DB/Temporal).", scale="Vendor rate limits, so a token bucket per vendor.",
    arch="`BackgroundCheckService` creates vendor candidates and reports through a vendor adapter (anti-corruption layer). `WebhookController` verifies HMAC and enqueues. `CheckPoller` sweeps stale checks. `AdverseActionFlow` runs legally-timed steps.",
    modules=[["VendorAdapter", "Map vendor API ↔ internal model"], ["WebhookController", "Signature verification, dedup"], ["CheckPoller", "Recover lost webhooks"], ["AdverseActionFlow", "Pre-adverse notice, wait, final"]],
    d_arch=("""flowchart LR
  WF["Workflow"] --> BCS["BackgroundCheckService"] --> VA["VendorAdapter"] --> V["Vendor"]
  V -->|signed webhook| WH["WebhookController"] --> BCS
  POLL["CheckPoller"] --> VA
  BCS --> AA["AdverseActionFlow"] --> N["Notifications"]""", "Push and pull both lead into the same idempotent status update."),
    d_seq=("""sequenceDiagram
  participant W as Workflow
  participant B as BGService
  participant V as Vendor
  W->>B: start(driver, consent_id)
  B->>V: POST /reports (Idempotency-Key)
  V-->>B: report_id
  V-->>B: webhook report.completed (CONSIDER)
  B->>B: policy(city) → pre-adverse
  B->>W: outcome pending adverse action""", "Check initiation and result."),
    d_state=("""stateDiagram-v2
  [*] --> Requested
  Requested --> Pending
  Pending --> Clear
  Pending --> Consider
  Consider --> Clear: policy allows
  Consider --> PreAdverse
  PreAdverse --> Adverse: 7 days, no dispute
  PreAdverse --> Clear: dispute upheld
  Pending --> Escalated: SLA exceeded""", "Includes the legally required adverse-action path."),
    d_flow=("""flowchart LR
  ID["name, DOB, licence, SSN (encrypted)"] --> V["vendor"] --> R["status + report URL"] --> DB[("background_checks")]""", "Raw reports stay at the vendor. We store status plus a reference."),
    d_fail=("""flowchart TB
  L["webhook lost"] --> P["poller after 24h"]
  F["forged webhook"] --> S["HMAC fails → 401, alert"]
  V["vendor outage"] --> Q["requests queued with backoff"]""", "Every failure path converges on the poller or a queue."),
    sql="""CREATE TABLE onboarding.background_checks (
  id uuid PRIMARY KEY, driver_id uuid NOT NULL, cycle int NOT NULL, vendor text NOT NULL, vendor_ref text,
  consent_id uuid NOT NULL, status text NOT NULL, status_rank int NOT NULL, updated_at timestamptz NOT NULL,
  UNIQUE (driver_id, cycle));
CREATE TABLE onboarding.vendor_events (vendor_event_id text PRIMARY KEY, received_at timestamptz NOT NULL);""",
    data="Retention per FCRA/local law. Raw reports not copied.", api="""POST /internal/bgchecks {driver_id, consent_id} -> {check_id}
POST /webhooks/bgcheck/{vendor}  (X-Signature: HMAC-SHA256) -> 200
event BackgroundCheckCompleted{driver_id, check_id, result, completed_at}""",
    mech=[("Webhook + poll hybrid", "Webhooks give low latency, polling gives completeness. Each covers the other's failure mode."), ("Status rank monotonicity", "`UPDATE ... WHERE status_rank < :newRank` makes processing order-independent.")],
    code="""@Transactional
public void onWebhook(VendorEvent ev) {
    if (!events.insertIfNew(ev.id())) return;
    checks.advance(ev.reportRef(), ev.status(), rank(ev.status())); // WHERE status_rank < :rank
}""", cx="O(1).",
    fail=[F("Webhook lost", "No update > SLA", "Delayed approval", "Poller fetches", "Converges"), F("Duplicate webhook", "vendor_event_id exists", "None", "Ignored", "Single transition")],
    alts=[["Poll only", "Rejected", "Latency/cost", "Vendors without webhooks"], ["Multiple vendors in parallel", "Advanced", "Cost", "Markets with unreliable vendors"]],
    adrs=[A("Anti-corruption adapter per vendor", "II", "Vendors differ and change.", [("Vendor model leaks into domain", "Rejected"), ("Adapter", "Chosen")], "Internal model + adapters.", "Swap vendors per country.", "Adapter maintenance.", "N/A")],
    qa=[Q("Compliance", "How are continuous (annual) re-checks scheduled?", "Each CLEAR check stores `next_due = completed_at + 12 months`. A scheduler starts cycle n+1 with an idempotency key (driver, cycle). Results flow through the same pipeline. A failing re-check sets eligibility false through the application workflow.", "")],
    tests=[T("Security", "Webhook with bad HMAC", "401"), T("Unit", "COMPLETE then PENDING out of order", "Stays COMPLETE"), T("Recovery", "Lost webhook", "Poller resolves")],
    evo=["N: Manual vendor portal use for a pilot", "I: Vendor API + webhooks + poller", "R: Activities within the Temporal onboarding workflow", "E: Multiple vendors per country", "E: Continuous monitoring products", "E: Region-specific vendors and data residency"],
    ideas={"now": ["Signature verification"], "next": ["Continuous monitoring"], "adv": ["Parallel vendors"], "rej": ["Storing full reports internally"]})

# ======================================================================= Driver Supply
comp(id="driver-supply", domain="driver", name="Driver Supply State (Availability)", tag="Supply · Hot path", phase="I", kind="Logical component → deployable service (Phase IV)",
     biz="Knows which drivers are online, available, on a trip or offline right now, and only lets eligible drivers go online.",
     eng="A high-frequency state machine per driver whose state is read by dispatch for every match and written by driver actions, trip transitions and liveness timeouts. It must never let one driver hold two trips.",
     deploy="Module (Phase I); service co-located with dispatch data (Phase IV); state in an in-memory store sharded by city (Phase V).",
     data_own="driver_status (state, current_trip_id, state_version, last_heartbeat), shift sessions.",
     up=["driver-onboarding", "fleet-vehicle", "location-ingest"], down=["dispatch", "geo-index", "trip", "pricing", "driver-earnings"], ext=[],
     interfaces="REST `/v1/drivers/me/online`, `/offline`; internal `tryReserve(driver, request)`, `release`, events `DriverStatusChanged`.",
     problem="Dispatch needs an accurate pool of available drivers, and a driver must never be assigned two trips. Drivers disappear without logging off (tunnel, battery, app killed).",
     fr=["Go online (eligibility + vehicle check)", "Go offline", "Reserve for an offer / assign to trip atomically", "Auto-offline when heartbeats stop", "Report hours online (fatigue limits)"],
     nfr=["Reserve p99 < 20 ms", "Zero double assignments", "Ghost drivers removed within 60 s", "Fatigue limit enforced (e.g. 12 h)"],
     workload="State reads ≈ location rate; writes on transitions (≈ 3–6 per trip). Phase V: 250K online drivers.", success="Available pool accurate within seconds; no double assignment.", failure="Riders matched to drivers who aren't there; double assignment; fatigue-limit violations.",
     derive="The single invariant is that a driver is in exactly one state, and ON_TRIP/RESERVED implies exactly one request or trip. That requires an atomic compare-and-set on a per-driver record. Liveness requires heartbeats and a timeout. Eligibility is an input from onboarding, checked at go-online and on change.",
     owns=["Driver operational state", "Reservations", "Liveness", "Hours-online accounting"], not_owns=["Eligibility (Onboarding)", "Location (Location)", "Trip state (Trip)"],
     sync=["Go online/offline", "tryReserve/release/assign"], **{"async": ["Heartbeat timeouts", "Eligibility-change enforcement", "Status events to geo index and analytics"]},
     boundary_why="Dispatch must not own driver state: then trips, onboarding and the driver app would all write into dispatch. Supply is a small, very consistent component with a tiny API that dispatch calls.",
     hld=("""flowchart LR
  DA["Driver app"] -->|online/offline| AV["Availability state machine"]
  AV --> EG["Eligibility gate"]
  EG --> ELIG[("eligibility snapshot")]
  DSP["Dispatch"] -->|tryReserve / assign| AV
  TRIP["Trip"] -->|release on complete/cancel| AV
  LOC["Location heartbeats"] --> HB["Liveness monitor"] --> AV
  AV --> ST[("driver_status")]
  AV -->|DriverStatusChanged| GEO["Geo index"]""", "All state changes go through the state machine. The gate and liveness monitor feed it."),
     seq=("""sequenceDiagram
  participant D as Driver
  participant A as Availability
  participant G as Gate
  participant X as Dispatch
  D->>A: go online
  A->>G: eligible? vehicle active?
  G-->>A: ok
  A->>A: OFFLINE→AVAILABLE
  X->>A: tryReserve(driver, req, ttl 15s)
  A-->>X: reserved (version 42)
  X->>A: assign(driver, trip, version 42)
  A-->>X: ON_TRIP""", "Online, reserve, assign."),
     state=("""stateDiagram-v2
  [*] --> OFFLINE
  OFFLINE --> AVAILABLE: go online (gate ok)
  AVAILABLE --> RESERVED: offer sent
  RESERVED --> AVAILABLE: declined / timeout
  RESERVED --> ON_TRIP: accepted + assigned
  ON_TRIP --> AVAILABLE: trip completed/cancelled
  AVAILABLE --> OFFLINE: go offline / heartbeat lost / ineligible
  ON_TRIP --> OFFLINE_AFTER_TRIP: ineligible during trip
  OFFLINE_AFTER_TRIP --> OFFLINE: trip ends""", "Driver operational state. RESERVED is a short lease, so a driver can't receive two offers at once."),
     subdeps=[("availability-state", "eligibility-gate"), ("liveness-monitor", "availability-state")],
     flow="Commands enter the state machine, which applies compare-and-set transitions on a versioned record. Dispatch reserves with a TTL. Expired reservations revert automatically. Trip end releases. Liveness and eligibility changes force transitions.",
     data="`driver_status(driver_id PK, state, request_id, trip_id, reserved_until, state_version, online_since, last_heartbeat_at, city)`; `shift_sessions(driver_id, started_at, ended_at)` for hours. Phase V: primary copy in Redis/in-memory shard per city with write-behind to PostgreSQL for audit.",
     rel=[["Atomicity", "Conditional update per driver (SQL in Phase I–IV; Lua script on Redis in Phase V)."], ["Lease expiry", "reserved_until enforced on read + sweeper."], ["Recovery", "Phase V: rebuild in-memory shard from PostgreSQL snapshot + recent events."]],
     sec=[["Spoofing", "Online requires device-bound token and attestation; mock-location detection feeds risk."], ["Abuse", "Rapid online/offline toggling to game incentives is rate limited and flagged."]],
     adrs=[A("Reservation lease before assignment", "I", "Offer → accept takes up to 15 s.", [("Assign immediately on offer", "Rejected: driver may decline"), ("No reservation", "Rejected: two offers at once"), ("Lease RESERVED with TTL", "Chosen")], "RESERVED with reserved_until.", "Exclusive offers; automatic cleanup.", "Driver unavailable for others during lease.", "If batch matching uses soft holds.")],
     qa=[Q("Concurrency", "Two dispatch workers try to reserve the same driver for different riders at the same millisecond. What happens?", "Both execute `UPDATE driver_status SET state='RESERVED', request_id=?, state_version=state_version+1 WHERE driver_id=? AND state='AVAILABLE'`. PostgreSQL row locking serialises them: the first commits and returns 1 row, and the second re-evaluates the WHERE after the lock is released, sees RESERVED and returns 0 rows. The losing worker moves to its next candidate. In Phase V the same compare-and-set runs as an atomic Lua script on the city's Redis shard.", "Distributed locks (Redlock) add a separate system and still need fencing. A conditional update on the record is both the lock and the write.")],
     impl_order=["availability-state", "eligibility-gate", "liveness-monitor"], pkg="""com.atlas.driver.supply
├── state    (DriverStatus, Transition, StatusRepository, SupplyService)
├── gate     (EligibilityGate, EligibilityCache)
├── liveness (HeartbeatTracker, LivenessSweeper)
└── events   (DriverStatusChanged)""",
     tests=[T("Concurrency", "100 parallel reserves on one driver", "Exactly one success"), T("Failure", "Driver app killed", "OFFLINE within 60 s; removed from geo index"), T("Correctness", "Eligibility false mid-trip", "Trip continues; driver goes OFFLINE after")],
     evo=[("I", "Module; PostgreSQL row per driver", "Sync calls", "Conditional updates", "Correctness"), ("E", "Same", "Redis cache of AVAILABLE set", "Lease sweeper; heartbeats", "Ghost drivers at scale"),
          ("E", "Same", "DriverStatusChanged events", "Versioned events", "Geo/analytics consumers"), ("R", "Supply service", "gRPC; own DB", "99.99% SLO", "Hot path isolation"),
          ("R", "In-memory per-city shards (Redis/Lua) + durable log", "Write-behind to PG", "Shard failover from log", "250K online drivers"), ("E", "Per-region shards", "City homed in region", "Failover with fencing", "Global")],
     ideas={"now": ["Lease TTL tied to offer timeout + margin"], "next": ["Soft holds for batch matching"], "adv": ["Actor-per-driver model (Akka/Orleans)"], "rej": ["Distributed lock service for reservations"]})

sub(id="availability-state", comp="driver-supply", name="Availability State Machine & Reservations", phase="I", cat="Concurrency · State machine",
    resp="Hold each driver's operational state and perform atomic transitions (online, reserve, assign, release, offline) with leases.",
    inp="driver commands, dispatch reserve/assign, trip release, liveness/eligibility forces", out="state transitions, DriverStatusChanged", deps="Eligibility gate", cons="Dispatch, Geo index, Trip", own="driver_status",
    problem="Guarantee that each driver is in exactly one state and committed to at most one request or trip, under concurrent dispatchers and unreliable devices.",
    without="Double assignment: two riders waiting for one car.", guar=["At most one reservation/trip per driver", "Expired reservations never block a driver beyond reserved_until", "Each transition increments state_version"], nong=["Location accuracy", "That an AVAILABLE driver is physically ready (liveness bounds it)"],
    usecase="Driver K is offered to rider A (RESERVED until 12:00:15). K doesn't respond. At 12:00:15 the reservation is considered expired, and dispatch can reserve K for rider B at 12:00:16.",
    derive="- Exclusive ownership → compare-and-set on (state, version).\n- Leases must expire without a sweeper (sweeper can lag) → treat `RESERVED AND reserved_until < now()` as AVAILABLE in the CAS predicate.\n- Assign must confirm the same reservation → require (request_id, state_version) match.",
    conc="CAS predicates: reserve: `WHERE driver_id=? AND (state='AVAILABLE' OR (state='RESERVED' AND reserved_until < now()))`. Assign: `WHERE driver_id=? AND state='RESERVED' AND request_id=? AND reserved_until >= now()`.",
    consistency="Linearizable per driver (single row / single Redis key).", idem="Reserve with the same request_id when already reserved for it returns success (retry-safe). Release for a trip already released is a no-op.",
    order="Commands are synchronous CAS operations. Events carry state_version so consumers drop stale ones.", restart="DB row is truth (Phase I–IV). In Phase V the Redis shard has AOF + replica, and on loss is rebuilt from PG write-behind + event log.",
    scale="One row per online driver; contention only per driver. Phase V: shard by city in Redis with Lua CAS.",
    arch="`SupplyService` exposes transition methods, each a single conditional SQL statement (or Lua script). A transition table defines legal moves. Events are written to the outbox in the same transaction.",
    modules=[["TransitionTable", "Allowed from→to"], ["StatusRepository", "CAS statements"], ["LeaseSweeper", "Cosmetic cleanup + events for expired leases"], ["StatusEvents", "Outbox"]],
    d_arch=("""flowchart LR
  DSP["Dispatch"] -->|tryReserve/assign| SS["SupplyService"]
  TR["Trip"] -->|release| SS
  SS --> TT["TransitionTable"]
  SS --> REPO["StatusRepository (CAS)"] --> DB[("driver_status")]
  SW["LeaseSweeper"] --> REPO
  SS --> OB["outbox"]""", "All writers go through the same CAS repository."),
    d_seq=("""sequenceDiagram
  participant X1 as Dispatch-1
  participant X2 as Dispatch-2
  participant DB
  X1->>DB: UPDATE ... SET RESERVED(req A) WHERE AVAILABLE
  X2->>DB: UPDATE ... SET RESERVED(req B) WHERE AVAILABLE
  DB-->>X1: 1 row
  DB-->>X2: 0 rows
  X2->>X2: next candidate""", "The race resolved by the database."),
    d_state=("""stateDiagram-v2
  AVAILABLE --> RESERVED: reserve(req)
  RESERVED --> RESERVED: reserve(same req) idempotent
  RESERVED --> AVAILABLE: decline / lease expiry
  RESERVED --> ON_TRIP: assign(req, version)
  ON_TRIP --> AVAILABLE: release(trip)""", "Reservation detail of the parent's state machine."),
    d_flow=("""flowchart LR
  CMD["command"] --> CAS["conditional update"] --> ROW[("row v+1")] --> EV["DriverStatusChanged v+1"] --> GEO["geo index availability flag"]""", "Each transition yields exactly one versioned event."),
    d_fail=("""flowchart TB
  C["dispatch crashes after reserve"] --> L["lease expires at reserved_until"] --> A["driver available again"]
  P["DB primary failover"] --> R["in-flight CAS fails; caller retries with same request_id (idempotent)"]""", "Leases make crash recovery automatic."),
    sql="""CREATE TABLE supply.driver_status (
  driver_id uuid PRIMARY KEY, city text NOT NULL,
  state text NOT NULL CHECK (state IN ('OFFLINE','AVAILABLE','RESERVED','ON_TRIP','OFFLINE_AFTER_TRIP')),
  request_id uuid, trip_id uuid, reserved_until timestamptz, state_version bigint NOT NULL DEFAULT 0,
  online_since timestamptz, last_heartbeat_at timestamptz,
  CHECK ((state='RESERVED') = (request_id IS NOT NULL AND reserved_until IS NOT NULL)),
  CHECK ((state IN ('ON_TRIP','OFFLINE_AFTER_TRIP')) = (trip_id IS NOT NULL)));
CREATE INDEX available_by_city ON supply.driver_status(city) WHERE state = 'AVAILABLE';""",
    data="CHECK constraints make illegal combinations unrepresentable. History goes to events/analytics, not this table.",
    api="""ReserveResult tryReserve(UUID driver, UUID requestId, Duration ttl)   // RESERVED | ALREADY_RESERVED_FOR_YOU | UNAVAILABLE
AssignResult  assign(UUID driver, UUID requestId, UUID tripId)       // ON_TRIP | LEASE_LOST
void          release(UUID driver, UUID tripId)                      // idempotent
event DriverStatusChanged{driver_id, state, state_version, city, occurred_at}""",
    mech=[("Compare-and-set in SQL", "The WHERE clause is the precondition and the UPDATE the effect, executed atomically under a row lock. A 0-row result means the precondition failed."), ("Leases with read-time expiry", "Correctness does not depend on a sweeper running on time, because the predicate itself treats expired leases as free."),
          ("Redis Lua CAS (Phase V)", "The same logic as a Lua script on the city shard: Redis executes scripts atomically, giving the same linearizable per-key semantics at memory speed.")],
    code="""@Transactional
public ReserveResult tryReserve(UUID driver, UUID req, Duration ttl) {
    int n = jdbc.update(\"\"\"
        UPDATE supply.driver_status SET state='RESERVED', request_id=?, reserved_until=now()+?::interval, state_version=state_version+1
        WHERE driver_id=? AND (state='AVAILABLE' OR (state='RESERVED' AND reserved_until < now()))\"\"\",
        req, ttl.toSeconds()+" seconds", driver);
    if (n == 1) { outbox.statusChanged(driver); return ReserveResult.RESERVED; }
    return repo.isReservedFor(driver, req) ? ReserveResult.ALREADY_RESERVED_FOR_YOU : ReserveResult.UNAVAILABLE;
}""", cx="O(1); one indexed update.",
    fail=[F("Dispatcher crash after reserve", "Lease ages", "Driver held ≤ TTL", "Lease expiry", "Driver free"), F("Assign after lease expired and re-reserved", "assign returns LEASE_LOST", "First rider not assigned", "Dispatch continues search", "No double assignment"),
          F("Redis shard loss (P5)", "Replica promotion; gap detection", "Brief unavailability in that city", "Rebuild from PG + events", "Versions prevent regressions")],
    alts=[["SELECT FOR UPDATE then UPDATE", "Acceptable", "Two statements, longer lock", "Complex multi-row logic"], ["Distributed lock + write", "Rejected", "Extra system, still needs fencing", "Never"], ["Actor per driver", "Advanced", "Single-threaded per driver, no DB contention", "Very high rates"]],
    adrs=[A("CAS on driver row as the assignment lock", "I", "Prevent double assignment.", [("Lock service", "Rejected"), ("Row CAS", "Chosen")], "Single conditional update.", "Atomic, simple, testable.", "Hot driver rows contend (rare).", "Phase V: same semantics in Redis Lua.")],
    qa=[Q("Correctness", "Why does assign require the reservation version and request id, not just state=RESERVED?", "Without them, a slow accept from rider A's offer could land after A's lease expired and the driver was reserved for B, and it would assign the driver to A while B also thinks they have them. Matching on request_id plus lease validity makes the accept apply only to the reservation it belongs to.", "")],
    tests=[T("Concurrency", "1,000 parallel reserves, 10 drivers", "≤ 1 reservation per driver"), T("Unit", "Assign after expiry", "LEASE_LOST"), T("Property", "Random command sequences", "CHECK constraints never violated")],
    evo=["I: PostgreSQL CAS", "E: Lease sweeper + Redis read cache of available set", "E: Versioned events", "E: gRPC Supply service", "R: Redis Lua CAS per city shard; write-behind to PG", "E: Regional shards with fencing on failover"],
    ideas={"now": ["CHECK constraints for illegal states"], "next": ["Soft holds"], "adv": ["Actors"], "rej": ["Optimistic read-then-write without CAS"]})

sub(id="eligibility-gate", comp="driver-supply", name="Eligibility Gate", phase="I", cat="Compliance · Enforcement",
    resp="Allow a driver to go online only if they are eligible (onboarding), their vehicle is active, they are not restricted, and they are under fatigue limits, and force them offline when that changes.",
    inp="DriverEligibilityChanged, VehicleStatusChanged, restrictions, hours online", out="allow/deny with reasons; forced offline commands", deps="Onboarding snapshot, Fleet & Vehicle, Risk", cons="Availability state machine", own="eligibility cache (copy), fatigue counters",
    problem="Several domains each hold one reason a driver may not drive. Supply needs a single fast check at go-online and immediate enforcement on change.",
    without="Ineligible drivers online; or Supply calling four services on every go-online.", guar=["Go-online denied if any input says ineligible or snapshot expired (valid_until passed)", "Change to ineligible forces offline (after current trip)"], nong=["Computing eligibility (Onboarding does)"],
    usecase="Driver hits 12 h online. Fatigue counter crosses the limit, the gate forces OFFLINE after the current trip, and the driver sees 'Take a 6-hour break'.",
    derive="- Inputs come from other domains, so cache them locally from events (with versions) and also check `valid_until` locally.\n- Fatigue requires accumulating online time, so shift sessions.\n- Enforcement mid-trip must not strand the rider, so use the OFFLINE_AFTER_TRIP state.",
    conc="Cache updates versioned per driver per source. Forced transitions use the same CAS as other transitions.", consistency="Eventually consistent copies (≤ seconds) + local expiry guard → fails safe.",
    idem="Applying the same eligibility version twice is a no-op.", order="Per-source version; older ignored.", restart="Cache rebuilt from source snapshots (bulk API) + events.", scale="One small record per driver.",
    arch="Local table `gate_inputs(driver_id, onboarding_eligible, onboarding_valid_until, onboarding_version, vehicle_active, vehicle_version, restricted, restriction_version, hours_rolling)`. `canGoOnline` is a pure check over the row and the current time. Event handlers update the row and, on a transition to ineligible, issue a force-offline.",
    modules=[["GateInputs", "Versioned copies"], ["GateCheck", "Pure decision with reasons"], ["Enforcer", "Force offline / offline-after-trip"], ["FatigueCounter", "Rolling online hours"]],
    d_arch=("""flowchart LR
  ON["Onboarding events"] --> GI[("gate_inputs")]
  VE["Vehicle events"] --> GI
  RK["Risk restrictions"] --> GI
  SH["Shift sessions"] --> FC["FatigueCounter"] --> GI
  GO["go online"] --> GC["GateCheck"] --> GI
  GI --> ENF["Enforcer"] --> SM["Availability CAS"]""", "Event-maintained local inputs and a pure check."),
    d_seq=("""sequenceDiagram
  participant O as Onboarding
  participant G as Gate
  participant S as StateMachine
  O->>G: DriverEligibilityChanged(v9, eligible=false)
  G->>G: apply if v9 > stored
  G->>S: force(driver): AVAILABLE→OFFLINE or ON_TRIP→OFFLINE_AFTER_TRIP
  S-->>G: ok""", "Enforcement of an ineligibility event."),
    nostate="The gate is stateless decision logic over versioned inputs. Driver states are defined in the availability state machine.",
    d_flow=("""flowchart LR
  I["inputs row"] --> C{"eligible AND valid_until>now AND vehicle_active AND NOT restricted AND hours<limit"} -->|yes| OK["allow"]
  C -->|no| NO["deny + reasons"]""", "The decision predicate."),
    d_fail=("""flowchart TB
  E["event lag"] --> V["valid_until local check denies expired"]
  M["inputs missing for driver"] --> D["deny (fail closed) + fetch snapshot"]""", "Missing data means deny."),
    sql="""CREATE TABLE supply.gate_inputs (driver_id uuid PRIMARY KEY,
  onboarding_eligible boolean NOT NULL DEFAULT false, onboarding_valid_until timestamptz, onboarding_version bigint NOT NULL DEFAULT 0,
  vehicle_active boolean NOT NULL DEFAULT false, vehicle_version bigint NOT NULL DEFAULT 0,
  restricted boolean NOT NULL DEFAULT false, restriction_version bigint NOT NULL DEFAULT 0,
  online_seconds_24h int NOT NULL DEFAULT 0);""",
    data="Derived copy; may be rebuilt anytime.", api="""GateDecision canGoOnline(UUID driver, Instant now) -> {allowed, reasons[]}
POST /v1/drivers/me/online -> 200 | 403 {reasons:["INSURANCE_EXPIRED","FATIGUE_LIMIT"]}""",
    mech=[("Versioned materialized copies", "Each upstream source has its own version column, so out-of-order events from different sources don't overwrite each other."), ("Fail closed", "Absent or stale inputs deny. The cost is a support ticket. The alternative cost is a safety incident.")],
    code="""public GateDecision canGoOnline(GateInputs g, Instant now) {
    var reasons = new ArrayList<String>();
    if (!g.onboardingEligible() || g.validUntil() == null || !g.validUntil().isAfter(now)) reasons.add("NOT_ELIGIBLE");
    if (!g.vehicleActive()) reasons.add("NO_ACTIVE_VEHICLE");
    if (g.restricted()) reasons.add("RESTRICTED");
    if (g.onlineSeconds24h() >= limits.maxOnlineSeconds()) reasons.add("FATIGUE_LIMIT");
    return new GateDecision(reasons.isEmpty(), reasons);
}""", cx="O(1).",
    fail=[F("Upstream events delayed", "Version lag metric", "Late enforcement", "Local valid_until guard", "Bounded"), F("Missing row", "Lookup miss", "Driver can't go online", "Synchronous snapshot fetch", "Converges")],
    alts=[["Synchronous calls to each source", "Rejected", "Latency/availability coupling", "Phase I in monolith (same DB)"], ["Single eligibility owner aggregating all", "Viable", "Onboarding could aggregate vehicle+risk", "If sources stay few"]],
    adrs=[A("Local copies with versions", "III", "Sources become separate services.", [("Sync fan-out", "Rejected"), ("Event-fed copies", "Chosen")], "Gate keeps versioned copies.", "Fast, resilient.", "Staleness bounded by events + guards.", "N/A")],
    qa=[Q("Safety", "How is fatigue measured if the driver toggles offline for 1 minute every 2 hours?", "Count online time over a rolling 24-hour window, and require a continuous offline break of N hours (e.g. 6) to reset. Short breaks don't reset the counter. Shift sessions record intervals, and the counter sums intervals in the window.", "Counting from the last login is trivially gamed.")],
    tests=[T("Unit", "valid_until = now", "Denied"), T("Integration", "Restriction while ON_TRIP", "OFFLINE_AFTER_TRIP; offline at completion"), T("Unit", "Out-of-order vehicle events", "Higher version wins")],
    evo=["I: Direct reads from onboarding/vehicle tables (same DB)", "E: Fatigue counter; restrictions", "R: Event-fed versioned copies", "U: No change needed: inside Supply service", "E: Moves with the in-memory shard", "E: Regional"],
    ideas={"now": ["Reasons in UX"], "next": ["Predictive warnings before limit"], "adv": ["Fatigue from telematics"], "rej": ["Fail open on missing data"]})

sub(id="liveness-monitor", comp="driver-supply", name="Heartbeat & Liveness Monitor", phase="II", cat="Reliability · Failure detection",
    resp="Detect drivers who stopped sending heartbeats (app killed, no signal) and move them out of the available pool.",
    inp="location updates as heartbeats", out="forced OFFLINE transitions", deps="Location ingest", cons="Availability state machine, Geo index", own="last_heartbeat_at",
    problem="Drivers vanish without logging off. Dispatching to a ghost wastes 15 s per offer and frustrates riders.",
    without="Ghost drivers inflate supply, surge pricing reads wrong, and offers time out.", guar=["AVAILABLE drivers with no heartbeat for 60 s are moved OFFLINE", "ON_TRIP drivers are not auto-offlined (trip safety flow instead)"], nong=["Distinguishing app-killed from tunnel"],
    usecase="Driver enters a parking garage. After 45 s without signal the geo index marks them stale (excluded from candidates). At 60 s the monitor moves them OFFLINE, and when they reappear, the app prompts to go online again.",
    derive="- Writing last_heartbeat to the DB on every GPS ping (every 4 s) is costly, so keep heartbeats in memory/Redis and sweep.\n- Use two thresholds: soft (stale, excluded from matching) and hard (offline), to avoid flapping.",
    conc="Sweeper uses CAS `WHERE state='AVAILABLE' AND last_heartbeat < now()-60s`. Concurrent heartbeat wins if it updates first.", consistency="Approximate by design (seconds).",
    idem="Forcing offline an already-offline driver is a no-op.", order="Heartbeats carry device timestamps; ignore older than stored.", restart="Redis sorted set by last-seen time survives restarts (AOF). On loss, all drivers become stale and must re-heartbeat within seconds.",
    scale="Phase V: 60K heartbeats/s handled as part of the location stream (Flink session windows) rather than per-update writes.",
    arch="Phase II: `ZADD heartbeats <ts> <driver>` per update. A sweeper every 10 s runs `ZRANGEBYSCORE heartbeats 0 now-60` and issues CAS offline. Phase V: a Flink keyed process function with timers per driver emits `DriverWentSilent`.",
    modules=[["HeartbeatRecorder", "ZADD on location ingest"], ["StaleMarker", "Soft threshold → geo exclusion"], ["Sweeper", "Hard threshold → CAS offline"]],
    d_arch=("""flowchart LR
  LOC["Location ingest"] -->|ZADD ts driver| Z[("Redis ZSET heartbeats")]
  SW["Sweeper (10s)"] -->|ZRANGEBYSCORE| Z
  SW -->|CAS offline| SM["Availability"]
  GEO["Geo index"] -->|exclude if > 45s| Z""", "A sorted set ordered by last-seen time makes 'who is silent' a range query."),
    d_seq=("""sequenceDiagram
  participant S as Sweeper
  participant Z as Redis
  participant M as StateMachine
  S->>Z: ZRANGEBYSCORE heartbeats 0 (now-60s)
  Z-->>S: [d1, d2]
  S->>M: forceOffline(d1, reason=SILENT)
  S->>M: forceOffline(d2, reason=SILENT)
  S->>Z: ZREM d1 d2""", "Sweep cycle."),
    nostate="Liveness is a derived property (age of last heartbeat). The resulting transitions belong to the availability state machine.",
    d_flow=("""flowchart LR
  GPS["GPS update"] --> HB["heartbeat ts"] --> Z[("ZSET")] --> SWP["sweeper"] --> OFF["OFFLINE"]""", "Heartbeats piggyback on location updates, so there is no extra traffic."),
    d_fail=("""flowchart TB
  SW["sweeper down"] --> STALE["geo index still excludes >45s drivers"]
  R["Redis lost"] --> ALL["all stale until re-heartbeat (seconds)"]""", "Failure shrinks supply briefly instead of including ghosts."),
    sql="-- No relational table: Redis ZSET `hb:{city}` (member=driver_id, score=epoch_ms). last_heartbeat_at copied to driver_status on transitions only.",
    data="Ephemeral. Not retained.", api="""void recordHeartbeat(UUID driver, String city, long epochMs)
event DriverWentSilent{driver_id, last_seen_at}""",
    mech=[("Sorted-set expiry index", "Score = timestamp, so the silent drivers are a prefix range. O(log n + k)."), ("Two-threshold hysteresis", "A soft exclusion at 45 s and a hard offline at 60 s avoid flapping in brief signal loss.")],
    code="""@Scheduled(fixedDelay = 10_000)
void sweep() {
    long cutoff = clock.millis() - 60_000;
    for (String city : cities.active()) {
        Set<String> silent = redis.zrangeByScore("hb:" + city, 0, cutoff, 0, 500);
        silent.forEach(d -> supply.forceOffline(UUID.fromString(d), "SILENT"));
        if (!silent.isEmpty()) redis.zrem("hb:" + city, silent.toArray(String[]::new));
    }
}""", cx="O(log n + k) per city per sweep.",
    fail=[F("Sweeper lag", "Sweep duration metric", "Ghosts linger", "Geo soft exclusion", "Bounded"), F("Clock skew between ingest nodes", "Skew alarm", "Wrong ordering", "Use server receive time, NTP", "None")],
    alts=[["DB column updated per ping", "Rejected", "Write storm", "Phase I tiny scale"], ["Key TTL expiry notifications", "Rejected", "Redis keyspace notifications are lossy", "Never for correctness"]],
    adrs=[A("ZSET sweep over keyspace notifications", "II", "Need reliable detection.", [("Keyspace notifications", "Rejected: fire-and-forget"), ("ZSET sweep", "Chosen")], "Sweep sorted set.", "Reliable and simple.", "10 s granularity.", "Phase V → Flink timers.")],
    qa=[Q("Distributed systems", "Is a heartbeat timeout a reliable failure detector?", "No. It cannot distinguish a slow network from a dead app. That's why it only removes the driver from the *available pool*, which is safe if wrong (the driver can go online again), and never auto-cancels trips. Trip-level silence goes to the safety flow instead.", "")],
    tests=[T("Unit", "Heartbeat at T, sweep at T+61", "Offline"), T("Integration", "Heartbeat arrives during sweep", "CAS fails; stays available")],
    evo=["N: Phase I relies on drivers logging off plus offer timeouts", "I: Redis ZSET + sweeper", "E: DriverWentSilent event", "U: No change needed: part of Supply service", "R: Flink keyed timers on location stream", "E: Regional"],
    ideas={"now": ["Soft exclusion threshold"], "next": ["App foreground/background signals"], "adv": ["Adaptive thresholds per network quality"], "rej": ["Auto-cancel trips on silence"]})

# ======================================================================= Fleet & Vehicle
comp(id="fleet-vehicle", domain="driver", name="Fleet & Vehicle Management", tag="Supply · Assets", phase="I", kind="Logical component (inside Driver service from Phase IV)",
     biz="Registers vehicles, their categories and inspections, links them to drivers, and lets fleet owners manage multiple drivers and cars.",
     eng="An asset registry with driver↔vehicle assignment invariants that determines which product categories a driver can serve.",
     deploy="Module; part of Driver service (Phase IV).", data_own="vehicles, vehicle_documents, driver_vehicle_links, fleets, fleet_memberships.",
     up=["driver-onboarding"], down=["driver-supply", "product-catalog", "dispatch", "driver-earnings"], ext=["Vehicle registries", "Insurance APIs"],
     interfaces="REST `/v1/vehicles`, `/v1/fleets`; events `VehicleStatusChanged`, `ActiveVehicleChanged`.",
     problem="Dispatch must know what vehicle a driver is in (category, seats, plate for rider safety), and vehicles have their own compliance.",
     fr=["Register vehicle with documents", "Map vehicle to eligible categories (UberX, XL, Black)", "Driver selects active vehicle at go-online", "Fleet owners add drivers/vehicles (Phase IV)"],
     nfr=["Active vehicle read p99 < 10 ms (cached)", "Plate shown to rider must match the real car"], workload="Low writes; reads on every dispatch (cached in Supply).",
     success="Riders see the correct plate and car; categories accurate.", failure="Wrong car shown (safety risk); driver serving a category the vehicle isn't approved for.",
     derive="A vehicle is used by at most one driver at a time (active), but may be linked to several (fleet). Categories derive from vehicle attributes plus city rules, so compute and store category eligibility.",
     owns=["Vehicle records and docs", "Driver–vehicle links", "Fleets"], not_owns=["Driver eligibility", "Pricing per category"], sync=["Register", "Set active vehicle"], **{"async": ["Vehicle doc expiry", "Category recompute on rule change"]},
     boundary_why="Vehicles have a different lifecycle than drivers (one car shared by drivers in a fleet), so they get their own aggregate.",
     hld=("""flowchart LR
  DA["Driver app"] --> VR["Vehicle registry"]
  FO["Fleet owner portal"] --> FA["Fleet accounts"]
  FA --> VR
  VR --> DB[("vehicles, links")]
  VR -->|ActiveVehicleChanged| SUP["Supply"]
  VR -->|categories| CAT["Product catalog"]""", "Registry plus fleet layer."),
     seq=("""sequenceDiagram
  participant D as Driver
  participant V as VehicleRegistry
  participant S as Supply
  D->>V: set active vehicle (veh 9)
  V->>V: CAS: vehicle not active for another driver
  V-->>S: ActiveVehicleChanged(driver, veh 9, categories)
  D->>S: go online""", "Choosing a vehicle before going online."),
     subdeps=[("fleet-accounts", "vehicle-registry")],
     flow="Vehicle registration mirrors document verification for vehicle docs. Activation is an atomic claim. Category eligibility goes to Supply and Dispatch.",
     data="`vehicles(id, plate, make, model, year, color, seats, status, city)`, `vehicle_categories(vehicle_id, category)`, `driver_vehicle_links(driver_id, vehicle_id, active)` with a unique active per vehicle and per driver, `fleets(id, owner_id)`, `fleet_memberships`.",
     rel=[["Atomic activation", "Partial unique indexes guarantee one active driver per vehicle and one active vehicle per driver."], ["Expiry", "Vehicle inspection expiry → VehicleStatusChanged → gate."]],
     sec=[["Fleet owner access", "Fleet owners see only their fleet's drivers (relationship authz)."], ["Privacy", "Plates are shown to riders only during a trip."]],
     adrs=[A("Separate vehicle aggregate", "I", "Fleets share vehicles.", [("Vehicle fields on driver", "Rejected"), ("Separate aggregate", "Chosen")], "Vehicles + links.", "Supports fleets.", "Join on reads (cached).", "N/A")],
     qa=[Q("Concurrency", "Two fleet drivers try to activate the same car at shift change. What happens?", "`UPDATE driver_vehicle_links SET active=true WHERE driver_id=? AND vehicle_id=?` is guarded by the partial unique index `(vehicle_id) WHERE active`. The second activation fails with a unique violation, mapped to VEHICLE_IN_USE. The first driver must go offline (which deactivates) before handover.", "")],
     impl_order=["vehicle-registry", "fleet-accounts"], pkg="""com.atlas.driver.fleet
├── vehicle (VehicleService, CategoryRules)
└── fleet   (FleetService, Membership)""",
     tests=[T("Concurrency", "Parallel activation", "One VEHICLE_IN_USE"), T("Unit", "2012 sedan for Black", "Category not granted")],
     evo=[("I", "Module", "Tables", "Unique indexes", "Correct car shown"), ("U", "No change needed", "—", "—", "—"), ("E", "Same", "Events", "Versioned", "Consumers"), ("E", "Part of Driver service; fleet portal", "Own DB", "Relationship authz", "Fleet product"), ("U", "No change needed", "—", "—", "—"), ("E", "Regional", "—", "—", "Residency")],
     ideas={"now": ["Plate photo verification"], "next": ["Telematics integration"], "adv": ["EV range-aware dispatch"], "rej": ["Free-text category"]})

sub(id="vehicle-registry", comp="fleet-vehicle", name="Vehicle Registry & Activation", phase="I", cat="Domain · Asset registry",
    resp="Register vehicles, verify their documents, derive category eligibility, and atomically bind one active vehicle to one driver.",
    inp="vehicle data, docs, activation requests, city category rules", out="vehicle status, categories, ActiveVehicleChanged", deps="Document verification (reused), category rules", cons="Supply, Catalog, Trip (plate for rider)", own="vehicles, vehicle_categories, driver_vehicle_links",
    problem="Dispatch and riders need the actual car's details and eligible categories, and a car can't be in two places.",
    without="Wrong plate shown, or category fraud.", guar=["One active driver per vehicle and one active vehicle per driver", "Categories reflect current rules + attributes"], nong=["Real-time vehicle telemetry"],
    usecase="Driver adds a 2023 Toyota Innova (7 seats). Rules grant UberX and XL. Activation publishes categories, and dispatch can offer XL requests.",
    derive="- Uniqueness of active bindings belongs in DB constraints.\n- Categories are a function of attributes and rules, so recompute on either change.",
    conc="Partial unique indexes on active links; activation in a transaction that deactivates the driver's previous vehicle first.", consistency="Strong: the link table is the single source of truth and is updated in one transaction with the outbox event.", idem="Activation of an already-active pair is a no-op.", order="Events versioned per vehicle.",
    restart="State lives only in PostgreSQL. The outbox guarantees ActiveVehicleChanged is published after a crash.", scale="One row per vehicle; reads are served from Supply's cached copy, so the registry sees only registration and activation writes (≈ a few per second at Phase V).", arch="CRUD + rules evaluation + activation transaction.",
    modules=[["VehicleService", "CRUD, docs"], ["CategoryRules", "Attributes × city rules"], ["Activation", "Atomic bind"]],
    d_arch=("""flowchart LR
  D["Driver"] --> VS["VehicleService"] --> DB[("vehicles")]
  VS --> CR["CategoryRules"] --> VC[("vehicle_categories")]
  D --> ACT["Activation"] --> L[("driver_vehicle_links")]
  ACT --> EV["ActiveVehicleChanged"]""", "Three operations on one aggregate."),
    d_seq=("""sequenceDiagram
  participant D as Driver
  participant A as Activation
  participant DB
  D->>A: activate(veh 9)
  A->>DB: UPDATE links SET active=false WHERE driver=D
  A->>DB: UPDATE links SET active=true WHERE driver=D AND vehicle=9
  DB-->>A: ok or unique violation
  A-->>D: 200 or 409 VEHICLE_IN_USE""", "Activation transaction."),
    d_state=("""stateDiagram-v2
  [*] --> PendingDocs
  PendingDocs --> Active: docs verified
  Active --> Suspended: inspection expired
  Suspended --> Active: re-inspected
  Active --> Retired""", "Vehicle lifecycle."),
    d_flow=("""flowchart LR
  ATTR["year, seats, model"] --> R["city rules"] --> CATS["eligible categories"] --> SUP["Supply/Dispatch"]""", "Category derivation."),
    d_fail=("""flowchart TB
  RC["rule change"] --> RJ["recompute job"] --> EV["events for changed vehicles"]""", "Rule changes are applied by a recompute job."),
    sql="""CREATE TABLE fleet.driver_vehicle_links (driver_id uuid, vehicle_id uuid, active boolean NOT NULL DEFAULT false, PRIMARY KEY(driver_id, vehicle_id));
CREATE UNIQUE INDEX one_active_driver_per_vehicle ON fleet.driver_vehicle_links(vehicle_id) WHERE active;
CREATE UNIQUE INDEX one_active_vehicle_per_driver ON fleet.driver_vehicle_links(driver_id) WHERE active;""",
    data="Vehicles retained after retirement for trip history references (plate shown on old receipts).", api="""POST /v1/vehicles {...} -> 201
POST /v1/vehicles/{id}/activate -> 200 | 409 VEHICLE_IN_USE | 403 VEHICLE_NOT_ACTIVE
event ActiveVehicleChanged{driver_id, vehicle_id, categories[], seats, version}""",
    mech=[("Partial unique indexes as invariants", "The database refuses an illegal state regardless of application bugs or races.")],
    code="""@Transactional
public void activate(UUID driver, UUID vehicle) {
    if (!vehicles.isActive(vehicle)) throw new VehicleNotActive();
    links.deactivateAllFor(driver);
    try { links.activate(driver, vehicle); } catch (DuplicateKeyException e) { throw new VehicleInUse(); }
    outbox.add(new ActiveVehicleChanged(driver, vehicle, categories.of(vehicle)));
}""", cx="O(1).",
    fail=[F("Race on activation", "Unique violation", "One fails", "User retries later", "Single binding")],
    alts=[["App-level check", "Rejected", "Race-prone", "Never"]],
    adrs=[A("DB-enforced binding", "I", "Safety-critical correctness.", [("App check", "Rejected"), ("Partial unique", "Chosen")], "Constraints.", "Race-proof.", "Postgres-specific feature.", "N/A")],
    qa=[Q("Safety", "How do you ensure the plate shown to riders matches the car that arrives?", "Plate is verified from the registration document and photo at registration. Drivers can only drive the active vehicle. Riders get a 'wrong car?' button that triggers a safety check. Periodic in-app photo checks of the plate (selfie + car) are required.", "")],
    tests=[T("Concurrency", "Two drivers activate", "One 409"), T("Unit", "Category rules for 7 seats", "XL granted")],
    evo=["I: Registry + activation", "U: No change needed", "E: Events", "E: In Driver service", "U: No change needed", "E: Regional"], ideas={"now": ["Constraints"], "next": ["Plate photo checks"], "adv": ["Telematics"], "rej": ["Free-form category"]})

sub(id="fleet-accounts", comp="fleet-vehicle", name="Fleet Accounts", phase="IV", cat="Domain · B2B",
    resp="Let fleet owners manage drivers and vehicles they own, see earnings splits, and assign cars to drivers.",
    inp="fleet owner actions, invitations", out="memberships, permissions, earnings split config", deps="Vehicle registry, Authorization (relationships), Earnings", cons="Fleet portal, Earnings", own="fleets, fleet_memberships",
    problem="In many markets drivers rent cars from fleet owners, and owners need management access without seeing riders' data.",
    without="Off-platform spreadsheets; earnings disputes.", guar=["Owners see only their fleet", "A driver belongs to at most one fleet at a time"], nong=["Payment between owner and driver beyond configured split"],
    usecase="Fleet owner F invites driver D. D accepts. Earnings split 70/30 is configured and applied to payouts.",
    derive="- Relationship-based access (owner → fleet → driver).\n- Membership requires consent from both sides, so an invitation flow.",
    conc="Unique active membership per driver.", consistency="Strong for memberships. Relationship tuples in authorization are eventually consistent (seconds), and access is denied until the tuple arrives.", idem="Invitations idempotent per (fleet, driver).", order="Membership changes versioned.", restart="DB-backed. RelationshipSync re-sends all active tuples on start (idempotent upserts).", scale="Fleets have tens to thousands of drivers. Fleet listings are paginated and indexed by fleet_id.",
    arch="Invitation state machine plus relationship tuples consumed by authorization.", modules=[["FleetService", "Fleets, invitations"], ["SplitConfig", "Earnings split"], ["RelationshipSync", "Tuples to authz"]],
    d_arch=("""flowchart LR
  FO["Owner"] --> FS["FleetService"] --> DB[("fleets, memberships")]
  FS --> RS["RelationshipSync"] --> AZ["Authorization"]
  FS --> SC["SplitConfig"] --> ERN["Earnings"]""", "Fleet relationships feed both authorization and earnings."),
    d_seq=("""sequenceDiagram
  participant O as Owner
  participant F as FleetService
  participant D as Driver
  O->>F: invite(D)
  F-->>D: notification
  D->>F: accept
  F->>F: membership active (unique per driver)""", "Invitation flow."),
    d_state=("""stateDiagram-v2
  [*] --> Invited
  Invited --> Active: accepted
  Invited --> Expired
  Active --> Ended: either side leaves""", "Membership lifecycle."),
    d_flow=("""flowchart LR
  M["membership"] --> T["relationship tuple owner→driver"] --> AZ["authz decisions"]""", "Relationship data."),
    d_fail=("""flowchart TB
  S["relationship sync lag"] --> D["owner sees driver late; deny by default"]""", "Fail closed."),
    sql="""CREATE TABLE fleet.fleet_memberships (fleet_id uuid, driver_id uuid, status text NOT NULL, split_pct numeric(5,2), PRIMARY KEY (fleet_id, driver_id));
CREATE UNIQUE INDEX one_active_fleet ON fleet.fleet_memberships(driver_id) WHERE status='Active';""",
    data="Membership history retained for earnings audit.", api="""POST /v1/fleets/{id}/invitations {driver_phone} -> 201
POST /v1/fleet-invitations/{id}/accept -> 200
GET  /v1/fleets/{id}/drivers -> [...]""",
    mech=[("Relationship-based authorization", "Owner can read driver D's earnings iff a tuple fleet:F#owner@O and fleet:F#member@D exists.")],
    code="""public boolean canView(UUID owner, UUID driver) { return memberships.activeFleetOf(driver).map(f -> fleets.ownerOf(f).equals(owner)).orElse(false); }""", cx="O(1).",
    fail=[F("Driver joins two fleets", "Unique violation", "Rejected", "Leave first", "Single membership")],
    alts=[["Shared driver accounts", "Rejected", "Security", "Never"]],
    adrs=[A("Introduce fleets at Phase IV", "IV", "Fleet-heavy market launch.", [("Earlier", "No demand"), ("Phase IV", "Chosen")], "Add fleets.", "Demand-driven.", "Authz complexity.", "N/A")],
    qa=[Q("Privacy", "Can fleet owners see trip routes of their drivers?", "Only aggregated data: hours, earnings, trip count, and vehicle usage. Not rider identities or exact routes, which are rider personal data. A disputed trip goes to support.", "")],
    tests=[T("Security", "Owner A reads driver of fleet B", "403"), T("Concurrency", "Accept two invitations", "One fails")],
    evo=["N: Not needed for a pilot", "N: Not needed", "N: Not needed", "I: Fleets + relationship authz", "E: Fleet analytics", "E: Regional"], ideas={"now": ["n/a"], "next": ["Fleet payouts"], "adv": ["Vehicle leasing marketplace"], "rej": ["Owner access to rider PII"]})
