from model import comp, sub, A, Q, F, T

comp(id="trip", domain="trip", name="Trip Lifecycle", tag="Trip · System of record", phase="I", kind="Logical component → deployable service (Phase IV)",
     biz="The authoritative record of a ride from driver assignment to completion or cancellation: who, where, when and in which state.",
     eng="An aggregate with a strict state machine driven by driver actions, location signals and system timers, emitting the business events that payments, earnings, receipts, safety and analytics depend on.",
     deploy="Module (I); Trip service with own DB (IV); city-sharded DB (V); regional (VI).", data_own="trips, trip_events, pickup/dropoff details, waiting timers.",
     up=["dispatch", "location-ingest", "routing-eta", "driver-supply"], down=["trip-tracking", "fare-finalization", "payments", "driver-earnings", "receipts", "safety", "support", "event-pipeline"], ext=[],
     interfaces="Commands: `create`, `arrive`, `start`, `complete`, `cancel`; driver REST `/v1/trips/{id}/arrive|start|complete`; events `TripCreated`, `DriverArrived`, `TripStarted`, `TripCompleted`, `TripCancelled`.",
     problem="Many actors (driver app, rider app, dispatch, safety, support) act on the same trip, sometimes concurrently and from flaky networks. Downstream money flows depend on exactly-once business transitions.",
     fr=["Create from assignment", "Arrive (with geofence check)", "Start (with optional PIN)", "Complete (at dropoff)", "Cancel (rider/driver/system)", "Timeline of events", "Wait-time accounting"],
     nfr=["Transition p95 < 200 ms", "No illegal transitions", "Each business event emitted exactly once per transition (effectively)", "Trip history read p95 < 300 ms"],
     workload="≈ 5 transitions per trip; reads from apps every few seconds (served by tracking).", success="Every trip ends in exactly one terminal state with a full timeline.", failure="Double completion (double charge), stuck trips, missing events.",
     derive="A trip is a state machine, so transitions are conditional updates on (state, version). Every transition is a fact others need, so an event per transition via outbox. Actions come from devices with retries, so idempotent commands keyed by (trip, action). Location-based checks (arrived near pickup) are guards, not triggers, so the driver acts and the system validates.",
     owns=["Trip state and timeline", "Transition rules and guards", "Trip events"], not_owns=["Fare (Fare finalization)", "Payment (Payments)", "Live positions (Tracking)"], sync=["Transitions", "Get trip"], **{"async": ["Event publication", "Timers (no-show, stuck trip)"]},
     boundary_why="Trip is the system of record for what happened. Everything financial derives from its events, so it must be minimal and very correct.",
     hld=("""flowchart LR
  DSP["Dispatch commit"] -->|create| SM["Trip state machine"]
  DRV["Driver app"] -->|arrive/start/complete| SM
  RID["Rider app"] -->|cancel| SM
  SM --> PM["Pickup management"]
  SM --> EL["Trip event log + outbox"]
  EL -->|TripCompleted etc.| BUS[["events"]]
  BUS --> FARE["Fare finalization"] & PAY["Payments"] & ERN["Earnings"] & TRK["Tracking"]""", "Commands enter the state machine. Pickup management guards and times the pickup phase. The event log publishes facts."),
     seq=("""sequenceDiagram
  participant Dr as Driver
  participant T as Trip
  participant L as Location
  participant B as Bus
  Dr->>T: arrive
  T->>L: driver within 150 m of pickup?
  T->>T: ASSIGNED→ARRIVED (+event)
  Dr->>T: start (PIN)
  T->>T: ARRIVED→STARTED
  Dr->>T: complete
  T->>T: STARTED→COMPLETED
  T->>B: TripCompleted(trip, timeline)""", "Main lifecycle."),
     state=("""stateDiagram-v2
  [*] --> ASSIGNED
  ASSIGNED --> ARRIVED: driver at pickup
  ARRIVED --> STARTED: rider on board
  STARTED --> COMPLETED: dropoff
  ASSIGNED --> CANCELLED: rider/driver/system
  ARRIVED --> CANCELLED: no-show / cancel
  STARTED --> COMPLETED_EARLY: ended before destination
  COMPLETED --> [*]
  COMPLETED_EARLY --> [*]
  CANCELLED --> [*]""", "Trip state machine. Terminal states are final, and corrections (fare adjustments) are separate records."),
     subdeps=[("trip-state-machine", "trip-event-log"), ("pickup-management", "trip-state-machine")],
     flow="Every command loads the trip, checks the guard, applies a conditional update with version and appends a trip_event and an outbox row in the same transaction. Consumers react to events. Timers (no-show, stuck) are scheduled at transitions.",
     data="`trips(id, request_id UNIQUE, rider_id, driver_id, vehicle_id, city, product, state, quote_id, pickup, dropoff, assigned_at, arrived_at, started_at, ended_at, version)`, `trip_events(trip_id, seq, type, payload, actor, at)`.",
     er="""erDiagram
  TRIPS ||--o{ TRIP_EVENTS : records
  TRIPS ||--|| RIDE_REQUESTS : fulfils
  TRIPS }o--|| DRIVERS : driven_by
  TRIPS ||--o| FARES : priced_by""",
     rel=[["Idempotency", "Commands keyed by (trip, action, client_action_id)."], ["Outbox", "Events written in the same tx."], ["Timers", "No-show after arrived+5 min; stuck trip detection (no location for 10 min on STARTED → safety)."], ["Reconciliation", "Trips STARTED > 6 h flagged."]],
     sec=[["Authz", "Only assigned driver may transition; rider may cancel; support via RBAC with audit."], ["Safety", "PIN verification optional per market; route deviation alerts."]],
     adrs=[A("Event per transition via outbox", "I", "Downstream money flows.", [("Consumers poll trips table", "Rejected: coupling"), ("Outbox events", "Chosen")], "Outbox from Phase I (dispatch in-process until III).", "Exactly-once-effective facts.", "Outbox table ops.", "N/A")],
     qa=[Q("Correctness", "The driver taps 'complete' twice (network retry). How is double charging prevented?", "Complete is a conditional transition STARTED→COMPLETED. The second attempt finds state COMPLETED, returns the same result (idempotent by client_action_id) and writes no event. Only one TripCompleted is in the outbox. Even if the outbox relay publishes twice, payments dedupes on trip_id (one capture per trip, enforced by a unique constraint).", "")],
     impl_order=["trip-state-machine", "trip-event-log", "pickup-management"], pkg="""com.atlas.trip
├── domain  (Trip, TripState, Transition, Guards)
├── app     (TripCommandService, TripQueryService)
├── events  (TripEventLog, Outbox)
└── pickup  (PickupService, WaitTimer, NoShowHandler)""",
     tests=[T("Concurrency", "Complete ×2 parallel", "One COMPLETED, one event"), T("Property", "Random command sequences", "Only legal transitions"), T("Failure", "Crash after commit before relay", "Event published after restart")],
     evo=[("I", "Module", "PG + outbox", "Conditional transitions", "Correctness"), ("E", "Same", "Timers via queue", "Retries", "Reliability"), ("E", "Same", "Events on Kafka", "Idempotent consumers", "Many consumers"),
          ("R", "Trip service", "Own DB + replicas for history", "SLO 99.99%", "Isolation"), ("R", "City-sharded trips", "Shard by city", "Shard isolation", "Scale"), ("E", "Region by city", "Async DR replication", "Failover reconciliation", "Global")],
     ideas={"now": ["Outbox from day one"], "next": ["Trip timeline API for support"], "adv": ["Event-sourced trip"], "rej": ["Client-authoritative state"]})

sub(id="trip-state-machine", comp="trip", name="Trip State Machine", phase="I", cat="Correctness · State machine",
    resp="Apply trip commands as guarded, conditional, idempotent transitions and record them atomically with their events.",
    inp="commands (create, arrive, start, complete, cancel) with actor and client_action_id", out="new state + TripEvent", deps="Guards (location, PIN), Event log", cons="Apps, Dispatch, Support tools", own="trips",
    problem="Concurrent, retried commands from multiple actors must result in a single legal history.", without="Illegal states and duplicated money events.",
    guar=["Only transitions in the table are applied", "Each applied transition increments version and appends exactly one event", "Retried command returns the original outcome"], nong=["That the driver physically performed the action (guards bound it)"],
    usecase="Driver taps 'start' while rider cancels. Rider cancel commits first (ARRIVED → CANCELLED), so start fails with TRIP_NOT_IN_STATE and the driver app shows 'Rider cancelled'.",
    derive="- A transition table maps (state, command) → new state and guard.\n- Concurrency: optimistic version check in the UPDATE.\n- Idempotency: store applied client_action_ids per trip (in trip_events).",
    conc="`UPDATE trips SET state=:to, version=version+1, <ts>=now() WHERE id=:id AND state=:from AND version=:v`; on 0 rows reload and re-evaluate (maybe idempotent hit).", consistency="Linearizable per trip (single row).",
    idem="`trip_events` unique (trip_id, client_action_id); a retry finds the event and returns the current state.", order="Commands are applied in commit order. A late command whose precondition no longer holds is rejected with the current state.",
    restart="Stateless service; DB + outbox.", scale="Per-trip rows; partition by city at Phase V.", arch="Domain model `Trip.apply(Command) → Transition` (pure, uses table), persisted by `TripRepository.applyTransition` in one transaction with the event.",
    modules=[["TransitionTable", "Legal moves"], ["Guards", "Location proximity, PIN, actor"], ["TripRepository", "Conditional update + event + outbox"], ["CommandService", "Load, decide, persist, retry"]],
    d_arch=("""flowchart LR
  CMD["command"] --> CS["CommandService"] --> TT["TransitionTable"] & GD["Guards"]
  CS --> REPO["TripRepository"] --> DB[("trips, trip_events, outbox")]""", "Pure decision, transactional persistence."),
    d_seq=("""sequenceDiagram
  participant D as Driver
  participant S as CommandService
  participant DB
  D->>S: start(trip, action_id a7)
  S->>DB: load trip (ARRIVED, v3)
  S->>S: table: ARRIVED+start→STARTED, guard PIN ok
  S->>DB: UPDATE ... WHERE state=ARRIVED AND version=3
  S->>DB: INSERT trip_event(a7), outbox
  S-->>D: STARTED v4""", "Command processing."),
    d_state=("""stateDiagram-v2
  ASSIGNED --> ARRIVED: arrive [within 150m]
  ARRIVED --> STARTED: start [PIN ok]
  STARTED --> COMPLETED: complete
  ASSIGNED --> CANCELLED: cancel
  ARRIVED --> CANCELLED: cancel / no-show""", "Guarded transitions (guards in brackets)."),
    d_flow=("""flowchart LR
  C["command"] --> D["decision"] --> U["UPDATE trips"] --> E["INSERT trip_events"] --> O["INSERT outbox"]""", "Single transaction."),
    d_fail=("""flowchart TB
  V["version conflict"] --> R["reload; if action already applied → return; else re-decide"]
  G["guard fails (not near pickup)"] --> E["409 with reason; driver can override with reason (audited)"]""", "Conflicts are retried and guard failures are explicit."),
    sql="""CREATE TABLE trip.trips (id uuid PRIMARY KEY, request_id uuid NOT NULL UNIQUE, rider_id uuid NOT NULL, driver_id uuid NOT NULL, vehicle_id uuid NOT NULL,
  city text NOT NULL, product text NOT NULL, quote_id uuid NOT NULL, state text NOT NULL, version int NOT NULL DEFAULT 0,
  assigned_at timestamptz NOT NULL, arrived_at timestamptz, started_at timestamptz, ended_at timestamptz,
  CHECK (state IN ('ASSIGNED','ARRIVED','STARTED','COMPLETED','COMPLETED_EARLY','CANCELLED')));
CREATE INDEX trips_rider_time ON trip.trips(rider_id, assigned_at DESC);
CREATE INDEX trips_driver_active ON trip.trips(driver_id) WHERE state IN ('ASSIGNED','ARRIVED','STARTED');
CREATE UNIQUE INDEX one_active_trip_per_driver ON trip.trips(driver_id) WHERE state IN ('ASSIGNED','ARRIVED','STARTED');""",
    data="`one_active_trip_per_driver` is a second guard against double assignment.", api="""POST /v1/trips/{id}/arrive   {action_id, lat, lng}
POST /v1/trips/{id}/start    {action_id, pin?}
POST /v1/trips/{id}/complete {action_id, lat, lng}
-> 200 {state, version} | 409 TRIP_NOT_IN_STATE{state} | 409 GUARD_FAILED{reason}""",
    mech=[("Optimistic concurrency", "Version check in the WHERE clause detects concurrent changes without holding locks across a user action."), ("Transition table", "Encoding legal moves as data prevents ad-hoc if-chains and makes the state machine testable by enumeration.")],
    code="""public TripView handle(TripId id, Command c) {
    for (int attempt = 0; attempt < 3; attempt++) {
        Trip t = repo.load(id);
        if (repo.actionApplied(id, c.actionId())) return TripView.of(t);
        Transition tr = TransitionTable.decide(t.state(), c).orElseThrow(() -> new NotInState(t.state()));
        guards.check(tr, t, c);
        if (repo.apply(t, tr, c)) return TripView.of(repo.load(id));    // false on version conflict
    }
    throw new ConcurrentModification(id);
}""", cx="O(1).",
    fail=[F("Version conflict", "0 rows", "Retry", "Reload & re-decide", "Correct order"), F("Duplicate action", "Unique action id", "None", "Return current", "Single event")],
    alts=[["Pessimistic lock (SELECT FOR UPDATE)", "Viable", "Simpler retry logic", "High contention"], ["Event sourcing", "Advanced", "Full history natively", "If audit demands"]],
    adrs=[A("Optimistic locking for trips", "I", "Low contention per trip.", [("Pessimistic", "OK"), ("Optimistic", "Chosen")], "Version column.", "No lock waits.", "Retry loop.", "N/A")],
    qa=[Q("Correctness", "Should 'complete' be allowed far from the destination?", "Yes, with reason. Riders change destinations or get out early. Allow COMPLETED_EARLY when far from the dropoff, recording location, so fare finalization uses actual distance and time. Flag patterns (frequent early completions) to fraud.", "")],
    tests=[T("Property", "All (state, command) pairs", "Matches table"), T("Concurrency", "Start vs cancel", "One wins, other 409")],
    evo=["I: Conditional updates + outbox", "U: No change needed", "E: Events to Kafka", "E: Trip service API", "E: City-sharded", "E: Region fencing"],
    ideas={"now": ["Transition table tests"], "next": ["Driver override with reason"], "adv": ["Event-sourced trips"], "rej": ["Client-side state"]})

sub(id="trip-event-log", comp="trip", name="Trip Event Log & Outbox", phase="I", cat="Consistency · Events",
    resp="Keep an append-only timeline per trip and publish each business event reliably to consumers exactly once in effect.",
    inp="transitions from the state machine", out="trip_events rows; published events on the bus", deps="DB, Messaging (Phase III)", cons="Payments, Earnings, Receipts, Tracking, Safety, Analytics", own="trip_events, outbox",
    problem="Publish facts about trips atomically with the state change, so consumers never miss or invent events.", without="Dual-write bugs: state changed but event lost, or event published for a rolled-back change.",
    guar=["Event exists iff transition committed", "Per-trip order preserved", "At-least-once delivery with stable event ids"], nong=["Exactly-once delivery (consumers dedupe)"],
    usecase="TripCompleted written with the state change. The relay crashes before publishing, restarts and publishes. Payments receives it once (or twice and dedupes).",
    derive="- Atomicity: the event row in the same transaction.\n- Delivery: a relay reads unsent rows in order and publishes, marking sent after broker ack.\n- Order: partition key = trip_id.",
    conc="Relay: `SELECT ... FROM outbox WHERE sent_at IS NULL ORDER BY id LIMIT 500 FOR UPDATE SKIP LOCKED` (multiple relays) with per-partition ordering preserved by key-based partitioning and single relay per shard.", consistency="Events eventually published (seconds); consumers eventually consistent.",
    idem="event_id = UUID per row; consumers dedupe on it.", order="Per-trip order preserved because events for a trip come from one DB in commit order and are keyed by trip_id.",
    restart="Relay resumes from unsent rows.", scale="Phase IV: Debezium CDC on outbox table removes polling. Phase V: outbox per shard.",
    arch="Phase I–II: in-process event dispatch after commit (TransactionalEventListener) plus outbox for durability. Phase III: polling relay → Kafka. Phase IV: Debezium CDC → Kafka with outbox event router.",
    modules=[["TimelineWriter", "trip_events append"], ["OutboxWriter", "Same transaction"], ["Relay / CDC", "Publish to bus"], ["Purger", "Delete sent rows after 7 days"]],
    d_arch=("""flowchart LR
  SM["State machine tx"] --> TE[("trip_events")] & OB[("outbox")]
  OB --> RL["Relay (P3) / Debezium (P4)"] --> K[["trip-events topic (key=trip_id)"]]
  K --> C1["Payments"] & C2["Earnings"] & C3["Receipts"]""", "Outbox to bus."),
    d_seq=("""sequenceDiagram
  participant S as StateMachine
  participant DB
  participant R as Relay
  participant K as Kafka
  S->>DB: BEGIN, update trip, insert event+outbox, COMMIT
  R->>DB: select unsent FOR UPDATE SKIP LOCKED
  R->>K: produce(key=trip_id)
  K-->>R: ack
  R->>DB: mark sent""", "Relay cycle."),
    d_state=("""stateDiagram-v2
  [*] --> Unsent
  Unsent --> Sent: broker ack
  Sent --> Purged: after 7 days""", "Outbox row lifecycle."),
    d_flow=("""flowchart LR
  TX["transaction"] --> ROW["outbox row {event_id, trip_id, type, payload}"] --> MSG["Kafka record key=trip_id"]""", "Row to message."),
    d_fail=("""flowchart TB
  C["relay crash after produce, before mark"] --> D["duplicate publish on restart"] --> DD["consumers dedupe by event_id"]
  K["Kafka down"] --> B["outbox grows; alert at backlog > 10K"]""", "Duplicates are expected. Loss is impossible."),
    sql="""CREATE TABLE trip.trip_events (trip_id uuid, seq int, type text NOT NULL, payload jsonb NOT NULL, actor text NOT NULL, client_action_id uuid,
  at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (trip_id, seq), UNIQUE (trip_id, client_action_id));
CREATE TABLE trip.outbox (id bigserial PRIMARY KEY, event_id uuid NOT NULL UNIQUE, aggregate_id uuid NOT NULL, type text NOT NULL,
  payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), sent_at timestamptz);
CREATE INDEX outbox_unsent ON trip.outbox(id) WHERE sent_at IS NULL;""",
    data="trip_events retained with trips (3 years); outbox purged after 7 days.", api="""Event envelope (Avro/JSON):
{ "event_id":"uuid", "type":"TripCompleted", "version":2, "trip_id":"…", "occurred_at":"…", "producer":"trip",
  "data":{ "rider_id":"…","driver_id":"…","started_at":"…","ended_at":"…","quote_id":"…","city":"PUN" } }""",
    mech=[("Transactional outbox", "Writing the event as a row in the same DB transaction makes 'state changed' and 'event recorded' atomic. Publishing is a separate, retryable step."), ("CDC (Debezium)", "Reads the database's write-ahead log and turns outbox inserts into Kafka records in commit order, with no polling queries and lower latency.")],
    code="""@Scheduled(fixedDelay = 200)
@Transactional
public void relay() {
    List<OutboxRow> rows = outbox.lockUnsent(500);          // FOR UPDATE SKIP LOCKED, ORDER BY id
    for (OutboxRow r : rows) kafka.send(new ProducerRecord<>("trip-events", r.aggregateId().toString(), r.toEnvelope())).get();
    outbox.markSent(rows);
}""", cx="O(batch).",
    fail=[F("Relay crash mid-batch", "Unsent rows remain", "Delay; duplicates", "Republish", "Consumers dedupe"), F("Poison payload", "Serialization error", "Relay stuck", "Move to outbox_dead + alert", "Manual fix")],
    alts=[["Dual write", "Rejected", "Non-atomic", "Never"], ["Event sourcing (events are truth)", "Advanced", "No separate outbox", "If full ES adopted"]],
    adrs=[A("Debezium CDC at Phase IV", "IV", "Polling load/latency.", [("Polling relay", "Phase III"), ("CDC", "Chosen at IV")], "Debezium outbox router.", "Low latency, no polling.", "Connector ops.", "N/A")],
    qa=[Q("Distributed systems", "Why can't the relay guarantee exactly-once delivery to consumers?", "Publishing and marking sent are two systems (Kafka, Postgres) without a shared transaction. A crash between them republishes. Kafka transactions can make produce+offset atomic *within Kafka*, but not with Postgres. So the guarantee is at-least-once delivery plus consumer deduplication by event_id, which gives effectively-once business effects.", "")],
    tests=[T("Failure", "Kill relay after produce", "Duplicate published; consumer state unchanged"), T("Ordering", "100 events same trip", "Consumed in order")],
    evo=["I: Outbox + in-process dispatch", "U: No change needed", "R: Polling relay to Kafka", "R: Debezium CDC", "E: Outbox per shard", "E: Regional topics; DR mirror"],
    ideas={"now": ["Stable event ids"], "next": ["Schema registry"], "adv": ["Event sourcing"], "rej": ["Publishing before commit"]})

sub(id="pickup-management", comp="trip", name="Pickup Management (Arrival, Wait, No-Show)", phase="I", cat="Workflow · Timers",
    resp="Validate driver arrival at the pickup, notify the rider, run the wait timer, apply wait fees and handle no-shows.",
    inp="arrive command + location, rider location, timers", out="ARRIVED transition, wait fees, no-show cancellation", deps="Trip state machine, Location, Notifications, Cancellation policy", cons="Rider/driver apps, Fare finalization (wait fee)", own="wait_timers",
    problem="The pickup moment is error-prone: GPS inaccuracy, wrong side of the street, riders not showing up. Both parties need fairness.", without="False arrivals, unpaid waiting, stranded drivers.",
    guar=["Arrival requires driver within 150 m (or override with reason)", "Free wait period per policy, then per-minute fee", "No-show cancel allowed only after policy wait time"], nong=["Rider actually saw the notification"],
    usecase="Driver arrives at 10:00 (within 80 m). Rider notified. Free wait 2 min, then ₹2/min. At 10:05 the driver may cancel as no-show: fee ₹40 to driver.",
    derive="- Arrival guard is a distance check with filtered position.\n- Wait timer starts at ARRIVED.\n- No-show is a permission granted after a timer, so a durable timer.",
    conc="Timer firings and rider-start race; resolved by trip state conditional update.", consistency="Strong via trip state.", idem="Arrive is idempotent (already ARRIVED → return).", order="Timer firing after start is a no-op (state check).",
    restart="Durable timers (job table/delayed messages/workflow).", scale="One timer per trip in pickup phase.", arch="On ARRIVED: notify rider, schedule `noShowAllowedAt = arrived + policy`. Wait fee computed at start from timestamps (no ticking counters).",
    modules=[["ArrivalGuard", "Distance check with accuracy margin"], ["WaitPolicy", "Free minutes, fee per minute, no-show time"], ["NoShowTimer", "Durable timer → driver option"], ["WaitFeeCalc", "Computed from timestamps"]],
    d_arch=("""flowchart LR
  DRV["arrive"] --> AG["ArrivalGuard"] --> LOC["latest position"]
  AG --> SM["Trip: ARRIVED"] --> NT["Notify rider"]
  SM --> NST["NoShowTimer"] --> DRVOPT["driver may cancel no-show"]
  START["start"] --> WF["WaitFeeCalc(arrived, started)"]""", "Arrival, wait and no-show."),
    d_seq=("""sequenceDiagram
  participant D as Driver
  participant P as Pickup
  participant R as Rider
  participant Tm as Timer
  D->>P: arrive (lat,lng)
  P->>P: distance 80m ≤ 150m
  P->>R: "Your driver has arrived"
  P->>Tm: schedule no-show at +5m
  Tm->>P: fire
  P->>D: enable "Rider no-show" button""", "Pickup flow."),
    nostate="Pickup states (ARRIVED, wait) are part of the trip state machine. The timer is a scheduled job.",
    d_flow=("""flowchart LR
  A["arrived_at"] --> W["wait = started_at - arrived_at"] --> F["fee = max(0, wait - free) × rate"]""", "Wait fee from timestamps."),
    d_fail=("""flowchart TB
  G["GPS says far but driver is there"] --> O["override with reason + photo (audited)"]
  T["timer lost"] --> S["no-show button computed client-side from arrived_at, verified server-side on cancel"]""", "Server verification makes client display harmless."),
    sql="CREATE TABLE trip.wait_policies (city text, product text, free_wait_s int, fee_per_min_minor bigint, no_show_after_s int, PRIMARY KEY(city, product));",
    data="Policies versioned.", api="""POST /v1/trips/{id}/arrive {action_id, lat, lng, override_reason?}
POST /v1/trips/{id}/cancel {action_id, reason:"RIDER_NO_SHOW"} -> 409 NO_SHOW_TOO_EARLY{allowed_at}""",
    mech=[("Timestamp-derived fees", "Computing wait fees from immutable timestamps at the end avoids ticking counters and drift. The fee is reproducible."), ("Server-verified client affordances", "The app may show the no-show button early, but the server checks `now ≥ arrived_at + policy`.")],
    code="""long waitFee(Instant arrived, Instant started, WaitPolicy p) {
    long waited = Duration.between(arrived, started).toSeconds() - p.freeWaitS();
    return waited <= 0 ? 0 : (long) Math.ceil(waited / 60.0) * p.feePerMinMinor();
}""", cx="O(1).",
    fail=[F("Early no-show cancel", "Time check", "Rejected", "Client retries later", "None"), F("False arrival far away", "Guard", "Rejected or overridden with audit", "Fraud signal on frequent overrides", "None")],
    alts=[["Auto-arrive by geofence", "Viable", "Fewer taps; GPS errors", "As suggestion only"]],
    adrs=[A("Driver-initiated arrival with server guard", "I", "GPS unreliable.", [("Auto-arrive", "Error-prone"), ("Driver + guard", "Chosen")], "Driver taps, server validates.", "Accountable.", "Extra tap.", "N/A")],
    qa=[Q("Fairness", "Rider's GPS shows them 300 m away at a different entrance. Should the wait fee apply?", "If the driver arrived at the pin and the rider is far, wait fees apply after free wait. If the pin was inside a large venue with multiple entrances (geofence attribute), the free wait is extended and the app offers 'meet at' suggestions. The policy uses venue metadata.", "")],
    tests=[T("Unit", "Wait 2m59s with 2m free", "1 min fee"), T("Integration", "No-show at 4m59s", "409 NO_SHOW_TOO_EARLY")],
    evo=["I: Guard + timestamp fees + job-table timer", "E: Delayed-message timers", "E: Events (DriverArrived)", "U: No change needed", "E: Venue-aware pickup policies", "U: No change needed"],
    ideas={"now": ["Timestamp-derived fees"], "next": ["Venue meeting points"], "adv": ["AR pickup guidance"], "rej": ["Ticking fee counters"]})

# ======================================================================= Tracking
comp(id="trip-tracking", domain="trip", name="Real-time Trip Tracking", tag="Trip · Real-time", phase="I", kind="Logical component → connection-heavy service (Phase III)",
     biz="Shows the rider their car approaching and the trip progressing on a map, with a live ETA, and lets them share the trip with family.",
     eng="Fan-out of driver positions and trip state to subscribed clients (rider, shared viewers) over persistent connections, at scale, with low latency and bounded cost.",
     deploy="Polling endpoint (I–II); WebSocket service (III); regional connection gateways (VI).", data_own="Connection registry, subscriptions, last-sent state per subscriber.",
     up=["location-ingest", "trip", "routing-eta"], down=["notifications"], ext=[],
     interfaces="`GET /v1/trips/{id}/live` (poll, I–II); `wss://…/v1/live` subscribe `{trip_id}` (III+); share links `GET /share/{token}`.",
     problem="Every active trip has 1–3 viewers wanting updates every 1–2 s. Polling multiplies load. Persistent connections need a routing layer from 'trip X has a new position' to 'the server holding viewer Y's socket'.",
     fr=["Live driver position & heading", "Live ETA to pickup/destination", "State changes pushed (arrived, started)", "Share trip with link", "Reconnect resumption"], nfr=["Update latency p95 < 2 s from GPS", "Connections: 5M concurrent (VI)", "Cost per tracked trip bounded"],
     workload="Phase V: ≈ 200K active trips × 1.5 viewers, update every 2 s ⇒ 150K msgs/s outbound.", success="Smooth, timely car movement.", failure="Frozen cars, rider anxiety, support calls.",
     derive="Push beats poll once updates are frequent, so WebSockets. Producers (location stream) don't know which server holds a viewer's socket, so route by trip: partition subscriptions by trip_id so that the node consuming a trip's updates holds its viewers, or use pub/sub. Clients reconnect often (mobile), so they resume with a last-seen version.",
     owns=["Live connections and subscriptions", "Update throttling per viewer", "Share tokens"], not_owns=["Positions (Location)", "ETA (Routing)", "Trip state (Trip)"], sync=["Subscribe", "Share link resolution"], **{"async": ["Position and state fan-out"]},
     boundary_why="Connection management is a distinct scaling problem (memory per socket, long-lived) from the rest of the request/response services.",
     hld=("""flowchart LR
  LOC[["on-trip positions"]] --> RT["Router (by trip_id)"]
  TE[["trip events"]] --> RT
  ETA["ETA refresh"] --> RT
  RT --> GW1["WS gateway 1"] & GW2["WS gateway 2"]
  RID["Rider app"] <-->|WebSocket| GW1
  FAM["Shared viewer"] <-->|WebSocket| GW2
  GW1 & GW2 --> REG[("subscription registry")]""", "Updates routed by trip to the gateways holding viewers' connections."),
     seq=("""sequenceDiagram
  participant R as Rider app
  participant G as WS gateway
  participant RG as Registry
  participant P as Position stream
  R->>G: connect + subscribe(trip 42, last_v=17)
  G->>RG: register(trip 42 → gateway G)
  P->>G: position(trip 42, v18) via routing
  G->>R: {pos, heading, eta, v18}""", "Subscribe and receive."),
     subdeps=[("tracking-fanout", "eta-refresh")],
     flow="Clients connect to any gateway and subscribe to trips they're authorized for. A router delivers each trip's updates to gateways with subscribers. Gateways throttle and coalesce per viewer.",
     data="Registry: Redis `subs:{trip_id}` → set of gateway ids (TTL refreshed). Share tokens: `share_links(token, trip_id, expires_at)`.",
     rel=[["Reconnect", "Resume from version; send latest snapshot on subscribe."], ["Backpressure", "Per-connection buffer of 1 (latest state wins)."], ["Gateway loss", "Clients reconnect to another gateway; registry TTL cleans up."]],
     sec=[["Authz", "Subscribe only to own trip or via share token."], ["Privacy", "Shared view shows car, driver first name, plate, ETA. Share token expires at trip end + 15 min."]],
     adrs=[A("Push via WebSocket from Phase III", "III", "Polling load at 5K concurrent trips.", [("Polling", "Load ∝ viewers × freq"), ("SSE", "Viable one-way"), ("WebSocket", "Chosen (bidirectional for chat later)")], "WebSocket gateways.", "Lower load/latency.", "Stateful connection tier.", "N/A")],
     qa=[Q("Scaling", "How do 150K position updates/s reach 5M sockets without every gateway seeing every update?", "Partition: route each trip's updates to the gateway(s) holding its subscribers using the registry (trip → gateways), with gateways consuming a per-gateway delivery topic (or Redis pub/sub channel per gateway). Each update is sent only to the 1–2 gateways that need it. Alternatively, consistent-hash viewers to gateways by trip_id at connect time, so the consuming node is the socket node.", "Broadcasting to all gateways makes cost ∝ gateways × updates.")],
     impl_order=["tracking-fanout", "eta-refresh"], pkg="""com.atlas.tracking
├── ws       (WsGateway, SessionManager, Throttler)
├── routing  (SubscriptionRegistry, UpdateRouter)
├── share    (ShareLinkService)
└── eta      (EtaRefresher)""",
     tests=[T("Load", "1M connections, 150K msg/s", "p95 latency < 2 s; memory < 40 KB/conn"), T("Failure", "Kill gateway", "Clients reconnect < 5 s, resume")],
     evo=[("I", "Polling endpoint reading latest position", "PG", "—", "Simple"), ("E", "Polling + Redis latest position", "Redis", "Rate limits", "Load"), ("R", "WebSocket service + registry", "Redis pub/sub", "Reconnect resume", "5K trips"),
          ("E", "Gateway fleet + router", "Per-gateway topics", "Autoscale on connections", "Scale"), ("E", "Coalescing/throttling; MQTT-style compression", "Binary protocol", "Cost", "150K msg/s"), ("E", "Regional gateways", "—", "—", "Global")],
     ideas={"now": ["Poll with ETag"], "next": ["WebSocket"], "adv": ["Client-side dead reckoning to reduce update rate"], "rej": ["Broadcast to all gateways"]})

sub(id="tracking-fanout", comp="trip-tracking", name="Live Update Fan-out", phase="I", cat="Real-time · Connections",
    resp="Deliver the latest trip position/state to every authorized viewer with minimal latency and per-viewer throttling.",
    inp="positions and trip events keyed by trip", out="messages to viewers", deps="Location stream, Trip events, Registry", cons="Rider app, share viewers", own="connections, registry",
    problem="Route high-rate updates to the right sockets efficiently.", without="Polling storms or broadcast waste.",
    guar=["Viewers receive the latest state (intermediate states may be skipped)", "Only authorized viewers subscribe", "Resume after reconnect from snapshot"], nong=["Every position delivered"],
    usecase="Rider on a train with flaky signal: reconnects 5 times in 10 minutes. Each time the gateway sends the latest snapshot immediately, so the car jumps to the current spot.",
    derive="- Latest-wins semantics, so per-connection single-slot buffer (overwrite).\n- Routing: registry maps trip → gateways.\n- Resume: snapshot on subscribe.",
    conc="Per-connection actor/event loop (Netty); overwrite buffer is atomic reference.", consistency="Eventually consistent, latest-wins.", idem="Updates carry version; clients ignore older versions.", order="Version-based; out-of-order dropped client-side and server-side.",
    restart="Gateways stateless besides sockets; clients reconnect; registry entries expire (TTL 60 s).", scale="≈ 50K–100K connections per gateway node (Netty); horizontally.",
    arch="Phase I–II: `GET /trips/{id}/live` with ETag (latest position + state). Phase III+: Netty WebSocket gateways. Router service consumes positions and events, looks up registry and publishes to `gw.{id}` channels. Gateways write to sockets with throttling (≥ 1 s apart per viewer).",
    modules=[["SessionManager", "Auth, subscribe, heartbeat"], ["SubscriptionRegistry", "trip → gateways (Redis SET with TTL)"], ["UpdateRouter", "Consume streams, route by registry"], ["Throttler", "Latest-wins per viewer"]],
    d_arch=("""flowchart LR
  POS[["positions"]] --> UR["UpdateRouter"] --> REG[("registry")]
  UR -->|pub gw.N| PS["Redis pub/sub / topic per gateway"] --> GW["Gateway N"] --> TH["Throttler"] --> WS["sockets"]""", "Router publishes only to gateways with subscribers."),
    d_seq=("""sequenceDiagram
  participant U as Router
  participant R as Registry
  participant G as Gateway
  participant C as Client
  U->>R: SMEMBERS subs:42
  R-->>U: {G}
  U->>G: publish(gw.G, update v19)
  G->>G: throttle: last sent 0.4s ago → buffer
  G->>C: send v19 at t+0.6s""", "Routing with throttling."),
    d_state=("""stateDiagram-v2
  [*] --> Connecting
  Connecting --> Subscribed: auth + subscribe
  Subscribed --> Subscribed: updates
  Subscribed --> Disconnected: network loss
  Disconnected --> Connecting: client retry (backoff + jitter)
  Subscribed --> Closed: trip ended""", "Connection lifecycle."),
    d_flow=("""flowchart LR
  P["pos v19"] --> B["buffer slot (overwrite)"] --> S["send ≥1s cadence"]""", "Latest-wins buffering."),
    d_fail=("""flowchart TB
  G["gateway crash"] --> RC["clients reconnect elsewhere; snapshot"]
  R["registry down"] --> FB["router broadcasts to all gateways (degraded) or clients fall back to polling"]""", "Fallbacks degrade efficiency, not correctness."),
    sql="-- Redis: subs:{trip_id} SET of gateway ids (TTL 60s refreshed); latest:{trip_id} HASH snapshot",
    data="Ephemeral.", api="""WS: → {"op":"subscribe","trip_id":"…","last_v":17}  ← {"op":"update","v":19,"pos":{…},"heading":92,"eta_s":240,"state":"ASSIGNED"}
GET /v1/trips/{id}/live (If-None-Match) -> 200 | 304""",
    mech=[("Latest-wins buffer", "A single slot per connection, overwritten by newer updates, bounds memory and gives automatic backpressure for slow clients."), ("Reconnect with jittered backoff", "Prevents thundering herds when a gateway dies and 50K clients reconnect at once.")],
    code="""void onUpdate(TripUpdate u) {
    for (Conn c : conns.of(u.tripId())) {
        c.pending.accumulateAndGet(u, (old, nu) -> old == null || nu.v() > old.v() ? nu : old);
        if (c.lastSentNanos + 1_000_000_000L <= System.nanoTime()) c.flush();
    }
}""", cx="O(viewers) per update.",
    fail=[F("Slow client", "Buffer overwrite count", "Skipped frames", "Latest-wins", "None"), F("Herd reconnect", "Connection spike", "Gateway CPU", "Jitter + admission", "None")],
    alts=[["SSE", "Viable", "Simpler, one-way", "No client→server messages needed"], ["Long polling", "Rejected", "Overhead", "Legacy clients"], ["MQTT", "Viable", "Built-in pub/sub", "If adopting broker"]],
    adrs=[A("Registry-based routing", "III", "Avoid broadcast.", [("Broadcast", "Wasteful"), ("Registry", "Chosen")], "Registry.", "Targeted delivery.", "Registry dependency.", "Consistent hashing alternative at V.")],
    qa=[Q("Cost", "How do you cut tracking bandwidth by half without hurting UX?", "Send updates only on meaningful change (moved > 10 m or heading change > 15°). Use a compact binary format (delta-encoded coordinates). Let the client interpolate (dead reckoning) between updates with speed and heading. Lower cadence when the car is far from the pickup (> 2 km).", "")],
    tests=[T("Load", "100K conns/node", "Stable memory"), T("Unit", "Out-of-order versions", "Older dropped")],
    evo=["I: Poll endpoint", "E: Redis latest + ETag", "R: WebSocket gateways + registry", "E: Router service, per-gateway topics", "E: Delta encoding, dead reckoning", "E: Regional gateways"],
    ideas={"now": ["ETag polling"], "next": ["WebSocket"], "adv": ["QUIC/WebTransport"], "rej": ["Broadcast"]})

sub(id="eta-refresh", comp="trip-tracking", name="Live ETA Refresh & Rerouting", phase="II", cat="Real-time · Prediction",
    resp="Recompute ETA to pickup/destination as the trip progresses, detect route deviations and trigger rerouting suggestions.",
    inp="matched positions, trip state, route plan", out="ETA updates, deviation events, new route", deps="ETA service, Route calculation, Map matching", cons="Tracking fan-out, Safety (deviation), Driver navigation", own="per-trip route plan",
    problem="ETAs drift with traffic and driver choices. Deviations may be legitimate (closure) or a safety concern.", without="Stale ETAs, unnoticed deviations.",
    guar=["ETA refreshed at least every 30 s on active trips", "Deviation > threshold emits event", "Recompute budget bounded per trip"], nong=["Accurate cause of deviation"],
    usecase="Driver takes a detour around a closed road. Deviation 800 m from the planned route, so the route is recomputed from the current position, the ETA updates, and a soft deviation is logged (not a safety alert, since speed is normal and the trend is toward the destination).",
    derive="- Recompute ETA cheaply from remaining route + current speeds every 30 s, or immediately on deviation.\n- Deviation = distance from planned polyline > 200 m for 2 consecutive points.",
    conc="Per-trip processing keyed by trip_id.", consistency="Eventually consistent ETAs.", idem="ETA recompute is a pure function of state; repeated triggers merge.", order="Stale ETA results (computed from older positions) discarded by position version.",
    restart="Route plan stored with trip (Phase III+), so recomputation resumes.", scale="Proportional to active trips/30 s; ≈ 7K recomputes/s at Phase V.",
    arch="Keyed processor per trip: on position, check deviation against plan, and on deviation or every 30 s, call ETA for remaining route, update plan and emit to tracking.",
    modules=[["DeviationDetector", "Distance to polyline"], ["Refresher", "Timed + event-driven recompute"], ["Rerouter", "New route from current position"]],
    d_arch=("""flowchart LR
  POS["matched positions"] --> DD["DeviationDetector"] --> RR["Rerouter"] --> RC["Route engine"]
  POS --> RF["Refresher (30s)"] --> ETA["ETA service"]
  RR & RF --> OUT["ETA/route updates → tracking"]
  DD -->|deviation| SAF["Safety"]""", "Deviation and periodic refresh paths."),
    d_seq=("""sequenceDiagram
  participant P as Positions
  participant D as Detector
  participant R as Rerouter
  participant T as Tracking
  P->>D: pos (820 m off plan)
  D->>D: 2nd consecutive → deviation
  D->>R: reroute(current, dest)
  R-->>T: new route, ETA +3 min""", "Reroute on deviation."),
    nostate="Per-trip plan data, no lifecycle beyond the trip.",
    d_flow=("""flowchart LR
  P["position"] --> D["distance to polyline"] --> C{"> 200 m ×2?"} -->|yes| RR["reroute"]""", "Deviation check."),
    d_fail=("""flowchart TB
  E["ETA service down"] --> L["extrapolate: remaining distance / recent speed"]""", "Fallback estimate."),
    sql="CREATE TABLE trip.route_plans (trip_id uuid PRIMARY KEY, polyline text NOT NULL, planned_at timestamptz NOT NULL, eta_at timestamptz, version int NOT NULL);",
    data="Plans retained with trip for disputes.", api="""event RouteDeviated{trip_id, distance_m, at}
update {eta_s, route_polyline?, v}""",
    mech=[("Point-to-polyline distance", "Project the point onto each segment of the polyline (cross-track distance) and take the minimum. A spatial index on segments keeps it O(log n).")],
    code="""double off = polyline.distanceTo(pos);
if (off > 200 && ++state.offCount >= 2) { state.offCount = 0; rerouter.reroute(trip, pos); } else if (off <= 200) state.offCount = 0;""", cx="O(log segments).",
    fail=[F("Route engine slow", "Timeout", "Old route", "Retry next tick", "None")],
    alts=[["Driver app computes ETA", "Rejected", "Inconsistent with rider view", "Offline navigation only"]],
    adrs=[A("Server-side refresh", "II", "Consistency between rider and driver.", [("Client", "Inconsistent"), ("Server", "Chosen")], "Server.", "One source.", "Server cost.", "N/A")],
    qa=[Q("Safety", "When is a deviation a safety alert vs. a detour?", "Signals combine: deviation magnitude, heading away from the destination for > 3 min, unexpected stop > 5 min in an unusual location, and time of night. Combined, they score risk. Above threshold, the rider gets a 'Is everything OK?' check-in and safety ops are alerted. Single signals only log.", "")],
    tests=[T("Unit", "Single outlier point off route", "No deviation"), T("Integration", "Closure detour", "Reroute, ETA updated")],
    evo=["N: Phase I shows the provider ETA at assignment only", "I: Periodic ETA refresh", "E: Deviation events to safety", "E: In-house rerouting", "R: Stream-processed per trip in Flink", "U: No change needed"],
    ideas={"now": ["Periodic refresh"], "next": ["Deviation detection"], "adv": ["Predictive rerouting"], "rej": ["Client-computed rider ETA"]})

# ======================================================================= Fare Finalization
comp(id="fare-finalization", domain="trip", name="Fare Finalization & Trip Reconciliation", tag="Money · Correctness", phase="I", kind="Logical component",
     biz="Determines what the rider actually pays when the trip ends: the upfront price, or a recalculated fare if the trip changed materially, plus tolls, wait fees and adjustments.",
     eng="A deterministic post-trip computation from trip timeline, matched distance and the pinned quote, producing one final fare per trip, plus reconciliation across trip, payment and ledger.",
     deploy="Module (I); consumer of TripCompleted within Pricing/Payments boundary (III+).", data_own="fares, fare_adjustments, reconciliation results.",
     up=["trip", "location-history", "pricing", "pickup-management"], down=["payments", "receipts", "driver-earnings", "support"], ext=["Toll data providers"],
     interfaces="Consumes `TripCompleted`; emits `FareFinalized{trip_id, amount, breakdown}`; `POST /internal/fares/{trip}/adjust` (support).",
     problem="The upfront price is a promise, but trips change (destination edits, long detours requested by rider, tolls). The final fare must be fair, computed once, and adjustable only through audited adjustments.",
     fr=["Final fare from quote or recalculation", "Add tolls/airport fees from geofences", "Wait fees", "Adjustments by support", "Reconcile trip vs payment vs ledger"], nfr=["Fare within 30 s of completion", "Exactly one final fare per trip", "Deterministic recompute"],
     workload="One per completed trip.", success="Riders charged what they expect; disputes explainable.", failure="Charging twice, wrong fares, unexplained adjustments.",
     derive="One fare per trip is an invariant, so a unique constraint. Inputs come from several sources (trip, matched distance, quote, geofence crossings), so collect, then compute purely. Later changes go through adjustments (append-only), never by editing the fare.",
     owns=["Final fare", "Adjustments", "Reconciliation"], not_owns=["Quote (Pricing)", "Charging (Payments)"], sync=["Adjustment API"], **{"async": ["TripCompleted → FareFinalized"]},
     boundary_why="Separate from Pricing's quoting so post-trip logic (tolls, deviations) and adjustments have one owner, using Pricing's calculator library.",
     hld=("""flowchart LR
  TC["TripCompleted"] --> FC["Fare calculator"]
  FC --> Q[("quote")] & MD["matched distance/time"] & GF["toll/airport crossings"] & WT["wait time"]
  FC --> FR[("fares")]
  FC -->|FareFinalized| PAY["Payments capture"]
  SUP["Support"] --> ADJ["Adjustments"] --> FR
  REC["Trip reconciliation"] --> FR & PAY & LED["Ledger"]""", "Compute once, adjust by append, reconcile across systems."),
     seq=("""sequenceDiagram
  participant T as Trip
  participant F as FareCalc
  participant P as Payments
  T->>F: TripCompleted
  F->>F: inputs → final fare (quote honoured)
  F->>F: insert fare (unique trip)
  F->>P: FareFinalized
  P->>P: capture""", "Main flow."),
     subdeps=[("trip-reconciliation", "fare-calculator")],
     flow="TripCompleted triggers computation, and the unique insert guarantees one fare. FareFinalized drives capture, earnings and receipts. Reconciliation runs daily and continuously (Phase V).",
     data="`fares(trip_id PK, amount_minor, currency, basis(QUOTE|RECALC), breakdown, computed_at)`, `fare_adjustments(id, trip_id, amount_minor (+/−), reason, actor, approved_by, at)`.",
     rel=[["Idempotency", "Unique fare per trip; consumer dedupe."], ["Missing inputs", "Matched distance unavailable → quote basis + flag."]], sec=[["Adjustments", "RBAC limits per role; dual approval above thresholds; audit."]],
     adrs=[A("Final fare = quote unless material change", "I", "Trust in upfront pricing.", [("Always recalc", "Breaks promise"), ("Quote unless material change", "Chosen")], "Recalc if destination changed, rider-requested stops, or distance > quote × 1.25 due to rider.", "Predictability.", "Edge cases need policy.", "N/A")],
     qa=[Q("Correctness", "A toll road was used but the quote didn't include tolls. Who pays?", "If the quoted route had no tolls and the driver chose a toll road without rider request, the platform or driver absorbs it per policy and the rider pays the quote. If the rider requested the route or the quote stated 'tolls extra', tolls are added. Toll detection comes from matched segments crossing toll geofences.", "")],
     impl_order=["fare-calculator", "trip-reconciliation"], pkg="""com.atlas.fare
├── calc    (FinalFareService, MaterialChangePolicy)
├── adjust  (AdjustmentService)
└── recon   (TripReconciler)""",
     tests=[T("Idempotency", "TripCompleted ×3", "One fare"), T("Correctness", "Destination changed", "Recalc basis")],
     evo=[("I", "In-process after complete", "fares table", "Unique per trip", "Correctness"), ("E", "Async via queue", "—", "Retries", "Reliability"), ("E", "Kafka consumer", "—", "Idempotent", "Events"),
          ("U", "No change needed", "—", "—", "—"), ("E", "Streaming reconciliation", "—", "Alerts", "Scale"), ("E", "Regional tax/currency", "—", "—", "Global")],
     ideas={"now": ["Unique fare per trip"], "next": ["Toll detection"], "adv": ["Automated dispute resolution"], "rej": ["Editing fares in place"]})

sub(id="fare-calculator", comp="fare-finalization", name="Final Fare Calculator", phase="I", cat="Money · Computation",
    resp="Compute the single final fare for a completed trip from quote, timeline, matched distance, fees and policies.",
    inp="TripCompleted, quote, matched path, wait time, crossings", out="fare record, FareFinalized event", deps="Pricing calculator library, Location history/map matching, Geofences", cons="Payments, Receipts, Earnings", own="fares",
    problem="Turn messy real-world trip data into one correct, explainable number exactly once.", without="Double or wrong charges.",
    guar=["Exactly one fare per trip", "Breakdown sums to total", "Basis recorded (QUOTE or RECALC with reason)"], nong=["Collection"],
    usecase="Rider added a stop mid-trip, so material change → RECALC with actual 14.2 km / 38 min using pinned rate card + surge from quote → ₹389 vs quote ₹267.",
    derive="- Material change policy decides basis.\n- RECALC uses the same calculator with actuals and the quote's pinned rate card and surge.",
    conc="`INSERT INTO fares ... ON CONFLICT (trip_id) DO NOTHING` then read back.", consistency="Strong (single row).", idem="Unique per trip; replays return existing.", order="Consumes TripCompleted; ignores earlier events.",
    restart="Consumer offsets after insert; idempotent.", scale="One per trip; trivial CPU.", arch="Consumer → gather inputs (parallel) → `MaterialChangePolicy` → `FareCalculator` → insert + outbox `FareFinalized`.",
    modules=[["InputCollector", "Quote, matched distance, wait, crossings"], ["MaterialChangePolicy", "Quote vs recalc"], ["FinalFareService", "Compute + persist + event"]],
    d_arch=("""flowchart LR
  TC["TripCompleted"] --> IC["InputCollector"] --> MCP["MaterialChangePolicy"] --> CALC["FareCalculator (shared lib)"] --> DB[("fares + outbox")]""", "Pure computation inside an idempotent consumer."),
    d_seq=("""sequenceDiagram
  participant K as Kafka
  participant F as FinalFare
  participant DB
  K->>F: TripCompleted (maybe duplicate)
  F->>DB: SELECT fare WHERE trip
  alt exists
    F->>F: ack
  else
    F->>F: compute
    F->>DB: INSERT fare + outbox (ON CONFLICT DO NOTHING)
  end""", "Idempotent consumer."),
    nostate="A fare is immutable once written. Changes are adjustments.",
    d_flow=("""flowchart LR
  Q["quote ₹267"] --> P{"material change?"}
  P -->|no| F1["fare ₹267 + tolls/wait"]
  P -->|yes| R["recalc actuals"] --> F2["fare ₹389"]""", "Basis decision."),
    d_fail=("""flowchart TB
  M["matched path missing"] --> Q["use quote basis, flag for review"]""", "Fallback to the promise."),
    sql="""CREATE TABLE fare.fares (trip_id uuid PRIMARY KEY, amount_minor bigint NOT NULL CHECK (amount_minor >= 0), currency char(3) NOT NULL,
  basis text NOT NULL CHECK (basis IN ('QUOTE','RECALC')), reason text, breakdown jsonb NOT NULL, computed_at timestamptz NOT NULL);
CREATE TABLE fare.fare_adjustments (id uuid PRIMARY KEY, trip_id uuid NOT NULL REFERENCES fare.fares, amount_minor bigint NOT NULL,
  reason text NOT NULL, actor uuid NOT NULL, approved_by uuid, at timestamptz NOT NULL DEFAULT now());""",
    data="Retained 7 years.", api="""event FareFinalized{trip_id, rider_id, driver_id, amount_minor, currency, basis, breakdown[], quote_id}""",
    mech=[("Shared pure calculator", "Using Pricing's library with pinned inputs guarantees estimate and final use identical arithmetic.")],
    code="""@KafkaListener(topics = "trip-events")
public void on(TripCompleted e) {
    if (fares.exists(e.tripId())) return;
    var in = inputs.collect(e);
    var basis = policy.decide(in);
    var breakdown = calculator.calculate(in.rateCard(), basis == QUOTE ? in.quotedRoute() : in.actualRoute(), in.surge(), in.discounts());
    tx.run(() -> { if (fares.insertIfAbsent(e.tripId(), breakdown, basis)) outbox.add(FareFinalized.of(e, breakdown, basis)); });
}""", cx="O(1).",
    fail=[F("Duplicate event", "Exists", "None", "Skip", "One fare"), F("Pricing lib bug", "Recon mismatch", "Wrong fares", "Adjustments + fix", "Audited")],
    alts=[["Compute in Trip service", "Rejected", "Mixes concerns", "Never"]],
    adrs=[A("Material change policy", "I", "When to depart from quote.", [("Never", "Unfair to drivers"), ("Policy", "Chosen")], "Policy-driven.", "Fair.", "Policy edge cases.", "N/A")],
    qa=[Q("Product", "Should the rider be notified when the fare differs from the quote?", "Yes. The receipt shows quote vs final with the reason (stop added, destination changed), and a push explains differences > 10% before capture where regulations require consent.", "")],
    tests=[T("Idempotency", "Replay", "Single fare"), T("Property", "Breakdown sums", "Equal")],
    evo=["I: In-process", "E: Queue consumer", "E: Kafka consumer", "U: No change needed", "E: Toll detection", "E: Regional tax rules"],
    ideas={"now": ["Basis + reason"], "next": ["Pre-capture notification"], "adv": ["Automatic dispute handling"], "rej": ["Mutable fares"]})

sub(id="trip-reconciliation", comp="fare-finalization", name="Trip ↔ Payment ↔ Ledger Reconciliation", phase="II", cat="Consistency · Reconciliation",
    resp="Continuously verify that every completed trip has exactly one fare, one capture (or documented failure) and balanced ledger entries, and repair or escalate gaps.",
    inp="trips, fares, payments, ledger entries, PSP settlement files", out="reconciliation results, repair actions, alerts", deps="Trip, Fare, Payments, Ledger", cons="Finance, On-call", own="recon_runs, recon_breaks",
    problem="Asynchronous, multi-system money flows will diverge (lost events, bugs, PSP issues). Divergence must be found fast and fixed safely.", without="Silent revenue loss or double charges discovered months later.",
    guar=["Every completed trip checked within 24 h (Phase V: 15 min)", "Each break classified and owned", "Auto-repairs are idempotent and logged"], nong=["Preventing divergence (detection + repair only)"],
    usecase="A FareFinalized event was lost (consumer bug). Reconciliation finds trip T completed with a fare but no capture after 2 h, re-emits FareFinalized (idempotent at payments), and capture succeeds.",
    derive="- Compare sets keyed by trip_id across sources: anti-joins find missing items, and value comparisons find mismatches.\n- Repairs must be safe to re-run, so they reuse the same idempotent APIs.",
    conc="Single run per window (leader/lock); repairs idempotent.", consistency="Detects eventual consistency violations beyond a grace window (2 h).", idem="Re-running a window yields the same breaks; repairs no-op if fixed.", order="Windows processed by time; late data re-checked next run.",
    restart="Run ledger with windows.", scale="Phase II–IV SQL on replicas; Phase V streaming joins (Flink) with state TTL.", arch="Scheduled job per window: extract keys and amounts from each system (read replicas/lake), full outer join, classify breaks (MISSING_CAPTURE, AMOUNT_MISMATCH, DUPLICATE_CAPTURE, LEDGER_IMBALANCE), auto-repair safe classes, open tickets for others.",
    modules=[["Extractors", "Per system"], ["Matcher", "Outer join by trip_id"], ["Classifier", "Break types"], ["Repairer", "Safe idempotent repairs"], ["Escalator", "Tickets/alerts"]],
    d_arch=("""flowchart LR
  T[("trips/fares")] & P[("payments")] & L[("ledger")] & S[("PSP settlement")] --> EX["Extractors"] --> M["Matcher"] --> C["Classifier"]
  C --> R["Repairer"] --> API["idempotent APIs"]
  C --> E["Escalator"] --> TK["Finance tickets"]""", "Extract, match, classify, repair or escalate."),
    d_seq=("""sequenceDiagram
  participant J as ReconJob
  participant DB as Sources
  participant P as Payments
  J->>DB: extract window
  J->>J: join + classify
  J->>P: re-emit FareFinalized(trip T) for MISSING_CAPTURE
  P-->>J: captured (idempotent)
  J->>J: break resolved""", "Auto-repair."),
    d_state=("""stateDiagram-v2
  [*] --> Open
  Open --> AutoRepairing: safe class
  AutoRepairing --> Resolved
  AutoRepairing --> Escalated: repair failed
  Open --> Escalated: unsafe class
  Escalated --> Resolved: manual fix""", "Break lifecycle."),
    d_flow=("""flowchart LR
  A["trips completed"] --> J{"full outer join"}
  B["captures"] --> J
  C["ledger"] --> J
  J --> BR["breaks"]""", "Three-way match."),
    d_fail=("""flowchart TB
  R["repair causes harm?"] --> SAFE["only idempotent forward repairs automated; refunds/charges manual"]""", "Automation scope is limited by risk."),
    sql="""CREATE TABLE recon.breaks (id uuid PRIMARY KEY, window_start timestamptz, trip_id uuid, type text NOT NULL, details jsonb, state text NOT NULL,
  owner text, created_at timestamptz NOT NULL DEFAULT now(), resolved_at timestamptz, UNIQUE (window_start, trip_id, type));""",
    data="Breaks retained 7 years (audit).", api="""-- Matching query (Phase II)
SELECT t.id, f.amount_minor, p.captured_minor
FROM trip.trips t LEFT JOIN fare.fares f ON f.trip_id=t.id LEFT JOIN payments.captures p ON p.trip_id=t.id
WHERE t.state='COMPLETED' AND t.ended_at BETWEEN :from AND :to - interval '2 hours'
  AND (f.trip_id IS NULL OR p.trip_id IS NULL OR f.amount_minor + coalesce(adj,0) <> p.captured_minor);""",
    mech=[("Grace window", "Only flag items older than the expected propagation delay (2 h), which avoids false positives from in-flight events."), ("Idempotent repair", "Repairs call the same idempotent APIs as normal flow, so a repair racing with a late normal event is harmless.")],
    code="""for (Break b : classifier.classify(matcher.join(extract(window)))) {
    if (b.type().autoRepairable()) repairer.repair(b); else escalator.open(b);
}""", cx="O(trips in window).",
    fail=[F("Source unavailable", "Extract error", "Window skipped", "Retry; alert if > 2 windows", "Delayed detection")],
    alts=[["No recon", "Rejected", "Silent errors", "Never"], ["Only PSP settlement recon", "Insufficient", "Misses internal gaps", "Never"]],
    adrs=[A("Three-way recon from Phase II", "II", "Async flows begin.", [("Phase V only", "Too late"), ("Phase II", "Chosen")], "Daily recon.", "Early detection.", "Job maintenance.", "N/A")],
    qa=[Q("Distributed systems", "Is reconciliation a substitute for exactly-once processing?", "It's the complement. Idempotency and outbox make divergence rare. Reconciliation catches what slips through (bugs, operator error, third-party issues) and bounds its lifetime. Financial systems assume both.", "")],
    tests=[T("Integration", "Drop a FareFinalized", "Break found and repaired"), T("Unit", "Late capture within grace", "No break")],
    evo=["N: Phase I uses one transaction for trip→fare→capture intent plus a nightly SQL sanity report", "I: Daily SQL recon", "E: Hourly; PSP settlement files", "E: Recon service on replicas", "R: Streaming joins (Flink) 15-min SLA", "E: Per-region + cross-region currency"],
    ideas={"now": ["Daily recon"], "next": ["Settlement file recon"], "adv": ["Streaming recon"], "rej": ["Manual spreadsheets"]})
