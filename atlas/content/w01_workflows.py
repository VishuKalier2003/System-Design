from model import W, F


def wf(n, title, summary, actors, comps, owners, seq, expl, states, db, events, sync, async_, consistency, msg, fails):
    W(n=n, title=title, summary=summary, actors=actors, comps=comps, owners=owners, seq=(seq, expl), states=states, db=db, events=events,
      sync=sync, **{"async": async_}, consistency=consistency, msg=msg, fail=fails)


wf(1, "Rider registration", "A new rider verifies a phone number and gets an account, session and profile.", "Rider, SMS provider",
   ["identity", "rider-profile", "notifications", "risk-fraud"], "Identity owns user + session; Rider Profile owns the profile; Notifications owns delivery.",
   """sequenceDiagram
  participant A as App
  participant I as Identity
  participant K as Risk
  participant N as Notifications
  participant P as RiderProfile
  A->>I: POST /auth/otp {phone}
  I->>K: score(SIGNUP, device, prefix)
  I->>N: send OTP (critical)
  A->>I: verify(code)
  I->>I: create user + session (tx)
  I-->>A: tokens, is_new_user=true
  I->>P: UserRegistered (outbox)
  P->>P: create profile (idempotent)""", "Identity and profile creation are decoupled by an event. In Phase I it's in-process, from Phase III an outbox to Kafka.",
   "otp_challenge PENDING→CONSUMED; user Unverified→Active; profile created ACTIVE.", "identity.users, contact_points, sessions, refresh_tokens; rider.rider_profiles.", "UserRegistered{user_id, role, registered_at}",
   "OTP send/verify; token issue.", "Profile creation; welcome message.", "User+session atomic. Profile eventually consistent (seconds). The app tolerates a missing profile by retrying GET /riders/me.",
   '{"event_id":"…","type":"UserRegistered","data":{"user_id":"…","role":"RIDER","phone_country":"IN"}}',
   [F("SMS provider down", "Breaker", "Can't sign up", "Secondary provider / voice", "None"), F("UserRegistered consumed twice", "Inbox/ON CONFLICT", "None", "Idempotent create", "One profile")])

wf(2, "Contact verification (email/phone change)", "A signed-in user adds or changes a contact point and proves control of it.", "User",
   ["identity", "notifications", "risk-fraud"], "Identity owns contact points.",
   """sequenceDiagram
  participant A as App
  participant I as Identity
  participant N as Notifications
  A->>I: POST /me/contact {email} (step-up auth)
  I->>N: send code to new email
  A->>I: verify(code)
  I->>I: mark verified; old contact retained 30 days for recovery
  I->>N: notify old channel of change""", "Step-up plus notification on the old channel defend against takeover.",
   "contact_point Unverified→Verified; old contact Superseded.", "identity.contact_points.", "ContactChanged{user_id, type}", "Verify flow.", "Notifications to old channel.",
   "Uniqueness of verified contact enforced by a unique index (global directory in Phase VI).", '{"type":"ContactChanged","data":{"user_id":"…","contact_type":"EMAIL"}}',
   [F("Email already used by other account", "Unique violation", "Rejected", "Recovery path", "None")])

wf(3, "Driver onboarding", "An applicant submits documents and consents, and passes checks to become eligible.", "Driver applicant, reviewers, vendors",
   ["driver-onboarding", "identity", "fleet-vehicle", "notifications", "workflow"], "Onboarding owns application and eligibility; Fleet owns vehicle.",
   """sequenceDiagram
  participant D as Applicant
  participant O as Onboarding WF
  participant V as DocVerify
  participant B as BGCheck
  participant F as Fleet
  D->>O: submit application (city PUN)
  O->>V: verify licence, insurance
  O->>F: register vehicle
  O->>B: start check (consent)
  B-->>O: CLEAR (days later)
  O->>O: eligibility snapshot eligible
  O-->>D: approved""", "A durable workflow (Phase III) waits days for vendors.",
   "Application Draft→Submitted→DocumentsInReview→BackgroundCheck→Approved.", "onboarding.driver_applications, driver_documents, background_checks, driver_eligibility; fleet.vehicles.", "DriverApproved, DriverEligibilityChanged",
   "Step saves.", "Verification, checks, notifications.", "Eligibility snapshot is the single truth. Supply copies it via events with versioning.", '{"type":"DriverEligibilityChanged","data":{"driver_id":"…","eligible":true,"valid_until":"2027-03-01","version":3}}',
   [F("Vendor webhook lost", "Poller", "Delay", "Poll fetches", "Converges")])

wf(4, "Driver document verification", "Uploaded documents are extracted, verified and approved or reviewed.", "Driver, reviewers",
   ["driver-onboarding"], "Document verification subcomponent owns document state.",
   """sequenceDiagram
  participant D as Driver
  participant U as UploadBroker
  participant O as ObjectStore
  participant X as OCR
  participant R as Review
  D->>U: request URL
  D->>O: PUT file
  D->>U: complete
  U->>X: extract
  X-->>U: confidence 0.71
  U->>R: review task
  R-->>U: approved (expiry 2027-02)""", "Uncertain documents go to humans.",
   "Document Uploaded→Extracting→InReview→Approved.", "driver_documents (versioned), review_tasks.", "DocumentVerified", "Upload URL issue.", "OCR, review, outcome.",
   "Outcome applies only to the current document version.", '{"type":"DocumentVerified","data":{"driver_id":"…","doc_type":"INSURANCE","version":2,"status":"APPROVED","expires_at":"2027-02-01"}}',
   [F("Stale outcome for replaced document", "Version check", "Ignored", "—", "Latest wins")])

wf(5, "Driver going online", "An eligible driver goes online and becomes dispatchable.", "Driver",
   ["driver-supply", "driver-onboarding", "fleet-vehicle", "geo-index"], "Supply owns state; the gate uses copies of onboarding and vehicle state.",
   """sequenceDiagram
  participant D as Driver
  participant S as Supply
  participant G as Gate
  participant X as GeoIndex
  D->>S: POST /drivers/me/online
  S->>G: canGoOnline
  G-->>S: ok
  S->>S: OFFLINE→AVAILABLE (CAS)
  S->>X: DriverStatusChanged(available)
  S-->>D: online""", "The gate checks local copies plus valid_until.",
   "Driver OFFLINE→AVAILABLE.", "supply.driver_status, shift_sessions.", "DriverStatusChanged", "Online command.", "Geo index update.",
   "Geo index eventually consistent (seconds); reservation CAS is the real check.", '{"type":"DriverStatusChanged","data":{"driver_id":"…","state":"AVAILABLE","state_version":88,"city":"PUN"}}',
   [F("Insurance expired yesterday, event lagging", "valid_until guard", "Denied", "Upload prompt", "Correct")])

wf(6, "Driver location updates", "Driver apps stream positions that feed index, tracking and history.", "Driver app",
   ["location-ingest", "geo-index", "trip-tracking", "location-history", "driver-supply"], "Ingest owns intake; Geo owns index; History owns breadcrumbs.",
   """sequenceDiagram
  participant D as Driver app
  participant G as Gateway
  participant K as Kafka
  participant F as Filter
  participant X as GeoIndex
  participant H as History
  D->>G: batch seq 300-305
  G->>K: produce (acks=all)
  G-->>D: ack 305
  K->>F: points
  F->>X: latest
  F->>H: on-trip points""", "Ack after durable hand-off. Fan-out is async.",
   "No business state transitions; liveness heartbeat refreshed.", "Kafka topic; Redis/in-memory index; breadcrumbs.", "driver-locations stream", "Batch ack.", "All processing.",
   "Per-driver ordering by seq. Index eventually consistent.", '{"driver_id":"…","seq":305,"lat":18.52,"lng":73.85,"acc":7.5,"ts":1730540000123}',
   [F("Kafka outage", "Produce errors", "No acks", "Client buffers/resends", "No loss ≤ 10 min")])

wf(7, "Rider requests a fare estimate", "The rider enters a destination and gets per-product upfront quotes.", "Rider",
   ["pricing", "routing-eta", "product-catalog", "promotions"], "Pricing owns quotes.",
   """sequenceDiagram
  participant A as App
  participant P as Pricing
  participant R as Routing
  participant S as Surge
  participant M as Promotions
  A->>P: POST /quotes (3 products)
  P->>R: route
  P->>S: multiplier(cell)
  P->>M: applicable promos
  P->>P: compute, persist, sign
  P-->>A: quotes (expire 5 min)""", "Signed, stored quotes with audit.",
   "Quote Issued.", "pricing.quotes, pricing_audit.", "QuoteIssued", "Quote API.", "Analytics.", "Quote immutable. Surge value captured in quote.",
   '{"quote_id":"…","price":{"amount_minor":26700,"currency":"INR"},"expires_at":"…","signature":"…"}',
   [F("Routing down", "Timeout", "No upfront price", "Metered estimate range", "Flagged quote")])

wf(8, "Ride request creation", "The rider confirms. An idempotent request is created with a locked quote and payment hold.", "Rider",
   ["ride-request", "pricing", "payments", "risk-fraud"], "Request owns the request; Pricing owns quote use; Payments owns the hold.",
   """sequenceDiagram
  participant A as App
  participant I as Intake
  participant P as Pricing
  participant Pay as Payments
  A->>I: POST /ride-requests (Idempotency-Key)
  I->>I: reserve key
  I->>P: use(quote)
  I->>Pay: authorize hold (key req:K)
  I->>I: insert SEARCHING + outbox RideRequested
  I-->>A: 201""", "Local saga with compensations.",
   "Request SEARCHING; quote Used; intent AUTHORIZED.", "request.ride_requests, idempotency_keys; pricing.quotes; payments.payment_intents/attempts.", "RideRequested",
   "Create through authorize.", "Dispatch trigger.", "One active request per rider (unique index). Compensations on failure.", '{"type":"RideRequested","data":{"request_id":"…","pickup":{…},"product":"UberX","city":"PUN"}}',
   [F("Crash after auth", "Abandoned key", "Hold", "Recovery void/complete", "Converges")])

wf(9, "Driver candidate discovery", "Dispatch finds nearby fresh available drivers with ETAs.", "System",
   ["dispatch", "geo-index", "routing-eta"], "Dispatch owns the attempt; Geo answers queries.",
   """sequenceDiagram
  participant D as Dispatch
  participant G as Geo
  participant E as ETA
  D->>G: nearby(pickup, 3 km, UberX)
  G-->>D: 37 → 20 after filters
  D->>E: etaMatrix(20)
  E-->>D: ETAs""", "Funnel from geometry to road ETA.",
   "Attempt Searching (round 1).", "dispatch.dispatch_attempts.", "None (internal).", "Geo and ETA calls.", "—", "Index may be seconds stale; reservation validates.", "candidates: [{driver_id, eta_s:240}, …]",
   [F("ETA timeout", "Deadline", "Approximate ranking", "Straight-line fallback", "None")])

wf(10, "Driver matching and ranking", "Candidates are ranked by expected wait and fairness, or batch-matched in dense zones.", "System",
   ["dispatch", "applied-models", "feature-store"], "Dispatch owns ranking policy.",
   """sequenceDiagram
  participant D as Dispatch
  participant F as Features
  participant M as Acceptance model
  D->>F: driver features
  D->>M: p_accept[20]
  D->>D: score = eta + (1-p)·cost − fairness
  D->>D: pick best (or batch solve)""", "Expected-wait ranking.",
   "Attempt Searching→Offering.", "Score logs to lake.", "None.", "Model calls (deadline).", "Logging.", "Deterministic per config version.", "ranked: [{driver_id, score}]",
   [F("Model timeout", "Deadline", "ETA-only ranking", "Fallback", "None")])

wf(11, "Dispatch and driver acceptance", "An exclusive offer is sent, and the driver accepts within 15 s.", "Driver",
   ["dispatch", "driver-supply", "notifications"], "Offer manager owns offers; Supply owns reservation.",
   """sequenceDiagram
  participant D as Dispatch
  participant S as Supply
  participant Dr as Driver
  D->>S: tryReserve(K, 17s)
  D->>Dr: offer (15s)
  Dr->>D: accept
  D->>D: resolve offer ACCEPTED (conditional)""", "Accept vs timeout race resolved by one conditional update.",
   "Driver AVAILABLE→RESERVED; offer PENDING→ACCEPTED.", "dispatch.offers; supply.driver_status.", "OfferResolved", "Accept API.", "Timeout timers.", "Exactly one outcome per offer.", '{"offer_id":"…","request_id":"…","pickup_area":"FC Road","est_fare":26700,"expires_in_s":15}',
   [F("Accept after expiry", "State check", "409", "Next round already running", "None")])

wf(12, "Driver assignment", "The accepted offer commits: driver ON_TRIP, trip created, request ASSIGNED.", "System",
   ["dispatch", "driver-supply", "trip", "ride-request", "notifications"], "Supply owns driver claim; Trip owns trip; Request owns request.",
   """sequenceDiagram
  participant C as Committer
  participant S as Supply
  participant T as Trip
  participant R as Request
  C->>S: assign (pivot)
  C->>T: createIfAbsent(uuid5(req))
  C->>R: markAssigned
  C->>C: DriverAssigned event""", "Forward-recovery saga (Phase IV) or one transaction (Phase I–III).",
   "Driver RESERVED→ON_TRIP; trip ASSIGNED; request ASSIGNED.", "supply.driver_status; trip.trips; request.ride_requests; dispatch_attempts.commit_step.", "DriverAssigned, TripCreated", "Commit steps.", "Rider/driver notifications.",
   "Brief windows (≤ seconds) between steps; reconciler closes gaps.", '{"type":"DriverAssigned","data":{"request_id":"…","trip_id":"…","driver_id":"…","vehicle":{"plate":"MH12…"},"eta_s":240}}',
   [F("Crash mid-commit", "Lease expiry", "Delay", "Resume", "One trip")])

wf(13, "Pickup and arrival", "The driver arrives, the rider is notified, and the wait timer runs.", "Driver, Rider",
   ["trip", "notifications", "location-ingest"], "Trip owns state.",
   """sequenceDiagram
  participant Dr as Driver
  participant T as Trip
  participant N as Notifications
  Dr->>T: arrive (lat,lng)
  T->>T: guard ≤150 m; ASSIGNED→ARRIVED
  T->>N: "Driver arrived"
  T->>T: schedule no-show timer""", "Guarded arrival.",
   "Trip ASSIGNED→ARRIVED.", "trip.trips.arrived_at, trip_events; timers.", "DriverArrived", "Arrive.", "Notify, timers.", "Trip row linearizable.", '{"type":"DriverArrived","data":{"trip_id":"…","at":"…"}}',
   [F("GPS far", "Guard", "Rejected/override", "Override with reason", "Audited")])

wf(14, "Trip execution", "The rider boards, the trip starts and progresses to dropoff.", "Driver, Rider",
   ["trip", "trip-tracking", "location-ingest", "safety"], "Trip owns state; Tracking owns fan-out; Safety monitors.",
   """sequenceDiagram
  participant Dr as Driver
  participant T as Trip
  participant K as Tracking
  participant S as Safety
  Dr->>T: start (PIN)
  T->>T: ARRIVED→STARTED
  loop every 2s
    Dr->>K: positions (via ingest)
    K->>K: fan-out to rider
    K->>S: anomaly checks
  end""", "Execution with monitoring.",
   "Trip ARRIVED→STARTED.", "trips.started_at; breadcrumbs.", "TripStarted", "Start.", "Tracking, safety.", "Positions eventually consistent.", '{"type":"TripStarted","data":{"trip_id":"…","at":"…"}}',
   [F("Long unexpected stop", "Anomaly detector", "Possible safety issue", "Check-in, escalation", "Incident")])

wf(15, "Real-time location updates to the rider", "The rider sees the car move and ETA update live.", "Rider",
   ["trip-tracking", "location-ingest"], "Tracking owns delivery.",
   """sequenceDiagram
  participant P as Positions
  participant R as Router
  participant G as WS gateway
  participant A as Rider app
  P->>R: pos(trip 77, v19)
  R->>G: route via registry
  G->>A: update (throttled, latest wins)""", "Registry-routed fan-out.",
   "None.", "Registry (ephemeral).", "None (stream).", "WebSocket.", "Routing.", "Latest-wins; versions drop stale.", '{"op":"update","v":19,"pos":{"lat":…,"lng":…},"eta_s":180}',
   [F("Gateway crash", "Disconnect", "Gap", "Reconnect + snapshot", "None")])

wf(16, "ETA recalculation", "ETAs refresh every 30 s and on route deviation.", "System",
   ["trip-tracking", "routing-eta"], "ETA refresh subcomponent owns refresh; Routing computes.",
   """sequenceDiagram
  participant D as Detector
  participant R as Route engine
  participant E as ETA
  D->>D: off-route 2× → deviation
  D->>R: reroute(current, dest)
  D->>E: eta(remaining)
  E-->>D: +3 min""", "Event-driven plus periodic refresh.",
   "None.", "route_plans.", "RouteDeviated", "Route/ETA calls.", "Push to tracking.", "Eventual.", '{"type":"RouteDeviated","data":{"trip_id":"…","distance_m":820}}',
   [F("ETA down", "Timeout", "Stale ETA", "Extrapolate", "None")])

wf(17, "Trip completion", "The driver completes the trip at dropoff.", "Driver",
   ["trip", "driver-supply", "fare-finalization"], "Trip owns completion; Supply releases driver.",
   """sequenceDiagram
  participant Dr as Driver
  participant T as Trip
  participant S as Supply
  Dr->>T: complete
  T->>T: STARTED→COMPLETED + outbox TripCompleted
  T->>S: release(driver)
  S->>S: ON_TRIP→AVAILABLE""", "One transition, one event.",
   "Trip STARTED→COMPLETED; driver ON_TRIP→AVAILABLE.", "trips; driver_status.", "TripCompleted", "Complete.", "Fare, payments, earnings, receipts consumers.", "Exactly one TripCompleted (conditional transition); consumers dedupe.",
   '{"type":"TripCompleted","data":{"trip_id":"…","rider_id":"…","driver_id":"…","started_at":"…","ended_at":"…","quote_id":"…"}}',
   [F("Double tap", "Conditional update", "None", "Idempotent", "One event")])

wf(18, "Fare finalization", "The final fare is computed once from the quote and the trip facts.", "System",
   ["fare-finalization", "pricing", "location-history"], "Fare finalization owns the fare.",
   """sequenceDiagram
  participant K as Kafka
  participant F as FareCalc
  K->>F: TripCompleted
  F->>F: material change? no → quote basis
  F->>F: + wait fee, tolls
  F->>F: insert fare (unique) + FareFinalized""", "Unique fare per trip.",
   "Fare created.", "fare.fares.", "FareFinalized", "—", "All.", "Exactly one fare; adjustments separate.", '{"type":"FareFinalized","data":{"trip_id":"…","amount_minor":26700,"basis":"QUOTE"}}',
   [F("Duplicate event", "Unique", "None", "Skip", "One fare")])

wf(19, "Payment authorization and capture", "Hold at request, capture after fare finalization.", "System, PSP",
   ["payments", "ledger"], "Payments owns intents; Ledger records.",
   """sequenceDiagram
  participant F as FareFinalized
  participant P as Payments
  participant S as PSP
  participant L as Ledger
  F->>P: capture(267)
  P->>P: attempt PENDING (WAL)
  P->>S: capture (idem key)
  S-->>P: captured
  P->>L: PaymentCaptured → entries""", "Attempt log plus idempotency.",
   "Intent AUTHORIZED→CAPTURED.", "payment_intents, payment_attempts; ledger entries.", "PaymentCaptured", "PSP call.", "Ledger posting, receipt.", "At most one capture; ledger balanced.",
   '{"type":"PaymentCaptured","data":{"trip_id":"…","amount_minor":26700,"psp_ref":"ch_…"}}',
   [F("PSP timeout", "PENDING attempt", "Unknown", "Status by key / webhook", "PSP truth")])

wf(20, "Receipt generation", "A numbered receipt is issued and emailed after capture.", "Rider",
   ["receipts", "notifications"], "Receipts owns documents.",
   """sequenceDiagram
  participant P as PaymentCaptured
  participant R as Receipts
  participant N as Notifications
  P->>R: event
  R->>R: allocate number + insert (tx)
  R->>R: render, store
  R->>N: email (dedupe receipt:trip)""", "Gap-free numbering.",
   "Receipt Issued.", "receipts, number_sequences.", "ReceiptIssued", "—", "All.", "Receipt amount = captured.", '{"type":"ReceiptIssued","data":{"trip_id":"…","number":"INV-PUN-2026-000123"}}',
   [F("Render failure", "Error", "No PDF", "Retry render", "Number kept")])

wf(21, "Driver earnings calculation", "Per-trip earnings lines are computed and credited.", "Driver",
   ["driver-earnings", "ledger"], "Earnings owns lines; Ledger records balances.",
   """sequenceDiagram
  participant F as FareFinalized
  participant E as Earnings
  participant L as Ledger
  F->>E: fare 267
  E->>E: fee 25% → 200.25 line
  E->>L: Cr driver_payable 200.25""", "Lines and postings.",
   "Earnings line created.", "earnings_lines; ledger.", "EarningsCredited", "—", "All.", "Lines = ledger credits.", '{"type":"EarningsCredited","data":{"driver_id":"…","trip_id":"…","amount_minor":20025}}',
   [F("Duplicate", "Unique ref", "None", "Skip", "Exact")])

wf(22, "Driver payout", "Weekly or instant payout of available balance.", "Driver, bank",
   ["driver-earnings", "ledger", "risk-fraud"], "Payout processing owns payouts.",
   """sequenceDiagram
  participant B as Batcher
  participant L as Ledger
  participant P as Provider
  B->>L: debit driver_payable (ref payout:d:W44)
  B->>P: transfer (same key)
  P-->>B: paid (webhook)""", "Debit before send.",
   "Payout CREATED→SUBMITTED→PAID.", "payouts; ledger.", "PayoutPaid", "Instant request.", "Batch, webhooks.", "Never pay more than balance; exactly once.", '{"type":"PayoutPaid","data":{"payout_id":"…","amount_minor":184200}}',
   [F("Bank reject", "Webhook", "Unpaid", "Reverse debit; notify", "Balanced")])

wf(23, "Trip cancellation", "The rider or driver cancels, a fee may apply, and the hold is voided or charged.", "Rider/Driver",
   ["cancellation", "trip", "ride-request", "payments", "driver-supply"], "Cancellation owns decision; Trip/Request own transitions.",
   """sequenceDiagram
  participant R as Rider
  participant C as Cancellation
  participant T as Trip
  participant P as Payments
  R->>C: cancel
  C->>T: ASSIGNED→CANCELLED (conditional)
  C->>C: fee decision (4 min > grace) = ₹40
  C->>P: capture fee / void rest""", "Policy-based fee.",
   "Trip→CANCELLED; driver released.", "cancellations; trips; intents.", "RideCancelled", "Cancel.", "Fee charge, release, earnings comp.", "Race with accept resolved by conditional transitions.", '{"type":"RideCancelled","data":{"trip_id":"…","by":"RIDER","fee_minor":4000}}',
   [F("Cancel vs accept race", "Conditional updates", "One wins", "Revert other", "No race fee")])

wf(24, "Refund", "An agent or policy refunds part of a fare.", "Agent, Rider",
   ["wallet", "payments", "ledger", "support"], "Refunds subcomponent owns refunds.",
   """sequenceDiagram
  participant A as Agent
  participant R as Refunds
  participant P as PSP
  participant L as Ledger
  A->>R: refund 60 (id r1)
  R->>R: reserve ≤ captured
  R->>P: refund (key r1)
  P-->>R: succeeded
  R->>L: reversal entries""", "Reserve-then-execute.",
   "Refund Requested→Pending→Succeeded.", "refunds; intents.amount_refunded; ledger.", "RefundIssued", "Request.", "PSP, ledger, notification.", "Σ refunds ≤ captured.", '{"type":"RefundIssued","data":{"refund_id":"r1","amount_minor":6000,"destination":"CARD"}}',
   [F("Parallel refunds", "CHECK", "Second rejected", "Show refundable", "No over-refund")])

wf(25, "Safety incident (SOS)", "The rider triggers SOS. Emergency services and agents respond.", "Rider, Safety agent, Emergency services",
   ["safety", "trip-tracking", "location-history"], "Safety owns SOS and incident.",
   """sequenceDiagram
  participant A as App
  participant S as SOS
  participant E as Emergency API
  participant G as Agent
  A->>S: SOS (cached context)
  par
    S->>E: location + vehicle
    S->>G: page
  end
  S->>S: legal hold on evidence""", "Isolated path.",
   "SOS Triggered→Acknowledged→Resolved; incident Open.", "emergency_events; incidents; evidence holds.", "EmergencyTriggered", "SOS.", "Alerts, holds.", "Persist before ack.", '{"client_sos_id":"…","trip_id":"…","lat":…,"lng":…}',
   [F("Main stack down", "—", "None", "Isolated service", "None")])

wf(26, "Fraud detection", "A card-add checkpoint blocks a card-velocity attack.", "Fraudster, Risk analysts",
   ["risk-fraud", "payments", "identity"], "Risk decides; Payments enforces.",
   """sequenceDiagram
  participant A as App
  participant P as Vault
  participant K as Risk
  A->>P: add card
  P->>K: score(CARD_ADD)
  K-->>P: BLOCK [CARD_VELOCITY]
  P-->>A: 403""", "Checkpoint decision.",
   "None for the card (not added).", "risk_decisions.", "RiskDecisionMade", "Score.", "Signals, labels.", "Decision logged.", '{"checkpoint":"CARD_ADD","decision":"BLOCK","reasons":["CARD_VELOCITY"]}',
   [F("Risk down", "Timeout", "Unknown", "Checkpoint policy (fail closed for cards)", "None")])

wf(27, "Customer support dispute", "A rider disputes a fare. An evidence-based decision is applied.", "Rider, Agent",
   ["support", "fare-finalization", "pricing", "location-history", "wallet"], "Support owns dispute; Fare owns adjustment.",
   """sequenceDiagram
  participant R as Rider
  participant S as Support
  participant D as Disputes
  participant F as Fare
  R->>S: ticket FARE_REVIEW
  S->>D: evidence + recommend
  D->>F: adjust −45 (key decision)
  F->>F: adjustment + refund""", "Evidence-driven.",
   "Ticket→Resolved; adjustment created.", "tickets; dispute_decisions; fare_adjustments.", "FareAdjusted", "Ticket APIs.", "Refund, notify.", "Idempotent adjustments.", '{"type":"FareAdjusted","data":{"trip_id":"…","amount_minor":-4500,"reason":"ROUTE"}}',
   [F("Duplicate apply", "Key", "None", "No-op", "Exact")])

wf(28, "Account restriction", "Risk or Support restricts a rider, and enforcement propagates.", "Risk analyst/Agent",
   ["rider-profile", "risk-fraud", "ride-request", "notifications"], "Rider Profile owns status.",
   """sequenceDiagram
  participant K as Risk
  participant P as RiderProfile
  participant R as Request
  K->>P: RestrictRider(cmd, reason)
  P->>P: ACTIVE→RESTRICTED + event
  P-->>R: RiderAccountStatusChanged
  R->>R: reject new requests""", "Command + event.",
   "Rider ACTIVE→RESTRICTED.", "rider_profiles; rider_restrictions.", "RiderAccountStatusChanged", "Command.", "Enforcement caches.", "Status cache ≤ 60 s stale (Phase IV); critical paths read source.", '{"type":"RiderAccountStatusChanged","data":{"rider_id":"…","status":"RESTRICTED","status_version":5}}',
   [F("Duplicate command", "Dedup", "None", "Ignore", "One transition")])

wf(29, "Data deletion (privacy request)", "A user requests deletion. Every system erases or anonymizes.", "User, Compliance",
   ["privacy", "identity", "rider-profile", "location-history", "event-pipeline", "support"], "Privacy orchestrates; each owner erases its data.",
   """sequenceDiagram
  participant U as User
  participant O as Orchestrator
  participant H as Handlers
  participant I as Identity
  U->>O: delete
  O->>O: obligations ok
  O->>H: ErasureRequested
  H-->>O: completed ×N
  O->>I: tombstone identity
  O-->>U: confirmation""", "Fan-out with proof.",
   "Case Received→Completed; user→Deleted.", "dsr_cases/tasks; all owners' data.", "ErasureRequested, ErasureCompleted", "Intake.", "Fan-out.", "Completion only when all handlers ack.", '{"type":"ErasureRequested","data":{"case_id":"…","user_id":"…"}}',
   [F("Handler fails", "Overdue", "Incomplete", "Escalate", "Tracked")])
