from model import comp, sub, A, Q, F, T

# ======================================================================= Payment Orchestration
comp(id="payments", domain="payments", name="Payment Orchestration", tag="Money · PCI", phase="I", kind="Logical component → deployable service in PCI-minimized zone (Phase IV)",
     biz="Charges riders reliably for completed trips and fees, with the payment methods they prefer, without double charges and with minimal fraud losses.",
     eng="Orchestrates the payment lifecycle (tokenize → authorize → capture → refund) against external PSPs, with idempotency, retries, failover and a complete record of intents and attempts.",
     deploy="Module (I); Payment service (IV) in a segregated network zone; regional PSP routing (VI).", data_own="payment_methods (tokens only), payment_intents, payment_attempts, captures, refunds.",
     up=["identity", "risk-fraud", "fare-finalization", "ride-request"], down=["ledger", "receipts", "support", "wallet"], ext=["PSPs (Stripe, Adyen, Braintree)", "Local wallets/UPI", "Card network tokens"],
     interfaces="`authorize(intent)`, `capture(intent, amount)`, `void`, `refund`; PSP webhooks; events `PaymentAuthorized`, `PaymentCaptured`, `PaymentFailed`, `RefundIssued`.",
     problem="PSPs are slow, occasionally fail ambiguously (timeout after charging), and send asynchronous webhooks. Card data must never touch our servers. Money operations must be exactly-once in effect.",
     fr=["Add/remove payment methods via PSP tokenization", "Authorize hold at request", "Capture final fare after trip", "Void/partial capture", "Refunds", "Retry failed captures", "Multiple PSPs with failover"],
     nfr=["Authorize p95 < 1.5 s", "No duplicate captures (0 tolerance)", "Capture success within 72 h > 99.5%", "PCI DSS scope: SAQ-A (no PAN storage)"],
     workload="Two PSP calls per trip (auth, capture) + refunds; Phase V ≈ 1,000 PSP calls/s peak.", success="Every completed trip captured once; low decline and fraud rates.", failure="Double charges, lost revenue, PCI breach.",
     derive="Ambiguous PSP results (timeouts) are inevitable, so every PSP call carries an idempotency key and every attempt is recorded before the call (intent log) so outcomes can be queried and reconciled. The money lifecycle is a state machine per payment intent. PCI scope is minimized by client-side tokenization (card → PSP directly).",
     owns=["Payment intents and attempts", "PSP integration", "Method tokens"], not_owns=["Fare amount (Fare finalization)", "Accounting (Ledger)", "Fraud decisions (Risk)"], sync=["Authorize at request", "Method management"], **{"async": ["Capture after FareFinalized", "Retries", "Webhooks", "Refunds"]},
     boundary_why="Payments speaks to the outside financial world. The Ledger records internal truth. Keeping them separate lets the ledger stay PSP-agnostic and lets payments fail and retry without corrupting accounting.",
     hld=("""flowchart LR
  APP["App"] -->|card via PSP SDK| PSP1["PSP"]
  APP -->|token| VAULT["Payment method vault"]
  REQ["Ride request"] -->|authorize| AC["Authorization & capture"]
  FARE["FareFinalized"] --> AC
  AC --> RT["PSP router"] --> PSP1 & PSP2["PSP B"]
  PSP1 & PSP2 -->|webhooks| WH["Webhook handler"] --> AC
  AC -->|PaymentCaptured| LED["Ledger"]
  AC --> DB[("intents, attempts")]""", "Tokenization keeps card data at the PSP. Authorization and capture is a per-intent state machine. The router chooses a PSP, webhooks confirm outcomes, and the ledger records results."),
     seq=("""sequenceDiagram
  participant R as Request
  participant P as Payments
  participant S as PSP
  participant L as Ledger
  R->>P: authorize(req, ₹300 hold)
  P->>P: intent AUTH_PENDING, attempt row
  P->>S: authorize (Idempotency-Key)
  S-->>P: authorized auth_123
  Note over P: trip happens
  P->>S: capture(auth_123, ₹267, key)
  S-->>P: captured
  P->>L: PaymentCaptured(trip, ₹267)""", "Authorize at request, capture after the fare is final."),
     state=("""stateDiagram-v2
  [*] --> CREATED
  CREATED --> AUTHORIZED
  CREATED --> AUTH_FAILED
  AUTHORIZED --> CAPTURED
  AUTHORIZED --> VOIDED: trip cancelled without fee
  AUTHORIZED --> CAPTURE_RETRYING: capture failed (retryable)
  CAPTURE_RETRYING --> CAPTURED
  CAPTURE_RETRYING --> CAPTURE_FAILED: retries exhausted (collections)
  CAPTURED --> PARTIALLY_REFUNDED
  CAPTURED --> REFUNDED""", "Payment intent lifecycle."),
     subdeps=[("auth-capture", "payment-vault"), ("auth-capture", "psp-router")],
     flow="Intents are created per ride request. Each PSP interaction is an attempt row written before the call with a deterministic idempotency key. Outcomes come from synchronous responses or webhooks, whichever arrives first, applied idempotently. Ledger events follow state changes via outbox.",
     data="`payment_methods(id, user_id, psp, psp_token, network_token_ref, brand, last4, exp, fingerprint, status)`, `payment_intents(id, request_id UNIQUE, trip_id, amount_auth, amount_captured, currency, state, psp, version)`, `payment_attempts(id, intent_id, kind, idem_key UNIQUE, psp_ref, status, request, response, created_at)`.",
     rel=[["Idempotency", "PSP idempotency keys = `{intent}:{kind}:{n}`; unique attempt keys."], ["Ambiguity", "Timeouts → status lookup by idempotency key before retry."], ["Retries", "Capture retries with backoff for 72 h; card updater; alternate method."], ["Failover", "Router per PSP breaker (auth only; capture must use the authorizing PSP)."]],
     sec=[["PCI", "No PAN/CVV ever on our servers; tokens only; SAQ-A."], ["Secrets", "PSP keys in HSM-backed secrets manager; webhook HMAC verification."], ["Fraud", "Risk score gates authorization; 3-D Secure step-up where required."]],
     adrs=[A("Record attempt before PSP call", "I", "Ambiguous outcomes.", [("Call then record", "Rejected: crash loses knowledge of charge"), ("Record then call", "Chosen")], "Attempt row (PENDING) committed before call; updated after.", "Every charge traceable and recoverable.", "Extra write per call.", "N/A")],
     qa=[Q("Distributed systems", "Capture request times out at the PSP. Did we charge the rider?", "Unknown, so never blindly retry with a new key. Retry with the *same* idempotency key: the PSP returns the original result if it processed it, or processes it once if it didn't. If the PSP is down, the attempt stays PENDING, and a recovery job queries status by idempotency key or reference until resolved. The webhook may also resolve it. Ledger posting waits for a definitive outcome.", "Retrying with a new key risks double charges. Assuming failure risks lost revenue and wrong customer messaging.")],
     impl_order=["payment-vault", "auth-capture", "psp-router"], pkg="""com.atlas.payments
├── methods  (PaymentMethodService, PspTokenizer)
├── intent   (PaymentIntent, IntentStateMachine, AttemptLog)
├── psp      (PspRouter, StripeAdapter, AdyenAdapter, WebhookController)
└── recovery (PendingAttemptResolver, CaptureRetryScheduler)""",
     tests=[T("Failure", "PSP timeout then success on retry", "One capture"), T("Contract", "PSP sandbox webhooks", "States converge"), T("Security", "Log scan for PAN patterns", "None found")],
     evo=[("I", "Module; one PSP", "PG intents + attempts", "Idempotency keys; attempt-before-call", "Correctness"), ("E", "Same", "Capture via queue", "Retries, breaker, webhook handling", "Reliability"),
          ("R", "Saga steps driven by events", "Outbox", "Pending-attempt resolver", "Async"), ("R", "Payment service, PCI zone", "Own DB", "Multi-PSP router", "Isolation & failover"),
          ("E", "Smart retries, network tokens", "—", "Risk-based deferral", "Scale"), ("E", "Regional PSPs/methods (UPI, Pix)", "In-region processing", "Residency", "Global")],
     ideas={"now": ["Attempt log"], "next": ["Network tokens"], "adv": ["Local payment methods per market"], "rej": ["Storing PANs"]})

sub(id="payment-vault", comp="payments", name="Payment Method Vault (Tokenization)", phase="I", cat="Security · PCI",
    resp="Let users add, list and remove payment methods while card data is tokenized client-side by the PSP and only tokens and display metadata are stored.",
    inp="PSP tokens from client SDK, user commands", out="payment method records", deps="PSP tokenization APIs, Risk (fingerprint velocity)", cons="Auth & capture, Rider app", own="payment_methods",
    problem="Accept cards without entering PCI scope, and detect stolen-card patterns.", without="Massive PCI scope or fraud.",
    guar=["No PAN/CVV persisted or logged", "Each method tied to one user; fingerprint stored for duplicate detection", "Removal prevents future use"], nong=["Card validity beyond PSP verification"],
    usecase="Rider adds a card in the PSP's SDK sheet, the app receives `pm_abc`, and the server attaches it to the PSP customer with a $0 verification. Stored: brand VISA, last4 4242, exp 11/28, fingerprint f9a…",
    derive="- Client-side tokenization means card data goes device → PSP only.\n- The fingerprint (PSP-provided) shows the same card across accounts, which is a fraud signal.\n- A verification auth confirms the card works.",
    conc="Unique (user, fingerprint) for active methods; default flag via partial unique index.", consistency="Strong: method rows are written only after the PSP attach succeeds, in one local transaction.", idem="Attach with PSP idempotency key = token id.", order="User commands are sequential; version check on default changes.",
    restart="Stateless service. An attach that succeeded at the PSP but crashed before insert is retried with the same idempotency key (token id), which returns the same PSP result.", scale="Few methods per user.", arch="`PaymentMethodService.add(token)`: attach to PSP customer → verify → store metadata → emit risk signal (fingerprint used by N accounts).",
    modules=[["Attach", "PSP customer attach + verify"], ["MetadataStore", "Display info only"], ["FingerprintSignals", "Velocity to Risk"], ["DefaultSelector", "One default per user"]],
    d_arch=("""flowchart LR
  APP["App PSP SDK"] -->|PAN| PSP["PSP"]
  PSP -->|token| APP --> SVC["PaymentMethodService"] --> PSP
  SVC --> DB[("payment_methods")]
  SVC --> RISK["Risk signals"]""", "PAN flows only between the device and the PSP."),
    d_seq=("""sequenceDiagram
  participant A as App
  participant S as PSP
  participant V as Vault
  A->>S: tokenize card
  S-->>A: pm_abc
  A->>V: POST /payment-methods {token: pm_abc}
  V->>S: attach + $0 verify (key pm_abc)
  S-->>V: ok, fingerprint, last4
  V-->>A: 201""", "Add a card."),
    d_state=("""stateDiagram-v2
  [*] --> Active
  Active --> Expired: exp date passed (updater may refresh)
  Active --> Removed
  Active --> Blocked: risk""", "Payment method lifecycle."),
    d_flow=("""flowchart LR
  PAN["PAN"] -.->|never| SRV["our servers"]
  TOK["token"] --> SRV --> META["brand,last4,exp,fingerprint"]""", "Data minimization."),
    d_fail=("""flowchart TB
  V["verification declined"] --> R["reject add, suggest another card"]
  P["PSP down"] --> L["retry later; user notified"]""", "Fail closed."),
    sql="""CREATE TABLE payments.payment_methods (id uuid PRIMARY KEY, user_id uuid NOT NULL, psp text NOT NULL, psp_token text NOT NULL,
  brand text, last4 char(4), exp_month smallint, exp_year smallint, fingerprint text, is_default boolean NOT NULL DEFAULT false,
  status text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX one_default ON payments.payment_methods(user_id) WHERE is_default AND status='Active';
CREATE UNIQUE INDEX no_dup_card ON payments.payment_methods(user_id, fingerprint) WHERE status='Active';""",
    data="Tokens are not secrets usable outside our PSP account but are treated as confidential.", api="""POST /v1/payment-methods {psp_token} -> 201 {id, brand, last4, exp}
GET /v1/payment-methods -> [...]
DELETE /v1/payment-methods/{id} -> 204""",
    mech=[("Client-side tokenization", "The PSP's SDK posts card data directly to the PSP and returns a token, so our servers never see card data and PCI scope shrinks to SAQ-A.")],
    code="""public PaymentMethod add(UUID user, String token) {
    var r = psp.attachAndVerify(customerOf(user), token, /*idempotencyKey*/ token);
    risk.signal(new CardAdded(user, r.fingerprint()));
    return repo.insert(user, r.toMetadata());
}""", cx="O(1).",
    fail=[F("Same card added twice", "Unique fingerprint", "409", "Use existing", "No dup"), F("Card used across 20 accounts", "Velocity signal", "Fraud risk", "Block/step-up", "N/A")],
    alts=[["Own vault (PCI DSS L1)", "Rejected", "Huge compliance cost", "Massive scale with multi-PSP routing (use network tokens instead)"], ["PSP-agnostic vault vendor", "Next phase", "Multi-PSP portability", "Phase IV"]],
    adrs=[A("Network tokens for multi-PSP (Phase IV)", "IV", "Failover across PSPs needs portable tokens.", [("PSP-specific tokens", "Lock-in"), ("Network tokens via token service", "Chosen")], "Network tokens.", "Portability, higher auth rates.", "Integration effort.", "N/A")],
    qa=[Q("Security", "How do you prove PCI scope is minimal?", "Data-flow evidence: client SDK posts directly to the PSP domain (CSP/pinning), servers receive only tokens, and automated log/DB scanners detect PAN-like patterns (Luhn-valid 13–19 digit sequences) in logs, traces and tables, with zero tolerance alerts.", "")],
    tests=[T("Security", "PAN regex scan", "No matches"), T("Integration", "Add + remove", "Removed method unusable")],
    evo=["I: PSP tokens", "E: Card updater", "U: No change needed", "R: Network tokens, multi-PSP", "E: Local methods", "E: Regional"],
    ideas={"now": ["SAQ-A"], "next": ["Network tokens"], "adv": ["Passkey-bound payments"], "rej": ["Own card vault"]})

sub(id="auth-capture", comp="payments", name="Authorization & Capture", phase="I", cat="Money · Exactly-once effects",
    resp="Run the payment intent state machine: authorize holds, capture final amounts, void unused holds, retry failed captures, and resolve ambiguous outcomes.",
    inp="authorize commands, FareFinalized, cancellation fees, webhooks", out="intent states, PaymentCaptured/Failed events", deps="PSP router, Vault, Ledger (events)", cons="Request intake, Ledger, Receipts, Support", own="payment_intents, payment_attempts",
    problem="Exactly-once financial effects over an unreliable external API.", without="Double charges or lost revenue.",
    guar=["At most one successful capture per intent", "Every PSP call recorded before execution", "Every PENDING attempt resolved (by response, webhook or status query)", "Capture ≤ authorized amount (or re-auth)"], nong=["Capture success (cards decline)"],
    usecase="Final fare ₹267 vs hold ₹300: partial capture ₹267, remainder released automatically.",
    derive="- Intent state + version for transitions.\n- Attempts table as a write-ahead log for external calls.\n- Same idempotency key across retries of the same logical operation.\n- Webhooks and sync responses both update the attempt, first-writer-wins via conditional update.",
    conc="Intent transitions conditional on state/version. Attempt completion `UPDATE attempts SET status=? WHERE id=? AND status='PENDING'`.", consistency="Strong internally; external truth reconciled via PSP status and settlement files.",
    idem="PSP idempotency key `intent:{id}:capture:1`; FareFinalized consumer dedupes on trip_id (intent already CAPTURED).", order="Webhook may arrive before sync response; both apply to attempt via conditional update; intent transitions follow attempt status.",
    restart="PendingAttemptResolver scans PENDING attempts > 60 s and queries PSP by idempotency key.", scale="I/O-bound on PSP latency; worker pools sized by PSP concurrency limits.",
    arch="`IntentService` (state machine) + `AttemptLog` (WAL for PSP calls) + `PspRouter` + `WebhookHandler` + `PendingAttemptResolver` + `CaptureRetryScheduler` (smart retry schedule: +1 h, +6 h, +24 h, +72 h, card-updater check).",
    modules=[["IntentService", "Transitions"], ["AttemptLog", "Record-before-call"], ["WebhookHandler", "Verify, dedupe, apply"], ["PendingAttemptResolver", "Ambiguity resolution"], ["CaptureRetryScheduler", "Retry policy"]],
    d_arch=("""flowchart LR
  FF["FareFinalized"] --> IS["IntentService"] --> AL["AttemptLog"] --> DB[("intents, attempts")]
  IS --> PR["PspRouter"] --> PSP["PSP"]
  PSP -->|webhook| WH["WebhookHandler"] --> AL
  RES["PendingAttemptResolver"] --> AL & PSP
  CRS["CaptureRetryScheduler"] --> IS
  IS -->|outbox| LED["Ledger events"]""", "The attempt log sits between intent logic and the PSP."),
    d_seq=("""sequenceDiagram
  participant F as FareFinalized
  participant I as IntentService
  participant A as AttemptLog
  participant P as PSP
  F->>I: capture(trip, 267)
  I->>A: insert attempt(key intent:9:capture:1, PENDING) COMMIT
  I->>P: capture(auth, 267, key)
  P--xI: timeout
  Note over I: attempt stays PENDING
  P-->>A: webhook charge.captured (key)
  A->>A: PENDING→SUCCEEDED
  A->>I: intent AUTHORIZED→CAPTURED, outbox PaymentCaptured""", "Ambiguous timeout resolved by webhook."),
    d_state=("""stateDiagram-v2
  [*] --> PENDING
  PENDING --> SUCCEEDED: response/webhook/status
  PENDING --> FAILED_RETRYABLE
  PENDING --> FAILED_FINAL
  FAILED_RETRYABLE --> [*]: new attempt n+1 scheduled""", "Attempt lifecycle (the intent lifecycle is on the component page)."),
    d_flow=("""flowchart LR
  AMT["fare 267"] --> CAP["capture 267 of 300"] --> REL["release 33"] --> LED["ledger: rider receivable cleared"]""", "Partial capture."),
    d_fail=("""flowchart TB
  T["timeout"] --> P["attempt PENDING"] --> Q["status by idem key"] --> D["definitive state"]
  D2["decline"] --> R["retry schedule / alternate method / collections"]
  E["auth expired (7 days)"] --> RA["re-authorize then capture"]""", "Ambiguity, decline and expiry each have a path."),
    sql="""CREATE TABLE payments.payment_intents (id uuid PRIMARY KEY, request_id uuid NOT NULL UNIQUE, trip_id uuid UNIQUE, rider_id uuid NOT NULL,
  method_id uuid NOT NULL, currency char(3) NOT NULL, amount_authorized bigint, amount_captured bigint NOT NULL DEFAULT 0,
  psp text, psp_auth_ref text, state text NOT NULL, version int NOT NULL DEFAULT 0,
  CHECK (amount_captured <= coalesce(amount_authorized, amount_captured)));
CREATE TABLE payments.payment_attempts (id uuid PRIMARY KEY, intent_id uuid NOT NULL REFERENCES payments.payment_intents, kind text NOT NULL,
  seq int NOT NULL, idem_key text NOT NULL UNIQUE, amount bigint NOT NULL, status text NOT NULL, psp_ref text, error_code text,
  created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz, UNIQUE (intent_id, kind, seq));
CREATE INDEX attempts_pending ON payments.payment_attempts(created_at) WHERE status = 'PENDING';""",
    data="Retained 7+ years.", api="""internal: Authorization authorize(UUID requestId, UUID methodId, Money hold, String idemKey)
internal: void capture(UUID tripId, Money amount)    // idempotent per trip
POST /webhooks/psp/{psp}  (signature header)        -> 200
event PaymentCaptured{intent_id, trip_id, amount, psp, psp_ref, captured_at}""",
    mech=[("Write-ahead attempt log", "Before calling the PSP, commit a PENDING attempt with the idempotency key. Whatever happens next (crash, timeout), we know an operation may have occurred and can ask the PSP about it using the key."), ("Idempotency keys at the PSP", "PSPs store the key with the result for ~24 h+, so a repeated request returns the stored result instead of charging again."), ("Smart retry schedule", "Declines like 'insufficient funds' succeed later more often, so retry at spaced intervals. Hard declines ('stolen card') are not retried.")],
    code="""public void capture(UUID tripId, Money amount) {
    var intent = intents.byTrip(tripId);
    if (intent.state() == CAPTURED) return;                                  // idempotent
    var att = attempts.insertPending(intent.id(), CAPTURE, amount);          // committed before call
    try {
        var r = router.forIntent(intent).capture(intent.pspAuthRef(), amount, att.idemKey());
        attempts.complete(att.id(), r);                                     // conditional on PENDING
    } catch (PspTimeout e) { /* leave PENDING: resolver/webhook will settle */ return; }
    intents.applyAttemptOutcome(intent.id(), att.id());                      // state machine + outbox
}""", cx="O(1) + PSP latency.",
    fail=[F("Ambiguous timeout", "PENDING > 60 s", "Unknown charge", "Status query by key", "Converges to PSP truth"), F("Webhook duplicate", "psp event id seen", "None", "Ignore", "Single transition"),
          F("Webhook before response", "Attempt already SUCCEEDED", "None", "Response update no-op", "Consistent"), F("Capture declined", "Decline code", "Unpaid trip", "Retry schedule; alternate method; collections", "Receivable in ledger")],
    alts=[["Charge (auth+capture) at end only", "Rejected", "Fraud, unpaid trips", "Trusted business accounts with invoicing"], ["PSP orchestration platform", "Viable", "Faster multi-PSP", "Small teams"]],
    adrs=[A("Partial capture of authorized amount", "I", "Final fare usually ≤ hold.", [("Void + new charge", "Two operations, worse UX"), ("Partial capture", "Chosen")], "Hold quote×1.2, capture actual.", "One charge on statement.", "Fare > hold needs incremental auth.", "If incremental auth unsupported in a market → capture hold + separate charge.")],
    qa=[Q("Correctness", "The final fare exceeds the authorized hold. What do you do?", "Use incremental authorization where supported (increase the hold), then capture the full amount. Otherwise capture the hold and create a second intent for the difference, charged with a new idempotency key and marked as a linked supplement. The ledger shows both against the trip.", "")],
    tests=[T("Failure", "Timeout + webhook later", "CAPTURED once"), T("Failure", "Crash after insertPending", "Resolver settles"), T("Concurrency", "Two FareFinalized deliveries", "One capture")],
    evo=["I: Sync capture with attempt log", "E: Queue-based capture + retry scheduler + webhooks", "R: Saga step on FareFinalized; resolver job", "E: Payment service; router", "E: Smart retries; network tokens", "E: Regional PSPs"],
    ideas={"now": ["Attempt log"], "next": ["Incremental auth"], "adv": ["ML retry timing"], "rej": ["New idempotency key per retry"]})

sub(id="psp-router", comp="payments", name="PSP Router & Failover", phase="IV", cat="Reliability · External integration",
    resp="Choose the PSP for each authorization by method, market, cost and health, and fail over when a PSP degrades, while pinning captures and refunds to the PSP that authorized.",
    inp="authorization requests, PSP health, routing rules", out="PSP selection + adapter call", deps="PSP adapters, Resilience toolkit, network tokens", cons="Auth & capture", own="routing rules, PSP health metrics",
    problem="A single PSP outage stops all revenue. PSPs differ in cost and approval rates per card type and market.", without="Full payment outage when a PSP fails.",
    guar=["Captures/refunds go to the authorizing PSP", "No routing to PSP with open breaker", "Routing decisions logged"], nong=["Equal approval rates across PSPs"],
    usecase="PSP-A latency spikes. Its breaker opens and new authorizations route to PSP-B using network tokens. Existing auths on A are captured on A once it recovers (captures queue with retry).",
    derive="- Authorizations are portable if the token is (network tokens).\n- Captures are not portable (the hold lives at PSP-A).\n- Routing rules: data (market, brand, BIN range → ordered PSPs).",
    conc="Stateless decisions; breakers per instance with shared health signals.", consistency="Rules propagate via config (≤ 60 s).", idem="Failover to B uses a different PSP, so it gets a new attempt row and a new key (no risk of double charge across PSPs because A's attempt is resolved FAILED first, or VOIDed if later found successful).", order="Ordered rule evaluation.",
    restart="Rules loaded at boot.", scale="Stateless routing decisions per call. Throughput is bounded by PSP rate limits, so worker pools are sized per PSP.", arch="Rule table → candidate PSP list → filter by breaker → call → on retryable failure before any ambiguous state, next PSP. Ambiguous failures don't fail over (risk of double hold), but resolve first.",
    modules=[["RoutingRules", "BIN/market/method → PSP order"], ["HealthGate", "Breakers + latency SLO"], ["FailoverPolicy", "Only on definitive failures"], ["Adapters", "PSP APIs"]],
    d_arch=("""flowchart LR
  AUTH["authorize"] --> RR["RoutingRules"] --> HG["HealthGate"] --> FP["FailoverPolicy"] --> A1["PSP A"] & A2["PSP B"]
  CAP["capture/refund"] -->|pinned| A1""", "Auth is routable. Captures are pinned."),
    d_seq=("""sequenceDiagram
  participant R as Router
  participant A as PSP-A
  participant B as PSP-B
  R->>A: authorize
  A-->>R: 503 (definitive, not processed)
  R->>B: authorize (new attempt, network token)
  B-->>R: authorized""", "Failover on a definitive failure."),
    d_state=("""stateDiagram-v2
  [*] --> Healthy
  Healthy --> Degraded: p99 > SLO or errors > 5%
  Degraded --> Open: errors > 50%
  Open --> Healthy: probes succeed""", "PSP health state."),
    d_flow=("""flowchart LR
  BIN["BIN, country, method"] --> RULE["rule match"] --> ORDER["[A, B]"]""", "Rule evaluation."),
    d_fail=("""flowchart TB
  AMB["ambiguous (timeout) at A"] --> NO["do not fail over; resolve via A status"]
  DEF["definitive failure at A"] --> B["fail over to B"]""", "The rule that prevents double holds."),
    sql="CREATE TABLE payments.routing_rules (id serial PRIMARY KEY, market text, method text, bin_prefix text, psp_order text[] NOT NULL, priority int NOT NULL);",
    data="Routing decisions logged for cost/approval analysis.", api="""PspAdapter selectForAuth(AuthContext ctx)
PspAdapter forIntent(PaymentIntent i)   // pinned""",
    mech=[("Definitive vs ambiguous failure classification", "Connection refused, 4xx validation or 503 before processing are definitive (safe to fail over). Timeouts after sending are ambiguous (must resolve). This classification prevents double authorizations.")],
    code="""for (PspAdapter p : rules.order(ctx)) {
    if (!health.allows(p)) continue;
    var att = attempts.insertPending(ctx.intent(), AUTH, p);
    var r = p.authorize(ctx, att.idemKey());
    if (r.isSuccess() || r.isDecline()) return r;           // declines are not retried elsewhere by default
    if (r.isAmbiguous()) throw new AmbiguousOutcome(att);   // resolve before anything else
}""", cx="O(PSPs).",
    fail=[F("PSP outage", "Breaker", "Auths routed elsewhere", "Failover", "Captures for old auths queued"), F("Decline shopping", "Retrying declines at other PSPs", "Fraud/compliance risk", "Not allowed except soft declines by rule", "N/A")],
    alts=[["Single PSP", "Phase I–III", "Simple", "Small scale"], ["Payment orchestration vendor", "Viable", "Faster", "Lack of in-house expertise"]],
    adrs=[A("No failover on ambiguous outcomes", "IV", "Double holds.", [("Always fail over", "Rejected"), ("Definitive only", "Chosen")], "Classification.", "No double holds.", "Some latency on ambiguous cases.", "N/A")],
    qa=[Q("Compliance", "Is routing a declined card to another PSP allowed?", "Hard declines (stolen, do not honour) must not be retried anywhere, because card network rules penalize it. Soft declines (issuer unavailable) may be retried per network rules, with limits. Rules encode allowed retry codes.", "")],
    tests=[T("Failure", "PSP A 503", "B used"), T("Failure", "PSP A timeout", "No failover; resolver")],
    evo=["N: Single PSP in Phase I", "N: Secondary PSP used manually only", "N: Single PSP plus breaker", "I: Router with network tokens", "E: Cost/approval optimization", "E: Regional PSPs"],
    ideas={"now": ["n/a before IV"], "next": ["Approval-rate-based routing"], "adv": ["ML routing"], "rej": ["Failover on timeouts"]})

# ======================================================================= Ledger
comp(id="ledger", domain="payments", name="Ledger (Double-Entry Accounting)", tag="Money · System of record", phase="I", kind="Logical component → deployable service (Phase IV)",
     biz="The single source of financial truth: what each rider owes, what each driver is owed, what the platform earned, and where every cent moved.",
     eng="An append-only double-entry journal with accounts, balanced transactions, idempotent posting, derived balances and reconciliation against external settlement.",
     deploy="Module (I); Ledger service (IV) with its own DB; partitioned journal (V).", data_own="accounts, journal_entries, postings, balances.",
     up=["payments", "fare-finalization", "driver-earnings", "wallet", "promotions", "cancellation"], down=["driver-earnings", "receipts", "support", "data-governance"], ext=["PSP settlement reports", "Bank statements"],
     interfaces="`post(JournalEntry)` idempotent by external_ref; `balance(account)`; event `JournalPosted`.",
     problem="Money moves through many flows (fares, fees, promos, refunds, payouts, chargebacks) and must always balance and be explainable to auditors.",
     fr=["Accounts per rider, driver, platform revenue, PSP clearing, promo expense, tax", "Balanced multi-line entries", "Idempotent posting", "Balances", "Reversals", "Audit trail"], nfr=["Σ debits = Σ credits always", "Posting p99 < 50 ms", "Immutable entries"],
     workload="≈ 4–8 postings per trip; Phase V ≈ 5K entries/s.", success="Books balance daily; auditors satisfied.", failure="Unbalanced books, untraceable money.",
     derive="Every movement has a source and a destination, so double-entry (each transaction's lines sum to zero). Mistakes are corrected by reversal, not edit, so append-only. Retries are inevitable, so idempotency keys (external_ref). Balances are derived, so cached projections updated in the same transaction.",
     owns=["Chart of accounts", "Journal", "Balances"], not_owns=["Business decisions (amounts come from callers)", "External movement (Payments)"], sync=["Post", "Balance query"], **{"async": ["Settlement reconciliation", "Reporting exports"]},
     boundary_why="Ledger is the accountant: it records but never decides. Every domain posts facts in its own terms (fare captured, payout sent), mapped to entries by posting rules owned here.",
     hld=("""flowchart LR
  SRC["Payments / Fares / Earnings / Promotions / Wallet"] -->|events| PR["Posting rules"]
  PR --> DEL["Double-entry journal"] --> J[("journal_entries, postings")]
  DEL --> BAL[("balances (projection)")]
  SET["PSP settlement files"] --> SR["Settlement reconciliation"] --> J""", "Domain events are mapped by posting rules into balanced journal entries. Balances are projections, and settlement reconciliation compares with external records."),
     seq=("""sequenceDiagram
  participant P as Payments
  participant L as Ledger
  P->>L: PaymentCaptured(trip, 267)
  L->>L: rules → entry: Dr psp_clearing 267 / Cr rider_receivable 267
  L->>L: insert entry (external_ref unique), postings, update balances (tx)
  L-->>P: posted""", "Posting a capture."),
     subdeps=[("settlement-reconciliation", "double-entry-ledger")],
     flow="Events arrive (at-least-once), are mapped deterministically to entries with external_ref = event id, posted in one transaction with balance updates, and later reconciled against PSP settlement and bank statements.",
     data="`accounts(id, type, owner_id, currency, normal_side)`, `journal_entries(id, external_ref UNIQUE, kind, occurred_at, posted_at)`, `postings(entry_id, account_id, amount_minor signed, currency)`, `balances(account_id, balance_minor, version)`.",
     er="""erDiagram
  JOURNAL_ENTRIES ||--|{ POSTINGS : contains
  ACCOUNTS ||--o{ POSTINGS : affected_by
  ACCOUNTS ||--|| BALANCES : summarized_by""",
     rel=[["Idempotency", "external_ref unique."], ["Invariant", "Deferred constraint trigger: Σ postings per entry = 0."], ["Recovery", "Balances rebuildable from postings."]],
     sec=[["Access", "Write only via posting API with service identity; finance read roles."], ["Audit", "Immutable; hash-chained daily digests."]],
     adrs=[A("Double-entry from Phase I", "I", "Money correctness from day one.", [("Single-entry transactions table", "Rejected: can't prove balance"), ("Double-entry", "Chosen")], "Double-entry journal.", "Self-checking books.", "More rows.", "N/A")],
     qa=[Q("Correctness", "How do you guarantee the ledger always balances, even with bugs in posting rules?", "Enforce it in the database. A deferred constraint trigger checks, at commit, that the postings of each entry sum to zero per currency, so an unbalanced entry can't commit. Additionally, a daily job sums all postings (must be zero) and compares balance projections with posting sums.", "")],
     impl_order=["double-entry-ledger", "settlement-reconciliation"], pkg="""com.atlas.ledger
├── journal  (JournalService, PostingRules, Account, Entry)
├── balance  (BalanceProjection)
└── recon    (SettlementImporter, SettlementMatcher)""",
     tests=[T("Property", "Random entries", "Global sum zero"), T("Idempotency", "Same event ×5", "One entry")],
     evo=[("I", "Module", "PG journal", "Balance trigger", "Correctness"), ("E", "Same", "—", "Daily balance check", "Audit"), ("E", "Event-driven posting", "—", "Idempotent", "Events"),
          ("R", "Ledger service", "Own DB", "Service identity writes only", "Isolation"), ("R", "Partitioned journal; hot-account sharding", "Partition by month; sub-accounts", "—", "5K/s"), ("E", "Regional ledgers + consolidation", "Currency per region", "FX", "Global")],
     ideas={"now": ["DB-enforced balance"], "next": ["Settlement recon"], "adv": ["Dedicated ledger DB (TigerBeetle)"], "rej": ["Mutable balances without journal"]})

sub(id="double-entry-ledger", comp="ledger", name="Double-Entry Journal & Balances", phase="I", cat="Money · Data integrity",
    resp="Post balanced, idempotent, immutable journal entries and maintain account balances.",
    inp="posting requests (from events)", out="entries, balances, JournalPosted", deps="Posting rules", cons="Earnings, Wallet, Receipts, Finance", own="journal_entries, postings, balances",
    problem="Record every money movement such that the books provably balance and can be audited.", without="Unprovable finances.",
    guar=["Σ postings per entry = 0 per currency", "external_ref posted at most once", "Entries immutable; corrections by reversal", "Balance = Σ postings for account"], nong=["Correct business amounts (callers' responsibility)"],
    usecase="Trip completed, ₹267 fare, 25% platform fee: Dr rider_receivable 267, Cr driver_payable 200.25, Cr platform_revenue 66.75. After capture: Dr psp_clearing 267, Cr rider_receivable 267.",
    derive="- Entry + postings in one transaction.\n- Balance projection updated in the same transaction (or derived).\n- Hot accounts (platform_revenue) get every trip, so contention; split into sub-accounts (Phase V).",
    conc="Balance updates `UPDATE balances SET balance=balance+? WHERE account_id=?` (row lock); hot accounts sharded into N sub-accounts.", consistency="Strong (ACID): entry, postings and balance updates commit together, and the deferred trigger validates balance at commit.", idem="external_ref unique; duplicates return existing entry id.", order="Entries are order-independent (sums commute). occurred_at recorded for reporting.",
    restart="DB-backed; balances rebuildable.", scale="Partition postings by month; hot account sharding.", arch="`JournalService.post(entry)` validates (balanced, accounts exist, currency match), inserts entry + postings, updates balances, writes outbox, all in one transaction.",
    modules=[["PostingRules", "Event → entry lines"], ["JournalService", "Validate + persist"], ["BalanceProjection", "Incremental balances"], ["BalanceVerifier", "Daily recompute"]],
    d_arch=("""flowchart LR
  EV["events"] --> PR["PostingRules"] --> JS["JournalService"] --> J[("entries, postings")] & B[("balances")]
  BV["BalanceVerifier"] --> J & B""", "Rules, journal and projection."),
    d_seq=("""sequenceDiagram
  participant C as Consumer
  participant J as Journal
  participant DB
  C->>J: post(ext_ref=evt-91, lines)
  J->>J: Σ lines = 0 ✔
  J->>DB: INSERT entry (ext_ref unique)
  J->>DB: INSERT postings, UPDATE balances
  DB-->>J: commit (trigger checks balance)""", "Posting."),
    nostate="Entries are immutable facts. Reversals are new entries.",
    d_flow=("""flowchart LR
  FARE["fare 267"] --> L1["Dr rider_receivable 267"] & L2["Cr driver_payable 200.25"] & L3["Cr platform_revenue 66.75"]""", "Trip completion entry."),
    d_fail=("""flowchart TB
  U["unbalanced entry"] --> X["trigger rejects commit"]
  D["duplicate event"] --> E["unique ext_ref → return existing"]""", "The database enforces the invariants."),
    sql="""CREATE TABLE ledger.journal_entries (id uuid PRIMARY KEY, external_ref text NOT NULL UNIQUE, kind text NOT NULL, occurred_at timestamptz NOT NULL, posted_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE ledger.postings (entry_id uuid NOT NULL REFERENCES ledger.journal_entries, line int NOT NULL, account_id uuid NOT NULL, amount_minor bigint NOT NULL, currency char(3) NOT NULL, PRIMARY KEY(entry_id, line));
CREATE TABLE ledger.balances (account_id uuid PRIMARY KEY, currency char(3) NOT NULL, balance_minor bigint NOT NULL DEFAULT 0, version bigint NOT NULL DEFAULT 0);
CREATE FUNCTION ledger.check_balanced() RETURNS trigger AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM ledger.postings WHERE entry_id = NEW.entry_id GROUP BY currency HAVING sum(amount_minor) <> 0) THEN
    RAISE EXCEPTION 'unbalanced entry %', NEW.entry_id; END IF; RETURN NULL;
END $$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER postings_balanced AFTER INSERT ON ledger.postings DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ledger.check_balanced();""",
    data="Immutable; retained permanently (or per statute ≥ 10 years).", api="""PostResult post(String externalRef, String kind, Instant occurredAt, List<Line> lines)  // idempotent
long balance(UUID account)""",
    mech=[("Deferred constraint trigger", "Runs at commit after all lines are inserted, verifying the entry balances per currency. An unbalanced transaction rolls back."), ("Signed amounts", "Debits positive and credits negative (or vice versa) make 'sum = 0' the single invariant."), ("Hot account sharding", "platform_revenue is split into 16 sub-accounts. Postings pick hash(entry) % 16, which removes row-lock contention, and reports sum the sub-accounts.")],
    code="""@Transactional
public PostResult post(String ref, String kind, Instant at, List<Line> lines) {
    if (lines.stream().collect(groupingBy(Line::currency, summingLong(Line::amount))).values().stream().anyMatch(s -> s != 0)) throw new Unbalanced();
    Optional<UUID> existing = entries.insertIfAbsent(ref, kind, at);         // ON CONFLICT (external_ref) DO NOTHING RETURNING id
    if (existing.isEmpty()) return PostResult.duplicate(entries.idByRef(ref));
    postings.insertAll(existing.get(), lines);
    lines.forEach(l -> balances.add(shard(l.account()), l.amount()));
    return PostResult.posted(existing.get());
}""", cx="O(lines).",
    fail=[F("Bug produces unbalanced lines", "Exception", "Event processing fails", "DLQ + fix rules", "Books untouched"), F("Hot-row contention", "Lock wait metric", "Latency", "Sub-accounts", "None")],
    alts=[["Specialized ledger DB (TigerBeetle)", "Advanced", "Very high throughput", "> 50K entries/s"], ["Event-sourced balances only", "Viable", "Same idea", "—"]],
    adrs=[A("DB-enforced balance invariant", "I", "Defense against rule bugs.", [("App check only", "Insufficient"), ("Deferred trigger", "Chosen")], "Trigger.", "Impossible to commit unbalanced.", "Trigger overhead.", "If throughput needs, move to app check + daily verify.")],
    qa=[Q("Data modeling", "How do you represent a refund?", "As a new entry reversing the relevant lines: Dr rider_receivable / Cr psp_clearing for the refunded amount, plus driver clawback lines if policy requires. The original entry is untouched. external_ref = refund id.", "")],
    tests=[T("Property", "Fuzz entries", "Global sum 0"), T("Concurrency", "1,000 parallel postings to revenue", "No deadlocks; balance correct")],
    evo=["I: PG journal + trigger", "E: Daily verifier", "E: Event consumers", "E: Ledger service API", "R: Partitioned postings; sub-accounts", "E: Regional ledgers + consolidation"],
    ideas={"now": ["Trigger"], "next": ["Daily verifier"], "adv": ["TigerBeetle"], "rej": ["Floating point"]})

sub(id="settlement-reconciliation", comp="ledger", name="PSP Settlement Reconciliation", phase="II", cat="Money · Reconciliation",
    resp="Match PSP settlement reports and bank deposits against ledger postings, line by line, and flag fees, chargebacks and missing items.",
    inp="PSP settlement files/APIs, bank statements, ledger", out="matched/unmatched items, fee and chargeback entries", deps="Ledger, Payments (psp refs)", cons="Finance", own="settlement_items, recon_matches",
    problem="PSPs net fees and chargebacks before paying out. Our ledger must match external cash exactly.", without="Unknown cash gaps, misstated revenue.",
    guar=["Every settlement line matched or flagged within 1 day", "PSP fees posted as expense entries", "Chargebacks open disputes"], nong=["Correctness of PSP reports"],
    usecase="Daily settlement shows 10,000 captures, 12 refunds, 3 chargebacks and fees ₹4,120. Matching posts fee and chargeback entries, and psp_clearing equals the bank deposit.",
    derive="- Match on PSP reference (psp_ref) one-to-one.\n- Unmatched both sides → investigate.\n- Fees and chargebacks generate ledger entries with external_ref = settlement line id.",
    conc="One import per file (unique file hash).", consistency="Batch, point-in-time: each file is matched against the ledger as of import. Late ledger items are matched on the next run.", idem="Settlement lines unique (psp, line_id); entries via external_ref.", order="Files processed by date; late files supported.",
    restart="Import ledger per file.", scale="Millions of lines/day → bulk load + set-based matching.", arch="Import (SFTP/API) → staging table → set-based match against payment_attempts psp_ref → post fees/chargebacks → report.",
    modules=[["Importer", "Fetch + parse + stage"], ["Matcher", "SQL joins"], ["EntryGenerator", "Fees, chargebacks"], ["Reporter", "Unmatched queue"]],
    d_arch=("""flowchart LR
  PSP["PSP SFTP/API"] --> IM["Importer"] --> ST[("staging")]
  ST --> MA["Matcher"] --> PA[("payment_attempts")]
  MA --> EG["EntryGenerator"] --> LED["Ledger"]
  MA --> RP["Unmatched report"]""", "Stage, match, post, report."),
    d_seq=("""sequenceDiagram
  participant I as Importer
  participant M as Matcher
  participant L as Ledger
  I->>I: load file (hash unique)
  M->>M: join on psp_ref
  M->>L: post fees, chargebacks (ext_ref = line id)
  M-->>M: unmatched → queue""", "Daily run."),
    d_state=("""stateDiagram-v2
  [*] --> Imported
  Imported --> Matched
  Imported --> Unmatched
  Unmatched --> Resolved: manual""", "Settlement line states."),
    d_flow=("""flowchart LR
  GROSS["gross captures"] --> NET["− fees − chargebacks − refunds"] --> PAYOUT["bank deposit"]""", "Netting."),
    d_fail=("""flowchart TB
  F["file missing"] --> AL["alert after cutoff"]
  P["parse error"] --> Q["quarantine file"]""", "Missing and malformed files are both caught."),
    sql="""CREATE TABLE ledger.settlement_items (psp text, line_id text, file_hash text NOT NULL, type text, psp_ref text, amount_minor bigint, fee_minor bigint,
  currency char(3), settled_on date, match_state text NOT NULL DEFAULT 'Imported', PRIMARY KEY(psp, line_id));""",
    data="Retained 10 years.", api="Batch job: settlement-import-{psp} daily 06:00 UTC",
    mech=[("Set-based matching", "One SQL join over millions of rows is far faster than per-row lookups.")],
    code="""UPDATE ledger.settlement_items s SET match_state='Matched'
FROM payments.payment_attempts a WHERE a.psp_ref = s.psp_ref AND a.amount = s.amount_minor AND s.match_state='Imported';""", cx="O(n log n).",
    fail=[F("Amount mismatch", "Unmatched", "Gap", "Investigate", "Flagged")],
    alts=[["Vendor recon tool", "Viable", "Faster setup", "Finance preference"]],
    adrs=[A("Recon from Phase II", "II", "Real money volume.", [("Later", "Risky"), ("II", "Chosen")], "Daily recon.", "Early detection.", "Job upkeep.", "N/A")],
    qa=[Q("Finance", "Where do PSP fees show up?", "As expense entries: Dr psp_fees_expense / Cr psp_clearing, posted from settlement lines, so platform margin is net of fees.", "")],
    tests=[T("Integration", "Sample settlement file", "All matched, fees posted"), T("Idempotency", "Re-import same file", "No duplicates")],
    evo=["N: Phase I finance reconciles manually in a spreadsheet from PSP dashboard", "I: Daily import + match", "E: Chargeback flows", "E: Multi-PSP", "E: Bank statement matching automation", "E: Regional entities"],
    ideas={"now": ["File hash dedupe"], "next": ["Chargeback automation"], "adv": ["Real-time settlement APIs"], "rej": ["Manual spreadsheets at scale"]})

# ======================================================================= Wallet & Refunds
comp(id="wallet", domain="payments", name="Wallet, Credits & Refunds", tag="Money · Balances", phase="II", kind="Logical component",
     biz="Lets riders hold credits (refunds, promotions, gift cards) and spend them on trips, and gives support a safe way to refund.",
     eng="Stored-value balances backed by the ledger, with atomic spend and expiry, plus a refund workflow that routes money back to card or wallet.",
     deploy="Module (II); inside Payments service boundary (IV).", data_own="wallet_accounts (view of ledger), credit_lots, refunds.",
     up=["ledger", "payments", "support"], down=["payments", "receipts"], ext=["PSP refunds"],
     interfaces="`spend(rider, amount, trip)`, `credit(rider, amount, reason, expiry)`, `refund(trip, amount, destination)`.",
     problem="Credits are money-like (liability on the balance sheet). Spend must never go negative, expiry must be honoured, and refunds must not exceed what was paid.",
     fr=["Credit with reason and expiry", "Spend at capture (credits first, then card)", "Refund to card or wallet", "Expiry processing"], nfr=["No negative balances", "Refund ≤ captured − already refunded"],
     workload="Credits on ~5% of trips.", success="Credits usable and auditable.", failure="Negative balances, refund loops.",
     derive="Wallet balance is a ledger account (rider_wallet liability). Expiry requires lots (each credit with its own expiry), spent in FIFO-by-expiry order. Refund limits require tracking refunded amount per payment.",
     owns=["Credit lots", "Refund records"], not_owns=["Balance truth (Ledger account)"], sync=["Spend", "Refund"], **{"async": ["Expiry job", "PSP refund completion"]},
     boundary_why="Wallet is a business view on top of ledger accounts. It adds lots and rules, but balances reconcile to the ledger.",
     hld=("""flowchart LR
  SUP["Support"] --> RF["Refunds"] --> PAY["PSP refund"] & WB["Wallet credit"]
  CAP["Capture"] --> WB["Wallet balance & lots"] --> LED["Ledger rider_wallet account"]
  EXP["Expiry job"] --> WB""", "Lots plus ledger account."),
     seq=("""sequenceDiagram
  participant P as Payments
  participant W as Wallet
  participant L as Ledger
  P->>W: spend(rider, 267, trip)
  W->>W: consume lots FIFO by expiry (₹100 available)
  W->>L: Dr rider_wallet 100 / Cr rider_receivable 100
  W-->>P: covered 100, remaining 167 to card""", "Credits first."),
     subdeps=[("refunds", "wallet-balance")],
     flow="Spend consumes lots in expiry order and posts ledger entries. Refunds validate limits, then go to PSP or wallet.",
     data="`credit_lots(id, rider_id, amount, remaining, expires_at, reason)`, `refunds(id, payment_intent_id, amount, destination, state, reason, actor)`.",
     rel=[["Atomicity", "Lot consumption + ledger posting in one transaction (same DB until IV; outbox after)."]], sec=[["Abuse", "Refund limits per agent role; velocity checks."]],
     adrs=[A("Lots for expiry", "II", "Credits expire differently.", [("Single balance", "Can't expire correctly"), ("Lots", "Chosen")], "Lots.", "Correct expiry.", "More rows.", "N/A")],
     qa=[Q("Accounting", "Are wallet credits revenue?", "No. Credits from refunds or purchases are liabilities (we owe the rider). Promotional credits are recorded as promo expense when spent, not when granted, and expired credits are recognized as breakage per accounting policy.", "")],
     impl_order=["wallet-balance", "refunds"], pkg="""com.atlas.wallet
├── lots    (CreditLotService, ExpiryJob)
└── refunds (RefundService)""",
     tests=[T("Concurrency", "Parallel spends", "Never negative"), T("Unit", "Refund > captured", "Rejected")],
     evo=[("N", "Not needed in pilot", "—", "—", "—"), ("I", "Module", "Lots + ledger", "Atomic spend", "Refunds/credits"), ("E", "Same", "Events", "Idempotent", "Events"), ("E", "Inside Payments", "—", "—", "Services"), ("U", "No change needed", "—", "—", "—"), ("E", "Regional currencies", "—", "—", "Global")],
     ideas={"now": ["Lots"], "next": ["Gift cards"], "adv": ["Family wallets"], "rej": ["Negative balances"]})

sub(id="wallet-balance", comp="wallet", name="Wallet Balance & Credit Lots", phase="II", cat="Money · Concurrency",
    resp="Grant, spend and expire credits atomically with no negative balances, consistent with the ledger.",
    inp="credit grants, spend requests, clock", out="lot changes + ledger entries", deps="Ledger", cons="Payments, Rider app", own="credit_lots",
    problem="Concurrent spends and expiries against a balance with per-lot expiry.", without="Double-spent credits.",
    guar=["Σ remaining ≥ 0 per lot", "Spend consumes earliest-expiring lots first", "Ledger rider_wallet balance = Σ remaining lots"], nong=["Cross-currency spend"],
    usecase="Rider has ₹50 (exp Dec 1) + ₹100 (exp Jan 1). Spend ₹80 consumes all ₹50 then ₹30 of the second.",
    derive="- Lock the rider's lots during spend (SELECT ... FOR UPDATE ordered by expiry).\n- Ledger posting in the same transaction.",
    conc="`SELECT ... FROM credit_lots WHERE rider_id=? AND remaining>0 AND expires_at>now() ORDER BY expires_at FOR UPDATE` serializes per rider.", consistency="Strong: lot updates and the ledger posting commit in one transaction while the services share a database.", idem="Spend keyed by (trip_id); grant keyed by source ref.", order="Per-rider serialization by row locks.",
    restart="DB-backed with no in-memory state. A crashed spend either committed fully or not at all.", scale="Per-rider locks; no global hot spot.", arch="Transactional service with lock-ordered lot consumption.",
    modules=[["GrantService", "Create lots"], ["SpendService", "FIFO-by-expiry consumption"], ["ExpiryJob", "Expire and post breakage"]],
    d_arch=("""flowchart LR
  G["grant"] --> GS["GrantService"] --> L[("credit_lots")]
  S["spend"] --> SS["SpendService"] --> L
  SS & GS --> LED["Ledger"]
  EJ["ExpiryJob"] --> L""", "Lots and ledger."),
    d_seq=("""sequenceDiagram
  participant P as Payments
  participant S as Spend
  participant DB
  P->>S: spend(rider, 80, trip)
  S->>DB: lock lots ORDER BY expires_at
  S->>DB: update remaining (50→0, 100→70)
  S->>DB: ledger entry
  S-->>P: 80 covered""", "Spend."),
    d_state=("""stateDiagram-v2
  [*] --> Active
  Active --> Depleted: remaining 0
  Active --> Expired: expires_at""", "Lot lifecycle."),
    d_flow=("""flowchart LR
  L1["lot A 50 (Dec)"] --> S["spend 80"]
  L2["lot B 100 (Jan)"] --> S
  S --> R["A 0, B 70"]""", "FIFO by expiry."),
    d_fail=("""flowchart TB
  C["concurrent spends"] --> W["second waits for locks; sees reduced remaining"]""", "Serialization prevents overspend."),
    sql="""CREATE TABLE wallet.credit_lots (id uuid PRIMARY KEY, rider_id uuid NOT NULL, currency char(3) NOT NULL, amount_minor bigint NOT NULL,
  remaining_minor bigint NOT NULL CHECK (remaining_minor >= 0 AND remaining_minor <= amount_minor), expires_at timestamptz, source_ref text NOT NULL UNIQUE, reason text);
CREATE TABLE wallet.spends (trip_id uuid PRIMARY KEY, rider_id uuid NOT NULL, amount_minor bigint NOT NULL);""",
    data="Lots retained 7 years.", api="""long spend(UUID rider, UUID trip, long maxAmount)   // returns covered amount, idempotent per trip
void grant(UUID rider, long amount, Instant expires, String sourceRef)""",
    mech=[("Ordered row locking", "Locking lots in a deterministic order (by expiry, id) prevents deadlocks between concurrent spenders and gives FIFO semantics.")],
    code="""@Transactional
public long spend(UUID rider, UUID trip, long max) {
    if (spends.exists(trip)) return spends.amount(trip);
    long left = max, covered = 0;
    for (Lot l : lots.lockActive(rider)) { long take = Math.min(left, l.remaining()); if (take == 0) break; lots.decrement(l.id(), take); left -= take; covered += take; }
    spends.insert(trip, rider, covered); ledger.post("spend:" + trip, walletLines(rider, covered));
    return covered;
}""", cx="O(lots).",
    fail=[F("Duplicate spend", "spends PK", "None", "Return previous", "Exact")],
    alts=[["Single balance column", "Rejected", "No expiry", "No-expiry credits"]],
    adrs=[A("Spend idempotent per trip", "II", "Retries.", [("Per request id", "Weaker"), ("Per trip", "Chosen")], "Per trip.", "Simple.", "One spend per trip.", "N/A")],
    qa=[Q("Concurrency", "Why lock instead of optimistic updates?", "Spends touch multiple lots and need FIFO order across them. Row locks give a simple, correct serialization per rider with negligible contention (one rider rarely spends concurrently).", "")],
    tests=[T("Concurrency", "10 parallel spends", "Total ≤ balance"), T("Unit", "Expired lot", "Skipped")],
    evo=["N: No wallet in pilot", "I: Lots + ledger in same DB", "E: Events to analytics", "R: Ledger posting via outbox after split", "U: No change needed", "E: Regional"],
    ideas={"now": ["CHECK constraints"], "next": ["Gift card lots"], "adv": ["Multi-currency wallets"], "rej": ["Optimistic overdraft"]})

sub(id="refunds", comp="wallet", name="Refunds", phase="II", cat="Money · Workflow",
    resp="Return money to riders for overcharges and service failures, to the original payment method or wallet, within limits and with audit.",
    inp="refund requests (support, automated policies)", out="PSP refund or wallet credit; ledger reversal; RefundIssued", deps="Payments (PSP refund), Wallet, Ledger, Authorization", cons="Support, Rider", own="refunds",
    problem="Refunds must never exceed what was paid, must be idempotent and must reach the right place.", without="Over-refunds, duplicate refunds, fraud by agents.",
    guar=["Σ refunds ≤ captured per intent", "Idempotent by refund request id", "Agent limits enforced"], nong=["Instant bank-side visibility (card refunds take days)"],
    usecase="Rider overcharged ₹60 due to route issue. The agent refunds ₹60 to card. Ledger: Dr rider_receivable... reversal, and the driver clawback per policy (no clawback for platform error).",
    derive="- Track refunded total per intent; conditional update to reserve the refund amount.\n- PSP refund is async; state machine.",
    conc="`UPDATE payment_intents SET amount_refunded = amount_refunded + ? WHERE id=? AND amount_refunded + ? <= amount_captured`.", consistency="Strong on intent; PSP eventually.", idem="Refund id = client-provided; PSP idempotency key = refund id.", order="Refund completion webhooks can come before sync response; conditional state updates.",
    restart="Pending refunds resolved like payment attempts.", scale="Refund volume is a small fraction of trips. Row-level reservation on the intent has no global contention.", arch="RefundService: authorize (RBAC limits) → reserve amount on intent → destination (PSP or wallet) → ledger → event.",
    modules=[["RefundPolicy", "Limits, auto-approval rules"], ["RefundService", "Reserve + execute"], ["Destinations", "PSP / wallet"]],
    d_arch=("""flowchart LR
  SUP["Agent"] --> RP["RefundPolicy"] --> RS["RefundService"] --> PI[("intent refunded total")]
  RS --> PSP["PSP refund"] & W["Wallet credit"]
  RS --> LED["Ledger reversal"]""", "Policy, reserve, execute, record."),
    d_seq=("""sequenceDiagram
  participant A as Agent
  participant R as Refunds
  participant P as PSP
  A->>R: refund(trip, 60, card, id r1)
  R->>R: reserve 60 on intent (≤ captured)
  R->>P: refund (key r1)
  P-->>R: pending → succeeded (webhook)
  R->>R: ledger + RefundIssued""", "Card refund."),
    d_state=("""stateDiagram-v2
  [*] --> Requested
  Requested --> Pending: reserved
  Pending --> Succeeded
  Pending --> Failed: release reserve""", "Refund lifecycle."),
    d_flow=("""flowchart LR
  CAP["captured 267"] --> RES["refunded 0→60"] --> LEFT["refundable 207"]""", "Limit tracking."),
    d_fail=("""flowchart TB
  F["PSP refund fails (card closed)"] --> W["fallback to wallet credit with rider consent"]""", "Fallback destination."),
    sql="""ALTER TABLE payments.payment_intents ADD COLUMN amount_refunded bigint NOT NULL DEFAULT 0, ADD CONSTRAINT refund_le_capture CHECK (amount_refunded <= amount_captured);
CREATE TABLE payments.refunds (id uuid PRIMARY KEY, intent_id uuid NOT NULL, amount_minor bigint NOT NULL, destination text NOT NULL, state text NOT NULL,
  reason text NOT NULL, actor uuid NOT NULL, psp_ref text, created_at timestamptz NOT NULL DEFAULT now());""",
    data="Retained 7 years.", api="""POST /internal/refunds {id, trip_id, amount_minor, destination: CARD|WALLET, reason} -> 202
event RefundIssued{refund_id, trip_id, amount, destination}""",
    mech=[("Reserve-then-execute", "Increment refunded total before calling the PSP, guarded by a CHECK constraint, so concurrent refunds can't exceed captured. Release on definitive failure.")],
    code="""@Transactional
public void reserve(UUID intent, long amt) { if (intents.addRefunded(intent, amt) == 0) throw new RefundExceedsCapture(); }""", cx="O(1).",
    fail=[F("Two agents refund simultaneously", "Constraint", "Second rejected", "Show refundable", "Never over-refund"), F("PSP timeout", "Pending", "Unknown", "Resolve by key", "Converges")],
    alts=[["Refund always to wallet", "Rejected", "Regulations require original method", "Rider preference"]],
    adrs=[A("Original method by default", "II", "Regulation and trust.", [("Wallet default", "Rejected"), ("Original method", "Chosen")], "Card default; wallet on request/fallback.", "Compliant.", "Slower visibility.", "N/A")],
    qa=[Q("Fraud", "How do you prevent agents from refunding to themselves?", "Refunds can only go to the original payment method or the rider's own wallet, never to an arbitrary destination. Agents have per-refund and daily limits, refunds above threshold need second approval, and analytics flag agents with anomalous refund patterns.", "")],
    tests=[T("Concurrency", "Parallel refunds", "Σ ≤ captured"), T("Integration", "Card refund webhook", "Succeeded")],
    evo=["N: Phase I refunds via PSP dashboard with manual ledger entry", "I: Refund service", "E: Events; automated policies", "E: Inside Payments service", "E: Auto-refunds by policy at scale", "E: Regional rules"],
    ideas={"now": ["CHECK constraint"], "next": ["Automated refunds for known failures"], "adv": ["Instant refunds to wallet"], "rej": ["Arbitrary destinations"]})

# ======================================================================= Driver Earnings & Payouts
comp(id="driver-earnings", domain="payments", name="Driver Earnings, Incentives & Payouts", tag="Money · Supply", phase="I", kind="Logical component → service (Phase IV)",
     biz="Shows drivers exactly what they earned per trip and per week, pays them reliably to their bank, and runs incentive programmes that bring drivers online when needed.",
     eng="Per-trip earnings computation, incentive evaluation over windows, and batched, idempotent payouts to banks reconciled with the ledger.",
     deploy="Module (I); Earnings service (IV).", data_own="earnings_lines, incentive_programs, incentive_progress, payout_batches, payouts, bank_accounts (tokenized).",
     up=["fare-finalization", "trip", "ledger", "fleet-vehicle", "cancellation"], down=["ledger", "notifications", "support"], ext=["Banks / payout providers"],
     interfaces="Consumes `FareFinalized`, `TripCompleted`, `CancellationFeeCharged`; `GET /v1/drivers/me/earnings`; payouts batch API.",
     problem="Drivers depend on accurate, timely pay. Earnings must be derivable from trips, incentives must be fair and gaming-resistant, and payouts must never double-pay.",
     fr=["Per-trip earnings (fare − service fee + tips + bonuses)", "Weekly statements", "Incentives (quests, guarantees)", "Weekly and instant payouts", "Fleet splits"], nfr=["Earnings visible < 1 min after trip", "Payouts exactly once", "Statement = ledger driver_payable movements"],
     workload="One earnings line per trip; weekly payout batch of all drivers; instant payouts on demand.", success="Accurate, timely pay; trust.", failure="Wrong or late pay; double payouts.",
     derive="Earnings are a function of fare and policy, computed from events. Payouts move real money externally, so the same attempt-log and idempotency pattern as payments. Incentives depend on counts over windows, so incremental counters per driver per program.",
     owns=["Earnings lines", "Incentives", "Payouts"], not_owns=["Fare (Fare finalization)", "Ledger truth (Ledger)"], sync=["Earnings view", "Instant payout request"], **{"async": ["Earnings from events", "Incentive evaluation", "Payout batches"]},
     boundary_why="Driver-side money has its own lifecycle (weekly cycles, incentives, banks), different from rider payments.",
     hld=("""flowchart LR
  FF["FareFinalized"] --> EC["Earnings calculator"] --> EL[("earnings_lines")] --> LED["Ledger driver_payable"]
  TC["TripCompleted"] --> INC["Incentives engine"] --> EL
  PB["Payout processing"] --> LED
  PB --> BANK["Payout provider"]""", "Earnings and incentives credit driver_payable. Payouts debit it and move money out."),
     seq=("""sequenceDiagram
  participant F as FareFinalized
  participant E as Earnings
  participant L as Ledger
  participant P as Payouts
  F->>E: trip 267
  E->>E: 267 − 25% fee = 200.25
  E->>L: Cr driver_payable 200.25
  Note over P: Monday batch
  P->>L: Dr driver_payable 1,842 / Cr bank_clearing
  P->>P: send to bank (idempotent)""", "Earn, then pay out."),
     subdeps=[("payout-processing", "earnings-calculator"), ("incentives", "earnings-calculator")],
     flow="Events produce earnings lines. Incentives produce bonus lines. Weekly batches pay the ledger balance of driver_payable, net of instant payouts already taken.",
     data="`earnings_lines(id, driver_id, trip_id, kind, amount, week, external_ref UNIQUE)`, `payouts(id, driver_id, amount, batch_id, state, idem_key)`, `incentive_programs`, `incentive_progress(driver_id, program_id, count, window)`.",
     rel=[["Idempotency", "external_ref on lines; idem keys on payouts."], ["Recon", "Σ lines = ledger driver_payable credits."]], sec=[["Bank data", "Tokenized at provider; changes require step-up + 72 h cooling-off (account recovery)."]],
     adrs=[A("Pay ledger balance, not sum of lines", "II", "Single source of truth.", [("Sum lines", "Diverges with adjustments"), ("Ledger balance", "Chosen")], "Payout = driver_payable balance at cutoff.", "Consistent.", "Requires accurate ledger.", "N/A")],
     qa=[Q("Correctness", "A fare adjustment reduces a trip after the weekly payout. What happens?", "An adjustment posts a negative earnings line (debit driver_payable) in the current week. Next week's payout is net of it. If the balance goes negative (driver left the platform), it's tracked as a receivable with collection policy. Paid-out money is never 'unpaid'.", "")],
     impl_order=["earnings-calculator", "payout-processing", "incentives"], pkg="""com.atlas.earnings
├── calc       (EarningsCalculator, FeePolicy)
├── incentives (IncentiveEngine, ProgramRules)
└── payouts    (PayoutBatcher, PayoutProviderAdapter, PayoutResolver)""",
     tests=[T("Idempotency", "Duplicate FareFinalized", "One line"), T("Failure", "Bank provider timeout", "No double payout")],
     evo=[("I", "Module; manual payouts weekly via provider portal", "Lines + ledger", "Unique refs", "Pilot"), ("E", "Automated weekly payouts", "Batches", "Attempt log", "Volume"), ("E", "Event-driven", "—", "Idempotent", "Events"),
          ("R", "Earnings service; instant payouts; incentives", "Own DB", "Provider failover", "Scale"), ("E", "Streaming incentive progress", "—", "—", "Real-time quests"), ("E", "Regional providers, tax rules", "—", "—", "Global")],
     ideas={"now": ["Per-trip breakdown"], "next": ["Instant payouts"], "adv": ["Earnings forecasts"], "rej": ["Opaque earnings"]})

sub(id="earnings-calculator", comp="driver-earnings", name="Earnings Calculator", phase="I", cat="Money · Computation",
    resp="Compute each trip's driver earnings (fare minus service fee, plus tips, fees, tolls passthrough) and post them.",
    inp="FareFinalized, tips, cancellation fees, adjustments", out="earnings lines + ledger postings", deps="Fee policy, Ledger, Fleet splits", cons="Driver app, Payouts, Support", own="earnings_lines",
    problem="Transparent, exact, idempotent per-trip earnings.", without="Disputes and mistrust.",
    guar=["One line per (trip, kind)", "Breakdown visible to driver", "Line sum = ledger credits"], nong=["Payout timing"],
    usecase="Trip fare ₹267, service fee 25% → ₹200.25. Tip ₹30 (100% to driver) → ₹230.25 total for the trip.",
    derive="- Pure function of fare breakdown + fee policy (versioned).\n- Unique external_ref = `{trip}:{kind}`.",
    conc="Insert-if-absent per line.", consistency="Strong (line + ledger in same tx until IV; outbox after).", idem="external_ref unique.", order="Adjustments are separate lines; order independent.",
    restart="Consumer idempotent.", scale="One line per trip; trivial.", arch="Event consumer computing lines with `FeePolicy` and fleet split, inserting lines and posting ledger entries.",
    modules=[["FeePolicy", "Per city/product, versioned"], ["Calculator", "Lines"], ["Poster", "Ledger entries"]],
    d_arch=("""flowchart LR
  FF["FareFinalized"] --> C["Calculator"] --> FP["FeePolicy"]
  C --> EL[("earnings_lines")] --> L["Ledger"]""", "Compute and post."),
    d_seq=("""sequenceDiagram
  participant F as FareFinalized
  participant C as Calculator
  F->>C: fare 267
  C->>C: fee 25% → 66.75
  C->>C: insert line (trip:FARE) 200.25
  C->>C: ledger: Dr rider_receivable … Cr driver_payable 200.25""", "Per trip."),
    nostate="Lines are immutable facts.", d_flow=("""flowchart LR
  F["fare"] --> FEE["− service fee"] --> T["+ tips"] --> TOT["trip earnings"]""", "Composition."),
    d_fail=("""flowchart TB
  P["policy missing"] --> D["DLQ + alert (never guess)"]""", "Never guess money."),
    sql="""CREATE TABLE earnings.earnings_lines (id uuid PRIMARY KEY, driver_id uuid NOT NULL, trip_id uuid, kind text NOT NULL, amount_minor bigint NOT NULL,
  currency char(3) NOT NULL, week date NOT NULL, policy_version int NOT NULL, external_ref text NOT NULL UNIQUE, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX earnings_driver_week ON earnings.earnings_lines(driver_id, week);""",
    data="7 years.", api="""GET /v1/drivers/me/earnings?week=2026-W44 -> {total, lines:[{trip_id, kind, amount}]}""",
    mech=[("Versioned fee policy", "Each line records the policy version used, so changing the fee next week never alters past earnings.")],
    code="""long earnings(Fare f, FeePolicy p) { return f.amountMinor() - Math.round(f.amountMinor() * p.feeBps() / 10_000.0) + f.passThroughMinor(); }""", cx="O(1).",
    fail=[F("Duplicate event", "Unique ref", "None", "Skip", "Exact")],
    alts=[["Compute at payout time", "Rejected", "Drivers want real-time", "Never"]],
    adrs=[A("Real-time per-trip lines", "I", "Transparency.", [("Weekly calc", "Opaque"), ("Per trip", "Chosen")], "Per trip.", "Trust.", "More rows.", "N/A")],
    qa=[Q("Transparency", "Should drivers see the rider's fare?", "Many markets now require showing the rider fare and the platform's cut per trip. The design supports it because lines include fare, fee and earnings, and display is a policy flag per market.", "")],
    tests=[T("Unit", "Fee rounding", "Lines sum exactly"), T("Idempotency", "Replay", "One line")],
    evo=["I: In-process", "U: No change needed", "E: Kafka consumer", "E: Earnings service", "U: No change needed", "E: Regional fee/tax rules"],
    ideas={"now": ["Policy version per line"], "next": ["Fare transparency"], "adv": ["Earnings simulator"], "rej": ["Hidden fees"]})

sub(id="payout-processing", comp="driver-earnings", name="Payout Processing", phase="II", cat="Money · External transfer",
    resp="Pay drivers their available balance on schedule (weekly) or on demand (instant), exactly once, via payout providers.",
    inp="ledger driver_payable balances, bank tokens, schedule", out="payouts, ledger debits, provider transfers", deps="Ledger, Payout providers, Risk (holds)", cons="Drivers, Finance", own="payout_batches, payouts",
    problem="Move money out of the platform exactly once, tolerate provider failures, and never pay more than the balance.", without="Double payouts (irrecoverable) or missed pay.",
    guar=["Payout amount ≤ available balance at cutoff", "One payout per (driver, period) or per instant request id", "Ledger debit recorded before transfer; reversed on definitive failure"], nong=["Bank arrival time"],
    usecase="Monday 02:00: batch for 80K drivers. Each payout row is created with an idempotency key and a ledger debit, then sent to the provider in chunks. 12 bank rejects are reversed and the drivers are notified to fix their bank details.",
    derive="- Record intent + ledger debit before transfer (same write-ahead pattern).\n- Idempotency key per payout.\n- Batches chunked for provider limits.\n- Holds (fraud, disputes) reduce available balance.",
    conc="Balance snapshot at cutoff with ledger lock (debit posting checks balance ≥ amount via conditional update on balance).", consistency="Strong in ledger; provider eventually.", idem="Payout idem key `payout:{driver}:{period}` or instant request id.", order="Weekly and instant payouts serialized per driver (advisory lock).",
    restart="Batch ledger: each payout has a state; resume from first non-terminal.", scale="Batch of 1M payouts/week; parallel chunks.", arch="Batcher creates payout rows + ledger debits (Dr driver_payable / Cr payout_clearing) → Sender submits to provider with keys → webhooks/statuses finalize → failures reverse the debit.",
    modules=[["Batcher", "Cutoff, eligibility, holds"], ["Sender", "Chunked provider calls"], ["Resolver", "Pending resolution"], ["Reverser", "Reverse failed payouts"]],
    d_arch=("""flowchart LR
  CR["cron weekly"] --> BA["Batcher"] --> LED["Ledger debit"] & PO[("payouts")]
  PO --> SE["Sender"] --> PRV["Payout provider"]
  PRV -->|webhook| RS["Resolver"] --> PO
  RS -->|failed| RV["Reverser"] --> LED""", "Debit before send, reverse on failure."),
    d_seq=("""sequenceDiagram
  participant B as Batcher
  participant L as Ledger
  participant S as Sender
  participant P as Provider
  B->>L: debit driver_payable 1842 (ref payout:d1:W44)
  B->>B: payout row PENDING
  S->>P: transfer (key payout:d1:W44)
  P-->>S: accepted
  P-->>S: webhook paid""", "One payout."),
    d_state=("""stateDiagram-v2
  [*] --> CREATED
  CREATED --> SUBMITTED
  SUBMITTED --> PAID
  SUBMITTED --> FAILED: bank reject
  FAILED --> REVERSED: ledger reversal""", "Payout lifecycle."),
    d_flow=("""flowchart LR
  BAL["driver_payable 1,950"] --> H["− holds 108"] --> AV["available 1,842"] --> PAY["payout"]""", "Available balance."),
    d_fail=("""flowchart TB
  T["provider timeout"] --> Q["resolve by key; never resend with new key"]
  R["bank reject"] --> V["reverse debit; notify driver"]""", "Same rules as rider payments."),
    sql="""CREATE TABLE earnings.payouts (id uuid PRIMARY KEY, driver_id uuid NOT NULL, period text, amount_minor bigint NOT NULL CHECK (amount_minor > 0), currency char(3),
  idem_key text NOT NULL UNIQUE, state text NOT NULL, provider_ref text, batch_id uuid, created_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX one_weekly_payout ON earnings.payouts(driver_id, period) WHERE period IS NOT NULL;""",
    data="7–10 years.", api="""POST /v1/drivers/me/payouts/instant {request_id} -> 202 {payout_id, amount, fee}
event PayoutPaid{payout_id, driver_id, amount}""",
    mech=[("Debit-before-transfer", "The ledger shows money leaving as soon as we commit to send it, so a driver can't request an instant payout of the same funds concurrently. Definitive failure reverses it.")],
    code="""@Transactional
public Payout create(UUID driver, String period) {
    long avail = ledger.available(driver);       // balance − holds, under advisory lock per driver
    if (avail <= 0) return null;
    String key = "payout:" + driver + ":" + period;
    ledger.post(key, debitDriverPayable(driver, avail));
    return payouts.insert(driver, period, avail, key);
}""", cx="O(drivers) per batch.",
    fail=[F("Double submission", "Unique key at provider", "None", "Provider dedupes", "One transfer"), F("Partial batch crash", "Non-terminal rows", "Delay", "Resume", "Exact")],
    alts=[["Pay sum of week's lines", "Rejected", "Ignores adjustments", "Never"]],
    adrs=[A("Instant payouts at Phase IV", "IV", "Driver demand.", [("Weekly only", "Driver churn"), ("Instant with fee", "Chosen")], "Instant via debit-card push.", "Retention.", "Fraud risk → holds.", "N/A")],
    qa=[Q("Fraud", "A compromised driver account requests instant payout to a newly added card. Defence?", "Bank/card changes trigger a 72 h cooling-off on payouts (from account recovery), step-up auth, a notification to the old channels and risk scoring. Instant payouts to new destinations are blocked during cooling-off.", "")],
    tests=[T("Concurrency", "Instant + weekly concurrently", "Σ ≤ balance"), T("Recovery", "Kill batch at 50%", "Resumes, no duplicates")],
    evo=["N: Phase I uses manual weekly payouts via provider portal plus ledger entries", "I: Automated weekly batches", "E: Event-driven state", "E: Instant payouts", "E: Multi-provider", "E: Regional providers"],
    ideas={"now": ["Debit before send"], "next": ["Instant payouts"], "adv": ["Daily auto-payouts"], "rej": ["Payouts without ledger"]})

sub(id="incentives", comp="driver-earnings", name="Driver Incentives (Quests & Guarantees)", phase="IV", cat="Money · Programs",
    resp="Run programs like 'complete 30 trips this week for ₹1,500' or 'earn at least ₹600/hour during peak', track progress and pay bonuses fairly.",
    inp="TripCompleted, online-time events, program rules", out="progress, bonus earnings lines", deps="Earnings calculator, Supply (online time), Risk", cons="Driver app, Supply planning", own="incentive_programs, incentive_progress",
    problem="Shape supply with incentives without budget overruns or gaming (fake trips).", without="Supply shortfalls at peaks.",
    guar=["Progress counts only eligible trips", "Bonus paid once per program per driver", "Budget caps per program"], nong=["Supply outcome"],
    usecase="Quest: 30 trips Mon–Thu in Pune. Driver at 29 sees a progress bar. The 30th trip completes, the bonus line is created at window end after fraud checks, and it's paid in the weekly payout.",
    derive="- Progress = counter per (driver, program) incremented by eligible events (idempotent by trip id).\n- Evaluation at window close.\n- Fraud review before payout.",
    conc="Progress increments via insert of (program, driver, trip) unique rows; count derived.", consistency="Eventual (seconds); final at window close.", idem="Unique (program, driver, trip).", order="Event time decides window membership; late events within grace counted.",
    restart="Rebuild from unique rows.", scale="Programs × eligible drivers; Phase V streaming counters.", arch="Event consumer matches trips to active programs (rule DSL like promotions) → progress rows → window-close job → bonus lines.",
    modules=[["ProgramRules", "Eligibility"], ["ProgressTracker", "Counted trips"], ["WindowCloser", "Award + fraud check"], ["BudgetGuard", "Caps"]],
    d_arch=("""flowchart LR
  TC["TripCompleted"] --> PR["ProgramRules"] --> PT["ProgressTracker"] --> DB[("progress rows")]
  WC["WindowCloser"] --> DB --> FR["Fraud check"] --> EL["Bonus earnings line"]""", "Count, close, award."),
    d_seq=("""sequenceDiagram
  participant T as TripCompleted
  participant P as Progress
  participant W as WindowCloser
  T->>P: eligible? yes → insert(program, driver, trip)
  W->>P: count ≥ 30 for driver?
  W->>W: fraud ok → bonus line""", "Award flow."),
    d_state=("""stateDiagram-v2
  [*] --> InProgress
  InProgress --> Qualified: target met
  Qualified --> Awarded: window closed + checks
  Qualified --> Withheld: fraud""", "Per driver per program."),
    d_flow=("""flowchart LR
  E["events"] --> C["count"] --> UI["progress bar"]""", "Progress display."),
    d_fail=("""flowchart TB
  L["late events after close"] --> G["grace 2h then frozen"]""", "Window freeze."),
    sql="""CREATE TABLE earnings.incentive_progress (program_id uuid, driver_id uuid, trip_id uuid, counted_at timestamptz NOT NULL, PRIMARY KEY(program_id, driver_id, trip_id));""",
    data="Retained with earnings.", api="""GET /v1/drivers/me/incentives -> [{program, target, progress, ends_at, reward}]""",
    mech=[("Set-based counting", "Storing counted trip ids makes counting idempotent and auditable. The count is a COUNT(*) per driver, not a mutable counter.")],
    code="""@KafkaListener(topics="trip-events") void on(TripCompleted t) { programs.matching(t).forEach(p -> progress.insertIgnore(p.id(), t.driverId(), t.tripId())); }""", cx="O(programs).",
    fail=[F("Fake trips to hit quest", "Fraud signals (same rider, short trips)", "Budget loss", "Withhold + review", "N/A")],
    alts=[["Mutable counters", "Rejected", "Not idempotent", "Never"]],
    adrs=[A("Award at window close", "IV", "Fraud review time.", [("Instant award", "Fraud"), ("Window close", "Chosen")], "Close + check.", "Safer.", "Delayed gratification.", "N/A")],
    qa=[Q("Fairness", "Should guarantees count time when the driver declines offers?", "Guarantee eligibility requires a minimum acceptance rate and online time in the zone. Otherwise drivers could sit online declining and collect guarantees. Thresholds are disclosed in program terms.", "")],
    tests=[T("Idempotency", "Duplicate trips", "Counted once"), T("Unit", "Late event in grace", "Counted")],
    evo=["N: No incentives in pilot", "N: Manual bonuses only", "N: Manual bonuses only", "I: Quest programs", "R: Streaming progress", "E: Regional programs"],
    ideas={"now": ["n/a before IV"], "next": ["Guarantees"], "adv": ["Personalized incentives via ML"], "rej": ["Uncapped programs"]})

# ======================================================================= Receipts
comp(id="receipts", domain="payments", name="Receipts, Invoicing & Tax Reporting", tag="Money · Documents", phase="I", kind="Logical component",
     biz="Gives riders a receipt for every trip, business customers proper invoices, and finance the tax reports authorities require.",
     eng="Document generation from finalized financial facts, with templating, localization, regulatory numbering and periodic tax aggregation.",
     deploy="Module (I); async document workers (II); part of Payments boundary (IV).", data_own="receipts, invoices, tax reports, numbering sequences.",
     up=["fare-finalization", "payments", "ledger", "location-history", "notifications"], down=["notifications", "support"], ext=["E-invoicing portals (e.g. GST)", "Object storage"],
     interfaces="Consumes `PaymentCaptured`; `GET /v1/trips/{id}/receipt`; invoice APIs for business; periodic tax exports.",
     problem="Receipts must match charged amounts exactly, include legally required fields per country, and some jurisdictions require sequential invoice numbers or real-time e-invoicing.",
     fr=["Receipt per trip after capture", "Business invoices monthly", "Tax breakdown", "Legal numbering", "Regenerate on adjustment (credit notes)"], nfr=["Receipt < 5 min after capture", "Amounts match ledger exactly"],
     workload="One receipt per trip.", success="Correct, timely, compliant documents.", failure="Tax non-compliance, wrong receipts.",
     derive="Receipts derive from captured facts, so generate after PaymentCaptured. Documents are immutable, and corrections are credit notes. Gap-free numbering needs a sequence per legal entity and series.",
     owns=["Documents", "Numbering", "Tax reports"], not_owns=["Amounts (Fare/Payments/Ledger)"], sync=["Get receipt"], **{"async": ["Generation", "E-invoicing submission", "Tax aggregation"]},
     boundary_why="Document rules vary by jurisdiction and change often. Isolating them protects the money paths.",
     hld=("""flowchart LR
  PC["PaymentCaptured"] --> RG["Receipt generator"] --> TPL["Templates (locale)"]
  RG --> OBJ[("PDF/HTML store")]
  RG --> NUM["Numbering"]
  RG --> N["Email/in-app"]
  LED["Ledger"] --> TAX["Tax reporting"] --> AUTH["Tax authority exports"]""", "Generation plus periodic reporting."),
     seq=("""sequenceDiagram
  participant P as PaymentCaptured
  participant R as Receipts
  participant N as Notifications
  P->>R: trip 77 captured 267
  R->>R: number INV-PUN-2026-000123
  R->>R: render, store
  R->>N: email receipt""", "Receipt flow."),
     subdeps=[("tax-reporting", "receipt-generator")],
     flow="Captured payments drive receipt generation with numbering. Adjustments produce credit notes. Monthly jobs aggregate taxes from the ledger.",
     data="`receipts(id, trip_id UNIQUE, number UNIQUE, entity, amount, tax, currency, file_key, issued_at)`, `number_sequences(entity, series, next)`.",
     rel=[["Idempotency", "Unique per trip."], ["Numbering", "Allocated in the same transaction as receipt insert."]], sec=[["Privacy", "Receipts show route map at reduced precision; access via ownership."]],
     adrs=[A("Credit notes instead of edits", "I", "Tax law.", [("Edit receipt", "Illegal in many places"), ("Credit note", "Chosen")], "Immutable docs.", "Compliant.", "More documents.", "N/A")],
     qa=[Q("Compliance", "How do you guarantee gap-free sequential invoice numbers under concurrency?", "Allocate from a sequence row per (entity, series) with `UPDATE number_sequences SET next = next + 1 ... RETURNING next - 1` in the same transaction as the receipt insert. If the transaction rolls back, the number is not consumed (unlike DB SEQUENCEs, which leave gaps). It serializes per series, so use per-city series where law allows to spread load.", "")],
     impl_order=["receipt-generator", "tax-reporting"], pkg="""com.atlas.receipts
├── gen  (ReceiptGenerator, TemplateRenderer, Numbering)
└── tax  (TaxAggregator, AuthorityExporter)""",
     tests=[T("Concurrency", "1,000 parallel receipts one series", "Contiguous numbers"), T("Correctness", "Receipt total vs ledger", "Equal")],
     evo=[("I", "Sync generation", "PG + object storage", "Unique per trip", "Pilot"), ("E", "Async workers", "—", "Retries", "Reliability"), ("E", "Event-driven", "—", "Idempotent", "Events"),
          ("E", "Business invoicing", "—", "—", "B2B"), ("E", "Per-city series for throughput", "—", "—", "Scale"), ("E", "Per-country e-invoicing", "In-country storage", "Residency", "Global")],
     ideas={"now": ["Immutable docs"], "next": ["E-invoicing"], "adv": ["Expense tool integrations"], "rej": ["DB sequences for legal numbers"]})

sub(id="receipt-generator", comp="receipts", name="Receipt & Invoice Generator", phase="I", cat="Documents · Compliance",
    resp="Produce immutable, localized, legally numbered receipts and credit notes from captured payments and adjustments.",
    inp="PaymentCaptured, RefundIssued, FareAdjusted", out="receipt/credit note documents + notification", deps="Numbering, Templates, Object storage, Notifications", cons="Riders, Business admins, Support", own="receipts, number_sequences",
    problem="Exact, compliant, timely documents.", without="Tax issues; rider confusion.",
    guar=["One receipt per captured trip", "Gap-free numbers per series", "Amounts equal captured amounts"], nong=["Email delivery"],
    usecase="Trip captured ₹267: receipt with fare breakdown, 5% GST line, entity GSTIN and number INV-PUN-2026-000123.",
    derive="- Generate from facts (fare breakdown + capture).\n- Number in the same transaction.\n- Render to HTML/PDF, store immutable.",
    conc="Sequence row lock per series.", consistency="Strong for numbering and the receipt row (same transaction). The rendered file is eventually consistent and retried until stored.", idem="Unique (trip_id, doc_type).", order="Credit notes reference the original receipt number.",
    restart="Generation retried; idempotent.", scale="Numbering contention per series → per-city series.", arch="Consumer → load breakdown → allocate number + insert receipt (tx) → render → upload → notify.",
    modules=[["Numbering", "Gap-free allocation"], ["Renderer", "Templates per locale/entity"], ["Store", "Immutable object storage"]],
    d_arch=("""flowchart LR
  EV["PaymentCaptured"] --> G["Generator"] --> NUM["Numbering"] --> DB[("receipts")]
  G --> RN["Renderer"] --> OBJ[("objects")]
  G --> NT["Notifications"]""", "Generation."),
    d_seq=("""sequenceDiagram
  participant G as Generator
  participant DB
  participant O as ObjectStore
  G->>DB: BEGIN; UPDATE sequences RETURNING n; INSERT receipt; COMMIT
  G->>O: put PDF (key immutable)
  G->>G: notify""", "Number then render."),
    d_state=("""stateDiagram-v2
  [*] --> Issued
  Issued --> Credited: credit note issued""", "Document status."),
    d_flow=("""flowchart LR
  B["fare breakdown"] --> T["tax lines"] --> R["receipt"]""", "Content."),
    d_fail=("""flowchart TB
  R["render failure"] --> RT["retry render (number already allocated, doc row exists)"]""", "Rendering is retryable after numbering."),
    sql="""CREATE TABLE receipts.number_sequences (entity text, series text, next bigint NOT NULL, PRIMARY KEY(entity, series));
CREATE TABLE receipts.receipts (id uuid PRIMARY KEY, trip_id uuid NOT NULL, doc_type text NOT NULL, number text NOT NULL UNIQUE, entity text NOT NULL,
  amount_minor bigint NOT NULL, tax_minor bigint NOT NULL, currency char(3) NOT NULL, file_key text, references_number text, issued_at timestamptz NOT NULL, UNIQUE(trip_id, doc_type));""",
    data="Retention per tax law (≥ 8 years).", api="""GET /v1/trips/{id}/receipt -> {number, url (signed, 10 min)}""",
    mech=[("Transactional numbering", "Taking the next number inside the same transaction as the insert means rollbacks don't burn numbers, which keeps the sequence gap-free.")],
    code="""@Transactional
public Receipt issue(Trip t, Breakdown b) {
    long n = jdbc.queryForObject("UPDATE receipts.number_sequences SET next=next+1 WHERE entity=? AND series=? RETURNING next-1", Long.class, t.entity(), t.series());
    return receipts.insert(t.id(), "RECEIPT", format(t.series(), n), b);
}""", cx="O(1).",
    fail=[F("Duplicate event", "Unique", "None", "Skip", "One doc")],
    alts=[["DB SEQUENCE", "Rejected", "Gaps on rollback", "Non-legal ids"]],
    adrs=[A("Per-city series", "V", "Contention.", [("One national series", "Hot row"), ("Per-city", "Chosen where legal")], "Series per city.", "Throughput.", "More series.", "N/A")],
    qa=[Q("Correctness", "The fare is adjusted after the receipt was sent. What does the rider get?", "A credit note (negative document) referencing the original receipt number and the new amount, plus an updated summary email. The original receipt is never modified.", "")],
    tests=[T("Concurrency", "Parallel issue", "Contiguous"), T("Idempotency", "Replay", "One receipt")],
    evo=["I: Sync generation", "E: Async workers", "E: Event-driven", "E: Business invoices", "E: Per-city series", "E: E-invoicing per country"],
    ideas={"now": ["Immutable"], "next": ["E-invoicing"], "adv": ["Expense integrations"], "rej": ["Editable receipts"]})

sub(id="tax-reporting", comp="receipts", name="Tax & Financial Reporting", phase="III", cat="Compliance · Batch",
    resp="Aggregate taxable amounts by jurisdiction, period and category from the ledger and documents, and export to authorities and finance.",
    inp="ledger postings, receipts, credit notes", out="tax returns data, reports", deps="Ledger, Receipts, Data platform", cons="Finance, Authorities", own="tax_reports",
    problem="Accurate periodic tax reporting across jurisdictions with different rules.", without="Fines and audits.",
    guar=["Report totals reconcile to ledger tax accounts", "Reports immutable once filed; amendments versioned"], nong=["Tax rule correctness (owned by tax team config)"],
    usecase="Monthly GST report for Maharashtra: Σ taxable fares, tax collected, credit notes. Equals the ledger tax_payable movements for the period.",
    derive="- Source of truth is the ledger tax accounts, cross-checked with documents.\n- Period close freezes data (late adjustments go to next period with references).",
    conc="One run per (jurisdiction, period).", consistency="Point-in-time snapshot at close.", idem="Re-run before filing yields the same result; after filing, a new version.", order="Periods sequential.",
    restart="Batch restartable.", scale="Warehouse queries.", arch="Warehouse job reads ledger and docs as of the period close, aggregates and validates against ledger totals, exports in authority format, and versions the report.",
    modules=[["PeriodClose", "Freeze"], ["Aggregator", "SQL in warehouse"], ["Validator", "Ledger cross-check"], ["Exporter", "Formats"]],
    d_arch=("""flowchart LR
  LED["ledger (lake copy)"] --> AG["Aggregator"]
  DOC["receipts"] --> AG
  AG --> VA["Validator"] --> EX["Exporter"] --> AUTH["Authority"]""", "Warehouse-based."),
    d_seq=("""sequenceDiagram
  participant J as Job
  participant W as Warehouse
  J->>W: aggregate period
  J->>W: compare with ledger tax account
  J-->>J: export v1""", "Monthly run."),
    d_state=("""stateDiagram-v2
  [*] --> Draft
  Draft --> Validated
  Validated --> Filed
  Filed --> Amended""", "Report lifecycle."),
    d_flow=("""flowchart LR
  P["postings (tax_payable)"] --> S["Σ by jurisdiction"] --> R["report"]""", "Aggregation."),
    d_fail=("""flowchart TB
  M["mismatch vs ledger"] --> B["block filing, investigate"]""", "Validation gate."),
    sql="""CREATE TABLE receipts.tax_reports (jurisdiction text, period text, version int, totals jsonb NOT NULL, state text NOT NULL, filed_at timestamptz, PRIMARY KEY(jurisdiction, period, version));""",
    data="Permanent.", api="Batch job: tax-report-{jurisdiction} monthly",
    mech=[("Ledger cross-check", "The report must equal ledger tax_payable movements for the period, which verifies document and ledger consistency at the same time.")],
    code="""SELECT jurisdiction, sum(amount_minor) FROM ledger_postings_lake WHERE account_type='TAX_PAYABLE' AND period=:p GROUP BY jurisdiction;""", cx="Warehouse scan.",
    fail=[F("Late adjustment after close", "Period frozen", "Next period", "Reference original", "Auditable")],
    alts=[["Third-party tax engine", "Viable", "Rule maintenance outsourced", "Many jurisdictions"]],
    adrs=[A("Ledger as source of truth", "III", "Consistency.", [("Receipts as source", "Misses non-receipt items"), ("Ledger", "Chosen")], "Ledger.", "Complete.", "Needs tax accounts per jurisdiction.", "N/A")],
    qa=[Q("Compliance", "How do marketplace facilitator rules affect tax?", "In some jurisdictions the platform collects and remits tax on the driver's service. Posting rules then credit tax_payable on the full fare and the report attributes it accordingly. The rule is per jurisdiction configuration.", "")],
    tests=[T("Integration", "Report vs ledger", "Equal")],
    evo=["N: Phase I uses accountant spreadsheets", "N: Accountant spreadsheets", "I: Warehouse job", "E: Multi-jurisdiction", "E: Automated filing", "E: Regional entities"],
    ideas={"now": ["n/a"], "next": ["Tax engine"], "adv": ["Real-time tax reporting APIs"], "rej": ["Manual at scale"]})
