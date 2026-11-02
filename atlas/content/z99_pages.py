from model import page, A, Q

page("home", "Uber System Design Atlas", "top", [
    ("md", """A ground-up architecture knowledge base for an Uber-like ride-hailing platform. It covers **17 domains**, every component and subcomponent from the pilot city to multi-continent operation, and **six phases** of architectural evolution.

**How to use it**

- Pick a **phase** in the top bar. The sidebar dims items not yet introduced, and every evolution table highlights that phase.
- Browse **domains → components → subcomponents** in the sidebar. Every component chapter follows sections 5.1–5.15 of the specification, and every subcomponent chapter follows 6.1–6.16.
- Follow the **29 end-to-end workflows** to see components interact.
- Use **search** (press `/`) to find any concept, table, API or question.
- Tick the **completion tracker** on each chapter as you study, design, implement, test and operate it. Progress is stored only in your browser.
- The **Quality audit** page is computed at build time and lists both what is complete and the known deviations from the master prompt.

**Recommended path**

1. [[p:overview]] and [[p:principles]]
2. [[phase:I]] and the Phase I chapters ([[c:identity]], [[c:ride-request]], [[c:dispatch]], [[c:trip]], [[c:payments]], [[c:ledger]])
3. The [[p:roadmap]] for implementation order, then Phases II–VI in sequence."""),
    ("auto", "phase_counts"),
])

page("overview", "System overview", "top", [
    ("md", """**What the platform does:** connects riders who need a trip with nearby drivers, prices the trip upfront, dispatches exactly one driver, tracks the trip live, charges the rider, pays the driver, and keeps everyone safe. All of this has to keep working as the system grows from one city to many continents.

**The core loop**

1. Rider gets a quote, and Pricing stores and signs it.
2. Rider confirms. Ride Request creates an idempotent request, locks the quote and authorizes payment.
3. Dispatch finds candidates (Geo index + ETA), ranks them, and offers the trip exclusively to one driver at a time.
4. The driver accepts. The assignment commit claims the driver, creates the trip and marks the request assigned.
5. Trip executes (arrive, start, complete) while Tracking streams the car's position.
6. Fare finalization computes one final fare, Payments captures it, the Ledger records it, Earnings credits the driver, and Receipts are issued.

**The hardest invariants** (and where each is enforced)

- One driver per trip at a time: compare-and-set in [[s:availability-state]], plus a unique index in [[s:trip-state-machine]].
- One request per rider intent: [[s:request-intake]] idempotency keys and a partial unique index.
- One capture per trip: [[s:auth-capture]] attempt log, PSP idempotency keys, unique trip on intent.
- Books always balance: deferred trigger in [[s:double-entry-ledger]].
- Ineligible drivers never online: [[s:application-workflow]] snapshot and [[s:eligibility-gate]] guard."""),
    ("diagram", ("""flowchart LR
  R["Rider app"] --> EDGE["API gateway / BFF"]
  D["Driver app"] --> EDGE
  D -->|GPS stream| LOC["Location ingest"]
  EDGE --> ID["Identity"] & RP["Rider profile"] & PR["Pricing"] & RQ["Ride request"] & TR["Trip"]
  RQ --> DSP["Dispatch"]
  DSP --> GEO["Geo index"] & ETA["Routing/ETA"] & SUP["Driver supply"]
  LOC --> GEO & TRK["Tracking"]
  TR --> FARE["Fare finalization"] --> PAY["Payments"] --> LED["Ledger"]
  LED --> ERN["Earnings & payouts"]
  TR --> SAF["Safety"]
  PAY --> PSP(["PSPs"])
  ID --> SMS(["SMS"])""", "The system context at a glance: two apps, the core ride path, and the main external dependencies. The full generated dependency graph is on [[p:global-architecture]]."), "System context"),
])

page("principles", "Architecture principles", "top", [
    ("table", ["Principle", "What it means here", "Where you see it"], [
        ["Correctness before scale", "Phase I enforces every money and dispatch invariant with database constraints and conditional updates.", "[[s:availability-state]], [[s:double-entry-ledger]]"],
        ["One owner per business state", "Each state (driver status, trip state, fare, balance) has exactly one owning component. Others send commands or consume events.", "[[c:driver-supply]], [[c:trip]], [[c:ledger]]"],
        ["Idempotency everywhere", "Every mutating API and consumer is safe to repeat: idempotency keys, inbox tables, deterministic ids.", "[[s:request-intake]], [[s:event-bus]]"],
        ["Record intent before side effects", "External calls are preceded by a durable record (attempt log, outbox, idempotency reservation).", "[[s:auth-capture]], [[s:trip-event-log]]"],
        ["Pivot first, then forward-only", "In cross-service flows, perform the conflict-prone step first, so later steps only need retries, not compensations.", "[[s:assignment-commit]]"],
        ["Complexity must be earned", "No broker before tasks exist, no microservice without a scaling, isolation or ownership driver, no region before latency or law require it.", "Phase transition tables"],
        ["Degrade, don't fail", "Every dependency has a documented fallback: ETA → base, risk → checkpoint policy, maps → coordinates.", "Failure tables in every chapter"],
        ["Fail closed on safety and money, open on convenience", "Marketing without consent fails closed. Payouts fail closed. Previews fail open.", "[[s:consent-preferences]], [[s:payout-processing]], [[s:ride-options-preview]]"],
        ["Locality", "Rides are local: shard by city, own by region, never cross oceans on the ride path.", "[[c:dispatch]], [[c:global-regions]]"],
        ["Measure what users feel", "SLOs on journeys (request success, time to offer), not on CPU.", "[[s:slo-alerting]]"],
    ]),
])

page("global-architecture", "Global architecture", "top", [
    ("auto", "domain_map"),
    ("auto", "component_dependency_graph"),
    ("diagram", ("""flowchart LR
  APP["App (JWT)"] -->|Bearer access token| GW["Gateway: verify JWT locally"]
  GW -->|x-atlas-user (signed internal token)<br/>traceparent| S1["Service A"]
  S1 -->|gRPC + mTLS (SPIFFE id)<br/>x-atlas-user, deadline| S2["Service B"]
  S2 -->|Kafka headers: traceparent, event_id| C["Consumer"]
  S1 & S2 -->|ownership check with principal| DB[("Own DB")]""", "How identity and context propagate. The user's identity enters as a JWT, the gateway converts it into a short-lived signed internal token, services authenticate each other with mTLS, and trace context flows through HTTP, gRPC and Kafka. Authorization of resources always happens in the owning service ([[s:ownership-guard]])."), "Security and identity propagation"),
    ("diagram", ("""flowchart TB
  subgraph Region["Region (Phase VI cell)"]
    subgraph AZ1["AZ 1"]
      K1["K8s nodes"] --- DB1[("DB primary")]
    end
    subgraph AZ2["AZ 2"]
      K2["K8s nodes"] --- DB2[("DB sync standby")]
    end
    subgraph AZ3["AZ 3"]
      K3["K8s nodes"] --- KF[("Kafka brokers ×3 AZ")]
    end
  end
  CP["Global control plane"] -.-> Region
  Region -.->|async replication| DR["DR region"]""", "Deployment topology from Phase IV: services spread across three AZs, a synchronous standby in another AZ, Kafka replicated across AZs, and in Phase VI async replication to a residency-compatible DR region."), "Deployment topology"),
    ("md", "Each phase also has its own system HLD: [[phase:I]], [[phase:II]], [[phase:III]], [[phase:IV]], [[phase:V]], [[phase:VI]]."),
])

page("phase-evolution", "Phase evolution summary", "top", [
    ("table", ["Phase", "Scale", "Maturity", "Defining additions"], [
        ["[[phase:I]]", "0–1K users", "Foundational correctness", "Modular monolith, PostgreSQL+PostGIS, idempotency keys, CAS assignment, double-entry ledger, job table timers"],
        ["[[phase:II]]", "1K–10K", "Reliability", "RabbitMQ work queues + DLQ, breakers, bulkheads, rate limiting, provider failover, Redis, multi-AZ DB"],
        ["[[phase:III]]", "10K–100K", "Distributed workflows", "Outbox → Kafka, inbox consumers, Temporal sagas, location ingest & tracking services, tracing, reconciliation"],
        ["[[phase:IV]]", "100K–1M", "Service isolation", "~14 services, mesh mTLS, CDC, BFFs, feature store, ML serving, batch matching, self-hosted routing, canary delivery"],
        ["[[phase:V]]", "1M–10M", "High-volume infra", "City shards, Flink streams, H3-sharded geo index, Cassandra breadcrumbs, streaming surge, tail sampling, warm DR"],
        ["[[phase:VI]]", "10M+", "Global", "Region cells, city ownership with epochs, global identity directory, residency-aware replication, fenced failover"],
    ]),
    ("auto", "phase_counts"),
])

page("tech-decisions", "Technology decisions", "top", [
    ("table", ["Technology", "Problem it solves", "Introduced", "Alternatives", "Operational cost", "Failure behaviour", "Migration path"], [
        ["Java 21 + Spring Boot", "Productive, typed services with mature transactions/security", "I", "Go, Kotlin", "Low", "JVM tuning; GC pauses (fencing tokens handle)", "—"],
        ["PostgreSQL (+PostGIS)", "ACID invariants, constraints, geospatial in one store", "I", "MySQL, CockroachDB", "Low→medium", "Primary failover (sync standby from II)", "Shard by city (V); global directory (VI)"],
        ["Redis", "Rate limits, caches, Phase II–III geo, online features", "II", "Memcached, KeyDB", "Medium", "Data loss on failover acceptable for derived data", "Cluster mode (IV)"],
        ["RabbitMQ", "Task queues with ack, delay, DLQ", "II", "SQS, Kafka", "Medium", "Quorum queues survive node loss", "Keep for tasks"],
        ["Kafka (+Schema Registry, Debezium)", "Durable, replayable, partitioned event log", "III", "Pulsar, Kinesis", "High", "RF3/minISR2; consumer lag", "Multi-cluster (V), mirroring (VI)"],
        ["Temporal", "Durable workflows, timers, sagas", "III", "Step Functions, hand-rolled", "Medium", "History shards; workers stateless", "Per-region clusters"],
        ["Kubernetes + Envoy/mesh", "Scheduling, discovery, mTLS, traffic policy", "II/IV", "Nomad, VMs", "High", "Control-plane outages don't stop data plane", "Ambient mesh (V)"],
        ["Flink", "Stateful stream processing (location, surge, features)", "V", "Kafka Streams, Spark SS", "High", "Checkpoints; exactly-once state", "—"],
        ["Iceberg on object storage + Trino/warehouse", "Lake with ACID, deletes, time travel", "III", "Delta, Hudi", "Medium", "Snapshot isolation", "Regional lakes"],
        ["Cassandra/Bigtable", "High-rate append with TTL (breadcrumbs)", "V", "PG partitions, Timescale", "High", "RF3, tunable consistency", "—"],
        ["OpenTelemetry + Prometheus/Grafana/Tempo/Loki", "Correlated telemetry, SLOs", "II/III", "Vendor APM", "Medium", "Drop telemetry, never block", "Regional stacks"],
        ["Vault + KMS", "Secrets, dynamic creds, key management", "II/IV", "Cloud secrets manager", "Medium", "Cached leases until TTL", "Regional"],
        ["H3", "Hexagonal spatial indexing and sharding", "II", "S2, geohash", "Library", "N/A", "—"],
        ["MLflow + KServe/Triton", "Registry and serving", "IV", "SageMaker, Vertex", "Medium", "Fallback to non-ML policies", "—"],
    ]),
    ("md", "Each choice is justified in context in the ADRs of the component that introduces it. No technology appears before its phase's workload requires it (see each phase's *Transition* table)."),
])

page("roadmap", "Implementation roadmap & learning path", "top", [
    ("md", """**How to use this roadmap.** Implement phase by phase. Within a phase, follow the dependency graph: an arrow B → A means build B before A. For each subcomponent, its §6.15 assignment lists deliverables and acceptance tests. Reading a chapter is *not* completion. Use the per-chapter tracker and only tick *Tests passed* and *Failure scenarios validated* when you have run them.

**Per-component learning loop**

1. Prerequisites: glossary terms used in the chapter.
2. Learning objectives: answer the component's §5.11 questions.
3. HLD exercise: redraw §5.6 from memory.
4. LLD exercise: write the §6.6 schema and §6.7 interfaces for each subcomponent.
5. Implement the §6.15 assignments.
6. Testing assignment: the §6.14 tables.
7. Failure simulation: the §6.10 tables (Toxiproxy, kill -9, duplicate delivery).
8. Architecture review: defend each ADR against its rejected options.

**Suggested Phase I build order (a working pilot):** identity (OTP, tokens) → rider profile → driver onboarding (manual review) → driver supply (CAS states) → PostGIS proximity → pricing quotes → request intake → dispatch (candidates, offers, commit) → trip state machine + outbox → fare finalization → payments (auth/capture with attempt log) → ledger → receipts → notifications → observability basics."""),
    ("auto", "roadmap"),
])

page("data-architecture", "Data architecture", "cross", [
    ("md", """**Ownership rule:** each table belongs to exactly one component's schema, and no component reads another's tables (enforced by schema permissions from Phase I and by separate databases from Phase IV). Cross-component data flows through APIs or events."""),
    ("auto", "data_ownership"),
    ("table", ["Guarantee", "Meaning", "Where used"], [
        ["At-most-once", "May lose, never duplicates. Fire-and-forget.", "Telemetry export, optional analytics pings"],
        ["At-least-once delivery", "Never lost once acknowledged, may duplicate.", "Kafka, RabbitMQ, webhooks, outbox relay"],
        ["Effectively-once business outcome", "At-least-once delivery + idempotent effects (inbox, unique keys, conditional updates).", "Payments capture, fares, earnings, ledger postings"],
        ["Exactly-once (scoped)", "Only within a single system's transaction boundary (DB transaction; Flink state with checkpoints; Kafka→Kafka transactions).", "Ledger entry+postings; Flink windows"],
        ["Transactional atomicity", "All-or-nothing within one database.", "Assignment in Phase I–III; outbox writes"],
        ["Cross-service consistency", "Sagas, reconciliation, bounded inconsistency windows.", "[[s:assignment-commit]], [[s:trip-reconciliation]]"],
    ]),
    ("md", """**Lifecycle:** hot OLTP (PostgreSQL), then events (Kafka 7 days), then lake (Iceberg, years), with retention per domain policy (location: 90 days full, 3 years downsampled; financial: 7–10 years; OTP: 24 h). Erasure runs through [[s:erasure-orchestrator]], with crypto-shredding for backups ([[s:pii-protection]]). Backups: [[s:backup-restore]]. Partitioning: by time (events, breadcrumbs), by city (trips, dispatch from Phase V), by user hash (sessions)."""),
])

page("event-architecture", "Event architecture", "cross", [
    ("md", """**Conventions**

- Topics `<domain>.<aggregate>.events`, keyed by aggregate id (trip_id, driver_id), which gives per-aggregate ordering.
- Envelope: `{event_id, type, version, aggregate_id, occurred_at, producer, data}` with Avro schemas, backward-compatible evolution and a registry.
- Producers write via the transactional outbox ([[s:trip-event-log]]), relayed by polling (III) or Debezium CDC (IV).
- Consumers use the inbox library ([[s:event-bus]]), so effects are effectively-once. Retries go to retry topics, then dead-letter topics with tooling to redrive.
- Replay: Kafka retention 7 days plus lake raw tables allow rebuilding any projection.
- Reconciliation jobs ([[s:trip-reconciliation]], [[s:settlement-reconciliation]]) catch what slips through.

**Ordering:** never global. Per key within a partition, with per-aggregate version numbers so consumers can drop stale events."""),
    ("diagram", ("""flowchart LR
  TRIP["trip.trip.events"] --> PAY["payments"] & ERN["earnings"] & RCP["receipts"] & TRK["tracking"] & SAF["safety"] & LAKE["lake"]
  REQ["request.ride_request.events"] --> DSP["dispatch"] & LAKE
  DSP2["dispatch.offer.events"] --> LAKE & ML["features"]
  PAYE["payments.intent.events"] --> LED["ledger"] & RCP & LAKE
  SUPE["supply.driver.events"] --> GEO["geo index"] & SRG["surge"] & LAKE
  LOCT["location.driver_locations"] --> GEO & TRK & HIST["history"] & FL["Flink jobs"]
  IDE["identity.user.events"] --> RP["rider profile"] & RISK["risk"]""", "Main topics and their consumer groups."), "Event topology"),
    ("auto", "event_catalog"),
])

page("security-architecture", "Security architecture", "cross", [
    ("table", ["Layer", "Control", "Chapter"], [
        ["Edge", "TLS, WAF, rate limits, header hygiene", "[[c:api-gateway]]"],
        ["User authentication", "OTP + JWT (ES256) + rotating refresh with reuse detection", "[[c:identity]]"],
        ["Authorization", "RBAC/ABAC policies; ownership predicates (anti-BOLA)", "[[c:authz]]"],
        ["Service-to-service", "mTLS with SPIFFE ids; caller allow-lists", "[[s:service-identity]]"],
        ["Secrets", "Vault dynamic credentials; KMS-held signing keys", "[[s:discovery-secrets]]"],
        ["Data", "Field-level encryption, per-user keys, masking, residency egress policies", "[[s:pii-protection]]"],
        ["Payments", "Client-side tokenization (SAQ-A), PSP idempotency, webhook HMAC", "[[c:payments]]"],
        ["Fraud & abuse", "Risk checkpoints, device graph, rules with shadow mode", "[[c:risk-fraud]]"],
        ["Insider risk", "JIT roles, four-eyes approvals, immutable admin audit", "[[c:admin-policy]]"],
        ["Supply chain", "Signed images, SBOM, dependency scanning", "[[s:progressive-delivery]]"],
    ]),
    ("md", "**Threat model highlights:** account takeover (SIM swap, refresh theft, support social engineering), BOLA on trip and receipt endpoints, GPS spoofing, promo farming, card testing, payout redirection, insider misuse and residency violations. Each is handled in the chapter listed above, with failure tables describing detection and containment."),
])

page("observability-architecture", "Observability architecture", "cross", [
    ("md", "Observability is specified in [[c:observability]] ([[s:telemetry-pipeline]], [[s:slo-alerting]]). Every subcomponent's §6.10 failure table names its *detection* signal, and each one maps to a metric and alert owned by that subcomponent's team."),
    ("table", ["Journey SLI", "Target", "Measured at"], [
        ["Ride request accepted (non-5xx)", "99.95%", "Gateway, /v1/ride-requests"],
        ["Time to first offer", "p95 < 5 s", "Dispatch attempt events"],
        ["Trip transition success", "99.99%", "Trip service"],
        ["Live tracking freshness", "p95 < 2 s", "Tracking gateway (position age at send)"],
        ["Capture within 72 h", "99.5%", "Payments + reconciliation"],
        ["SOS to agent alert", "p99 < 5 s", "SOS service"],
        ["Event pipeline lag (business topics)", "p99 < 2 s", "Kafka consumer lag"],
    ]),
])
