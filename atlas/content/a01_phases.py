from model import phase, A, Q

TQ = ["What limitation exists in the previous phase?", "What workload exposes it?", "What new engineering problem appears?",
      "What new subcomponents become necessary?", "What previous design must change?", "What existing mechanisms remain?",
      "What new guarantees become possible?", "What new failure modes are introduced?", "What operational complexity is added?",
      "Why is it worth the complexity?"]


def tr(*answers):
    return list(zip(TQ, answers))


phase(id="I", title="Foundational correctness", focus="One city, a modular monolith on one PostgreSQL primary. The goal is a system whose business rules cannot be violated: one driver per trip, one capture per trip, money that balances. Every later phase builds on these invariants.",
      workload=[("Registered users", "≈1,000 riders, 100 drivers"), ("Daily active users", "≈300"), ("Peak concurrent", "≈60 app sessions, ≈40 drivers online"),
                ("Ride requests", "≈400/day; peak ≈0.05/s"), ("Location updates", "40 drivers × 1 per 4 s ≈ 10/s"), ("Read/write ratio", "≈10:1 (app polling dominates)"),
                ("Geography", "One city, one time zone"), ("Data growth", "<1 GB/month (breadcrumbs dominate)"), ("Latency", "p95 API < 300 ms; dispatch decision < 2 s"),
                ("Availability", "99.5% (≈3.6 h/month); single-AZ acceptable"), ("Failure tolerance", "Restart-and-resume; nightly backup + WAL archiving, RPO ≤ 5 min"),
                ("Team", "3–6 engineers, one on-call rotation")],
      hld=("""flowchart LR
  RA["Rider app"] -->|HTTPS/JSON| LB["Reverse proxy / TLS"]
  DA["Driver app"] -->|HTTPS/JSON + poll| LB
  LB --> MONO
  subgraph MONO["Spring Boot modular monolith"]
    ID["identity"] --- RP["rider"] --- DR["driver"]
    LOC["location"] --- DSP["dispatch"] --- TRIP["trip"]
    PR["pricing"] --- PAY["payments+ledger"] --- NOTIF["notifications"]
  end
  MONO -->|JDBC| PG[("PostgreSQL primary<br/>+ PostGIS")]
  MONO -->|HTTPS| EXT["PSP · SMS · Push · Maps"]
  PG -.->|WAL archive| OBJ[("Object storage backups")]""",
           "A single deployable unit with module boundaries enforced in code (separate packages, no cross-module table access, ArchUnit tests). One PostgreSQL holds every module's schema, so cross-module invariants (assign driver + create trip) can use one ACID transaction. External providers are called synchronously with timeouts. No queue exists yet: the few background tasks (offer timeouts, payment capture) run from a DB-backed scheduler table polled with `FOR UPDATE SKIP LOCKED`."),
      arch="**Why a monolith:** at 0.05 requests/s, network boundaries add failure modes without solving a load problem. Separate schemas per module (`identity.*`, `trip.*`, `ledger.*`) and in-process interfaces keep later extraction cheap.\n\n**Why PostgreSQL + PostGIS:** relational integrity (FKs, unique constraints, CHECK) enforces invariants such as one active trip per driver. PostGIS `ST_DWithin` on a GiST index answers 'drivers within 3 km' at this scale in milliseconds.\n\n**Correctness toolkit:** idempotency keys on every mutating API, optimistic locking (`version` column) on aggregates, a conditional `UPDATE ... WHERE status='AVAILABLE'` to claim a driver atomically, and a double-entry ledger from day one.",
      transition=tr("None: this is the starting point. Phase I exists to establish invariants, schemas and APIs that later phases keep.",
                    "Pilot traffic in one city.", "Translating business rules into enforceable data constraints and safe concurrent updates.",
                    "All Phase I subcomponents: OTP auth, token service, rider/driver profiles, availability state machine, PostGIS proximity search, fare estimator, request intake, dispatch offer manager, trip state machine, payment auth/capture, double-entry ledger, notification sender.",
                    "Nothing yet.", "N/A", "Atomic driver assignment, idempotent requests, balanced ledger, auditable state transitions.",
                    "Single points of failure (one DB, one app instance pair); synchronous provider calls block request threads.",
                    "Minimal: one deploy pipeline, one database, structured logs, basic metrics.",
                    "Correctness bugs in money and dispatch are the most expensive to fix later. Fixing them now, while the code is small, is the cheapest it will ever be."),
      mechs=[("ACID transactions", "Assignment + trip creation + driver state change must commit together."), ("Optimistic locking", "Low contention; detects lost updates on profiles and trips."),
             ("Conditional updates (compare-and-set in SQL)", "Claim a driver without a separate lock service."), ("Idempotency keys", "Mobile networks retry; double ride requests and double charges must be impossible."),
             ("DB-backed job table", "A handful of delayed jobs (offer timeout, capture) need durability, not a broker."), ("Structured logging + RED metrics", "Diagnose with one dashboard.")],
      adrs=[A("Modular monolith instead of microservices", "I", "Team of ≤6, traffic ≈0.05 req/s, invariants that span rider/driver/trip/payment.",
              [("Microservices from day one", "Rejected: distributed transactions and network failure modes before any load justifies them."), ("Modular monolith", "Chosen"), ("Unstructured monolith", "Rejected: extraction later becomes a rewrite.")],
              "Spring Boot modular monolith with one schema per module and ArchUnit-enforced boundaries.", "Cross-module invariants use local ACID transactions; boundaries are still explicit so Phase III/IV extraction follows existing seams.",
              "Single deployable means a bad deploy affects everything; mitigated with canary-by-instance and fast rollback.", "When a module needs a different scaling profile (location ingest at Phase III) or independent release cadence (Phase IV).")],
      qa=[Q("Architectural judgment", "Why not start with Kafka and microservices if we know we'll need them?",
            "Because the costs arrive immediately and the benefits only arrive later. Kafka needs partition planning, consumer-group operations, schema governance and outbox plumbing. Microservices turn the assignment invariant (driver AVAILABLE→ON_TRIP plus trip CREATED) into a saga with compensations. At 0.05 req/s none of these solve a real problem. The cheaper approach keeps clean module seams (schemas, interfaces, events published in-process), so extraction later is mechanical.",
            "Starting distributed gives a team practice with the tooling but slows down feature work and correctness work. It only makes sense if the team already runs that platform.",
            "Phase III introduces the broker when asynchronous cross-module workflows and multiple consumers appear. Phase IV extracts services where scaling or ownership differs.")],
      testing="Unit tests for every invariant; Testcontainers PostgreSQL integration tests; concurrency tests that assign one driver from 50 parallel threads; idempotency replay tests; ledger balance property tests.",
      done="All 29 end-to-end workflows run against one deployment; invariant tests pass under concurrency; restore from backup verified once.")

phase(id="II", title="Reliability and resilience", focus="Ten times the load and real customers paying: slow providers and transient faults must no longer cascade. Introduce asynchronous work, durable queues, retries with budgets, circuit breakers, bulkheads and rate limits.",
      workload=[("Registered users", "≈10,000 riders, 800 drivers"), ("DAU", "≈3,000"), ("Peak concurrent", "≈600 sessions, ≈300 drivers online"),
                ("Ride requests", "≈4,000/day; peak ≈0.5/s"), ("Location updates", "≈75/s"), ("Read/write", "≈15:1"), ("Geography", "1–2 cities"),
                ("Data growth", "≈10 GB/month"), ("Latency", "p95 < 250 ms; dispatch < 2 s"), ("Availability", "99.9% (≈43 min/month); multi-AZ DB failover"),
                ("Failure tolerance", "Survive loss of one app instance, one AZ for DB (sync standby), any single external provider"), ("Team", "8–15 engineers, two on-call rotations")],
      hld=("""flowchart LR
  APPS["Rider & driver apps"] -->|HTTPS| GW["Edge proxy<br/>rate limit · TLS"]
  GW --> M1["Monolith instance A"] & M2["Monolith instance B"]
  M1 & M2 -->|JDBC| PG[("PostgreSQL primary")]
  PG -->|sync replication| PGS[("Standby (other AZ)")]
  M1 & M2 -->|enqueue| Q[["RabbitMQ<br/>work queues + DLQ"]]
  Q --> WK["Worker pool<br/>(notifications, payments, docs)"]
  WK -->|circuit breaker| EXT["PSP A/B · SMS A/B · Push"]
  M1 & M2 -->|cache| R[("Redis<br/>sessions, rate limits, hot reads")]
  WK --> PG""",
           "Two stateless monolith instances behind an edge proxy. Slow or failure-prone work (notifications, document checks, payment capture retries) moves to RabbitMQ work queues with dedicated worker pools, so a slow SMS provider cannot tie up the request threads used for dispatch. Each external integration has a timeout, a retry budget, a circuit breaker and, where commercially available, a secondary provider. Redis takes rate-limit counters and cacheable reads. PostgreSQL gains a synchronous standby in a second AZ."),
      arch="The structure is still a monolith. What changes is how failure is handled. Every synchronous dependency gets a timeout budget derived from the caller's SLO. Retries use exponential backoff with jitter and a per-dependency retry budget, so retries cannot amplify an outage. Work queues get dead-letter queues, plus a `job` table that records business-visible progress, since queue messages alone are not an audit trail.",
      transition=tr("Synchronous calls to providers block request threads. One slow SMS vendor can exhaust the shared thread pool and stall dispatch. One app instance and one DB node are single points of failure.",
                    "≈0.5 req/s with bursts at concert/airport peaks; provider p99 latency spikes to 10 s.",
                    "Isolating failure: retries that don't amplify outages, work that survives crashes, fairness under bursts.",
                    "Job queue + DLQ, retry/backoff policy, circuit breakers, bulkheads, rate limiter, provider failover router, durable job tracker, Redis cache.",
                    "Notification sending, document verification calls and payment capture retries leave the request path. Offer timeouts move from polling to delayed messages.",
                    "Monolith, single primary DB, ACID assignment, idempotency keys, ledger.",
                    "Bounded latency under dependency failure; at-least-once background execution with deduplication; graceful degradation.",
                    "Duplicate deliveries, poison messages, retry storms, stale cache reads, queue backlog.",
                    "Broker operations, DLQ triage, breaker tuning, cache invalidation rules.",
                    "Paying customers notice a failed or stuck ride. Containing failures is cheaper than an incident for every provider wobble."),
      mechs=[("Work queues (RabbitMQ)", "Durable, acked delivery to competing workers; per-queue DLQ."), ("Retry with exponential backoff + jitter + budget", "Absorb transient faults without synchronized retry storms."),
             ("Circuit breakers (Resilience4j)", "Fail fast when a provider is down; free threads."), ("Bulkheads", "Separate thread pools/connection pools per dependency class."),
             ("Token-bucket rate limiting (Redis)", "Protect the core from abusive clients and bursts."), ("Provider failover", "Secondary SMS/PSP when the primary breaker opens."), ("Read-through cache", "Profiles, product catalog, rate cards.")],
      adrs=[A("RabbitMQ work queues before Kafka", "II", "Need durable delayed work with competing consumers and per-message ack; no multi-consumer event fan-out yet.",
              [("Kafka", "Rejected now: log semantics + partition-level ordering not needed; per-message retry/DLQ awkward."), ("RabbitMQ", "Chosen"), ("DB job table only", "Kept for scheduled jobs, rejected for high-volume notifications (polling load).")],
              "RabbitMQ quorum queues with DLX-based retry and a DB `job` table for business-visible job state.", "Matches the task-queue semantics; simple ops; quorum queues survive node loss.",
              "Second stateful system to operate; messages are not replayable after ack.", "When multiple independent consumers need the same facts or replay becomes a requirement (Phase III event bus).")],
      qa=[Q("Reliability", "A PSP goes down for 20 minutes during the evening peak. What does the rider experience?",
            "Authorization runs before dispatch, with a 2 s timeout and a breaker. While PSP-A's breaker is open, the payment router sends authorizations to PSP-B, which holds the same card tokens through a network-token vault. If both fail, policy decides: riders with good trust scores and a payment history get a *deferred authorization* (ride proceeds; capture retried later from the job queue), and others see 'payment temporarily unavailable'. Captures after trips are queued and retried with backoff for up to 72 h. The ledger records `capture_pending` so nothing is lost.",
            "Blocking all rides is safest financially but loses revenue and goodwill. Allowing every ride without authorization invites fraud spikes during outages.",
            "Phase III makes payment a saga with explicit compensations. Phase V adds risk-model-driven deferral decisions.")],
      testing="Fault injection (Toxiproxy) for provider latency and errors; breaker-open tests; DLQ redrive tests; duplicate delivery tests; AZ failover drill on the DB.",
      done="Any single provider outage degrades gracefully without request-thread exhaustion; DB failover completes with RPO=0 (sync standby) and RTO < 2 min.")

phase(id="III", title="Distributed workflows", focus="Multiple cities, more teams and many consumers of the same business facts. Facts are published as events through a transactional outbox, long-running processes become sagas, and every consumer is idempotent.",
      workload=[("Registered users", "≈100,000 riders, 6,000 drivers"), ("DAU", "≈30,000"), ("Peak concurrent", "≈5,000 sessions, ≈3,000 drivers online"),
                ("Ride requests", "≈40,000/day; peak ≈5/s"), ("Location updates", "≈750/s"), ("Read/write", "≈20:1"), ("Geography", "5–10 cities, one country"),
                ("Data growth", "≈100 GB/month"), ("Latency", "p95 < 200 ms; dispatch < 2 s; live tracking lag < 2 s"), ("Availability", "99.95%"),
                ("Failure tolerance", "Any consumer can fall hours behind and catch up; any workflow step can crash and resume"), ("Team", "20–40 engineers, 4–6 teams")],
      hld=("""flowchart LR
  APPS["Apps"] --> GW["API gateway"]
  GW --> CORE["Core monolith<br/>(identity, rider, driver, dispatch, trip, pricing)"]
  GW -->|WebSocket| TRK["Tracking service"]
  DA["Driver app"] -->|batched GPS| LOCS["Location ingest service"]
  LOCS --> RLOC[("Redis GEO / H3 sets")]
  CORE -->|tx + outbox| PG[("PostgreSQL")]
  PG -->|outbox relay / CDC| K[["Kafka event bus"]]
  K --> PAYS["Payment workflow workers"]
  K --> NOT["Notification workers"]
  K --> TRK
  K --> DWH["Lake ingestion"]
  K --> RISK["Risk scoring"]
  ORCH["Workflow engine<br/>(Temporal)"] --> PAYS
  CORE --> ORCH""",
           "The core stays a monolith, but the facts it produces (`TripCompleted`, `DriverAssigned`) are written to an outbox table in the same transaction as the state change, then relayed to Kafka. Payments, notifications, tracking, analytics and risk consume independently and idempotently. Location ingestion is the first module extracted, because its write rate and latency profile differ from everything else. Multi-step processes with timers and compensations (payment, onboarding, payouts) run on a workflow engine instead of ad-hoc job chains."),
      arch="The key shift is that operations that were one local transaction become a **local transaction plus asynchronous follow-ups**. Assignment stays one ACID transaction inside the core. Payment capture after completion becomes a saga step triggered by the `TripCompleted` event. Every consumer stores processed event IDs (inbox table) or uses naturally idempotent upserts. Kafka partitions by aggregate ID (`trip_id`) give per-trip ordering, and nothing relies on global ordering.",
      transition=tr("The monolith calls payments, notifications and analytics inline or through bespoke queue messages. Each new consumer means changing the producer, and there's no replay to rebuild a consumer's state.",
                    "6+ downstream consumers of trip events; analytics needs a complete event history; a payment bug requires reprocessing a day's trips.",
                    "Keeping state and published facts consistent without 2PC; idempotent, order-tolerant consumers; recoverable multi-step workflows.",
                    "Transactional outbox + relay, Kafka event bus, inbox/dedup store, saga orchestrator, schema registry, reconciliation jobs, distributed tracing, location ingest service, tracking service.",
                    "Inline post-trip processing becomes event-driven; job chains become workflows; RabbitMQ stays for simple task queues only.",
                    "ACID assignment in the core, ledger, idempotency keys, breakers and bulkheads.",
                    "Replayable history; independent consumer scaling; workflows that resume after crashes; end-to-end traces.",
                    "Consumer lag, poison events, schema incompatibility, duplicate side effects when dedup is missing, saga steps stuck in compensation.",
                    "Kafka cluster ops, schema governance, lag monitoring, workflow engine ops.",
                    "Without events, each new consumer is a change to the core and failures can't be replayed. That cost grows with every team added."),
      mechs=[("Transactional outbox", "Atomic 'state change + event' without distributed transactions."), ("Kafka (partitioned log)", "Multi-consumer fan-out, retention and replay, per-key ordering."),
             ("Idempotent consumers (inbox table)", "At-least-once delivery → effectively-once effects."), ("Sagas (orchestrated)", "Payment/onboarding/payout steps with compensations."),
             ("Schema registry (Avro/Protobuf, backward-compatible)", "Producers and consumers evolve independently."), ("Reconciliation jobs", "Detect divergence between owners (trips vs ledger vs PSP)."), ("OpenTelemetry tracing", "Follow a ride across sync and async hops.")],
      adrs=[A("Outbox relay over dual writes", "III", "State lives in PostgreSQL, consumers need events. Writing to Kafka after the DB commit can lose events on crash, and writing before can publish events that never happened.",
              [("Dual write", "Rejected: non-atomic."), ("Outbox + polling relay", "Chosen for Phase III"), ("CDC (Debezium) on outbox table", "Adopted in Phase IV for lower latency/load"), ("Kafka transactions only", "Rejected: DB is the source of truth, not Kafka.")],
              "Outbox table written in the business transaction; a relay publishes in commit order and marks rows sent.", "Guarantees every committed state change produces its event at least once.",
              "Adds relay lag (~100–500 ms) and a table to purge; consumers must deduplicate.", "When relay polling load or lag matters → Debezium CDC (Phase IV).")],
      qa=[Q("Distributed systems", "TripCompleted is consumed by payments and by driver earnings. Payments fails permanently for one trip. How is consistency restored?",
            "Each consumer owns its own outcome. Payments retries with backoff. After exhausting retries the event goes to the payments DLQ and the payment saga moves to `CAPTURE_FAILED`, which opens a collections workflow and a support case. Driver earnings are *not* rolled back, because the driver did the work. The ledger records a receivable from the rider instead. A nightly reconciliation compares completed trips against captured payments and against ledger entries, and flags anything missing in any of the three.",
            "A distributed transaction across payments and earnings would couple driver pay to card failures. The business explicitly does not want that.",
            "Phase V automates this reconciliation in streaming form with alert thresholds per city.")],
      testing="Consumer replay tests (process the same partition twice → same state); out-of-order delivery tests; outbox crash-between-commit-and-publish tests; saga compensation tests; trace propagation tests.",
      done="Any consumer can be wiped and rebuilt from retained events; reconciliation reports zero unexplained divergence for 7 days.")

phase(id="IV", title="Service isolation and horizontal scale", focus="A national footprint with many teams. Extract services where scaling profile, failure isolation or ownership differs. Introduce service discovery, mTLS between services, contracts, SLOs per service, partitioned data and read replicas.",
      workload=[("Registered users", "≈1M riders, 60K drivers"), ("DAU", "≈300K"), ("Peak concurrent", "≈50K sessions, ≈25K drivers online"),
                ("Ride requests", "≈400K/day; peak ≈50/s"), ("Location updates", "≈6,000/s"), ("Read/write", "≈30:1"), ("Geography", "≈50 cities, one country, one region (3 AZs)"),
                ("Data growth", "≈1 TB/month"), ("Latency", "p95 < 150 ms at gateway; dispatch p99 < 3 s"), ("Availability", "99.95–99.99% per tier"),
                ("Failure tolerance", "Loss of an AZ; loss of any non-critical service without blocking ride flow"), ("Team", "80–200 engineers, 15–25 teams")],
      hld=("""flowchart LR
  APPS["Apps"] --> EDGE["Edge LB + API gateway<br/>authN, rate limits"]
  EDGE --> BFF["Rider BFF / Driver BFF"]
  BFF -->|gRPC mTLS| IDS["Identity svc"] & RPS["Rider svc"] & DSS["Driver/Supply svc"] & PRS["Pricing svc"] & RQS["Request svc"] & TRS["Trip svc"]
  RQS -->|gRPC| DIS["Dispatch svc"]
  DIS -->|gRPC| GEO["Geo index svc"] & ETA["Routing/ETA svc"]
  TRS -->|events| K[["Kafka (CDC via Debezium)"]]
  K --> PAY["Payment svc"] --> LED["Ledger svc"]
  K --> EARN["Earnings svc"] & NOT["Notification svc"] & RISK["Risk svc"] & DP["Data platform"]
  MESH["Service mesh: discovery · mTLS · retries"] -.- IDS & DIS & TRS
  IDS --> IDB[("Identity DB")]
  TRS --> TDB[("Trip DB + read replicas")]
  LED --> LDB[("Ledger DB")]""",
           "Services own their databases; no cross-service table reads. Extraction follows measured needs. Dispatch and Geo scale with driver count and need low latency. Payment and Ledger need PCI and audit isolation. Identity is on every request. The BFF layer shapes responses per app. A service mesh (or client-side discovery with gRPC) provides discovery, mTLS identity and uniform telemetry. CDC (Debezium) replaces polling outbox relays."),
      arch="**Services are extracted only where at least one of these holds:** an independent scaling dimension (Geo index: driver count × update rate), a stricter isolation requirement (Payments: PCI; Ledger: audit), different availability or latency tiers (Dispatch), or a separate owning team with a separate release cadence. Rider profile and promotions stay as modules of larger services because nothing justifies a network hop for them.",
      transition=tr("One deployable couples releases of 20 teams; one connection pool and one DB primary carry every workload; a memory leak in reporting endpoints can take down dispatch.",
                    "≈6K location writes/s plus 50 req/s with heavy fan-out reads; deploy frequency of 50/day contended on one pipeline.",
                    "Independent scaling and failure isolation without losing the invariants proven in Phases I–III.",
                    "Service discovery, mTLS service identity, API contracts (protobuf + contract tests), BFFs, read replicas, partitioned trip/location tables, distributed cache, per-service SLOs, capacity planning.",
                    "Module calls become gRPC calls with deadlines; cross-module transactions become owned transactions + events; shared DB is split per service.",
                    "Outbox/CDC events, sagas, idempotent consumers, ledger, breakers.",
                    "Independent deploys; blast-radius containment; per-service scaling and SLOs.",
                    "Network partitions between services, version skew, cascading retries across hops, cache stampedes.",
                    "Many pipelines, many databases, on-call per service, mesh operations.",
                    "Team throughput and blast-radius containment. Shared-everything is now the dominant source of incidents."),
      mechs=[("gRPC with deadlines and propagated cancellation", "Bounded fan-out latency."), ("Service mesh / mTLS (SPIFFE IDs)", "Service-to-service authentication and policy."),
             ("Consumer-driven contract tests (Pact)", "Prevent breaking changes between independently deployed services."), ("Read replicas", "Offload history/receipt reads from primaries."),
             ("Table partitioning (by time / city)", "Bounded index sizes and cheap retention drops."), ("Distributed cache (Redis Cluster)", "Hot reads shared across instances.")],
      adrs=[A("Extract by scaling/isolation driver, not by noun", "IV", "Pressure to create one service per entity.",
              [("One service per entity", "Rejected: chatty calls, distributed joins, no benefit."), ("Extract by measured driver", "Chosen"), ("Stay monolith", "Rejected: release contention and blast radius are measured problems.")],
              "≈14 services aligned to scaling/isolation/ownership drivers; remaining modules stay inside them.", "Each extraction removes a measured bottleneck or risk.",
              "More network failure modes; requires platform investment (mesh, CI templates).", "Revisit per service yearly: merge services whose separation produces only chatty calls.")],
      qa=[Q("Architectural judgment", "Should Rider Profile be its own microservice at Phase IV?",
            "No. Its traffic is low-write and cache-friendly, it scales with request volume like the BFF, and it shares ownership with the rider-facing team. It lives in a 'Rider service' together with saved places, preferences and consent. A separate deployable would add a hop to every rider request and an on-call surface without a scaling or isolation benefit.",
            "Extract it if a different team takes ownership or if consent/privacy requirements need separate audit isolation.", "Phase VI may require regional deployment of rider data for residency, which is a placement change rather than a split.")],
      testing="Contract tests in CI per service pair; AZ evacuation game day; load tests at 3× peak per service; chaos tests on mesh retries (verify no retry amplification).",
      done="Each service has an SLO, dashboard, runbook, owner and capacity model; losing an AZ keeps ride flow within SLO.")

phase(id="V", title="High-volume distributed infrastructure", focus="Millions of daily riders across many cities. Hot keys, stream processing, sharding by city/H3 cell, tiered storage, advanced fraud and cost optimization. Each cell (city cluster) degrades independently.",
      workload=[("Registered users", "≈10M riders, 600K drivers"), ("DAU", "≈3M"), ("Peak concurrent", "≈500K sessions, ≈250K drivers online"),
                ("Ride requests", "≈4M/day; peak ≈500/s (event spikes ×5 in a single city)"), ("Location updates", "≈60,000/s steady, 150K/s peak"), ("Read/write", "≈50:1 on tracking"),
                ("Geography", "Hundreds of cities, several countries, one or two regions"), ("Data growth", "≈20 TB/month raw events"), ("Latency", "dispatch p99 < 2 s; location index freshness < 5 s"),
                ("Availability", "99.99% ride flow"), ("Failure tolerance", "City-cell isolation: one city's overload doesn't affect others"), ("Team", "500+ engineers")],
      hld=("""flowchart LR
  DA["Driver apps"] -->|gRPC stream / QUIC| LGW["Location gateways"]
  LGW -->|partition by h3 res-5| KL[["Kafka: driver-locations"]]
  KL --> FL["Flink: filter, map-match, aggregate"]
  FL --> GIX["Geo index shards<br/>(in-memory, by city/H3)"]
  FL --> SUP["Supply/demand per cell"] --> SRG["Surge service"]
  FL --> HIST[("Breadcrumbs: Cassandra/Bigtable")]
  REQ["Request svc"] --> DSP["Dispatch shard (per city)"]
  DSP --> GIX & ETA["ETA svc + ML"]
  DSP --> TRIPDB[("Trip DB sharded by city")]
  KAll[["Kafka business events"]] --> LAKE[("Lake: Iceberg on object storage")] --> WH["Warehouse"]
  KAll --> RISK["Real-time risk (Flink + feature store)"]""",
           "The location path becomes a stream: gateways write to Kafka partitioned by coarse H3 cell, Flink filters, map-matches and aggregates, and in-memory geo-index shards own sets of cities or cells. Dispatch runs per-city shards so a city's demand spike stays inside that city. Breadcrumbs go to a wide-column store with TTL. Surge is computed continuously per H3 cell from streaming supply/demand. The lake moves to a table format (Iceberg) that supports time travel for ML training."),
      arch="The dominant concerns are now hot keys (stadium cells, airport queues), write amplification (60K/s location writes) and cost (most breadcrumbs are never read). Answers: partition by geography with split hot cells, aggregate before storing, tier storage by access frequency, and run per-city dispatch shards with bulkheads.",
      transition=tr("Single Redis GEO set per city and single Kafka partition for a busy city saturate; trip DB primary write rate approaches limits; surge computed every minute in batch lags real demand.",
                    "60K–150K location updates/s; stadium egress creates 10K requests in one H3 cell in 10 minutes.",
                    "Hot-partition mitigation, stateful stream processing, sharded OLTP, cost-efficient retention.",
                    "Location gateways, Flink jobs, geo-index shards with cell splitting, sharded trip/dispatch, stream surge, tiered breadcrumb storage, real-time risk features.",
                    "Redis GEO index → custom sharded in-memory index fed by streams; batch surge → streaming surge; single trip DB → city-sharded.",
                    "Service boundaries, events, sagas, ledger invariants.",
                    "City-level fault isolation, sub-5 s freshness at 150K/s, linear scale-out.",
                    "Stream job state loss/rebalance, cell-split races, cross-shard queries, skew.",
                    "Stream platform ops, shard rebalancing, cost dashboards.",
                    "Without it, peak events in one city degrade every city, and infrastructure cost grows faster than revenue."),
      mechs=[("Stateful stream processing (Flink, checkpoints)", "Exactly-once *state* within the job; at-least-once sinks with idempotent writes."), ("Geo-sharding with hot-cell split", "Spread a stadium across shards."),
             ("City-sharded OLTP", "Bound each shard's write rate; isolate failures."), ("Tiered storage + TTL", "Pay for hot data only."), ("Request hedging for ETA", "Cut tail latency.")],
      adrs=[A("City cells as the unit of isolation", "V", "Demand spikes are geographic; dispatch and supply are local.",
              [("Global sharding by hash(trip_id)", "Rejected: cross-shard dispatch queries."), ("City/cell sharding", "Chosen"), ("No sharding, bigger machines", "Rejected: vertical ceiling and no isolation.")],
              "Dispatch, geo index and trip storage are sharded by city (large cities by sub-region).", "Matching only ever needs local data; failure stays local.",
              "Cross-city trips (airport across a border) need a home-city rule; uneven city sizes need sub-sharding.", "When cross-city products (intercity rides) become significant.")],
      qa=[Q("Performance", "A stadium releases 50,000 people. What breaks first, and how is it contained?",
            "The geo-index shard and the dispatch shard owning those H3 cells are hit first, along with surge for those cells. Containment works in layers. The gateway applies per-cell request admission (queue riders with a visible wait). The hot cell is pre-split to finer H3 resolution across shard replicas via event calendars. Batch matching every 2 s replaces greedy matching in that zone. Surge responds within one stream window (≈30 s). Other cities on other shards are unaffected by construction.",
            "Pure autoscaling reacts too slowly (minutes) and does not fix a single hot key.", "Phase VI adds cross-region capacity spill for national events.")],
      testing="Replay of recorded peak days at 3×; hot-cell synthetic load; Flink checkpoint-restore tests; shard-failover tests; cost regression tests.",
      done="A synthetic stadium event in one city does not move p99 dispatch latency in another city; streaming jobs recover from task-manager loss without duplicate business effects.")

phase(id="VI", title="Global architecture", focus="Multiple continents. Each region owns its cities' operational data and keeps serving if other regions fail. Global identity and configuration via control planes, data residency enforcement, regional failover and disaster recovery.",
      workload=[("Registered users", "≈100M+ riders, 5M drivers"), ("DAU", "≈30M"), ("Peak concurrent", "≈5M sessions, ≈2M drivers online"),
                ("Ride requests", "≈30M/day; peak ≈5,000/s globally"), ("Location updates", "≈500K/s"), ("Read/write", "≈50:1"), ("Geography", "Multiple continents, 5+ regions"),
                ("Data growth", "≈200 TB/month raw"), ("Latency", "in-region p99 dispatch < 2 s; no cross-ocean calls on the ride path"), ("Availability", "99.99% per region; region loss → failover of its cities within 15 min"),
                ("Failure tolerance", "Full region loss"), ("Team", "Thousands of engineers")],
      hld=("""flowchart TB
  DNS["Geo DNS / anycast"] --> R1 & R2 & R3
  subgraph R1["Region EU"]
    E1["Edge+gateway"] --> S1["Full ride stack<br/>(cities homed in EU)"] --> D1[("Regional DBs")]
  end
  subgraph R2["Region US"]
    E2["Edge+gateway"] --> S2["Full ride stack"] --> D2[("Regional DBs")]
  end
  subgraph R3["Region APAC"]
    E3["Edge+gateway"] --> S3["Full ride stack"] --> D3[("Regional DBs")]
  end
  CP["Global control plane<br/>city→region map · config · feature flags"] -.-> R1 & R2 & R3
  GID["Global identity<br/>(replicated user directory)"] -.-> R1 & R2 & R3
  D1 <-.->|async replication of non-resident data<br/>to designated DR region| D2
  D2 <-.-> D3""",
           "Each region runs a full copy of the ride stack and is authoritative for the cities homed in it, a 'cell' architecture at region granularity. A ride never needs a cross-region call on its critical path. Identity is global: a user account replicates to every region, but sessions are minted locally. A global control plane distributes the city→region map, configuration and feature flags, and regions keep running on the last known configuration if it fails. Each region asynchronously replicates to a designated DR region, except data that residency rules pin to its jurisdiction."),
      arch="**Ownership rule:** every mutable business record has exactly one home region at a time (the city's home region). Users who travel are served by the city's region. Their profile is read from the replicated global directory, and the trip is written in the city's region. **Failover** moves a city's home to its DR region, accepting up to the replication lag (RPO ≈ seconds) of in-flight trip state. In-flight trips are reconciled from driver/rider app local state and PSP records.",
      transition=tr("A single region is a single point of failure for a whole continent; cross-ocean latency (150–250 ms RTT) breaks dispatch SLOs; regulations require EU/India data to stay in-jurisdiction.",
                    "Launch in a new continent; regulator audit; a regional cloud outage.",
                    "Data ownership across regions, residency, global uniqueness (email/phone), failover without split brain.",
                    "Geo routing, regional data ownership registry, cross-region replication, regional failover orchestrator, global identity directory, residency policy enforcement, global control plane.",
                    "City→shard mapping becomes city→region→shard; identity uniqueness moves to a global directory; configuration becomes a control plane with regional caches.",
                    "Everything inside a region (Phases I–V) is unchanged; regions are copies of the Phase V stack.",
                    "Region-loss survival, in-jurisdiction storage, low latency everywhere.",
                    "Split brain during failover, replication lag data loss, inconsistent global config, residency violations through logs/analytics.",
                    "Multi-region deploys, DR drills, regulatory audits.",
                    "Required to operate legally and reliably on multiple continents."),
      mechs=[("Home-region ownership with fencing tokens", "Exactly one writer per city at a time, even during failover."), ("Async cross-region replication", "DR copies without synchronous cross-ocean latency."),
             ("Global uniqueness via a consensus-backed directory (Spanner/CockroachDB or reservation protocol)", "Phone/email unique worldwide."), ("Control plane with last-known-good caching", "Config outages don't stop regions.")],
      adrs=[A("Region-as-cell, no global synchronous writes on the ride path", "VI", "Cross-ocean RTT and regulatory isolation.",
              [("Global active-active database for everything", "Rejected: latency on every write, residency conflicts."), ("Region cells + global directory for identity only", "Chosen"), ("Fully independent regional stacks with separate accounts", "Rejected: travelling users need one account.")],
              "Regions own their cities; only identity uniqueness and configuration are global.", "Ride path stays in-region; global state is small and slow-changing.",
              "Cross-region features (global trip history) are eventually consistent; failover loses ≤ replication lag.", "If a product needs cross-region transactions (global wallet transfers), use a dedicated global ledger with consensus for that product only.")],
      qa=[Q("Global architecture", "A rider from London opens the app in New York. Which region serves them, and where is their data?",
            "Geo-DNS routes them to the US region. Authentication validates their token with keys from the global identity directory (public keys replicated). Their profile is read from the US replica of the global directory, which holds core identity plus portable preferences. Trips taken in New York are written and stored in the US region (city home), and a pointer and summary replicates to the user's home region so trip history shows everything. EU-resident data such as consent records and payment tokens tied to EU processing is not copied. The US region calls a tokenized payment method reference, valid globally through the PSP's network tokens.",
            "Routing everything to the user's home region makes every NYC dispatch call cross the Atlantic, which is unacceptable.", "Before Phase VI there is a single region and the question doesn't arise.")],
      testing="Region evacuation drills (quarterly), failover with fencing tests, residency scanning of every data sink, global config rollback drills.",
      done="Region evacuation completes within 15 min with no split-brain writes; residency scanner finds zero violations.")
