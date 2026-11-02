from model import comp, sub, A, Q, F, T

# ======================================================================= API Gateway
comp(id="api-gateway", domain="platform", name="API Gateway & Edge", tag="Infrastructure · Edge", phase="I", kind="Infrastructure",
     biz="The single front door for apps: fast, secure and protected from abuse and overload.",
     eng="TLS termination, routing, authentication (JWT verification), rate limiting, request size limits, and observability at the edge, evolving to BFFs and multi-region anycast.",
     deploy="Nginx/Envoy reverse proxy (I); Envoy-based gateway with Redis rate limits (II); gateway + BFFs (IV); global edge (VI).", data_own="Routing config, rate-limit counters.",
     up=["identity", "service-runtime"], down=[], ext=["CDN / WAF", "DNS"],
     interfaces="Public HTTPS API; internal routing to services; JWKS fetch from Identity.",
     problem="Every request needs the same cross-cutting protections. Implementing them per service is inconsistent and leaves gaps.",
     fr=["TLS", "Routing by path/version", "JWT verification", "Rate limiting per user/IP/endpoint", "Request validation (size, schema for critical endpoints)", "Request ids/tracing headers"], nfr=["Added latency < 5 ms p99", "Availability ≥ the services behind it", "Rate-limit decisions < 1 ms"],
     workload="All API traffic: Phase V ≈ 100K req/s.", success="Consistent protection with negligible overhead.", failure="Gateway outage = total outage; abuse reaching services.",
     derive="Verification must be local (JWKS cache) because the gateway is on every request. Rate limiting must be shared across gateway instances, so a central counter store with local fallbacks. The gateway must be stateless and horizontally scalable.",
     owns=["Edge security", "Routing", "Rate limiting"], not_owns=["Authorization decisions (services)", "Business validation"], sync=["Everything"], **{"async": ["Config reloads", "JWKS refresh"]},
     boundary_why="Cross-cutting edge concerns are centralized. Resource-level authorization stays in services, which have the data.",
     hld=("""flowchart LR
  CL["Clients"] --> CDN["CDN/WAF"] --> LB["L4 LB"] --> GW["Gateway (Envoy)"]
  GW --> AF["JWT filter (JWKS cache)"] --> RL["Rate limiter"] --> RT["Router"]
  RT --> BFF["Rider/Driver BFFs"] --> SVCS["Services"]
  RL --> RC[("Redis counters")]""", "Layered edge."),
     seq=("""sequenceDiagram
  participant C as Client
  participant G as Gateway
  participant R as Redis
  participant S as Service
  C->>G: GET /v1/trips/77 (Bearer)
  G->>G: verify JWT (cached JWKS)
  G->>R: rate-limit check (user, endpoint)
  G->>S: forward + x-request-id + traceparent + x-atlas-user
  S-->>G: 200
  G-->>C: 200""", "Request path."),
     subdeps=[("edge-routing-auth", "rate-limiter")],
     flow="Requests pass WAF/CDN, the L4 LB, then the gateway filter chain (auth, rate limit, routing), then BFFs/services. Responses carry request ids.",
     data="Routes in config (GitOps); counters in Redis.",
     rel=[["Stateless", "Any instance serves any request."], ["Fallbacks", "Rate limiter fails open with local limits if Redis down."], ["Deploys", "Canary per instance group."]], sec=[["WAF", "Bot/DDoS protection at CDN."], ["Headers", "Strip client-supplied internal headers."]],
     adrs=[A("Envoy-based gateway", "II", "Extensibility + performance.", [("Nginx", "Phase I"), ("Envoy", "Chosen"), ("Managed API gateway", "Viable but cost/latency")], "Envoy.", "Filters, observability.", "Config complexity.", "N/A")],
     qa=[Q("Reliability", "The gateway is a single point of failure. How is it mitigated?", "There are many stateless instances across AZs behind L4 load balancers with health checks, and config changes are canaried. Dependencies (Redis, JWKS) have local fallbacks, and the gateway does nothing that requires a synchronous call to a single backend. Phase VI adds multiple regions behind anycast/geo-DNS.", "")],
     impl_order=["edge-routing-auth", "rate-limiter"], pkg="gateway/ (Envoy config, Lua/WASM filters), bff/ (Spring WebFlux)",
     tests=[T("Load", "100K rps", "p99 overhead < 5 ms"), T("Failure", "Redis down", "Local limits applied")],
     evo=[("I", "Nginx TLS proxy + app auth", "—", "—", "Simple"), ("R", "Envoy gateway, JWT filter, Redis limits", "Redis", "Fail-open local limits", "Abuse"), ("U", "No change needed", "—", "—", "—"),
          ("E", "BFFs, per-service routes", "—", "Canary", "Services"), ("E", "Edge rate limiting, adaptive concurrency", "—", "Load shedding", "Scale"), ("R", "Global anycast edge, regional gateways", "—", "Region failover", "Global")],
     ideas={"now": ["Request ids"], "next": ["Envoy"], "adv": ["Adaptive concurrency limits"], "rej": ["Auth only in services"]})

sub(id="edge-routing-auth", comp="api-gateway", name="Edge Routing, TLS & Token Verification", phase="I", cat="Infrastructure · Security",
    resp="Terminate TLS, verify access tokens locally, propagate identity and trace context, and route requests to the right backend version.",
    inp="client requests", out="routed requests with verified identity headers", deps="Identity JWKS, Service discovery", cons="All services", own="route config",
    problem="Authenticate every request cheaply and route reliably.", without="Every service re-implementing auth.",
    guar=["Unauthenticated requests to protected routes rejected", "Client-supplied internal headers stripped", "Trace context on every request"], nong=["Authorization"],
    usecase="Driver app v4.1 calls `/v1/trips/77/start`. The gateway verifies the JWT (kid k3), routes to the trip service, and adds `x-atlas-user` (signed) and `traceparent`.",
    derive="- JWKS cache with refresh on unknown kid.\n- Header hygiene prevents spoofing.\n- Route table versioned.",
    conc="Each request is handled independently by a stateless worker thread. Shared state (route table, JWKS) is swapped atomically on reload.", consistency="Route config versions roll out progressively.", idem="Routing has no side effects, so retries at the edge are allowed for idempotent methods only.", order="Requests are independent.",
    restart="Stateless; JWKS refetched.", scale="Horizontal by instance count behind L4 load balancers. CPU-bound on TLS and signature checks (≈ 20–40K req/s per node).", arch="Envoy listeners → jwt_authn filter (remote JWKS, cached) → header filters → router with clusters from discovery.",
    modules=[["TLS", "Certificates (ACME)"], ["JwtFilter", "Local verification"], ["HeaderHygiene", "Strip/inject"], ["Router", "Routes, retries, timeouts"]],
    d_arch=("""flowchart LR
  REQ["request"] --> TLS["TLS"] --> JWT["JwtFilter"] --> HH["HeaderHygiene"] --> RT["Router"] --> UP["upstream cluster"]
  JWT --> JWKS[("JWKS cache")]""", "Filter chain."),
    d_seq=("""sequenceDiagram
  participant G as Gateway
  participant I as Identity
  G->>G: token kid=k4 unknown
  G->>I: GET JWKS (rate-limited)
  I-->>G: keys incl. k4
  G->>G: verify ok""", "Key rotation handling."),
    nostate="Stateless request processing.",
    d_flow=("""flowchart LR
  JWT["JWT claims"] --> H["x-atlas-user (signed internal)"] --> SVC["service"]""", "Identity propagation."),
    d_fail=("""flowchart TB
  I["Identity down"] --> C["cached JWKS valid; stale-if-error 24h"]""", "Verification survives Identity outages."),
    sql="-- Envoy route config (YAML) in Git",
    data="Config only.", api="""route: { match: { prefix: "/v1/trips" }, route: { cluster: trip-svc, timeout: 2s, retry_policy: { retry_on: "connect-failure", num_retries: 1 } } }""",
    mech=[("Local JWT verification", "Signature check with cached public keys costs microseconds of CPU, with no network call."), ("Header hygiene", "Removing incoming `x-atlas-*` headers prevents clients from impersonating gateway-injected identity.")],
    code="""# envoy jwt_authn
providers: { atlas: { issuer: "https://id.atlas", remote_jwks: { http_uri: { uri: "https://id.atlas/.well-known/jwks.json", cluster: identity, timeout: 1s }, cache_duration: 3600s } } }""", cx="O(1).",
    fail=[F("JWKS rotation race", "Unknown kid", "401 spike", "Refetch on unknown kid; overlap keys", "None")],
    alts=[["Opaque token introspection", "Rejected", "Per-request call", "Never"]],
    adrs=[A("Signed internal identity header", "IV", "Services need user context.", [("Forward external JWT", "Leaks"), ("Signed internal header", "Chosen")], "Internal token.", "Decoupled.", "Key mgmt.", "N/A")],
    qa=[Q("Security", "Should the gateway retry failed requests?", "Only for idempotent methods (GET) and connection-level failures, once, within the deadline. POSTs are retried by clients with idempotency keys. Gateway retries of non-idempotent requests could double-charge.", "")],
    tests=[T("Security", "Client sends x-atlas-user", "Stripped"), T("Unit", "Expired token", "401")],
    evo=["I: Nginx TLS; app verifies JWT", "R: Envoy JWT filter", "U: No change needed", "E: Internal identity header", "E: HTTP/3", "E: Global edge"],
    ideas={"now": ["Request ids"], "next": ["Envoy"], "adv": ["mTLS to clients (drivers)"], "rej": ["Gateway POST retries"]})

sub(id="rate-limiter", comp="api-gateway", name="Distributed Rate Limiter", phase="II", cat="Reliability · Admission control",
    resp="Limit request rates per user, IP, device and endpoint across all gateway instances, protecting services from abuse and bursts.",
    inp="request keys, limit policies", out="allow/deny (429) with retry-after", deps="Redis", cons="Gateway, OTP auth, other services via library", own="limit policies, counters",
    problem="Fair, consistent limits across many stateless instances, fast enough for every request.", without="Scraping, OTP abuse, overload.",
    guar=["Limits approximately enforced (±small overshoot)", "Decision < 1 ms p99", "Fails open with local limits if Redis is unavailable"], nong=["Exactness under partitions"],
    usecase="A scraper hits `/v1/products` 50 req/s from one IP. The 10/s limit returns 429 with retry-after 1 s, and services are unaffected.",
    derive="- Token bucket: refill rate r, capacity b.\n- Atomic update in Redis via Lua (read tokens, refill by elapsed time, consume).\n- Local fallback buckets when Redis is down.",
    conc="Lua scripts execute atomically per key in Redis.", consistency="Per-key linearizable in Redis; approximate across failover.", idem="A retried request consumes another token. That is intended, because retries count toward the rate.", order="Uses Redis server time to avoid client clock skew.",
    restart="Counters in Redis; local buckets reset.", scale="Redis Cluster sharded by key; hot keys mitigated by local pre-aggregation.", arch="Envoy rate-limit service (or Lua filter) → Redis Cluster with token-bucket Lua. Policies from config.",
    modules=[["PolicyResolver", "Key → limit"], ["TokenBucket", "Lua script"], ["LocalFallback", "In-process buckets"]],
    d_arch=("""flowchart LR
  GW["gateway"] --> PR["PolicyResolver"] --> TB["TokenBucket (Lua)"] --> RC[("Redis Cluster")]
  TB -->|Redis down| LF["LocalFallback"]""", "Distributed with local fallback."),
    d_seq=("""sequenceDiagram
  participant G as Gateway
  participant R as Redis
  G->>R: EVALSHA bucket(key, rate 10, burst 20, cost 1)
  R-->>G: allowed=0, retry_after=0.4
  G-->>G: 429""", "Limit decision."),
    nostate="Counters are numeric state per key, not a lifecycle.",
    d_flow=("""flowchart LR
  T["tokens = min(b, tokens + r·Δt)"] --> C{"tokens ≥ cost?"} -->|yes| A["allow, tokens −= cost"]
  C -->|no| D["deny"]""", "Token bucket."),
    d_fail=("""flowchart TB
  R["Redis down"] --> L["local buckets at limit/instances"]""", "Fail open with bounds."),
    sql="""-- Lua token bucket
local tokens = tonumber(redis.call('HGET', KEYS[1], 't') or ARGV[2])
local ts = tonumber(redis.call('HGET', KEYS[1], 'ts') or ARGV[4])
local now = tonumber(ARGV[4]); tokens = math.min(tonumber(ARGV[2]), tokens + (now - ts) * tonumber(ARGV[1]))
local allowed = tokens >= tonumber(ARGV[3]); if allowed then tokens = tokens - tonumber(ARGV[3]) end
redis.call('HSET', KEYS[1], 't', tokens, 'ts', now); redis.call('PEXPIRE', KEYS[1], 60000)
return allowed and 1 or 0""",
    data="Ephemeral counters.", api="""429 Too Many Requests  Retry-After: 1  {code:"RATE_LIMITED"}""",
    mech=[("Token bucket", "Allows bursts up to capacity while enforcing an average rate, which suits mobile apps that send bursts after reconnecting."), ("Atomic Lua", "Redis runs a script without interleaving, so read-modify-write is atomic per key.")],
    code="""boolean allowed = redis.execute(bucketScript, List.of("rl:" + key), String.valueOf(rate), String.valueOf(burst), "1", String.valueOf(nowSeconds())) == 1L;""", cx="O(1).",
    fail=[F("Redis failover", "Errors", "Brief inaccuracy", "Local fallback", "Approximate"), F("Hot key (NAT IP)", "Latency", "Shard hot", "Local pre-limit + higher policy for known NATs", "None")],
    alts=[["Sliding window log", "Rejected", "Memory heavy", "Small scale exactness"], ["Fixed window", "Phase I", "Simple; burst at edges", "Low stakes"]],
    adrs=[A("Token bucket in Redis", "II", "Shared limits.", [("Per-instance only", "Inconsistent"), ("Redis token bucket", "Chosen")], "Redis.", "Consistent.", "Redis dependency.", "N/A")],
    qa=[Q("Design", "Rate limiting vs load shedding: what's the difference?", "Rate limiting enforces per-client fairness policies regardless of server health. Load shedding drops work when the *server* is overloaded, regardless of client. You need both: limits stop abusers, and shedding (adaptive concurrency, priority) protects the system from legitimate surges.", "")],
    tests=[T("Load", "Burst 2× limit", "~limit allowed"), T("Failure", "Redis down", "Local limits")],
    evo=["N: Phase I uses Nginx per-IP limit_req", "I: Redis token bucket", "U: No change needed", "E: Per-endpoint policies", "E: Edge pre-limits, adaptive", "E: Regional counters"],
    ideas={"now": ["Nginx limits"], "next": ["Redis buckets"], "adv": ["Adaptive limits by risk score"], "rej": ["Unlimited APIs"]})

# ======================================================================= Messaging Backbone
comp(id="messaging", domain="platform", name="Messaging Backbone (Queues & Event Bus)", tag="Infrastructure · Async", phase="II", kind="Infrastructure dependency",
     biz="Lets the platform do work later and tell many systems about events, without losing anything when parts fail.",
     eng="Work queues (RabbitMQ) for tasks with per-message ack, retries and DLQs; a partitioned event log (Kafka) for durable, replayable, multi-consumer business events; plus shared idempotent-consumer infrastructure.",
     deploy="DB job table (I); RabbitMQ (II); Kafka added (III); multi-cluster and tiered storage (V); regional clusters + mirroring (VI).", data_own="Topics, queues, consumer offsets, DLQs, inbox tables (library).",
     up=["service-runtime"], down=["trip", "payments", "notifications", "event-pipeline", "workflow"], ext=[],
     interfaces="Kafka topics with schema registry; RabbitMQ exchanges/queues; consumer library with inbox dedupe.",
     problem="Different async needs: tasks (one worker, retries, delays) vs facts (many consumers, replay, ordering per key). One tool forced onto both causes pain.",
     fr=["Durable task queues with delays and DLQ", "Event log with retention and replay", "Per-key ordering", "Consumer dedupe", "Schema governance"], nfr=["No acknowledged message loss", "Event end-to-end lag p99 < 2 s", "Throughput: 500K msg/s (V)"],
     workload="Phase V: location 150K/s, business events 20K/s, tasks 5K/s.", success="Async work reliable and observable.", failure="Lost events, poison-message stalls, unbounded lag.",
     derive="Tasks need individual ack/retry/delay, which is queue semantics. Facts need retention, replay and multiple consumers, which is log semantics. Both deliver at-least-once, so consumers need dedupe (inbox). Ordering is only needed per aggregate, so key partitioning.",
     owns=["Broker clusters", "Conventions", "Consumer library"], not_owns=["Message semantics (producers)"], sync=["Produce acks"], **{"async": ["Delivery"]},
     boundary_why="A platform team runs brokers and provides libraries so domain teams don't re-solve dedupe, retries and DLQs.",
     hld=("""flowchart LR
  SVC["Services"] -->|outbox/CDC| K[["Kafka event bus"]]
  K --> C1["consumers (inbox dedupe)"]
  SVC -->|tasks| RMQ[["RabbitMQ work queues"]] --> W["workers"]
  RMQ --> DLQ[["DLQs"]]
  K --> DLT[["dead-letter topics"]]""", "Two complementary systems."),
     seq=("""sequenceDiagram
  participant P as Producer
  participant K as Kafka
  participant C as Consumer
  participant DB as Consumer DB
  P->>K: TripCompleted (key trip)
  K->>C: deliver
  C->>DB: BEGIN; insert inbox(event_id); apply; COMMIT
  C->>K: commit offset""", "Idempotent consumption."),
     subdeps=[("job-queue", "event-bus")],
     flow="Events flow from outbox to Kafka to idempotent consumers. Tasks flow through RabbitMQ to workers with retry and DLQ.",
     data="Kafka topics `<domain>.<entity>.events` keyed by aggregate id; RabbitMQ queues per task type with DLX.",
     rel=[["Durability", "Kafka RF=3, min.insync=2, acks=all; RabbitMQ quorum queues."], ["Poison messages", "Retry topics/queues then DLQ with alert."]], sec=[["ACLs", "Per-topic produce/consume ACLs by service identity."], ["PII", "Event schemas classified."]],
     adrs=[A("Both RabbitMQ and Kafka", "III", "Different semantics.", [("Kafka only", "Task semantics awkward"), ("RabbitMQ only", "No replay"), ("Both", "Chosen")], "Both with clear usage rules.", "Right tool each.", "Two systems to run.", "Consolidate if one becomes negligible.")],
     qa=[Q("Distributed systems", "Queue vs event log: when do you use which?", "Use a queue when a unit of work should be done once by one of many workers, with individual retries, delays and priorities (send this SMS, capture this payment). Use a log when a fact should be available to many independent consumers, possibly later or replayed, with per-key order (TripCompleted). A queue forgets after ack, and a log remembers until retention.", "")],
     impl_order=["event-bus", "job-queue"], pkg="com.atlas.messaging (OutboxRelay, InboxConsumer, RetryPolicy, DlqHandler)",
     tests=[T("Durability", "Kill broker leader", "No acked loss"), T("Idempotency", "Redeliver batch", "No duplicate effects")],
     evo=[("I", "DB job table", "PG", "SKIP LOCKED", "Few tasks"), ("R", "RabbitMQ queues", "Quorum queues", "DLQ", "Reliability"), ("E", "Kafka event bus added", "Topics", "Inbox dedupe", "Fan-out"),
          ("E", "Kafka Connect/CDC, ACLs", "—", "Lag SLOs", "Services"), ("E", "Multi-cluster, tiered storage", "—", "Quotas", "Volume"), ("E", "Regional clusters + MirrorMaker for DR", "—", "Region isolation", "Global")],
     ideas={"now": ["Job table"], "next": ["RabbitMQ"], "adv": ["Pulsar for unified semantics"], "rej": ["Kafka for delayed tasks"]})

sub(id="job-queue", comp="messaging", name="Durable Job Queue, Retries & DLQ", phase="I", cat="Infrastructure · Task processing",
    resp="Run background tasks reliably: enqueue, deliver to one worker, retry with backoff, delay, and park poison messages in a dead-letter queue with tooling to redrive.",
    inp="task messages", out="executed tasks, DLQ entries", deps="PostgreSQL (I), RabbitMQ (II+)", cons="Notifications, Payments capture, Document checks, Timers", own="queues, job table",
    problem="Work must survive crashes, transient failures must be retried without storms, and bad messages must not block queues.", without="Lost or stuck work.",
    guar=["At-least-once execution", "Bounded retries with exponential backoff + jitter", "Poison messages isolated in DLQ", "Delayed execution supported"], nong=["Exactly-once (handlers idempotent)", "Global ordering"],
    usecase="Capture fails with PSP 503. Retries at 1 m, 5 m and 30 m succeed. A malformed message fails 5 times and moves to the DLQ with an alert, and the on-call fixes and redrives it.",
    derive="- Phase I: a `jobs` table with run_at and SKIP LOCKED claims is durable and simple.\n- Phase II: RabbitMQ with retry queues (TTL + DLX) for delays.\n- Retry policy per error class.",
    conc="Phase I: `SELECT ... WHERE run_at<=now() AND state='READY' FOR UPDATE SKIP LOCKED LIMIT n`. Phase II: competing consumers with prefetch.", consistency="At-least-once execution. In Phase I the enqueue is atomic with the business change (same transaction), and in Phase II it relies on an outbox or publisher confirms.", idem="Handlers must be idempotent (job id passed as idempotency key).", order="Not guaranteed. Use per-key serialization when needed (consistent-hash exchange).",
    restart="Phase I: claimed jobs with expired lease returned to READY. Phase II: unacked messages redelivered.", scale="Phase I ~hundreds jobs/s; Phase II thousands/s per queue; horizontal workers.",
    arch="Phase I: `jobs` table + scheduler threads. Phase II: RabbitMQ quorum queues, with retry tiers implemented as delay queues (TTL) dead-lettering back to the work queue, and a final DLQ.",
    modules=[["Enqueuer", "Transactional enqueue (job table) / publisher confirms"], ["Worker", "Claim, execute, ack"], ["RetryPolicy", "Backoff + jitter by error class"], ["Dlq", "Park + redrive tool"]],
    d_arch=("""flowchart LR
  P["producer"] --> Q[["work queue"]] --> W["workers"]
  W -->|transient fail| R1[["retry 1m (TTL)"]] -->|DLX| Q
  W -->|n failures| DLQ[["DLQ"]]
  OPS["redrive tool"] --> DLQ --> Q""", "Retry tiers via TTL queues."),
    d_seq=("""sequenceDiagram
  participant W as Worker
  participant Q as Queue
  participant R as Retry queue
  Q->>W: job (attempt 1)
  W-->>Q: nack (transient)
  Q->>R: dead-letter to retry-1m
  R->>Q: after TTL
  Q->>W: job (attempt 2)
  W-->>Q: ack""", "Retry."),
    d_state=("""stateDiagram-v2
  [*] --> READY
  READY --> RUNNING: claimed
  RUNNING --> DONE
  RUNNING --> READY: lease expired / retry scheduled
  RUNNING --> DEAD: max attempts""", "Job lifecycle (Phase I table)."),
    d_flow=("""flowchart LR
  J["job {id, type, payload, attempt}"] --> H["handler(idempotent by id)"]""", "Job envelope."),
    d_fail=("""flowchart TB
  P["poison message"] --> D["DLQ after 5 attempts"] --> A["alert + redrive after fix"]
  S["retry storm"] --> J["jittered backoff + circuit breaker on dependency"]""", "Isolation and storm control."),
    sql="""CREATE TABLE platform.jobs (id uuid PRIMARY KEY, type text NOT NULL, payload jsonb NOT NULL, run_at timestamptz NOT NULL, state text NOT NULL DEFAULT 'READY',
  attempts int NOT NULL DEFAULT 0, max_attempts int NOT NULL DEFAULT 5, locked_until timestamptz, last_error text);
CREATE INDEX jobs_ready ON platform.jobs(run_at) WHERE state = 'READY';""",
    data="Done jobs purged after 7 days; DEAD retained for investigation.", api="""void enqueue(String type, Object payload, Instant runAt)   // inside caller's transaction (Phase I)
@JobHandler("capture-payment") void handle(CaptureJob j)""",
    mech=[("SKIP LOCKED", "Rows locked by another transaction are skipped instead of waited on, so many workers can claim disjoint jobs from one table without contention."), ("Exponential backoff with full jitter", "delay = random(0, base·2^attempt) spreads retries and prevents synchronized storms.")],
    code="""@Transactional
public List<Job> claim(int n) { return jdbc.query(\"\"\"
  UPDATE platform.jobs SET state='RUNNING', locked_until=now()+interval '5 minutes', attempts=attempts+1
  WHERE id IN (SELECT id FROM platform.jobs WHERE state='READY' AND run_at<=now() ORDER BY run_at FOR UPDATE SKIP LOCKED LIMIT ?)
  RETURNING *\"\"\", jobMapper, n); }""", cx="O(log n) per claim.",
    fail=[F("Worker crash", "Lease expiry/unacked", "Delay", "Redelivery", "Handler idempotency"), F("Poison", "Attempts", "Isolated", "DLQ", "None")],
    alts=[["SQS", "Viable", "Managed", "Cloud-native"], ["Kafka for tasks", "Rejected", "No per-message delay/ack", "Never"]],
    adrs=[A("Job table first, broker later", "I", "Few jobs.", [("Broker in Phase I", "Ops overhead"), ("Job table", "Chosen")], "Table.", "Transactional enqueue.", "Polling load.", "Phase II when > ~200 jobs/s or many types.")],
    qa=[Q("Correctness", "Why is enqueueing into a job table inside the business transaction valuable?", "It's an outbox: the job exists if and only if the business change committed. With a separate broker in Phase II you need an outbox or publisher-confirm pattern to keep that guarantee.", "")],
    tests=[T("Concurrency", "10 workers, 10K jobs", "Each executed ≥ 1, effects once"), T("Failure", "Poison message", "DLQ after max attempts")],
    evo=["I: Job table", "R: RabbitMQ with retry tiers + DLQ", "E: Outbox → RabbitMQ publisher", "E: Per-team vhosts, quotas", "E: Autoscaled workers by lag", "E: Regional brokers"],
    ideas={"now": ["SKIP LOCKED"], "next": ["RabbitMQ"], "adv": ["Workflow engine for multi-step jobs"], "rej": ["In-memory queues"]})

sub(id="event-bus", comp="messaging", name="Event Bus (Kafka) & Idempotent Consumers", phase="III", cat="Infrastructure · Event streaming",
    resp="Provide durable, partitioned, replayable event streams with schema governance, plus a consumer library guaranteeing effectively-once processing via inbox dedupe.",
    inp="events from outbox/CDC", out="ordered per-key streams; consumer offsets", deps="Kafka, Schema registry", cons="All event consumers", own="topics, consumer library",
    problem="Many consumers need the same facts with per-aggregate order, retries, replay and no duplicate effects.", without="Point-to-point coupling and duplicate side effects.",
    guar=["Acked events durable (RF 3, min ISR 2)", "Per-key order within a partition", "Consumers apply each event_id at most once (inbox)"], nong=["Global order", "Exactly-once delivery across systems"],
    usecase="TripCompleted for trip 77 is consumed by payments, earnings, receipts and analytics. Payments crashes after applying but before committing the offset, gets redelivery, finds the inbox hit and skips.",
    derive="- Partition key = aggregate id gives per-aggregate ordering.\n- Inbox table in the consumer's DB, written in the same transaction as the effect, gives effectively-once.\n- Retry topics for transient failures avoid blocking partitions.",
    conc="One consumer per partition per group; parallelism = partitions.", consistency="Consumers eventually consistent; effects atomic with inbox insert.", idem="Inbox(event_id) primary key.", order="Per partition. Consumers detect gaps via per-aggregate version when strictness is needed.",
    restart="Committed offsets; reprocessing after crash deduped by inbox.", scale="Partitions sized for peak (≈ 5–10K msgs/s per partition), consumer groups scale to partitions.",
    arch="Topics per domain stream; producer via Debezium outbox router (Phase IV). Consumer library: poll → for each event → tx { inbox insert; handler } → commit offsets after batch. Failures → retry topic with delay → DLT.",
    modules=[["TopicConventions", "Naming, keys, retention"], ["InboxConsumer", "Dedupe + tx"], ["RetryTopics", "Non-blocking retries"], ["DLT", "Dead-letter topics + tooling"]],
    d_arch=("""flowchart LR
  OB["outbox/CDC"] --> T[["topic (key=aggregate)"]] --> IC["InboxConsumer"] --> DB[("inbox + state")]
  IC -->|fail| RT[["retry topic (5m)"]] --> IC
  RT -->|max| DLT[["DLT"]]""", "Consumer library internals."),
    d_seq=("""sequenceDiagram
  participant K as Kafka
  participant C as Consumer
  participant DB
  K->>C: batch offsets 100-150
  loop each event
    C->>DB: BEGIN; INSERT inbox(event_id) ON CONFLICT DO NOTHING
    alt inserted
      C->>DB: apply effect
    end
    C->>DB: COMMIT
  end
  C->>K: commit offset 151""", "Effectively-once processing."),
    nostate="Streams and offsets, with no entity lifecycle.",
    d_flow=("""flowchart LR
  E["event {event_id, key, version}"] --> P["partition hash(key)"] --> C["consumer"] --> I["inbox"]""", "Keying."),
    d_fail=("""flowchart TB
  CR["consumer crash after apply"] --> RD["redelivery"] --> IN["inbox hit → skip"]
  RB["rebalance"] --> R["partitions reassigned; same dedupe"]""", "Crash and rebalance safety."),
    sql="""CREATE TABLE <consumer_schema>.inbox (event_id uuid PRIMARY KEY, topic text NOT NULL, processed_at timestamptz NOT NULL DEFAULT now());
-- purge after max replay window (e.g. 14 days)""",
    data="Topic retention 7 days (business) / compacted (latest-state topics); inbox 14 days.", api="""@EventHandler(topic="trip.events", type="TripCompleted") void on(TripCompleted e)  // wrapped in inbox tx by the library""",
    mech=[("Effectively-once = at-least-once + idempotent effects", "Kafka redelivers on failure. The inbox makes the *effect* happen once, because it's committed atomically with the effect in the consumer's own DB."), ("Non-blocking retry topics", "Failing events move to a delayed retry topic so the partition keeps flowing. Use this only where per-key order isn't required for that consumer."),
         ("Partition-key ordering", "All events for a trip hash to one partition, so consumers see them in production order.")],
    code="""@Transactional
public void process(ConsumerRecord<String, Envelope> r) {
    if (inbox.insertIfAbsent(r.value().eventId(), r.topic())) handlers.dispatch(r.value());
}""", cx="O(1) per event.",
    fail=[F("Poison event", "Handler exception × N", "Partition stall avoided", "Retry topic → DLT", "Skipped event tracked"), F("Consumer lag", "Lag metric", "Stale views", "Scale consumers ≤ partitions", "Eventual")],
    alts=[["Kafka transactions (EOS)", "Partial", "Exactly-once only Kafka→Kafka", "Stream processing"], ["Idempotent upserts without inbox", "Viable", "Natural idempotency", "Last-write-wins projections"]],
    adrs=[A("Inbox in consumer DB", "III", "Effectively-once.", [("Rely on Kafka EOS", "Doesn't cover DB effects"), ("Inbox", "Chosen")], "Inbox.", "Simple, robust.", "Extra write per event.", "N/A")],
    qa=[Q("Distributed systems", "Is 'exactly-once' processing possible?", "Exactly-once *delivery* across a network is impossible in general. What we achieve is effectively-once *effects*: at-least-once delivery plus idempotent processing (inbox, conditional updates, unique constraints). Kafka's EOS gives exactly-once within Kafka read-process-write pipelines, not for side effects in external DBs or APIs.", "")],
    tests=[T("Failure", "Kill consumer mid-batch", "No duplicate effects"), T("Ordering", "Per-key", "In order")],
    evo=["N: Phase I uses in-process events + outbox table", "N: RabbitMQ for tasks only", "I: Kafka + inbox library", "E: CDC producers, ACLs, schema registry enforcement", "E: Tiered storage, multi-cluster", "E: Regional clusters + mirroring"],
    ideas={"now": ["n/a"], "next": ["Inbox library"], "adv": ["Streams with EOS for derived topics"], "rej": ["Assuming exactly-once"]})

# ======================================================================= Workflow & Scheduling
comp(id="workflow", domain="platform", name="Workflow Orchestration & Scheduling", tag="Platform · Durable execution", phase="III", kind="Platform capability",
     biz="Makes long multi-step business processes (driver onboarding, payment collection, payouts) finish correctly even across crashes, timeouts and days of waiting.",
     eng="A durable execution engine (Temporal) for sagas with timers, retries and compensations, plus a distributed scheduler for cron-like jobs.",
     deploy="Job table timers (I); delayed messages (II); Temporal cluster + scheduler (III); per-region clusters (VI).", data_own="Workflow histories, schedules.",
     up=["messaging", "service-runtime"], down=["driver-onboarding", "payments", "driver-earnings", "account-recovery"], ext=[],
     interfaces="Workflow SDK (Java), `startWorkflow`, `signal`, `query`; schedules API.",
     problem="Ad-hoc chains of queues and status columns for multi-step processes become impossible to reason about, and timers and compensations get lost.",
     fr=["Durable workflows with steps, timers, signals", "Retries per activity", "Compensations (sagas)", "Visibility (state of each instance)", "Cron schedules with single execution"], nfr=["No lost timers", "Workflow state survives worker and cluster restarts", "Thousands of concurrent workflows"],
     workload="Phase V: ~100K open workflows (onboarding, collections).", success="Processes complete or compensate predictably.", failure="Stuck processes, double side effects.",
     derive="Durable execution = persist an event history of each decision and replay deterministic workflow code to rebuild state. Activities (side effects) are retried with idempotency keys. Timers are persisted events.",
     owns=["Engine", "Scheduler"], not_owns=["Business logic in workflows (domain teams)"], sync=["Start/signal/query"], **{"async": ["Execution"]},
     boundary_why="Durable execution is generic infrastructure. Domains write workflows as code against it.",
     hld=("""flowchart LR
  SVC["Domain service"] -->|start/signal| TS["Temporal server"]
  TS --> HIST[("history store")]
  W["Workers (domain code)"] -->|poll tasks| TS
  W --> ACT["Activities: external calls (idempotent)"]
  SCH["Scheduler"] --> TS""", "Engine persists history. Workers run workflow and activity code."),
     seq=("""sequenceDiagram
  participant S as Service
  participant T as Temporal
  participant W as Worker
  S->>T: start CollectPayment(trip 77)
  T->>W: workflow task
  W->>T: schedule activity capture
  T->>W: activity task
  W-->>T: failed (decline)
  W->>T: timer 6h
  T->>W: timer fired → retry""", "Saga with timers."),
     subdeps=[("saga-orchestrator", "durable-timers")],
     flow="Services start workflows with business ids (idempotent). Workers execute deterministic workflow code, activities perform side effects with idempotency keys, and timers and signals drive waits.",
     data="Temporal persistence (Cassandra/PostgreSQL); visibility in Elasticsearch.",
     rel=[["Determinism", "Workflow code must be deterministic (no direct I/O, time via engine)."], ["Versioning", "Workflow versioning APIs for code changes with running instances."]], sec=[["Namespaces", "Per-domain namespaces with mTLS."]],
     adrs=[A("Temporal for durable workflows", "III", "Many long-running processes.", [("Hand-rolled state machines + queues", "Error-prone"), ("Step Functions", "Cloud lock-in"), ("Temporal", "Chosen")], "Temporal.", "Code-first sagas.", "Cluster ops, determinism discipline.", "N/A")],
     qa=[Q("Distributed systems", "Saga vs distributed transaction?", "A distributed transaction (2PC) locks resources across participants until a coordinator commits, which blocks on failures and is unsupported by external APIs. A saga runs local transactions step by step and, on failure, runs compensating actions for completed steps. It gives up isolation (intermediate states are visible) for availability. Ride payment collection, onboarding and payouts are sagas.", "")],
     impl_order=["durable-timers", "saga-orchestrator"], pkg="com.atlas.workflows (OnboardingWorkflow, CollectPaymentWorkflow, PayoutWorkflow, activities)",
     tests=[T("Recovery", "Kill workers mid-workflow", "Resume from history"), T("Determinism", "Replay tests with recorded histories", "No nondeterminism errors")],
     evo=[("N", "Job-table timers in Phase I", "—", "—", "Few processes"), ("N", "Delayed messages", "—", "—", "—"), ("I", "Temporal + scheduler", "History store", "Retries, timers", "Long workflows"),
          ("E", "Namespaces per domain", "—", "SLOs", "Teams"), ("E", "Scaled history shards", "—", "—", "Volume"), ("E", "Per-region clusters", "—", "Region-local workflows", "Global")],
     ideas={"now": ["Job table"], "next": ["Temporal"], "adv": ["Workflow-driven ops runbooks"], "rej": ["Status-column state machines across services"]})

sub(id="durable-timers", comp="workflow", name="Durable Timers & Distributed Scheduler", phase="I", cat="Platform · Time",
    resp="Fire business timers (offer expiry, no-show, auth expiry, document expiry) and cron jobs exactly when due, once, despite restarts and multiple instances.",
    inp="timer registrations, cron schedules", out="timer firings (callbacks/messages)", deps="DB (I), Broker delayed messages (II), Temporal (III+)", cons="Dispatch offers, Pickup, Payments, Onboarding, Retention jobs", own="timers, schedules",
    problem="Time-based logic must survive crashes and must not run twice concurrently (cron on N instances).", without="Missed expiries; duplicate batch runs.",
    guar=["Every timer fires at least once after due time", "Handlers idempotent; duplicate firings harmless", "Cron jobs: at most one active run (lease)"], nong=["Sub-second precision"],
    usecase="Payout batch cron at Monday 02:00. Three instances race, one acquires the lease, others skip. The holder crashes at 50%, the lease expires, and another instance resumes from the batch ledger.",
    derive="- Timers are rows/messages with due times, claimed with SKIP LOCKED.\n- Cron uses leader leases (row with lease_until) or a Temporal schedule.\n- Handlers check business state (timer may be obsolete).",
    conc="Claims via SKIP LOCKED; leases via conditional update with fencing token.", consistency="At-least-once firing.", idem="Timer id → handler idempotency.", order="Timers fire in due order approximately; handlers must not depend on relative order.",
    restart="Durable rows; overdue timers fire on recovery.", scale="Phase V: hierarchical timing wheels in shard-local memory backed by log for offer timers (very high rate).",
    arch="Phase I: `timers(id, due_at, kind, payload, state)` polled each second. Cron via `leases(name, holder, lease_until, token)`. Phase III: Temporal timers and schedules. Phase V: in-memory timing wheels for dispatch offers within shards.",
    modules=[["TimerStore", "Persist, claim"], ["Poller", "Due scan"], ["LeaseManager", "Cron single-runner with fencing"], ["TimingWheel (P5)", "In-memory high-rate timers"]],
    d_arch=("""flowchart LR
  REG["register timer"] --> TS[("timers")] --> PO["Poller (SKIP LOCKED)"] --> H["handler"]
  CRON["cron tick"] --> LM["LeaseManager"] --> JOB["job (fencing token)"]""", "Timers and cron."),
    d_seq=("""sequenceDiagram
  participant A as Instance A
  participant B as Instance B
  participant DB
  A->>DB: UPDATE leases SET holder=A, token=token+1, until=now()+60s WHERE name=payout AND until<now()
  B->>DB: same
  DB-->>A: 1 row (token 42)
  DB-->>B: 0 rows
  A->>A: run with token 42 (renew every 20s)""", "Lease acquisition."),
    d_state=("""stateDiagram-v2
  [*] --> SCHEDULED
  SCHEDULED --> FIRING: claimed
  FIRING --> DONE
  FIRING --> SCHEDULED: lease expired (crash)
  SCHEDULED --> CANCELLED""", "Timer lifecycle."),
    d_flow=("""flowchart LR
  T["timer {due_at, kind, payload}"] --> F["fire"] --> H["handler checks business state"]""", "Firing."),
    d_fail=("""flowchart TB
  P["poller down"] --> O["overdue timers fire on recovery"]
  Z["zombie cron holder after lease loss"] --> FT["fencing token rejected by downstream writes"]""", "Fencing prevents zombies."),
    sql="""CREATE TABLE platform.timers (id uuid PRIMARY KEY, kind text NOT NULL, due_at timestamptz NOT NULL, payload jsonb NOT NULL, state text NOT NULL DEFAULT 'SCHEDULED', locked_until timestamptz);
CREATE INDEX timers_due ON platform.timers(due_at) WHERE state='SCHEDULED';
CREATE TABLE platform.leases (name text PRIMARY KEY, holder text, token bigint NOT NULL DEFAULT 0, lease_until timestamptz NOT NULL DEFAULT 'epoch');""",
    data="Fired timers purged after 7 days.", api="""UUID schedule(String kind, Instant dueAt, Object payload)
void cancel(UUID timerId)
@Scheduled(cron = "0 0 2 * * MON") @SingleRunner(lease = "payout-weekly")""",
    mech=[("Leases with fencing tokens", "A lease is a time-bounded lock. Each acquisition increments a token, and downstream writes include the token and reject older tokens, so a paused process that lost its lease can't corrupt state when it wakes up."), ("Hierarchical timing wheel", "Buckets per tick (wheel slots) give O(1) insert and expiry for millions of short timers, which suits 15-second offer timeouts at high rates.")],
    code="""Optional<Long> acquire(String name, String me, Duration ttl) {
    return jdbc.query("UPDATE platform.leases SET holder=?, token=token+1, lease_until=now()+?::interval WHERE name=? AND (lease_until<now() OR holder=?) RETURNING token",
        (rs, i) -> rs.getLong(1), me, ttl.toSeconds() + " seconds", name, me).stream().findFirst();
}""", cx="O(log n) per poll.",
    fail=[F("Duplicate firing", "Two claims after lease expiry", "Double handling", "Idempotent handlers", "Safe"), F("Clock skew", "DB time used", "None", "Use DB now()", "None")],
    alts=[["Quartz clustered", "Viable", "Java standard", "Cron-heavy"], ["Redis keyspace expiry", "Rejected", "Lossy", "Never"]],
    adrs=[A("DB time as source", "I", "Skew.", [("Instance clocks", "Skew"), ("DB now()", "Chosen")], "DB time.", "Consistent.", "DB dependency.", "N/A")],
    qa=[Q("Distributed systems", "Leader election vs distributed lock: what's the difference here?", "Leader election chooses one long-lived coordinator among peers (e.g. the single dispatcher for a shard). A distributed lock protects a short critical section (one payout batch run). Both rely on leases, and both need fencing tokens because a holder can lose the lease while paused (GC) without knowing it.", "")],
    tests=[T("Concurrency", "3 instances cron", "1 run"), T("Recovery", "Kill holder", "Another resumes after TTL")],
    evo=["I: Timer table + leases", "R: Delayed messages for short timers", "R: Temporal timers/schedules", "U: No change needed", "E: Timing wheels in dispatch shards", "E: Region-local"],
    ideas={"now": ["Fencing tokens"], "next": ["Temporal schedules"], "adv": ["Timing wheels"], "rej": ["@Scheduled on every instance"]})

sub(id="saga-orchestrator", comp="workflow", name="Saga Orchestrator (Durable Workflows)", phase="III", cat="Platform · Consistency",
    resp="Execute multi-step business processes across services as durable workflows with retries, timers, signals and compensations.",
    inp="workflow starts and signals", out="activity invocations, completed/compensated outcomes", deps="Temporal, activity implementations", cons="Payments collection, Onboarding, Payouts, Recovery", own="workflow definitions (per domain), engine config",
    problem="Coordinate steps whose side effects live in different systems, with long waits, without losing progress or leaving partial state.", without="Stuck or half-done processes.",
    guar=["Workflow progress survives crashes", "Each activity retried per policy with idempotency key", "On unrecoverable failure, completed steps compensated in reverse order"], nong=["Isolation between concurrent sagas"],
    usecase="CollectPayment: capture fails (insufficient funds) → wait 6 h → retry → fail → try alternate method → fail → mark receivable, restrict rider ordering until paid, notify. Each step is durable.",
    derive="- Orchestration (central workflow) makes state visible, unlike choreography.\n- Workflow id = business id (trip id) prevents duplicates.\n- Activities idempotent with keys derived from workflow id + step.",
    conc="One workflow per business id (WorkflowIdReusePolicy).", consistency="Saga-level eventual consistency; each step locally atomic.", idem="Workflow id uniqueness; activity idempotency keys.", order="Workflow code defines step order; signals queued in arrival order.",
    restart="History replay on any worker.", scale="Sharded history; workers horizontal.", arch="Java workflows on Temporal: `@WorkflowMethod collect(TripId)` with activities `capture`, `tryAlternate`, `markReceivable`, `restrictRider` and compensations via `Saga` helper.",
    modules=[["Workflows", "Deterministic orchestration code"], ["Activities", "Idempotent side effects"], ["Compensations", "Saga helper"], ["Versioning", "Safe code evolution"]],
    d_arch=("""flowchart LR
  ST["start(trip 77)"] --> WF["CollectPaymentWorkflow"]
  WF --> A1["capture"] & A2["wait 6h"] & A3["tryAlternate"] & A4["markReceivable"]
  WF -->|on failure| C["compensations"]""", "Orchestrated saga."),
    d_seq=("""sequenceDiagram
  participant W as Workflow
  participant P as Payments
  participant R as Rider
  W->>P: capture (key wf:77:capture:1)
  P-->>W: declined
  W->>W: sleep 6h (durable)
  W->>P: capture (key wf:77:capture:2)
  P-->>W: declined
  W->>R: restrictUntilPaid
  W->>W: complete (RECEIVABLE)""", "Collection saga."),
    d_state=("""stateDiagram-v2
  [*] --> Running
  Running --> Waiting: timer/signal
  Waiting --> Running
  Running --> Completed
  Running --> Compensating: unrecoverable
  Compensating --> Compensated""", "Workflow lifecycle."),
    d_flow=("""flowchart LR
  H["event history"] --> RP["replay"] --> S["state"] --> NX["next commands"]""", "Durable execution."),
    d_fail=("""flowchart TB
  W["worker crash"] --> R["another worker replays history, continues"]
  N["nondeterministic code change"] --> V["versioning branch; replay tests in CI"]""", "Replay safety."),
    sql="-- Engine-managed persistence; business tables updated only by activities.",
    data="Histories retained 30 days after close (visibility archive longer).", api="""@WorkflowInterface interface CollectPayment { @WorkflowMethod Outcome collect(UUID tripId); @SignalMethod void paymentMethodUpdated(UUID methodId); }""",
    mech=[("Event-sourced workflow state", "The engine stores every decision/result as history events. Workflow code is replayed against history to rebuild local variables, which is why it must be deterministic."), ("Compensation stack", "As each step succeeds, push its undo. On failure, pop and execute undos in reverse.")],
    code="""public Outcome collect(UUID trip) {
    for (int i = 1; i <= 3; i++) {
        if (acts.capture(trip, "wf:" + trip + ":capture:" + i)) return Outcome.CAPTURED;
        Workflow.sleep(Duration.ofHours(i == 1 ? 6 : 24));
    }
    if (acts.tryAlternate(trip)) return Outcome.CAPTURED;
    acts.markReceivable(trip); acts.restrictRider(trip);
    return Outcome.RECEIVABLE;
}""", cx="O(steps).",
    fail=[F("Activity timeout", "Engine", "Retry", "Policy", "Idempotent"), F("Compensation fails", "Retries exhausted", "Partial", "Alert + manual", "Tracked")],
    alts=[["Choreography (events only)", "Viable", "Loose coupling", "Simple 2–3 step flows"], ["2PC", "Rejected", "Blocking", "Never"]],
    adrs=[A("Orchestration for money flows", "III", "Visibility/audit.", [("Choreography", "Hard to trace"), ("Orchestration", "Chosen")], "Temporal workflows.", "Traceable.", "Central dependency.", "N/A")],
    qa=[Q("Distributed systems", "What isolation anomalies do sagas allow, and how are they handled?", "Intermediate states are visible: a rider may appear 'receivable' before restriction applies, and two sagas may interleave. Countermeasures are semantic locks (a 'pending' flag that other operations respect), commutative updates, and ordering the pivot step so later steps can't fail for business reasons.", "")],
    tests=[T("Replay", "Recorded histories", "Deterministic"), T("Failure", "Kill mid-sleep", "Resumes")],
    evo=["N: Local orchestration in Phase I", "N: Job chains", "I: Temporal workflows", "E: Namespaces, versioning", "E: Scale", "E: Regional"],
    ideas={"now": ["n/a"], "next": ["Workflows"], "adv": ["Workflow visualizer for ops"], "rej": ["Chained cron jobs"]})

# ======================================================================= Service Runtime
comp(id="service-runtime", domain="platform", name="Service Runtime (Discovery, Config, Secrets, Cache)", tag="Platform · Runtime", phase="I", kind="Platform capability",
     biz="The plumbing every service uses to find others, get configuration and secrets safely, and serve hot data fast.",
     eng="Kubernetes-based runtime with service discovery (DNS/mesh), configuration distribution, secrets management (Vault/KMS), and a distributed cache with invalidation patterns.",
     deploy="VMs/containers with env config (I); Kubernetes + Redis + secrets manager (II–IV); multi-cluster (V–VI).", data_own="Secrets, runtime config, cache clusters.",
     up=[], down=["api-gateway", "messaging", "workflow", "identity", "geo-index", "pricing"], ext=["Cloud KMS", "Vault"],
     interfaces="DNS names / mesh endpoints; config client; secrets injection (CSI/sidecar); cache client library.",
     problem="Hardcoded endpoints, secrets in env files and ad-hoc caching cause outages and breaches.",
     fr=["Service discovery with health", "Secrets with rotation", "Distributed cache with TTL + invalidation", "Runtime config"], nfr=["Secret rotation without downtime", "Cache p99 < 2 ms"],
     workload="All services.", success="Services find each other and rotate secrets painlessly.", failure="Leaked credentials; cache stampedes.",
     derive="Endpoints change with autoscaling, so discovery via the orchestrator. Secrets must not live in code or images, so a manager with short-lived credentials. Caches need explicit invalidation for correctness-sensitive data.",
     owns=["Runtime platform"], not_owns=["Application semantics"], sync=["Lookups"], **{"async": ["Rotation", "Invalidation"]},
     boundary_why="Shared runtime concerns are owned by the platform team for consistency.",
     hld=("""flowchart LR
  SVC["Service pod"] -->|DNS/mesh| SD["Service discovery"]
  SVC -->|CSI/sidecar| SM["Secrets manager (Vault/KMS)"]
  SVC --> CC["Distributed cache client"] --> RC[("Redis Cluster")]
  SVC --> CFG["Config client"]""", "Runtime services."),
     seq=("""sequenceDiagram
  participant P as Pod
  participant V as Vault
  participant DB as Postgres
  P->>V: auth (k8s SA token)
  V->>DB: create role (TTL 1h)
  V-->>P: dynamic credentials
  P->>DB: connect
  Note over P,V: renew/rotate before TTL""", "Dynamic DB credentials."),
     subdeps=[("discovery-secrets", "distributed-cache")],
     flow="Pods resolve services via DNS/mesh, fetch secrets at start (and on rotation), and use the cache library with read-through and invalidation.",
     data="Vault storage; Redis cache clusters per domain group.",
     rel=[["Secrets outage", "Cached credentials valid until TTL; long TTL for break-glass."], ["Cache", "Stampede protection, TTL jitter."]], sec=[["Least privilege", "Per-service policies."], ["Audit", "Secret access logged."]],
     adrs=[A("Dynamic DB credentials", "IV", "Static passwords leak.", [("Static", "Risky"), ("Dynamic", "Chosen")], "Vault database engine.", "Short-lived creds.", "Vault dependency.", "N/A")],
     qa=[Q("Caching", "Cache expiration vs invalidation: when is TTL enough?", "TTL is enough when bounded staleness is acceptable (product catalog, 60 s). Invalidation is required when readers must see writes promptly (rider status after restriction). Delete the key after the DB commit, and keep a short TTL as a safety net for missed invalidations.", "")],
     impl_order=["discovery-secrets", "distributed-cache"], pkg="platform/k8s (helm charts), com.atlas.cache (CacheClient)",
     tests=[T("Security", "Rotate DB creds", "No errors"), T("Cache", "Stampede on hot key", "Single backend load")],
     evo=[("I", "VM + env vars", "—", "—", "Simple"), ("R", "Kubernetes + secrets manager + Redis", "—", "Rotation", "Reliability"), ("U", "No change needed", "—", "—", "—"), ("E", "Mesh discovery, dynamic creds", "—", "mTLS", "Services"), ("E", "Multi-cluster, cache tiers", "—", "—", "Scale"), ("E", "Multi-region", "—", "—", "Global")],
     ideas={"now": ["No secrets in Git"], "next": ["K8s"], "adv": ["Workload identity everywhere"], "rej": ["Long-lived static credentials"]})

sub(id="discovery-secrets", comp="service-runtime", name="Service Discovery & Secrets Management", phase="II", cat="Platform · Runtime security",
    resp="Let services locate healthy instances of other services and obtain short-lived secrets securely, with rotation.",
    inp="service registrations (k8s endpoints), secret requests", out="endpoints, credentials", deps="Kubernetes, Vault/KMS", cons="All services", own="secret policies",
    problem="Dynamic endpoints and secret hygiene at scale.", without="Outages from stale endpoints; credential leaks.",
    guar=["Only healthy endpoints returned", "Secrets never in images/Git", "Credentials rotate automatically"], nong=["Application-level authorization"],
    usecase="Trip service scales 10 → 40 pods. Dispatch's gRPC client sees new endpoints within seconds via xDS. DB credentials rotate hourly without restarts.",
    derive="- Kubernetes Services + readiness probes give health-based discovery.\n- Vault with Kubernetes auth issues per-pod credentials with TTL.",
    conc="Endpoint and secret updates are applied by the control plane and sidecars. Applications only read rendered files and swap connection pools on change.", consistency="Endpoint lists eventually consistent (seconds).", idem="Credential requests idempotent per lease.", order="Not applicable: lookups and leases are independent requests.",
    restart="Pods re-authenticate on start.", scale="Control-plane scales with pods.", arch="K8s Services + mesh xDS for discovery. Vault Agent sidecar renders secrets to tmpfs and renews leases, and apps reload on file change.",
    modules=[["Discovery", "K8s/mesh"], ["VaultAgent", "Auth, render, renew"], ["Reloader", "Hot-reload creds"]],
    d_arch=("""flowchart LR
  POD["pod"] --> VA["Vault Agent"] --> V["Vault"] --> KMS["KMS (unseal)"]
  POD --> XDS["mesh xDS"] --> EP["endpoints"]""", "Sidecars."),
    d_seq=("""sequenceDiagram
  participant A as Vault Agent
  participant V as Vault
  A->>V: login (k8s SA JWT)
  V-->>A: token
  A->>V: read database/creds/trip
  V-->>A: user/pass TTL 1h
  A->>A: render file; renew at 2/3 TTL""", "Secret retrieval."),
    nostate="Credentials have TTL leases managed by Vault rather than an app lifecycle.",
    d_flow=("""flowchart LR
  SA["service account"] --> V["Vault policy"] --> S["scoped secret"]""", "Least privilege."),
    d_fail=("""flowchart TB
  V["Vault down"] --> C["existing leases valid until TTL; alert"]""", "Graceful."),
    sql="-- Vault database secrets engine creates roles: CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT trip_rw TO \"{{name}}\";",
    data="Secrets never persisted in app stores.", api="Vault HTTP API; files under /vault/secrets/",
    mech=[("Dynamic secrets", "Credentials are generated per consumer with expiry, so leaks are time-limited and attributable.")],
    code="""@RefreshScope @Bean DataSource ds(@Value("${db.username}") String u, @Value("${db.password}") String p) { return hikari(u, p); }""", cx="N/A.",
    fail=[F("Secret leaked", "Audit/scan", "Exposure", "Revoke lease", "Short TTL bounds")],
    alts=[["Cloud secrets manager", "Viable", "Managed", "Single cloud"]],
    adrs=[A("Vault Agent sidecar", "IV", "App-agnostic.", [("SDK in app", "Coupling"), ("Sidecar", "Chosen")], "Sidecar.", "Uniform.", "Pod overhead.", "N/A")],
    qa=[Q("Security", "How do you rotate the token-signing key used by Identity?", "Signing keys live in KMS/HSM and are never exported. Rotation creates a new key version, publishes it in JWKS 24 h before use, switches signing, and retires the old key after max token TTL. No secret distribution is needed.", "")],
    tests=[T("Security", "Grep images for secrets", "None"), T("Rotation", "Hourly creds", "No errors")],
    evo=["N: Phase I uses env vars from a protected CI store", "I: K8s + secrets manager", "U: No change needed", "E: Dynamic creds, mesh", "E: Multi-cluster", "E: Regional Vault clusters"],
    ideas={"now": ["CI secret store"], "next": ["Vault"], "adv": ["SPIFFE-based secretless auth"], "rej": ["Secrets in Git"]})

sub(id="distributed-cache", comp="service-runtime", name="Distributed Cache", phase="II", cat="Performance · Caching",
    resp="Provide a shared, low-latency cache with read-through, explicit invalidation, stampede protection and hot-key handling.",
    inp="get/set/delete", out="cached values", deps="Redis Cluster", cons="Profiles, Catalog, Maps, Pricing, Features", own="cache clusters, key conventions",
    problem="Reduce latency and DB load without serving dangerously stale data.", without="DB overload; slow reads.",
    guar=["Keys namespaced and TTL'd (no immortal keys)", "Invalidation after commit", "At most one concurrent backend load per key per instance"], nong=["Durability", "Strong consistency"],
    usecase="Rider profile read 2K/s: hit rate 97%, DB sees 60 reads/s. An edit deletes the key after commit, and the next read refills.",
    derive="- Cache-aside with delete-on-write (not update-on-write, which races).\n- TTL jitter prevents synchronized expiry.\n- Single-flight per key per instance + optional `SET NX` lock.",
    conc="Delete after commit (Spring TransactionSynchronization).", consistency="Eventual; bounded by TTL + invalidation latency.", idem="Deletes and sets are idempotent.", order="Race 'read old → delete → set old' mitigated by short TTL or versioned values (set only if version ≥ cached).",
    restart="Cold cache after Redis restart → protect DB with request coalescing and rate limits.", scale="Redis Cluster sharding; hot keys replicated to local near-cache.",
    arch="Spring Cache abstraction over Redis Cluster plus a local Caffeine near-cache for hot keys, versioned values for correctness-sensitive entries.",
    modules=[["CacheClient", "Get/set/delete with namespaces"], ["SingleFlight", "Coalescing"], ["NearCache", "Hot keys"], ["Invalidator", "After-commit hooks"]],
    d_arch=("""flowchart LR
  SVC["service"] --> NC["near-cache (Caffeine)"] --> RC[("Redis Cluster")] --> DB[("DB")]
  SVC -->|after commit delete| INV["Invalidator"] --> RC""", "Two-level cache."),
    d_seq=("""sequenceDiagram
  participant W as Writer
  participant DB
  participant C as Cache
  participant R as Reader
  W->>DB: UPDATE profile (v8) COMMIT
  W->>C: DEL rider:1
  R->>C: GET rider:1 (miss)
  R->>DB: SELECT (v8)
  R->>C: SET rider:1 v8 TTL 600±60""", "Delete-on-write."),
    nostate="Cache entries have TTLs and no business lifecycle.",
    d_flow=("""flowchart LR
  K["ns:entity:id"] --> V["{v, data}"]""", "Key and value convention."),
    d_fail=("""flowchart TB
  R["Redis down"] --> DB["direct DB with coalescing + shed non-critical reads"]
  ST["stale set race"] --> VV["versioned set: SET only if newer"]""", "Failure handling."),
    sql="-- Keys: rider:profile:{id} -> JSON {v:8,...} TTL 600±60s",
    data="Ephemeral.", api="""<T> T getOrLoad(String key, Duration ttl, Supplier<T> loader)
void evictAfterCommit(String key)""",
    mech=[("Cache-aside with delete", "Deleting rather than updating on writes avoids races where two writers update the cache in the opposite order of their DB commits."), ("TTL jitter", "Random ±10% TTL prevents many keys expiring together and stampeding the DB.")],
    code="""public <T> T getOrLoad(String k, Duration ttl, Supplier<T> loader) {
    T v = near.getIfPresent(k); if (v != null) return v;
    v = redis.get(k); if (v != null) { near.put(k, v); return v; }
    return inflight.computeIfAbsent(k, x -> CompletableFuture.supplyAsync(loader)).thenApply(val -> { redis.set(k, val, jitter(ttl)); inflight.remove(k); return val; }).join();
}""", cx="O(1).",
    fail=[F("Cold start stampede", "Miss spike", "DB load", "Coalescing + warmers", "None"), F("Stale read after write", "Race", "Bounded staleness", "Versioned sets, short TTL", "Bounded")],
    alts=[["Write-through", "Viable", "Simpler reads", "Single writer"], ["No cache", "Phase I", "Correctness", "Low load"]],
    adrs=[A("Delete-on-write", "II", "Races.", [("Update-on-write", "Races"), ("Delete", "Chosen")], "Delete after commit.", "Simpler correctness.", "Extra miss.", "N/A")],
    qa=[Q("Correctness", "Should rider account status (restricted) be cached?", "Only with invalidation plus a short TTL (≤ 60 s), and with critical decisions (payouts, high-value requests) reading the source of truth. Caching security-relevant state needs an explicit staleness budget.", "")],
    tests=[T("Concurrency", "Write/read races", "Staleness ≤ TTL"), T("Load", "Hot key 50K/s", "Near-cache absorbs")],
    evo=["N: Phase I reads from the DB directly", "I: Redis cache-aside", "U: No change needed", "E: Redis Cluster, near-cache", "E: Hot-key replication", "E: Regional clusters"],
    ideas={"now": ["n/a"], "next": ["Near-cache"], "adv": ["CDC-driven invalidation"], "rej": ["Update-on-write from multiple writers"]})
