from model import comp, sub, A, Q, F, T

# ======================================================================= Ride Request
comp(id="ride-request", domain="dispatch", name="Ride Request Management", tag="Dispatch · Entry point", phase="I", kind="Logical component (inside Request/Dispatch service from Phase IV)",
     biz="Turns a rider's tap on 'Confirm' into exactly one ride request with a locked price, then tracks it until it becomes a trip or ends unfulfilled.",
     eng="An idempotent, validated command endpoint that creates the request aggregate, locks the quote, authorizes payment and hands off to dispatch, with a request state machine.",
     deploy="Module (I); part of the Request service (IV) together with cancellation; city-sharded storage (V).", data_own="ride_requests, idempotency records.",
     up=["identity", "rider-profile", "pricing", "payments", "risk-fraud", "product-catalog"], down=["dispatch", "trip", "cancellation", "notifications"], ext=[],
     interfaces="`POST /v1/ride-requests` (Idempotency-Key), `GET /v1/ride-requests/{id}`, events `RideRequested`, `RequestUnfulfilled`.",
     problem="Mobile taps get retried, the same rider may have only one active request, prices must be locked, and payment must be authorized before a driver drives to the pickup.",
     fr=["Create request from quote", "Validate rider status, service area, product, payment", "One active request per rider", "Expose status to rider", "Expire unfulfilled after N minutes"],
     nfr=["Create p95 < 400 ms (including payment auth)", "Exactly one request per idempotency key", "Never two active requests per rider"],
     workload="0.05/s (I) → 5,000/s peak (VI).", success="Each tap yields exactly one request, processed promptly.", failure="Duplicate rides, charged twice, or requests lost.",
     derive="Retries cause duplicates, which calls for idempotency keys with stored responses. 'One active request per rider' is an invariant, enforced with a partial unique index. Validation needs data from several domains, so it runs synchronously before creation (fail fast), with payment authorization as the final step.",
     owns=["Request aggregate and its states", "Idempotency of creation"], not_owns=["Matching (Dispatch)", "Trip (Trip)", "Price computation (Pricing)", "Payment auth (Payments)"], sync=["Create", "Get status"], **{"async": ["Hand-off to dispatch", "Expiry", "Notifications"]},
     boundary_why="Separating the request (rider intent) from dispatch (search process) and trip (fulfilment) gives each a clean state machine, and lets dispatch retry or re-search without touching rider-facing state.",
     hld=("""flowchart LR
  APP["Rider app"] -->|POST + Idempotency-Key| RI["Request intake"]
  RI --> RV["Request validation"]
  RV --> RP["Rider status"] & CAT["Catalog"] & GF["Geofence"] & RK["Risk"]
  RI --> PQ["Pricing: use quote"]
  RI --> PA["Payments: authorize hold"]
  RI --> DB[("ride_requests")]
  RI -->|RideRequested| DSP["Dispatch"]""", "Intake orchestrates validation, quote locking and payment authorization, persists the request and triggers dispatch."),
     seq=("""sequenceDiagram
  participant A as App
  participant I as Intake
  participant V as Validation
  participant P as Pricing
  participant Pay as Payments
  participant D as Dispatch
  A->>I: POST /ride-requests (key K)
  I->>I: idempotency lookup K
  I->>V: validate
  I->>P: use(quote)
  I->>Pay: authorize(hold)
  I->>I: insert request (SEARCHING) + idempotency response
  I->>D: RideRequested
  I-->>A: 201 {request_id, status: SEARCHING}""", "Creation path. Every step before insert is reversible: quote use and auth hold are released if insert fails."),
     state=("""stateDiagram-v2
  [*] --> SEARCHING
  SEARCHING --> ASSIGNED: driver accepted (trip created)
  SEARCHING --> UNFULFILLED: no driver within timeout
  SEARCHING --> CANCELLED: rider cancels
  ASSIGNED --> [*]
  UNFULFILLED --> [*]
  CANCELLED --> [*]""", "Request lifecycle. After ASSIGNED, the Trip aggregate takes over."),
     subdeps=[("request-intake", "request-validation")],
     flow="Intake runs synchronous validation and resource locking (quote, payment hold), persists atomically with the idempotency record, and emits RideRequested. Failure after locking runs compensations (release quote, void hold).",
     data="`ride_requests(id, rider_id, city, product, pickup, dropoff, quote_id, payment_auth_id, status, created_at, expires_at, version)` with `UNIQUE(rider_id) WHERE status='SEARCHING'`; `idempotency_keys(key, rider_id, request_hash, response, created_at)`.",
     rel=[["Compensation", "If insert fails after auth: void auth; release quote."], ["Expiry", "Scheduled/delayed message at created_at + 3 min."], ["Idempotency", "24 h key retention."]],
     sec=[["Authz", "Rider can create only for themselves; business profiles check policy."], ["Abuse", "Rate-limit creates; risk gate."]],
     adrs=[A("Authorize payment before dispatch", "I", "Driver effort wasted on unpayable trips.", [("Authorize after trip", "Rejected: fraud"), ("Authorize before dispatch", "Chosen")], "Auth hold at request.", "Reduces unpaid trips.", "+150–400 ms latency; holds on rider's card.", "Trusted riders may skip pre-auth (Phase V risk-based).")],
     qa=[Q("Correctness", "The rider taps 'Confirm' twice quickly on a flaky network. What prevents two rides?", "Two layers. The client sends the same Idempotency-Key for both taps (generated when the confirm screen opens), so the server returns the stored response for the second. Independently, the partial unique index on (rider_id) WHERE status='SEARCHING' rejects a second active request even if the client bug generates two keys.", "Debouncing the button helps UX but isn't a guarantee.")],
     impl_order=["request-validation", "request-intake"], pkg="""com.atlas.request
├── intake     (RideRequestController, IntakeService, IdempotencyStore)
├── validation (RequestValidator, ValidationRule implementations)
└── lifecycle  (RequestStateMachine, ExpiryHandler)""",
     tests=[T("Concurrency", "Same key ×10 parallel", "One request, identical responses"), T("Failure", "Payment auth timeout", "No request created; quote released"), T("Integration", "Restricted rider", "403 ACCOUNT_RESTRICTED")],
     evo=[("I", "Module", "PG", "Idempotency + unique index", "Correctness"), ("E", "Same", "Delayed expiry via queue", "Payment breaker; compensation", "Reliability"),
          ("R", "Same", "RideRequested via outbox; payment as saga step", "Saga compensations", "Async dispatch"), ("R", "Request service", "Own DB", "SLO", "Isolation"), ("E", "City-sharded", "Shard by city", "Per-city bulkheads", "5K/s"), ("E", "Region by city", "—", "—", "Global")],
     ideas={"now": ["Idempotency keys"], "next": ["Risk-based skip of pre-auth"], "adv": ["Scheduled rides"], "rej": ["Client-side-only duplicate prevention"]})

sub(id="request-intake", comp="ride-request", name="Request Intake (Idempotent Create)", phase="I", cat="Correctness · Idempotency",
    resp="Create exactly one ride request per rider intent: dedupe retries, lock quote, authorize payment, persist, and hand off to dispatch, with compensation on partial failure.",
    inp="POST body {quote_id, quote_sig, pickup, dropoff, payment_method_id} + Idempotency-Key", out="request record, RideRequested, HTTP response", deps="Validation, Pricing, Payments, Dispatch", cons="Rider app", own="ride_requests, idempotency_keys",
    problem="Create a request reliably across multiple external steps when the client may retry at any moment and any step may fail.", without="Duplicate rides, orphaned payment holds, used-up quotes for failed requests.",
    guar=["Same key + same body → same response", "Same key + different body → 422", "No request without a successful auth hold (unless policy waives)", "Every acquired resource is released if creation fails"], nong=["Driver availability"],
    usecase="Network drops after the server committed. The client retries with the same key and gets the original 201 response, and no second hold is placed.",
    derive="- An idempotency record must be reserved *before* side effects, or concurrent duplicates both run side effects. Insert key as IN_PROGRESS first.\n- Side effects (quote use, payment auth) themselves need idempotency keys derived from the request key so retries don't duplicate them.\n- On failure, compensate in reverse order.",
    conc="`INSERT INTO idempotency_keys(key, status='IN_PROGRESS') ON CONFLICT DO NOTHING`. Losers poll the stored response or get 409 IN_PROGRESS. Request insert guarded by partial unique index.", consistency="Request + idempotency response committed in one transaction. External effects made idempotent with derived keys.",
    idem="Key scope = (rider_id, key). Response stored for 24 h. Payment auth uses key `req:{key}`, and quote use uses request_id derived deterministically (UUIDv5 of key).", order="Within one key, the first completion wins and later duplicates read its result.",
    restart="An IN_PROGRESS key older than 30 s is considered abandoned: a recovery job checks external state (payment auth by key) and either completes or compensates.", scale="Per-rider operations; key table partitioned by day, dropped after 2 days.",
    arch="An orchestrated local workflow inside the request handler:\n\n1. reserve idempotency key\n2. validate\n3. use quote\n4. authorize payment\n5. insert request + store response + outbox `RideRequested` (single transaction)\n6. return.\n\nCompensations: void auth, release quote, mark key FAILED with stored error response.",
    modules=[["IdempotencyStore", "Reserve/complete/fail keys"], ["IntakeOrchestrator", "Ordered steps + compensations"], ["DeterministicIds", "UUIDv5 from key → request id"], ["AbandonedKeyRecovery", "Resolve stuck IN_PROGRESS"]],
    d_arch=("""flowchart LR
  API["POST /ride-requests"] --> IS["IdempotencyStore"] --> DB[("idempotency_keys")]
  API --> OR["IntakeOrchestrator"]
  OR --> VAL["Validation"] & PR["Pricing.use"] & PAY["Payments.authorize"]
  OR --> TX["tx: request + response + outbox"] --> DB2[("ride_requests, outbox")]
  REC["AbandonedKeyRecovery"] --> IS & PAY""", "Orchestrator with an idempotency guard and recovery."),
    d_seq=("""sequenceDiagram
  participant C as Client
  participant I as Intake
  participant K as KeyStore
  participant P as Payments
  C->>I: POST (K)
  I->>K: insert K IN_PROGRESS
  I->>P: authorize(key=req:K)
  P--xI: timeout
  I->>P: authorize(key=req:K) retry
  P-->>I: auth_id (same hold)
  I->>I: tx insert request + K=COMPLETED(response)
  I-->>C: 201
  C->>I: POST (K) retry
  I->>K: lookup K → COMPLETED
  I-->>C: 201 (stored)""", "A timeout retried safely thanks to the derived payment key, then a client retry served from the stored response."),
    d_state=("""stateDiagram-v2
  [*] --> IN_PROGRESS
  IN_PROGRESS --> COMPLETED: request committed
  IN_PROGRESS --> FAILED: validation/payment error (response stored)
  IN_PROGRESS --> RECOVERING: abandoned > 30 s
  RECOVERING --> COMPLETED
  RECOVERING --> FAILED""", "Idempotency key lifecycle."),
    d_flow=("""flowchart LR
  K["Idempotency-Key"] --> RID["request_id = UUIDv5(ns, rider:K)"]
  K --> PK["payment key req:K"]
  BODY["body"] --> H["sha256(body)"] --> CMP["mismatch → 422"]""", "Derived identifiers make every downstream call idempotent."),
    d_fail=("""flowchart TB
  P["payment declined"] --> R1["release quote"] --> F["key FAILED (402 stored)"]
  C["crash after auth"] --> REC["recovery: auth exists by key → complete insert or void"]
  D["DB insert fails"] --> V["void auth, release quote"]""", "Compensations in reverse order. The recovery job covers crashes."),
    sql="""CREATE TABLE request.idempotency_keys (rider_id uuid, key text, request_hash bytea NOT NULL, status text NOT NULL,
  response_code int, response_body jsonb, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (rider_id, key));
CREATE TABLE request.ride_requests (id uuid PRIMARY KEY, rider_id uuid NOT NULL, city text NOT NULL, product text NOT NULL,
  pickup_lat double precision, pickup_lng double precision, dropoff_lat double precision, dropoff_lng double precision,
  quote_id uuid NOT NULL UNIQUE, payment_auth_id text, status text NOT NULL, expires_at timestamptz NOT NULL,
  version int NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX one_searching_per_rider ON request.ride_requests(rider_id) WHERE status = 'SEARCHING';""",
    data="Keys purged after 24 h (daily partition drop in Phase IV). Requests retained 3 years (support, analytics).",
    api="""POST /v1/ride-requests
Headers: Idempotency-Key: 6f1c…(uuid), Authorization: Bearer …
{ "quote_id":"…", "quote_sig":"…", "pickup":{"lat":..,"lng":..}, "dropoff":{...}, "payment_method_id":"pm_…" }
201 {"request_id":"…","status":"SEARCHING","expires_at":"…"}
409 ACTIVE_REQUEST_EXISTS{request_id} | 409 IDEMPOTENCY_IN_PROGRESS | 422 IDEMPOTENCY_KEY_REUSED | 402 PAYMENT_DECLINED | 410 QUOTE_EXPIRED""",
    mech=[("Idempotency key reservation", "Inserting the key first makes the database the arbiter among concurrent duplicates. Only the inserter executes side effects, and others read the outcome."), ("Derived downstream keys", "Passing `req:K` to payments makes the PSP deduplicate authorizations, so a timeout-then-retry results in one hold."), ("Compensation (local saga)", "Each step registers an undo, and on failure undos run in reverse. This is the same structure as a distributed saga, inside one process.")],
    code="""public Response create(UUID rider, String key, CreateRequest body) {
    var reserved = keys.reserve(rider, key, sha256(body));
    if (reserved.existing().isPresent()) return reserved.existing().get().replay(body);
    var undo = new ArrayDeque<Runnable>();
    try {
        validator.validate(rider, body);
        UUID requestId = DeterministicIds.v5(rider, key);
        pricing.use(body.quoteId(), body.quoteSig(), requestId);          undo.push(() -> pricing.release(body.quoteId()));
        String auth = payments.authorize("req:" + key, rider, body.paymentMethodId(), quoteAmount); undo.push(() -> payments.voidAuth(auth));
        return tx.execute(s -> { requests.insert(requestId, rider, body, auth); outbox.add(new RideRequested(requestId));
                                   return keys.complete(rider, key, Response.created(requestId)); });
    } catch (RuntimeException e) { undo.forEach(Runnable::run); return keys.fail(rider, key, Errors.map(e)); }
}""", cx="O(1) DB ops + 2 remote calls.",
    fail=[F("Crash after auth before insert", "IN_PROGRESS > 30 s", "Hold on card", "Recovery voids or completes", "Converges"), F("Duplicate concurrent POST", "Key conflict", "None", "Second waits/409", "One request"),
          F("Payment provider timeout", "Breaker/timeout", "Slow create", "Retry with same key; then fail 503", "No double hold"), F("Second active request (new key)", "Unique index", "Rejected", "409 with existing id", "Invariant held")],
    alts=[["Two-phase commit with PSP", "Impossible", "PSPs don't support XA", "Never"], ["Async creation (202) + polling", "Viable", "Hides latency", "If auth latency hurts UX (Phase V option)"]],
    adrs=[A("Reserve idempotency key before side effects", "I", "Concurrent duplicates.", [("Store response after", "Rejected: duplicates both execute"), ("Reserve first", "Chosen")], "Reserve, execute, complete.", "Single execution.", "Recovery job needed for abandoned keys.", "N/A")],
    qa=[Q("Distributed systems", "Why is a stored HTTP response the right idempotency result rather than just 'already exists'?", "Clients need the same outcome to proceed: the request id and status. Returning the original response, including original errors such as 402, makes retries indistinguishable from the first attempt. That property is what makes client retry logic simple and correct.", ""),
        Q("Reliability", "What happens if the rider's payment authorization takes 3 seconds at peak?", "Phase I–II: the request waits with a 2.5 s timeout, then fails with 503 and the rider retries (same key, safe). Phase III+: request creation becomes asynchronous. The request is persisted as PENDING_PAYMENT and returned with 202, and the payment saga step authorizes. Dispatch starts only after authorization, or immediately for low-risk riders with deferred auth.", "")],
    tests=[T("Concurrency", "Same key 20×", "1 request; all responses identical"), T("Failure", "Kill process after authorize", "Recovery voids or completes within 1 min"), T("Contract", "Key reused with different body", "422")],
    evo=["I: Synchronous orchestration with local compensations", "E: Recovery job; payment breaker", "R: Persist PENDING_PAYMENT + saga via outbox events", "E: In Request service with gRPC to Pricing/Payments", "E: City-sharded storage", "E: Regional, city-homed"],
    ideas={"now": ["Body hash check"], "next": ["Async creation"], "adv": ["Risk-based deferred auth"], "rej": ["Server-generated idempotency"]})

sub(id="request-validation", comp="ride-request", name="Request Validation", phase="I", cat="Correctness · Business rules",
    resp="Reject requests that must not proceed: restricted riders, out-of-area pickups, disabled products, invalid quotes, unsafe or abusive patterns.",
    inp="rider, pickup/dropoff, product, quote, device", out="ok or typed validation error", deps="Rider profile, Catalog, Geofencing, Risk", cons="Request intake", own="Validation rules config",
    problem="Fail fast with clear reasons before any resources are locked.", without="Wasted dispatch on invalid requests; confusing failures later.",
    guar=["Rules evaluated in fixed order (cheap → expensive)", "Each failure has a stable error code", "Rule set versioned per city"], nong=["Fraud certainty"],
    usecase="Pickup in the airport restricted lane → rejected with PICKUP_NOT_ALLOWED and a suggested pickup point at the official zone.",
    derive="- Rules are independent predicates, so a chain of `ValidationRule` objects.\n- Order by cost (local checks first, remote risk call last).\n- Some failures carry suggestions (pickup points), so result objects, not booleans.",
    conc="Read-only checks.", consistency="Reads may be slightly stale (cached rider status ≤ 60 s from Phase IV).", idem="Validation has no side effects, so it is safe to repeat on retries.", order="Rules run in a fixed order. Inputs are read at validation time, and later changes are handled by owning domains.",
    restart="Stateless: a restarted instance reloads rule config from the table and is immediately ready.", scale="Cheap; risk call is the cost.", arch="Chain of responsibility with short-circuit on first failure, and per-city rule enablement.",
    modules=[["ValidationRule", "Interface"], ["RuleChain", "Ordered evaluation"], ["Rules", "RiderStatus, ServiceArea, ProductEnabled, PickupZone, DropoffReachable, RiskGate"]],
    d_arch=("""flowchart LR
  REQ["request"] --> CH["RuleChain"]
  CH --> R1["RiderStatus"] --> R2["ServiceArea"] --> R3["ProductEnabled"] --> R4["PickupZone"] --> R5["RiskGate"]""", "Cheap rules first."),
    d_seq=("""sequenceDiagram
  participant I as Intake
  participant C as Chain
  participant G as Geofence
  participant K as Risk
  I->>C: validate
  C->>G: zones(pickup)
  G-->>C: airport-restricted
  C-->>I: PICKUP_NOT_ALLOWED + suggested point""", "Short-circuit failure."),
    nostate="Stateless rule evaluation.",
    d_flow=("""flowchart LR
  IN["request"] --> RULES["rules"] --> OUT["ok | error{code, message, suggestion}"]""", "Typed result."),
    d_fail=("""flowchart TB
  K["risk service down"] --> P["policy: allow low-value, block high-value; flag for post-review"]""", "Explicit degraded policy for remote rules."),
    sql="CREATE TABLE request.validation_rules (city text, rule text, enabled boolean, params jsonb, PRIMARY KEY(city, rule));",
    data="Rule config versioned.", api="""interface ValidationRule { Optional<ValidationError> check(RequestContext ctx); int cost(); }
Errors: ACCOUNT_RESTRICTED | OUT_OF_SERVICE_AREA | PRODUCT_UNAVAILABLE | PICKUP_NOT_ALLOWED{suggested_pickup} | RISK_BLOCKED""",
    mech=[("Chain of responsibility with cost ordering", "Evaluating cheap, frequently-failing rules first minimizes average latency and remote calls.")],
    code="""public void validate(RequestContext ctx) {
    for (ValidationRule r : rules.forCity(ctx.city())) r.check(ctx).ifPresent(err -> { throw new ValidationException(err); });
}""", cx="O(rules).",
    fail=[F("Risk timeout", "Breaker", "Unknown risk", "Degraded policy", "Flagged for review")],
    alts=[["Validate in client", "Insufficient", "Untrusted", "UX hints only"]],
    adrs=[A("Typed errors with suggestions", "I", "UX recovery.", [("Generic 400", "Rejected"), ("Typed codes", "Chosen")], "Stable codes.", "Clients can react.", "Contract maintenance.", "N/A")],
    qa=[Q("Product", "Should the dropoff be validated against the service area?", "Allow dropoffs outside the area up to a max distance (driver may return empty), with a return-trip fee per city policy, and reject only unreachable destinations (no road route, across borders without permits).", "")],
    tests=[T("Unit", "Each rule failure", "Correct code"), T("Failure", "Risk down", "Degraded policy applied")],
    evo=["I: In-process rules", "E: Risk gate with breaker", "U: No change needed", "E: Cached remote inputs", "U: No change needed", "E: Region-specific rules"],
    ideas={"now": ["Suggested pickups"], "next": ["Smart pickup points"], "adv": ["ML-based pickup correction"], "rej": ["Silent rejection"]})

# ======================================================================= Matching & Dispatch
comp(id="dispatch", domain="dispatch", name="Matching & Dispatch Engine", tag="Dispatch · Core algorithm", phase="I", kind="Logical component → deployable service (Phase IV) → city-sharded (Phase V)",
     biz="Finds the best available driver for each request and gets them to accept, quickly and fairly, so riders wait less and drivers earn more.",
     eng="A search-and-commit loop: generate candidates near the pickup, rank by ETA and other signals, offer exclusively with timeouts, commit the assignment atomically with driver state and trip creation, and repeat until matched or timed out.",
     deploy="Module (I); Dispatch service (IV); one dispatch shard per city/region-of-city with batch matching (V).", data_own="dispatch_attempts, offers, matching configs.",
     up=["ride-request", "geo-index", "routing-eta", "driver-supply", "applied-models", "workflow"], down=["trip", "notifications", "cancellation", "event-pipeline"], ext=[],
     interfaces="Consumes `RideRequested`; driver app `POST /v1/offers/{id}/accept|decline`; emits `DriverAssigned`, `OfferSent`, `DispatchFailed`.",
     problem="Supply and demand are spatially scattered and change by the second, drivers may decline or ignore offers, and the assignment must be exclusive. Greedy nearest-first choices are locally optimal but globally wasteful at high density.",
     fr=["Candidate generation within radius/ETA", "Ranking by ETA, acceptance probability, fairness", "Exclusive offer with 15 s timeout", "Atomic assignment + trip creation", "Re-search on decline/timeout", "Batch matching at density (Phase IV+)"],
     nfr=["Time to first offer p95 < 2 s", "Zero double assignment", "Match rate > 95% when supply exists", "Per-city isolation (Phase V)"],
     workload="Per request ≈ 1–3 offers; ETA matrix per round. Phase V ≈ 500 req/s peak, stadium bursts concentrated in one shard.", success="Short pickup ETAs, high acceptance, no double assignment.", failure="Riders wait while nearby drivers idle; double assignments; offer storms to the same driver.",
     derive="Exclusive offers need a lease on the driver, which Supply's RESERVED state provides. Assignment changes driver state, request state and creates the trip, so it is one transaction in Phase I–III and an ordered commit protocol with idempotent steps after the services split. Ranking needs ETAs for many drivers, so many-to-one ETA. Global efficiency at density needs batching: collect requests for 1–2 s and solve an assignment problem.",
     owns=["Dispatch attempts and offers", "Ranking policy", "Matching algorithm"], not_owns=["Driver state (Supply: reserve/assign via API)", "Trip record (Trip creates it)", "Positions (Geo)"], sync=["Offer accept/decline", "Reserve/assign calls"], **{"async": ["Triggered by RideRequested", "Offer timeouts", "Re-search loops"]},
     boundary_why="Dispatch is a decision process and owns only its own attempt/offer records. State it changes elsewhere goes through those owners' atomic APIs, which keeps every invariant with one owner.",
     hld=("""flowchart LR
  RR["RideRequested"] --> DL["Dispatch loop"]
  DL --> CG["Candidate generation"] --> GEO["Geo index"]
  CG --> ETA["ETA matrix"]
  DL --> RK["Ranking"] --> ML["Match model"]
  DL --> OM["Offer manager"] --> SUP["Supply: tryReserve"]
  OM -->|push| DRV["Driver app"]
  DRV -->|accept| OM --> AC["Assignment commit"] --> SUP & TRIP["Trip: create"] & REQ["Request: ASSIGNED"]
  DL --> BM["Batch matcher (P4+)"]""", "The loop generates, ranks and offers. Acceptance triggers the assignment commit across Supply, Trip and Request. At density, the batch matcher replaces per-request greedy ranking."),
     seq=("""sequenceDiagram
  participant R as Request
  participant D as Dispatch
  participant G as Geo
  participant E as ETA
  participant S as Supply
  participant Dr as Driver
  participant T as Trip
  R->>D: RideRequested
  D->>G: nearby(pickup, 3km)
  D->>E: etaMatrix(20)
  D->>D: rank
  D->>S: tryReserve(best, ttl 17s)
  D->>Dr: offer (15s)
  Dr->>D: accept
  D->>S: assign(driver, req)
  D->>T: createTrip(req, driver)
  D->>R: mark ASSIGNED""", "The happy path from request to assignment."),
     state=("""stateDiagram-v2
  [*] --> Searching
  Searching --> Offering: candidate reserved
  Offering --> Searching: declined / timeout
  Offering --> Committing: accepted
  Committing --> Matched: trip created
  Committing --> Searching: lease lost
  Searching --> Failed: request timeout (3 min)
  Matched --> [*]
  Failed --> [*]""", "Dispatch attempt state per request."),
     subdeps=[("candidate-generation", "driver-ranking"), ("driver-ranking", "offer-manager"), ("offer-manager", "assignment-commit"), ("batch-matching", "candidate-generation"), ("batch-matching", "offer-manager")],
     flow="A dispatch attempt is a small state machine driven by events (request, accept, decline, timeout). Each round excludes drivers already offered. The commit step is idempotent and ordered: Supply assign → Trip create → Request ASSIGNED, with retries and a reconciler for partial completion.",
     data="`dispatch_attempts(request_id PK, city, state, round, offered_driver_ids uuid[], started_at, matched_driver_id, version)`, `offers(id, request_id, driver_id, state, sent_at, expires_at, responded_at)`.",
     rel=[["Timeouts", "Offer 15 s + lease 17 s; request 3 min."], ["Idempotency", "Accept keyed by offer id; commit steps keyed by request id."], ["Isolation", "Per-city worker pools (II), shards (V)."], ["Reconciliation", "Detect Supply ON_TRIP without trip, or trip without request ASSIGNED; repair."]],
     sec=[["Fairness", "Ranking must not use protected attributes; acceptance-rate penalties capped."], ["Abuse", "Drivers can't see destination before accept where regulations require (or must, in others)."]],
     adrs=[A("Sequential exclusive offers (Phase I–III) then batch matching (IV+)", "IV", "Greedy is simple. Batching wins at density.", [("Broadcast offer to many drivers (first-accept wins)", "Rejected: poor driver experience, races"), ("Sequential exclusive", "Chosen for I–III"), ("Batch assignment every 1–2 s", "Chosen for dense cities from IV")],
             "Greedy sequential offers, then batched bipartite matching in dense zones.", "Simplicity early, efficiency at scale.", "Batch adds up to 2 s latency.", "When density is low, the batch window adds latency without gain; fall back to greedy per zone.")],
     qa=[Q("Distributed systems", "After services split (Phase IV), assignment spans Supply, Trip and Request. How do you keep it consistent without 2PC?", "Use an ordered, idempotent commit protocol owned by Dispatch.\n\n1. `Supply.assign(driver, req, version)` is the linearization point: if it succeeds the driver is committed.\n2. `Trip.create(tripId=f(req), req, driver)` is idempotent by deterministic trip id.\n3. `Request.markAssigned(req, tripId)` is idempotent.\n\nIf Dispatch crashes between steps, a durable attempt record (state=Committing) is resumed by another worker, which replays the steps safely. A reconciler also scans for drivers ON_TRIP whose trip doesn't exist after 30 s and completes or reverts them. The rider never sees ASSIGNED before the trip exists, because the request is marked last.", "2PC across services needs a coordinator and blocks on failure. A saga with the linearization point first avoids compensating the hardest step.")],
     impl_order=["candidate-generation", "driver-ranking", "offer-manager", "assignment-commit", "batch-matching (Phase IV)"], pkg="""com.atlas.dispatch
├── loop       (DispatchLoop, DispatchAttempt, AttemptRepository)
├── candidates (CandidateGenerator)
├── ranking    (Ranker, Features, FairnessPolicy)
├── offers     (OfferManager, OfferTimeoutHandler)
├── commit     (AssignmentCommitter, AssignmentReconciler)
└── batch      (BatchWindow, HungarianSolver)  // Phase IV""",
     tests=[T("Concurrency", "500 requests, 100 drivers, simulated accepts", "No driver on two trips; all attempts terminate"), T("Failure", "Kill dispatch worker mid-commit", "Resumed; one trip"), T("Simulation", "Replay peak hour with greedy vs batch", "Batch reduces mean pickup ETA ≥ 10%")],
     evo=[("I", "Module: greedy sequential offers", "PG; in-process timers via job table", "Single DB transaction for commit", "Correctness"), ("E", "Same; per-city worker pools", "Delayed messages for offer timeouts", "Bulkheads per city", "Reliability"),
          ("R", "Event-driven attempts", "RideRequested/OfferResponded events", "Durable attempts; reconciler", "Async workflows"), ("R", "Dispatch service + batch matching in dense zones", "gRPC to Supply/Trip", "Ordered idempotent commit", "Isolation; efficiency"),
          ("R", "City shards; ML acceptance model", "In-memory attempt state + log", "Shard failover", "500 req/s, hot cities"), ("E", "Regional shards by city home", "—", "Fencing on failover", "Global")],
     ideas={"now": ["Exclude previously-offered drivers"], "next": ["Batch matching"], "adv": ["Forward dispatch (offer to drivers finishing nearby trips)"], "rej": ["Broadcast offers"]})

sub(id="candidate-generation", comp="dispatch", name="Candidate Generation", phase="I", cat="Algorithm · Search",
    resp="Produce a bounded set of plausible drivers for a request: fresh, available, right category, within radius/ETA, not previously offered.",
    inp="request (pickup, product), round number, excluded drivers", out="≤ N candidates with ETAs", deps="Geo index (proximity search), ETA service, Supply", cons="Ranking", own="No data (per-attempt exclusion list owned by attempt)",
    problem="Narrow thousands of drivers to a few dozen worth ranking, quickly and with high recall.", without="Ranking over too many (slow) or too few (poor matches).",
    guar=["Candidates satisfy hard constraints (category, availability, freshness)", "Radius expands by round (3 → 5 → 8 km)", "ETA computed for every returned candidate"], nong=["Optimal choice (ranking)"],
    usecase="Round 1: 3 km gives 6 drivers, 2 excluded (declined earlier), so 4 candidates with ETAs 4–9 min. Round 2 if needed: 5 km.",
    derive="- Recall over precision: straight-line nearest N, then road ETA.\n- Expanding radius per round trades wait time for reach.\n- Hard filters belong here, soft preferences in ranking.",
    conc="Read-only queries.", consistency="Positions/availability may be seconds stale; reservation at offer time is the real check.", idem="Same inputs produce the same candidates (modulo index changes); no side effects.", order="Rounds are sequential within an attempt.",
    restart="Stateless; attempt state holds exclusions.", scale="Cost dominated by ETA matrix; bounded N (20).", arch="`CandidateGenerator.generate(req, round, excluded)`: geo nearby (N×2) → drop excluded → ETA matrix → drop ETA > max(round) → top N by ETA.",
    modules=[["RadiusPolicy", "Per city/product/round"], ["GeoQuery", "Nearby"], ["EtaEnricher", "Matrix"], ["HardFilters", "Category, freshness, exclusions, accessibility"]],
    d_arch=("""flowchart LR
  REQ["req, round"] --> RP["RadiusPolicy"] --> GQ["GeoQuery"] --> HF["HardFilters"] --> EE["EtaEnricher"] --> OUT["candidates"]""", "Linear pipeline."),
    d_seq=("""sequenceDiagram
  participant D as Dispatch
  participant C as CandidateGen
  participant G as Geo
  participant E as ETA
  D->>C: generate(req, round 1, excluded)
  C->>G: nearby(3km, 40)
  C->>C: filter excluded
  C->>E: etaMatrix(≤20)
  C-->>D: candidates with ETA""", "Single round."),
    nostate="Stateless per call. Rounds are tracked by the dispatch attempt.",
    d_flow=("""flowchart LR
  ALL["~300 drivers in city"] --> NEAR["40 nearest"] --> F["20 after filters"] --> E["ETA"] --> OUT["≤ 20"]""", "Funnel."),
    d_fail=("""flowchart TB
  E["ETA down"] --> SL["use straight-line × city detour factor"]
  G["Geo down"] --> NONE["no candidates; retry round after 2s"]""", "Degrades to approximate ranking."),
    sql="-- No owned tables.", data="None.", api="""List<Candidate> generate(RideRequest req, int round, Set<UUID> excluded)
record Candidate(UUID driverId, double distanceM, int etaS, long positionTs)""",
    mech=[("Funnel filtering", "Apply cheap filters on large sets and expensive enrichment (ETA) on small sets."), ("Round-based radius expansion", "Search wider only when nearby supply is exhausted, keeping typical pickups short.")],
    code="""public List<Candidate> generate(RideRequest r, int round, Set<UUID> excluded) {
    int radius = radiusPolicy.radius(r.city(), r.product(), round);
    var near = geo.nearby(r.pickup(), radius, r.product(), 40, Duration.ofSeconds(30)).stream()
        .filter(c -> !excluded.contains(c.driverId())).limit(20).toList();
    int[] etas = eta.manyToOne(near.stream().map(Candidate::pos).toList(), r.pickup(), Deadline.ms(120));
    return zip(near, etas).filter(c -> c.etaS() <= radiusPolicy.maxEta(round)).sorted(comparingInt(Candidate::etaS)).toList();
}""", cx="O(N) + ETA matrix.",
    fail=[F("ETA timeout", "Deadline", "Approximate ETAs", "Straight-line fallback", "None"), F("Stale positions", "ts filter", "Fewer candidates", "Next round", "None")],
    alts=[["ETA for all drivers in radius", "Rejected", "Expensive", "Very sparse areas"]],
    adrs=[A("N=20 cap", "I", "Latency budget.", [("Unbounded", "Rejected"), ("20", "Chosen")], "Cap 20.", "Bounded ETA cost.", "Rarely misses best.", "Tune by measured recall.")],
    qa=[Q("Performance", "How do you verify that capping at 20 straight-line candidates doesn't miss the best ETA driver?", "Offline: for a sample of requests, compute ETAs for all drivers within 8 km and measure how often the best ETA driver is outside the top 20 by distance (recall@20). Raise N or add barrier-aware rules where recall < 98%.", "")],
    tests=[T("Unit", "Excluded driver nearest", "Not returned"), T("Failure", "ETA service down", "Fallback ETAs")],
    evo=["I: PostGIS query + provider ETA", "E: Redis geo + ETA cache", "U: No change needed", "E: Geo/ETA services via gRPC", "E: Per-shard in-memory geo access", "U: No change needed"],
    ideas={"now": ["Recall measurement"], "next": ["Forward dispatch candidates (drivers about to finish)"], "adv": ["Learned candidate generation"], "rej": ["City-wide scans"]})

sub(id="driver-ranking", comp="dispatch", name="Driver Ranking", phase="I", cat="Algorithm · Scoring",
    resp="Order candidates by expected value: pickup ETA first, adjusted for acceptance probability, rider rating, driver fairness and product constraints.",
    inp="candidates with ETAs, driver features, request context", out="ranked list with scores", deps="Feature store, Match model (Phase V)", cons="Offer manager", own="Ranking configs",
    problem="The nearest driver isn't always the best offer: they may decline, be finishing a shift, or have just been offered many trips while others idle.", without="Wasted offer rounds; unfair earnings distribution.",
    guar=["Score is deterministic given features and config version", "Fairness adjustment bounded", "Explainable score components logged"], nong=["Optimality across requests (batch matching)"],
    usecase="Driver A ETA 4 min, acceptance probability 0.4. Driver B ETA 5 min, p=0.9. Expected time to an accepted match favours B.",
    derive="- Objective: minimize expected rider wait = ETA + E[time lost to declines].\n- Score = ETA + (1 − p_accept) × offer_timeout_cost.\n- Fairness: small bonus for long-idle drivers, bounded so pickup ETA increases are capped.",
    conc="Pure function over immutable inputs, so concurrent ranking calls share nothing.", consistency="Config version pinned per attempt.", idem="Same inputs and config version give the same ranking.", order="Each ranking call is independent.",
    restart="Stateless: config and model are reloaded at start, and attempts in flight simply re-rank in their next round.", scale="O(N log N) with N ≤ 20.", arch="Phase I: ETA sort. Phase III: rule-based score with acceptance rate from history. Phase V: model-predicted p_accept (online features) in the score formula.",
    modules=[["FeatureFetcher", "Acceptance rate, idle time, rating"], ["Scorer", "Score formula"], ["FairnessPolicy", "Idle-time bonus cap"], ["Explainer", "Log components"]],
    d_arch=("""flowchart LR
  C["candidates"] --> FF["FeatureFetcher"] --> FS[("online features")]
  FF --> SC["Scorer"] --> FP["FairnessPolicy"] --> OUT["ranked"]
  SC --> ML["p_accept model (P5)"]""", "Feature-enriched scoring."),
    d_seq=("""sequenceDiagram
  participant D as Dispatch
  participant R as Ranker
  participant F as Features
  D->>R: rank(candidates)
  R->>F: batch get(driver features)
  R->>R: score = eta + (1-p)·15s·k − fairness
  R-->>D: ordered""", "Ranking call."),
    nostate="Stateless scoring.",
    d_flow=("""flowchart LR
  ETA["eta 300s"] --> S["score"]
  P["p_accept 0.6"] --> S
  IDLE["idle 25 min"] --> S
  S --> RANK["rank"]""", "Score inputs."),
    d_fail=("""flowchart TB
  F["features unavailable"] --> E["ETA-only ranking"]""", "Fallback to the Phase I policy."),
    sql="CREATE TABLE dispatch.ranking_config (city text, version int, params jsonb, active boolean, PRIMARY KEY(city, version));",
    data="Score components logged to lake for evaluation.", api="""List<Ranked> rank(List<Candidate> cs, RequestContext ctx)""",
    mech=[("Expected-wait scoring", "Each decline costs roughly the offer timeout plus re-search, so weighting by (1−p) converts acceptance probability into seconds, the same unit as ETA."), ("Bounded fairness", "Bonus = min(cap, α × idle_minutes) seconds. Fairness can't add more than e.g. 60 s pickup time.")],
    code="""double score(Candidate c, DriverFeatures f, RankingParams p) {
    double expectedDeclineCost = (1 - f.pAccept()) * p.declineCostSeconds();
    double fairness = Math.min(p.fairnessCapS(), p.alpha() * f.idleMinutes());
    return c.etaS() + expectedDeclineCost - fairness;  // lower is better
}""", cx="O(N log N).",
    fail=[F("Feature store down", "Timeout", "ETA-only", "Fallback", "None"), F("Model bias", "Fairness dashboards", "Unequal offers", "Config rollback", "None")],
    alts=[["Nearest only", "Phase I", "Simple", "Low density"], ["Pure ML ranking", "Advanced", "Opaque", "With strong guardrails"]],
    adrs=[A("Expected-wait formula", "III", "Declines waste time.", [("ETA only", "Ignores declines"), ("Expected wait", "Chosen")], "Formula.", "Interpretable.", "p_accept quality matters.", "N/A")],
    qa=[Q("Fairness", "Using acceptance probability penalizes drivers who decline unsafe areas. Is that acceptable?", "Not unbounded. Acceptance features are computed excluding declines with protected reasons (safety, accessibility mismatch) and capped in influence. Drivers can see their acceptance rate. Ranking audits check outcome distributions across neighbourhoods.", "")],
    tests=[T("Unit", "Higher p wins within ETA delta", "Correct order"), T("Fairness", "Simulated idle bonus", "Max added ETA ≤ cap")],
    evo=["I: ETA sort", "U: No change needed", "E: Rule-based score with history", "E: Feature store", "R: ML p_accept", "E: Regional configs"],
    ideas={"now": ["Log components"], "next": ["p_accept model"], "adv": ["Reinforcement learning dispatch"], "rej": ["Unbounded acceptance penalties"]})

sub(id="offer-manager", comp="dispatch", name="Offer Manager (Exclusive Offers & Timeouts)", phase="I", cat="Concurrency · Timers",
    resp="Send one exclusive offer at a time to a reserved driver, enforce the response timeout, and process accept/decline exactly once.",
    inp="ranked candidates, driver responses, timer firings", out="offers, OfferAccepted/Declined/Expired, next-candidate triggers", deps="Supply (reserve/release), Notifications (push), Scheduler", cons="Assignment commit, Dispatch loop", own="offers",
    problem="Coordinate a human response with a deadline while guaranteeing a driver can't accept an offer that has already expired or been reassigned.", without="Accepts on expired offers; drivers getting two offers; stuck attempts.",
    guar=["At most one live offer per driver and per request", "A response after expiry is rejected", "Every offer ends in exactly one of ACCEPTED, DECLINED, EXPIRED"], nong=["Delivery of the push (in-app polling backup)"],
    usecase="Offer to K at 12:00:00 (expires 12:00:15). K taps accept at 12:00:16 → OFFER_EXPIRED shown. Timer fired at 12:00:15 and the next candidate was offered.",
    derive="- Exclusive: reserve driver in Supply before sending.\n- Deadline: durable timer at expires_at.\n- Race between accept and timeout: resolve with a conditional update on the offer row (first wins).",
    conc="`UPDATE offers SET state=:s WHERE id=:id AND state='PENDING' AND (:s<>'ACCEPTED' OR now() <= expires_at)`. Accept and timer race; exactly one wins.", consistency="Strong on offer row.",
    idem="Accept/decline keyed by offer id; repeated accept returns the same result. Timer firing on a resolved offer is a no-op.", order="Late responses rejected by state check; timer and response order irrelevant.",
    restart="Phase I: job table polled with SKIP LOCKED. Phase II: delayed messages (RabbitMQ delayed exchange). Phase III+: workflow timers. Restart reloads pending timers.", scale="Offers ≈ 2× requests; timers cheap.",
    arch="`OfferManager.offer(req, candidate)`: tryReserve(driver, ttl=17s) → insert offer (PENDING, expires +15s) → schedule timer → push to driver. Responses and timers both funnel into `resolve(offerId, outcome)`.",
    modules=[["OfferStore", "Conditional state transitions"], ["TimerScheduler", "Durable timers"], ["PushSender", "Push + in-app pull fallback"], ["Resolver", "Single resolution path for accept/decline/expire"]],
    d_arch=("""flowchart LR
  DL["Dispatch loop"] --> OM["OfferManager"] --> SUP["Supply tryReserve"]
  OM --> OS[("offers")]
  OM --> TS["TimerScheduler"] --> JOBS[("jobs / delayed queue")]
  OM --> PS["Push"] --> DRV["Driver app"]
  DRV -->|accept/decline| RS["Resolver"] --> OS
  JOBS -->|fire| RS
  RS -->|accepted| AC["Assignment commit"]
  RS -->|declined/expired| DL""", "Responses and timers converge on one resolver."),
    d_seq=("""sequenceDiagram
  participant O as OfferManager
  participant S as Supply
  participant Dr as Driver
  participant Tm as Timer
  O->>S: tryReserve(K, req, 17s)
  O->>O: insert offer PENDING exp+15s
  O->>Tm: schedule(offer, +15s)
  O->>Dr: push offer
  par race
    Dr->>O: accept (t=14.9s)
  and
    Tm->>O: fire (t=15s)
  end
  O->>O: conditional update: first wins
  Note over O: accept wins, timer sees state != PENDING → no-op""", "Accept vs timeout race resolved by one conditional update."),
    d_state=("""stateDiagram-v2
  [*] --> PENDING
  PENDING --> ACCEPTED: accept ≤ expires_at
  PENDING --> DECLINED: decline
  PENDING --> EXPIRED: timer
  ACCEPTED --> [*]
  DECLINED --> [*]
  EXPIRED --> [*]""", "Offer lifecycle."),
    d_flow=("""flowchart LR
  OFFER["offer {pickup area, est. fare, eta}"] --> PUSH["push"] --> APP["driver screen countdown"]
  APP --> RESP["response with offer_id"]""", "Offer payload and response."),
    d_fail=("""flowchart TB
  P["push not delivered"] --> POLL["driver app polls /offers/current every 3s while online"]
  T["timer service down"] --> SW["sweeper expires offers with expires_at < now()"]
  A["accept after expiry"] --> R["409 OFFER_EXPIRED"]""", "Each failure has a backstop."),
    sql="""CREATE TABLE dispatch.offers (id uuid PRIMARY KEY, request_id uuid NOT NULL, driver_id uuid NOT NULL, round int NOT NULL,
  state text NOT NULL CHECK (state IN ('PENDING','ACCEPTED','DECLINED','EXPIRED')), sent_at timestamptz NOT NULL, expires_at timestamptz NOT NULL, responded_at timestamptz);
CREATE UNIQUE INDEX one_pending_offer_per_request ON dispatch.offers(request_id) WHERE state = 'PENDING';
CREATE UNIQUE INDEX one_pending_offer_per_driver ON dispatch.offers(driver_id) WHERE state = 'PENDING';""",
    data="Offers retained 1 year for acceptance analytics.", api="""POST /v1/offers/{id}/accept   (driver)  -> 200 {trip_id} | 409 OFFER_EXPIRED | 409 OFFER_NOT_PENDING
POST /v1/offers/{id}/decline  {reason} -> 204
GET  /v1/offers/current       -> offer | 204
event OfferResolved{offer_id, request_id, driver_id, outcome, at}""",
    mech=[("Durable timers", "Phase I: a `jobs(run_at, payload)` table polled every second with `FOR UPDATE SKIP LOCKED`. Phase II: RabbitMQ delayed messages. Phase III+: Temporal timers. All are durable: a restart does not lose a deadline."), ("Single resolver", "Accept, decline and expiry all call one conditional update. Races resolve in the database, not in application logic."), ("Lease > offer timeout", "Supply lease 17 s vs offer 15 s means the reservation can't lapse while the offer is still valid.")],
    code="""@Transactional
public Resolution resolve(UUID offerId, Outcome outcome) {
    int n = jdbc.update(\"\"\"
        UPDATE dispatch.offers SET state=?, responded_at=now()
        WHERE id=? AND state='PENDING' AND (? <> 'ACCEPTED' OR now() <= expires_at)\"\"\", outcome.name(), offerId, outcome.name());
    if (n == 0) return Resolution.alreadyResolved(offers.get(offerId));
    var o = offers.get(offerId);
    if (outcome == ACCEPTED) committer.commitAsync(o); else { supply.releaseReservation(o.driverId(), o.requestId()); loop.nextRound(o.requestId()); }
    return Resolution.applied(o);
}""", cx="O(1).",
    fail=[F("Accept/timeout race", "Conditional update", "One wins", "Deterministic", "Single outcome"), F("Timer lost", "Sweeper finds overdue PENDING", "Delayed re-offer", "Sweeper expiry", "Converges"),
          F("Driver double-taps accept", "Second update 0 rows", "None", "Return existing result", "Idempotent")],
    alts=[["Broadcast to N drivers", "Rejected", "Driver frustration; contention", "Never"], ["Client-side countdown only", "Rejected", "Clock skew; untrusted", "Never"]],
    adrs=[A("DB-arbitrated resolution", "I", "Race between human and timer.", [("In-memory lock", "Rejected: multi-instance"), ("Conditional update", "Chosen")], "Single conditional update.", "Correct under any interleaving.", "DB round trip per response.", "Phase V: same in shard-local store.")],
    qa=[Q("Concurrency", "Why both a unique index (one pending offer per driver) and a Supply reservation?", "Defence in depth with different scopes. The Supply reservation prevents *any* other dispatcher (or batch matcher) from claiming the driver. The unique index protects the offer table's own invariant if a bug skips reservation. In Phase V, when offers and supply live in different stores, the reservation is the one that matters.", "")],
    tests=[T("Concurrency", "Accept at expires_at ± 5 ms, 1,000 runs", "Exactly one outcome each"), T("Failure", "Timer service down", "Sweeper expires within 5 s"), T("Contract", "Accept unknown offer", "404")],
    evo=["I: Job-table timers + conditional updates", "R: RabbitMQ delayed messages", "E: OfferResolved events; workflow timers", "E: In Dispatch service", "R: Shard-local timers (hierarchical timing wheel) + log", "E: Regional"],
    ideas={"now": ["Lease > timeout"], "next": ["Adaptive timeout per driver responsiveness"], "adv": ["Offer stacking for forward dispatch"], "rej": ["Broadcast offers"]})

sub(id="assignment-commit", comp="dispatch", name="Assignment Commit", phase="I", cat="Consistency · Cross-aggregate commit",
    resp="Make an accepted offer real: assign the driver (Supply), create the trip (Trip), mark the request ASSIGNED, so either all happen or the system converges to a consistent state.",
    inp="accepted offer", out="trip created, request ASSIGNED, DriverAssigned event", deps="Supply, Trip, Request", cons="Rider/driver apps (via events), Tracking", own="dispatch_attempts.commit_state",
    problem="Three aggregates must change together. In the monolith that's one transaction, after extraction it's three services.", without="Driver ON_TRIP without a trip, or rider told 'assigned' with no driver.",
    guar=["Driver assignment is the linearization point", "Trip id is deterministic from request id (idempotent create)", "Request ASSIGNED only after trip exists", "Partial commits are completed or reverted within 60 s"], nong=["Atomic visibility across services at every instant (Phase IV+)"],
    usecase="Dispatch worker crashes after Supply.assign. Another worker picks up the attempt in state COMMITTING, re-runs Trip.create (same trip id → no-op if exists) and Request.markAssigned. The rider sees ASSIGNED 2 s later than usual.",
    derive="- Phase I–III: one ACID transaction (same DB).\n- Phase IV+: no 2PC, so order steps so the hardest-to-undo (driver commitment) happens first and later steps are idempotent and retryable forward. That is a forward-recovery saga.\n- Durable attempt state records progress.",
    conc="Attempt row version prevents two workers committing the same attempt (lease on attempt: `UPDATE ... SET owner=?, lease_until=? WHERE request_id=? AND (owner IS NULL OR lease_until<now())`).", consistency="Phase I–III atomic; Phase IV+ eventually consistent within seconds, with a forward-only protocol.",
    idem="Each step idempotent: assign with (req, version), trip create with deterministic id, markAssigned conditional on status.", order="Steps strictly ordered; retries re-run from the first incomplete step.",
    restart="Attempt state COMMITTING + step marker persisted; recovered by lease expiry.", scale="Per-request; no shared hot spots.", arch="Phase I: `@Transactional commit()` updating driver_status, inserting trip, updating request. Phase IV: `AssignmentCommitter` with a persisted step log and an `AssignmentReconciler` that scans for divergence.",
    modules=[["Committer", "Ordered steps"], ["StepLog", "Persisted progress"], ["AttemptLease", "Single active committer"], ["Reconciler", "Detect/repair divergence"]],
    d_arch=("""flowchart LR
  ACC["OfferAccepted"] --> CM["Committer"] --> SL[("attempt step log")]
  CM -->|1 assign| SUP["Supply"]
  CM -->|2 create trip| TRIP["Trip"]
  CM -->|3 mark assigned| REQ["Request"]
  RC["Reconciler"] --> SUP & TRIP & REQ""", "Ordered forward-only steps with a step log and reconciler."),
    d_seq=("""sequenceDiagram
  participant C as Committer
  participant S as Supply
  participant T as Trip
  participant R as Request
  C->>C: step=ASSIGNING
  C->>S: assign(driver, req, v42)
  S-->>C: ON_TRIP
  C->>C: step=CREATING_TRIP
  C->>T: create(trip_id=uuid5(req), ...)
  T-->>C: created (or exists)
  C->>R: markAssigned(req, trip_id)
  C->>C: step=DONE, emit DriverAssigned""", "Phase IV+ commit protocol."),
    d_state=("""stateDiagram-v2
  [*] --> ASSIGNING
  ASSIGNING --> CREATING_TRIP: Supply ok
  ASSIGNING --> ABORTED: LEASE_LOST (→ next round)
  CREATING_TRIP --> MARKING_REQUEST
  MARKING_REQUEST --> DONE
  CREATING_TRIP --> CREATING_TRIP: retry
  MARKING_REQUEST --> MARKING_REQUEST: retry""", "Only the first step may abort. After it, the protocol only moves forward."),
    d_flow=("""flowchart LR
  REQ["request_id"] --> TID["trip_id = UUIDv5(request_id)"] --> TRIP["Trip.create idempotent"]""", "The deterministic id makes trip creation idempotent."),
    d_fail=("""flowchart TB
  X["crash after assign"] --> L["attempt lease expires"] --> W["new worker resumes CREATING_TRIP"]
  T["Trip service down"] --> RT["retry with backoff ≤ 60s"] --> ESC["if still failing: release driver, request back to SEARCHING, alert"]""", "Forward recovery, with an escalation path if forward steps keep failing."),
    sql="""ALTER TABLE dispatch.dispatch_attempts ADD COLUMN commit_step text, ADD COLUMN owner text, ADD COLUMN lease_until timestamptz;
-- Phase I single-transaction version:
-- BEGIN; UPDATE supply.driver_status ...; INSERT INTO trip.trips ...; UPDATE request.ride_requests SET status='ASSIGNED' ...; COMMIT;""",
    data="Step log kept with attempt (1 year).", api="""void commit(Offer accepted)    // idempotent per request
event DriverAssigned{request_id, trip_id, driver_id, vehicle_id, eta_s, at}""",
    mech=[("Linearization point first", "Ordering the step that can conflict (driver claim) first means later steps can't fail for business reasons, only transiently. Transient failures are retried, which gives a saga with no compensations after the pivot."), ("Deterministic ids", "UUIDv5(namespace, request_id) gives every retry the same trip id, so 'create' becomes 'create if absent'."), ("Reconciler", "A periodic scan joins Supply ON_TRIP, trips and requests, and repairs any combination older than 60 s that violates the invariants.")],
    code="""public void commit(Offer o) {
    var a = attempts.lease(o.requestId(), workerId, Duration.ofSeconds(30)).orElseThrow(NotOwner::new);
    if (a.step().before(CREATING_TRIP)) {
        if (supply.assign(o.driverId(), o.requestId(), tripId(o)) == LEASE_LOST) { attempts.abort(a); loop.nextRound(o.requestId()); return; }
        attempts.advance(a, CREATING_TRIP);
    }
    if (a.step().before(MARKING_REQUEST)) { retry.run(() -> trips.createIfAbsent(tripId(o), o)); attempts.advance(a, MARKING_REQUEST); }
    retry.run(() -> requests.markAssigned(o.requestId(), tripId(o)));
    attempts.advance(a, DONE); outbox.add(new DriverAssigned(o.requestId(), tripId(o), o.driverId()));
}""", cx="O(1) + 3 remote calls.",
    fail=[F("Crash between steps", "Lease expiry", "Delay", "Resume", "Converges"), F("Lease lost at assign", "LEASE_LOST", "Offer wasted", "Next round", "Consistent"), F("Trip service prolonged outage", "Retry exhaustion", "Driver stuck ON_TRIP", "Escalation: release driver, request SEARCHING", "Reverted")],
    alts=[["2PC/XA", "Rejected", "Blocking, unsupported across services", "Never"], ["Choreography via events", "Viable", "Harder to see state", "If teams prefer decoupling"], ["Keep assignment in one DB (Supply+Trip+Request co-located)", "Viable at IV", "Simpler", "If service split not needed"]],
    adrs=[A("Forward-recovery saga with pivot first", "IV", "Services split.", [("2PC", "Rejected"), ("Compensating saga", "Complex undo of driver claim"), ("Pivot-first forward saga", "Chosen")], "Ordered steps.", "Few compensations.", "Brief inconsistency windows.", "N/A")],
    qa=[Q("Consistency", "During the window between Supply.assign and Request.markAssigned, what does each party see?", "The driver sees the offer accepted and a 'loading trip' screen until the trip exists (usually < 200 ms). The rider still sees 'searching'. The geo index removes the driver from availability. No one sees contradictory *final* states, and the window is bounded by retries plus the reconciler (60 s worst case).", "")],
    tests=[T("Failure", "Crash injected after each step", "Converges to DONE with one trip"), T("Concurrency", "Two workers same attempt", "Lease prevents double commit"), T("Reconciliation", "Manually create divergence", "Repaired in ≤ 60 s")],
    evo=["I: Single ACID transaction", "U: No change needed", "E: DriverAssigned via outbox", "R: Forward saga across services + reconciler", "E: Shard-local commit when Supply co-located in shard", "E: Regional fencing tokens on assign"],
    ideas={"now": ["Deterministic trip id even in Phase I"], "next": ["Reconciler dashboards"], "adv": ["Co-locate Supply+Dispatch per shard for local transactions"], "rej": ["Mark request assigned first"]})

sub(id="batch-matching", comp="dispatch", name="Batch Matching Optimizer", phase="IV", cat="Algorithm · Optimization",
    resp="In dense zones, collect requests and available drivers over a short window and compute a globally better assignment than greedy one-by-one matching.",
    inp="open requests and candidate drivers in a zone over 1–2 s", out="assignments (request → driver) passed to the offer manager", deps="Candidate generation (ETA matrices), Offer manager", cons="Dispatch loop", own="Batch window state",
    problem="Greedy matching gives the first request the nearest driver even if that driver is the only one near the second request. At density this inflates average pickup times.", without="10–20% longer average pickup ETAs in busy areas.",
    guar=["Each driver assigned to at most one request per batch", "Batch window ≤ 2 s", "Requests unmatched in a batch carry over"], nong=["Global optimality across batches"],
    usecase="Requests R1, R2. Drivers D1 (2 min to R1, 3 min to R2) and D2 (9 min to R1, 10 min to R2). Greedy R1→D1 leaves R2→D2 (10), total 12. Batch gives the same here. With D1 3→R1, 2→R2 and D2 4→R1, 9→R2, greedy R1→D1, R2→D2 totals 12 while batch R1→D2, R2→D1 totals 6.",
    derive="- Minimum-cost bipartite matching on a cost matrix (ETA plus penalties), solved with the Hungarian algorithm (O(n³)) or auction.\n- Window size trades latency for quality.\n- Zones must be small enough for n ≤ ~200.",
    conc="One batch solver per zone (single owner); reservations still go through Supply CAS (drivers can disappear between solve and offer).", consistency="Solve uses a snapshot. Conflicts at reserve time fall back to next best.", idem="Deterministic solve for the same matrix and tie-breaking.", order="Batches are sequential per zone.",
    restart="Window state is ephemeral. On restart, open requests are re-collected from attempts in Searching.", scale="n ≤ 200 per zone keeps solve < 50 ms. Zones are partitioned by H3 res-6/7 with border handling.",
    arch="Per zone, every 1–2 s: gather Searching requests + available candidates (union of their candidate sets) → ETA matrix (many-to-many) → cost matrix with penalties (unassigned cost) → Hungarian → reserve + offer per pair → unmatched requests to next window.",
    modules=[["BatchWindow", "Collect per zone"], ["CostMatrixBuilder", "ETA + penalties + dummy columns"], ["Solver", "Hungarian / auction"], ["Dispatcher", "Reserve and offer per assignment"]],
    d_arch=("""flowchart LR
  ATT["Searching attempts in zone"] --> BW["BatchWindow (1-2s)"]
  BW --> CMB["CostMatrixBuilder"] --> ETA["ETA many-to-many"]
  CMB --> SOL["Hungarian solver"] --> DSP["Reserve + offer"] --> OM["Offer manager"]
  DSP -->|unmatched| BW""", "Windowed optimization feeding the same offer machinery."),
    d_seq=("""sequenceDiagram
  participant W as Window
  participant E as ETA
  participant S as Solver
  participant O as Offers
  W->>W: t=0..2s collect R1..R40, D1..D60
  W->>E: matrix 40×60
  W->>S: solve
  S-->>W: pairs
  W->>O: offer each pair (reserve first)""", "One batch cycle."),
    nostate="A batch is a periodic computation. Requests keep their own attempt state.",
    d_flow=("""flowchart LR
  R["requests"] --> M["cost matrix (ETA s; ∞ if > max)"]
  D["drivers"] --> M
  M --> H["Hungarian"] --> P["pairs"]""", "Cost matrix assembly."),
    d_fail=("""flowchart TB
  SL["solve > 200ms"] --> G["fallback to greedy for this window"]
  RC["reserve conflict"] --> NB["try next best driver for that request"]""", "Fallbacks preserve latency."),
    sql="-- No persistent tables; batch metrics to lake: batches(zone, ts, n_req, n_drv, solve_ms, total_cost, greedy_cost)",
    data="Metrics only.", api="""List<Pair> solve(double[][] cost)  // returns min-cost assignment
config: batch.window_ms (per zone), batch.min_density""",
    mech=[("Hungarian algorithm", "Finds a minimum-cost perfect matching on an n×m cost matrix in O(n³) via row/column reductions and augmenting paths. Rectangular matrices are padded with dummy rows/columns at an 'unassigned' cost."), ("Adaptive window", "Window length scales with density: sparse zones use greedy (window 0), dense zones 2 s, so latency is only paid where efficiency gains exist.")],
    code="""int[] assignment = hungarian.solve(cost);   // assignment[i] = driver index for request i, -1 if unassigned
for (int i = 0; i < requests.size(); i++) if (assignment[i] >= 0 && cost[i][assignment[i]] < UNASSIGNED_COST)
    offers.offerReserved(requests.get(i), drivers.get(assignment[i]));""", cx="O(n³), n ≤ 200 → < 50 ms.",
    fail=[F("Solver slow", "Timer", "Delay", "Greedy fallback", "None"), F("Driver taken between solve and reserve", "CAS fails", "Pair lost", "Next best", "No double assignment")],
    alts=[["Greedy", "Default outside dense zones", "No latency", "Sparse"], ["Auction algorithm", "Viable", "Parallelizable", "Large n"], ["Min-cost flow with future demand", "Advanced", "Considers repositioning", "Phase V+"]],
    adrs=[A("Batch only where density justifies", "IV", "Latency vs efficiency.", [("Batch everywhere", "Hurts sparse zones"), ("Adaptive", "Chosen")], "Adaptive per zone.", "Gains where it matters.", "More config.", "N/A")],
    qa=[Q("Architectural judgment", "How do you prove batch matching is worth 2 s of added latency?", "Shadow mode: run the solver on live data without acting, and compare its total ETA to greedy decisions actually made. If dense zones show ≥ 10% total-ETA reduction, run a switchback experiment (time-sliced zones alternate policies) measuring rider wait including the window, and completed trips.", "A/B by rider is invalid here because riders in the same zone compete for the same drivers. Switchback designs avoid that interference.")],
    tests=[T("Unit", "Known matrices", "Optimal assignment"), T("Simulation", "Dense replay", "≥ 10% total ETA reduction"), T("Load", "200×300 matrix", "< 50 ms")],
    evo=["N: Greedy is sufficient at low density", "N: Still greedy", "N: Still greedy", "I: Batch in dense zones of top cities", "E: Shard-local solvers; demand-aware costs", "U: No change needed: per region"],
    ideas={"now": ["n/a before IV"], "next": ["Repositioning suggestions"], "adv": ["Min-cost flow with forecast demand"], "rej": ["Global city-wide solve every second"]})

# ======================================================================= Cancellation
comp(id="cancellation", domain="dispatch", name="Cancellation & Reassignment", tag="Dispatch · Policy", phase="I", kind="Logical component (inside Request service from Phase IV)",
     biz="Lets riders and drivers cancel fairly, charges fees when someone's time was wasted, and finds a new driver when a driver cancels.",
     eng="Policy-driven state transitions on request/trip with fee computation, payment side-effects and automatic re-dispatch, safe under races with assignment and arrival.",
     deploy="Module (I); within Request service (IV).", data_own="cancellations, cancellation policies.",
     up=["ride-request", "trip", "dispatch", "payments", "driver-supply"], down=["payments", "driver-earnings", "notifications", "risk-fraud"], ext=[],
     interfaces="`POST /v1/ride-requests/{id}/cancel`, `POST /v1/trips/{id}/cancel`; events `RideCancelled`.",
     problem="Cancellations race with assignment and arrival. Fees must be fair and explainable. Driver cancellations must not leave riders stranded.",
     fr=["Rider cancel before/after assignment", "Driver cancel before pickup", "Fee if beyond grace period or driver arrived", "Auto-reassign on driver cancel", "No-show handling"], nfr=["Cancel p95 < 300 ms", "Fee decisions reproducible"],
     workload="≈ 10–20% of requests cancel.", success="Fair fees, quick reassignment.", failure="Fees charged unfairly; riders stranded after driver cancel.",
     derive="Cancel acts on whichever aggregate is current (request if SEARCHING, trip if ASSIGNED+), so route by state with conditional transitions. Fee depends on timestamps (assigned_at, arrived_at), so a pure policy function over trip timeline.",
     owns=["Cancellation records and policies", "Fee decisions", "Reassignment trigger"], not_owns=["Charging (Payments)", "Trip state machine (Trip, via commands)"], sync=["Cancel commands"], **{"async": ["Fee charge", "Reassignment", "Abuse signals"]},
     boundary_why="Policy and fees change often and are city-specific, so they're separated from the trip state machine, which stays stable.",
     hld=("""flowchart LR
  R["Rider/Driver"] --> CP["Cancellation policy engine"]
  CP --> REQ["Request (if SEARCHING)"] & TRIP["Trip (if ASSIGNED/ARRIVED)"]
  CP --> FEE["Fee decision"] --> PAY["Payments: charge fee / void auth"]
  CP --> RA["Reassignment"] --> DSP["Dispatch: new attempt"]""", "Policy decides outcome. Owners apply transitions. Payments and dispatch react."),
     seq=("""sequenceDiagram
  participant D as Driver
  participant C as Cancellation
  participant T as Trip
  participant Dp as Dispatch
  D->>C: cancel trip (before pickup)
  C->>T: cancelByDriver (conditional on ASSIGNED/ARRIVED)
  T-->>C: CANCELLED_BY_DRIVER
  C->>Dp: re-dispatch(request, exclude driver, priority)
  C-->>D: ok (cancellation counted)""", "Driver cancellation with reassignment."),
     subdeps=[("reassignment", "cancellation-policy")],
     flow="The command is routed to the current aggregate and applied conditionally. The policy computes the fee, payments act asynchronously, and driver-initiated cancels trigger reassignment with priority.",
     data="`cancellations(id, request_id, trip_id, by, reason, fee_minor, policy_version, decided_at)`, `cancellation_policies(city, product, grace_s, fee_minor, no_show_wait_s, version)`.",
     rel=[["Races", "Conditional transitions on trip/request state."], ["Idempotency", "Cancel keyed by (aggregate, actor)."]], sec=[["Abuse", "Driver cancel-to-cherry-pick patterns flagged; rider fee farming by collusion flagged."]],
     adrs=[A("Policy as versioned data", "I", "City rules differ.", [("Code", "Rejected"), ("Versioned policy rows", "Chosen")], "Data.", "Ops agility, audit.", "Validation needed.", "N/A")],
     qa=[Q("Concurrency", "The rider cancels at the same instant the driver accepts. Outcome?", "Both operations target conditional transitions. If the cancel commits first (request SEARCHING → CANCELLED), the assignment commit's markAssigned fails, and the committer reverts: it releases the driver in Supply and cancels the trip if created, without fee. If assignment commits first, the cancel applies to the trip (ASSIGNED → CANCELLED_BY_RIDER) within the grace period, so no fee. The rider is charged only per policy timestamps, never because of the race.", "")],
     impl_order=["cancellation-policy", "reassignment"], pkg="""com.atlas.cancellation
├── policy (CancellationPolicy, FeeCalculator)
└── reassign (ReassignmentService)""",
     tests=[T("Concurrency", "Cancel vs accept race ×1,000", "No fee from race; consistent states"), T("Unit", "Cancel 2 min after assignment, grace 2 min", "Boundary handled per policy (≤ grace free)")],
     evo=[("I", "Module", "PG", "Conditional transitions", "Correctness"), ("E", "Same", "Async fee charging", "Retries", "Reliability"), ("E", "Same", "RideCancelled events", "Idempotent consumers", "Events"),
          ("E", "In Request service", "—", "—", "Services"), ("E", "ML abuse detection", "—", "—", "Scale"), ("E", "Regional policies", "—", "—", "Global")],
     ideas={"now": ["Grace period"], "next": ["Fee waivers by risk/tenure"], "adv": ["Dynamic fees by demand"], "rej": ["Fees without timeline evidence"]})

sub(id="cancellation-policy", comp="cancellation", name="Cancellation Policy & Fees", phase="I", cat="Business rules · Money",
    resp="Decide whether a cancellation incurs a fee, and how much, from the trip timeline, actor and city policy.",
    inp="actor, reason, timeline (requested, assigned, arrived), policy version", out="decision {fee, beneficiary, reason_code}", deps="Trip timeline, Policy store", cons="Payments, Earnings (driver compensation), Support", own="cancellation_policies, cancellations",
    problem="Compensate drivers for wasted time without punishing riders unfairly. The decision must be explainable.", without="Disputes, unfair fees.",
    guar=["Deterministic given timeline and policy version", "No fee within grace period", "No fee if driver ETA increased significantly after assignment"], nong=["Collection success (Payments)"],
    usecase="Rider cancels 4 min after assignment while the driver is 1 min away: fee ₹40, paid to driver as compensation.",
    derive="- Inputs are timestamps and ETAs, so the fee is a pure function.\n- Fairness exceptions (driver going wrong way) need the ETA at assignment vs ETA at cancel.",
    conc="Decision stored once per cancellation (unique on trip/request).", consistency="Strong: the decision is stored in the same transaction as the cancellation record and never recomputed.", idem="Re-evaluation returns the stored decision.", order="Uses timeline as recorded by Trip; late timeline events (arrival) are authoritative by event time.",
    restart="Stateless compute; decisions persisted.", scale="One decision per cancellation (≈ 20% of requests). Pure CPU work with no hot rows.", arch="Pure `FeeCalculator.decide(timeline, policy)` plus persistence.",
    modules=[["PolicyStore", "Versioned"], ["FeeCalculator", "Pure"], ["DecisionStore", "Persist + explain"]],
    d_arch=("""flowchart LR
  CMD["cancel"] --> FC["FeeCalculator"] --> PS["PolicyStore"]
  FC --> TL["Trip timeline"]
  FC --> DS[("cancellations")]""", "Pure calculation over inputs."),
    d_seq=("""sequenceDiagram
  participant C as Cancel
  participant F as FeeCalc
  C->>F: decide(rider, assigned 4m ago, driver eta 1m, policy v3)
  F-->>C: fee 40 (beyond grace 2m)""", "Decision."),
    nostate="A decision is a single immutable record.",
    d_flow=("""flowchart LR
  T["timeline"] --> G{"> grace?"} -->|no| Z["fee 0"]
  G -->|yes| E{"driver eta worsened > 5m?"} -->|yes| Z
  E -->|no| FEE["fee per policy"]""", "Decision tree."),
    d_fail=("""flowchart TB
  P["policy missing for city"] --> D["default 0 fee + alert"]""", "Fail toward no fee."),
    sql="""CREATE TABLE cancellation.cancellations (id uuid PRIMARY KEY, request_id uuid NOT NULL, trip_id uuid, by text NOT NULL, reason text,
  fee_minor bigint NOT NULL DEFAULT 0, policy_version int NOT NULL, inputs jsonb NOT NULL, decided_at timestamptz NOT NULL, UNIQUE(request_id));""",
    data="Retained 7 years (financial).", api="""FeeDecision decide(Timeline t, Actor a, Policy p)""",
    mech=[("Pure decision function", "No I/O inside makes it unit-testable across every timeline edge case and reproducible in disputes.")],
    code="""FeeDecision decide(Timeline t, Actor a, Policy p) {
    if (a == DRIVER) return FeeDecision.none("DRIVER_CANCEL");
    if (t.assignedAt() == null || Duration.between(t.assignedAt(), t.cancelledAt()).compareTo(p.grace()) <= 0) return FeeDecision.none("WITHIN_GRACE");
    if (t.etaAtCancel() - t.etaAtAssign() > p.etaWorsenedThresholdS()) return FeeDecision.none("DRIVER_DELAYED");
    return FeeDecision.fee(t.arrivedAt() != null ? p.arrivedFee() : p.lateCancelFee(), "LATE_CANCEL");
}""", cx="O(1).",
    fail=[F("Timeline incomplete", "Null fields", "Possible wrong fee", "Default no fee", "Conservative")],
    alts=[["Flat fee", "Rejected", "Unfair", "Never"]],
    adrs=[A("ETA-worsened exemption", "II", "Fairness to riders.", [("No exemption", "Unfair"), ("Exemption", "Chosen")], "Exempt when driver delays.", "Fairer.", "Needs ETA timeline.", "N/A")],
    qa=[Q("Product", "Who receives the cancellation fee?", "Mostly the driver (compensation for time and distance), with an optional platform share per city. The ledger records rider receivable → driver payable and platform revenue accordingly.", "")],
    tests=[T("Unit", "All timeline permutations", "Matches policy table"), T("Property", "Fee never > policy max", "Holds")],
    evo=["I: Pure calculator + table", "E: ETA-worsened exemption", "E: Events to earnings/ledger", "U: No change needed", "E: Abuse-aware waivers", "E: Regional"],
    ideas={"now": ["Explain fee in receipt"], "next": ["Waivers for loyal riders"], "adv": ["Personalized grace"], "rej": ["Fees without explanation"]})

sub(id="reassignment", comp="cancellation", name="Reassignment After Driver Cancel / No-Show", phase="I", cat="Workflow · Recovery",
    resp="When a driver cancels or never moves toward pickup, return the request to dispatch with priority and exclusions, preserving the rider's quote.",
    inp="driver cancel, stuck-driver detection", out="new dispatch attempt (priority), rider notification", deps="Dispatch, Trip, Request", cons="Rider", own="reassignment records",
    problem="A driver cancel must not leave the rider to start over (new quote, new wait).", without="Riders stranded; abandoned rides.",
    guar=["Original quote honoured", "Cancelling driver excluded", "Reassigned requests ranked with priority"], nong=["Same ETA as original"],
    usecase="Driver cancels 3 min into pickup. Request returns to SEARCHING with priority, the original driver is excluded, the new driver is found in 20 s, and the rider sees 'We found you a new driver'.",
    derive="- Reuse the same request (state back to SEARCHING) and trip cancelled with reason.\n- Exclusion list carried in the attempt.\n- Detection of stuck drivers (not moving toward pickup for 3 min) triggers the same flow.",
    conc="Request transition ASSIGNED→SEARCHING conditional on the trip being CANCELLED_BY_DRIVER.", consistency="Strong within request.", idem="Keyed by cancelled trip id.", order="Follows trip cancellation event.",
    restart="Triggered by event; durable.", scale="Proportional to driver cancellations (a few percent of trips). Each one is a single-row insert plus one dispatch attempt.", arch="Event handler on TripCancelledByDriver: request → SEARCHING (priority flag, exclusions), new dispatch attempt round 1 with boosted radius.",
    modules=[["ReassignHandler", "Event → new attempt"], ["StuckDriverDetector", "No progress toward pickup"], ["PriorityPolicy", "Ranking boost"]],
    d_arch=("""flowchart LR
  TC["TripCancelledByDriver"] --> RH["ReassignHandler"] --> REQ["Request → SEARCHING"]
  RH --> DSP["Dispatch attempt (priority, exclusions)"]
  SD["StuckDriverDetector"] --> RH""", "One handler for cancel and stuck detection."),
    d_seq=("""sequenceDiagram
  participant T as Trip
  participant H as Reassign
  participant R as Request
  participant D as Dispatch
  T->>H: TripCancelledByDriver(trip, driver)
  H->>R: reopen(request, exclude driver)
  H->>D: attempt(priority=true)
  D-->>H: searching""", "Reassignment flow."),
    nostate="Reuses the request and dispatch attempt state machines.",
    d_flow=("""flowchart LR
  EX["excluded {driver}"] --> ATT["attempt"] --> CG["candidate gen"]""", "Exclusions flow into candidate generation."),
    d_fail=("""flowchart TB
  N["no driver found in 3 min"] --> U["UNFULFILLED, void auth, apology credit"]""", "Ends with compensation."),
    sql="CREATE TABLE cancellation.reassignments (cancelled_trip_id uuid PRIMARY KEY, request_id uuid NOT NULL, reason text, created_at timestamptz NOT NULL DEFAULT now());",
    data="Retained for driver quality metrics.", api="""event RequestReopened{request_id, excluded_driver_ids[], priority:true}""",
    mech=[("Idempotent reopen", "Primary key on cancelled_trip_id makes duplicate events no-ops.")],
    code="""@Transactional
public void on(TripCancelledByDriver e) {
    if (!reassignments.insertIfNew(e.tripId(), e.requestId())) return;
    requests.reopen(e.requestId(), e.driverId());
    outbox.add(new RequestReopened(e.requestId(), Set.of(e.driverId()), true));
}""", cx="O(1).",
    fail=[F("Duplicate event", "PK", "None", "Ignored", "Single reassignment")],
    alts=[["New request for rider", "Rejected", "Loses quote, bad UX", "Never"]],
    adrs=[A("Reopen same request", "I", "UX + quote.", [("New request", "Rejected"), ("Reopen", "Chosen")], "Reopen.", "Continuity.", "Request state machine allows ASSIGNED→SEARCHING.", "N/A")],
    qa=[Q("Product", "How do you detect a driver who accepted but isn't coming?", "Compare the driver's progress toward the pickup: if ETA hasn't decreased in 3 minutes, or distance increased by > 1 km, prompt the driver, and without a response after 60 s, auto-cancel with reason DRIVER_NOT_PROGRESSING and reassign. Not counted against the rider.", "")],
    tests=[T("Integration", "Driver cancel", "New driver offered; original excluded"), T("Unit", "Duplicate cancel event", "One reopen")],
    evo=["I: Synchronous reopen", "E: Stuck-driver detection", "E: Event-driven", "U: No change needed", "E: ML no-show prediction", "U: No change needed"],
    ideas={"now": ["Priority flag"], "next": ["Stuck detection"], "adv": ["Proactive reassignment before cancel"], "rej": ["Making rider re-request"]})
