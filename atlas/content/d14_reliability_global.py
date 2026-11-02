from model import comp, sub, A, Q, F, T

# ======================================================================= Observability
comp(id="observability", domain="reliability", name="Observability (Logs, Metrics, Traces, SLOs)", tag="Operations · Visibility", phase="I", kind="Platform capability",
     biz="Lets engineers know the platform is healthy and find the cause quickly when it isn't, measured against what riders and drivers actually experience.",
     eng="Structured logs, RED/USE metrics, distributed tracing via OpenTelemetry, SLOs with error budgets and burn-rate alerting, and correlation across signals.",
     deploy="Logs + basic metrics (I); Prometheus/Grafana + alerting (II); OpenTelemetry tracing (III); SLO platform per service (IV); sampled, cost-managed telemetry (V); regional stacks with global views (VI).",
     data_own="Telemetry pipelines, dashboards, SLO definitions, alert rules.", up=[], down=[], ext=["Prometheus/Mimir", "Grafana", "Loki/Elasticsearch", "Tempo/Jaeger", "PagerDuty"],
     interfaces="OTel SDK in services; `/metrics`; log shipping; SLO definitions as code.",
     problem="In a distributed system, symptoms appear far from causes. Without consistent telemetry and user-centric SLOs, teams alert on noise and miss real outages.",
     fr=["Structured JSON logs with request/trace ids", "RED metrics per endpoint, USE per resource", "Traces across sync and async hops", "SLOs + burn-rate alerts", "Business KPIs (match rate, completion)"], nfr=["Telemetry overhead < 3% CPU", "Alert to page < 2 min for fast burn", "Cost-bounded retention"],
     workload="Phase V: millions of spans/s before sampling; TBs of logs/day.", success="Fast detection and diagnosis; few false pages.", failure="Silent outages; alert fatigue; huge telemetry bills.",
     derive="Correlation needs a shared id (trace id) in logs, metrics exemplars and spans. User experience is measured by SLIs at edges (success rate, latency of ride request). Alerting on error-budget burn rates catches fast and slow problems with few false positives.",
     owns=["Telemetry standards and pipelines", "SLO tooling"], not_owns=["Service-specific SLO targets (service owners)"], sync=["None on request path"], **{"async": ["All telemetry export"]},
     boundary_why="A shared standard makes cross-service diagnosis possible.",
     hld=("""flowchart LR
  SVC["Services (OTel SDK)"] -->|OTLP| COL["OTel collectors"]
  COL --> MET[("Metrics: Prometheus/Mimir")] & TR[("Traces: Tempo")] & LOG[("Logs: Loki")]
  MET --> SLO["SLO engine + burn alerts"] --> PG["PagerDuty"]
  MET & TR & LOG --> GF["Grafana (correlated views)"]""", "OTel pipeline to three stores with SLO alerting."),
     seq=("""sequenceDiagram
  participant G as Gateway
  participant R as Request svc
  participant K as Kafka
  participant P as Payments
  G->>R: traceparent t1
  R->>K: event headers traceparent t1 (link)
  K->>P: consume, continue trace t1
  Note over G,P: one trace spans sync and async hops""", "Trace propagation through Kafka headers."),
     subdeps=[("slo-alerting", "telemetry-pipeline")],
     flow="SDKs emit spans, metrics and logs with shared context. Collectors sample and route. SLO rules compute burn rates and page owners.",
     data="Metrics 13 months downsampled; traces 7 days (sampled); logs 14–30 days hot.",
     rel=[["Telemetry must not take down services", "Async export, bounded buffers, drop on overload."]], sec=[["PII", "Log redaction filters; no tokens/OTP in logs."], ["Access", "RBAC for logs with PII risk."]],
     adrs=[A("OpenTelemetry standard", "III", "Vendor neutrality.", [("Vendor agents", "Lock-in"), ("OTel", "Chosen")], "OTel.", "Portable.", "Maturity gaps.", "N/A")],
     qa=[Q("Operations", "Which SLOs matter most for a ride-hailing platform?", "User-journey SLOs: ride request success (request accepted and dispatched without error) ≥ 99.95%, time to first driver offer p95 < 5 s, trip state transition success ≥ 99.99%, payment capture success within 72 h ≥ 99.5%, and SOS delivery ≥ 99.99%. Component SLOs support these but don't replace them.", "")],
     impl_order=["telemetry-pipeline", "slo-alerting"], pkg="platform/observability (OTel collector config, dashboards-as-code, SLO yaml)",
     tests=[T("Trace", "Request → payment capture", "Single trace with links"), T("Alert", "Inject 5% errors", "Fast-burn page < 5 min")],
     evo=[("I", "JSON logs + basic metrics + uptime checks", "—", "—", "Basics"), ("E", "Prometheus/Grafana + alerting", "—", "On-call", "Reliability"), ("E", "OTel tracing incl. async", "—", "—", "Distributed"),
          ("E", "Per-service SLOs, error budgets", "—", "Burn alerts", "Services"), ("E", "Tail sampling, cost controls", "—", "—", "Volume"), ("E", "Regional stacks + global views", "—", "—", "Global")],
     ideas={"now": ["Request ids"], "next": ["Tracing"], "adv": ["eBPF auto-instrumentation"], "rej": ["Alerting on CPU only"]})

sub(id="telemetry-pipeline", comp="observability", name="Telemetry Pipeline (Logs, Metrics, Traces)", phase="I", cat="Operations · Instrumentation",
    resp="Instrument services and move logs, metrics and traces to their stores with consistent context, sampling and redaction.",
    inp="SDK telemetry", out="stored, queryable signals", deps="OTel collectors, stores", cons="Engineers, SLO engine", own="collector config, conventions",
    problem="Correlated, affordable telemetry from hundreds of services.", without="Blind debugging.",
    guar=["Every log line has trace_id when in a request", "Async hops propagate context", "Secrets/PII redacted"], nong=["100% trace capture (sampled)"],
    usecase="Payment capture latency spike. An exemplar on the latency histogram links to a trace showing the PSP span at 4.8 s, and the logs for that trace show retries.",
    derive="- W3C traceparent in HTTP/gRPC/Kafka headers.\n- Tail-based sampling keeps all errors and slow traces plus a small % of normal ones.",
    conc="Non-blocking exporters with bounded queues.", consistency="Best-effort; telemetry may drop under overload.", idem="Duplicate spans deduped by span id in store.", order="Timestamps; not required.",
    restart="Collectors stateless (tail sampling needs consistent routing by trace id).", scale="Collector tiers (agent → gateway), sharded stores.", arch="OTel SDK (auto + manual spans) → node agent collectors → gateway collectors (tail sampling, redaction) → Mimir/Tempo/Loki.",
    modules=[["SDK conventions", "Attributes, naming"], ["Agents", "Node-local"], ["Gateways", "Tail sampling, redaction"], ["Stores", "Metrics/traces/logs"]],
    d_arch=("""flowchart LR
  APP["app SDK"] --> AG["agent collector"] --> GW["gateway collector (tail sampling by trace_id)"] --> ST[("stores")]""", "Two-tier collection."),
    d_seq=("""sequenceDiagram
  participant A as App
  participant G as Gateway collector
  A->>G: spans of trace t1 (from many services)
  G->>G: wait 10s, any error? keep : sample 5%
  G->>G: redact attributes""", "Tail sampling."),
    nostate="A pipeline of signals with no entity lifecycle.",
    d_flow=("""flowchart LR
  REQ["request"] --> SP["spans"] & LG["logs(trace_id)"] & MT["metrics(exemplar trace_id)"]""", "Correlation."),
    d_fail=("""flowchart TB
  O["collector overload"] --> D["drop low-priority telemetry; never block app"]""", "Telemetry never blocks the request path."),
    sql="-- No relational data.", data="Retention per signal type.", api="""Kafka header: traceparent: 00-<trace-id>-<span-id>-01
log: {"ts":"…","level":"INFO","svc":"trip","trace_id":"…","msg":"transition","trip_id":"…","from":"ARRIVED","to":"STARTED"}""",
    mech=[("Tail-based sampling", "The decision is made after the trace completes, so errors and slow traces are always kept. Head sampling would drop them randomly."), ("Exemplars", "Metric samples carry a trace id, so you can jump from a latency spike to a concrete trace.")],
    code="""Span span = tracer.spanBuilder("capture").setParent(Context.current()).startSpan();
try (Scope s = span.makeCurrent()) { psp.capture(...); } catch (Exception e) { span.recordException(e); throw e; } finally { span.end(); }""", cx="Overhead O(spans).",
    fail=[F("Telemetry backend outage", "Export errors", "Blind spots", "Buffer + drop", "N/A")],
    alts=[["Vendor APM", "Viable", "Turnkey", "Budget available"]],
    adrs=[A("Tail sampling", "V", "Cost.", [("Head 1%", "Misses errors"), ("Tail", "Chosen")], "Tail.", "Keeps important traces.", "Collector state.", "N/A")],
    qa=[Q("Operations", "Why propagate trace context through Kafka?", "Without it, a ride request trace stops at the producer and payment capture appears as an unrelated trace. With headers plus span links, you can follow a rider's request through dispatch, trip and payments.", "")],
    tests=[T("Redaction", "Log with OTP field", "Redacted")],
    evo=["I: JSON logs + request ids + basic metrics", "E: Prometheus", "E: OTel tracing", "E: Exemplars", "R: Tail sampling, tiered collectors", "E: Regional"],
    ideas={"now": ["Request ids"], "next": ["OTel"], "adv": ["eBPF"], "rej": ["Unstructured logs"]})

sub(id="slo-alerting", comp="observability", name="SLOs, Error Budgets & Alerting", phase="II", cat="Operations · Reliability management",
    resp="Define user-centric SLIs/SLOs per journey and service, compute error budgets, and page on burn rate rather than on raw symptoms.",
    inp="metrics", out="SLO dashboards, pages, budget reports", deps="Metrics store, Pager", cons="On-call, Engineering leadership", own="SLO definitions, alert rules",
    problem="Alert on what matters to users, with few false pages, and use budgets to balance features and reliability.", without="Alert fatigue or missed outages.",
    guar=["Every tier-1 service has SLOs", "Multi-window burn alerts (fast + slow)", "Budget policy enforced (freeze on exhaustion)"], nong=["Root cause"],
    usecase="Ride request SLO 99.95% over 30 days (budget ≈ 21.6 min). 2% errors for 5 min burns at 40× and pages immediately. 0.1% for 6 h burns at 2× and opens a ticket.",
    derive="- SLI = good events / valid events.\n- Burn rate = error rate / (1 − SLO).\n- Two windows (1 h & 5 m for fast, 6 h & 30 m for slow) reduce false alarms.",
    conc="Rule evaluation in metrics backend.", consistency="Metrics eventually consistent (≤ 1 min).", idem="Alert dedupe by fingerprint.", order="Not applicable: rules evaluate over time windows.",
    restart="Rules stateless.", scale="Rules per service; recording rules for efficiency.", arch="SLO-as-code (Sloth/OpenSLO) generates recording rules and multi-window burn alerts, with budget dashboards and monthly reports.",
    modules=[["SloSpecs", "YAML"], ["Generator", "Recording + alert rules"], ["BudgetPolicy", "Freeze rules"]],
    d_arch=("""flowchart LR
  SPEC["SLO yaml"] --> GEN["Generator"] --> RR["recording rules"] & AR["burn alerts"]
  AR --> PG["Pager"]""", "SLO as code."),
    d_seq=("""sequenceDiagram
  participant M as Metrics
  participant A as Alertmanager
  participant O as On-call
  M->>A: burn 1h>14.4 and 5m>14.4
  A->>O: page (fast burn)""", "Fast-burn page."),
    nostate="Rules over time series.",
    d_flow=("""flowchart LR
  E["errors/total"] --> BR["burn = err / (1−SLO)"] --> TH{"> 14.4 (1h & 5m)?"} --> PAGE["page"]""", "Burn computation."),
    d_fail=("""flowchart TB
  M["metrics down"] --> W["watchdog alert (dead-man's switch)"]""", "Alerting on alerting."),
    sql="""# recording rule
sli:ride_request_errors:ratio_rate5m = sum(rate(http_requests_total{route="/v1/ride-requests",code=~"5.."}[5m])) / sum(rate(http_requests_total{route="/v1/ride-requests"}[5m]))""",
    data="SLO history 13 months.", api="""slo: {service: request, objective: 99.95, sli: {events: http_requests_total{route="/v1/ride-requests"}, errors: code=~"5.."}}""",
    mech=[("Multi-window multi-burn-rate alerts", "Page when both a long window (1 h) and a short window (5 m) exceed a burn threshold. The long window ensures significance and the short window ensures the problem is ongoing.")],
    code="""- alert: RideRequestFastBurn
  expr: sli:ride_request_errors:ratio_rate1h > (14.4 * 0.0005) and sli:ride_request_errors:ratio_rate5m > (14.4 * 0.0005)""", cx="N/A.",
    fail=[F("Noisy alerts", "Page review", "Fatigue", "Tune SLOs/windows", "N/A")],
    alts=[["Threshold alerts", "Phase I", "Simple", "Few services"]],
    adrs=[A("Burn-rate alerting", "II", "Fatigue.", [("Static thresholds", "Noisy"), ("Burn rate", "Chosen")], "Burn.", "Signal.", "Learning curve.", "N/A")],
    qa=[Q("Operations", "What happens when a team exhausts its error budget?", "Policy: feature launches freeze for that service and engineering time shifts to reliability work until the budget recovers. Exceptions need director approval. This makes the reliability/feature trade-off explicit.", "")],
    tests=[T("Alert", "Synthetic errors", "Correct alert class")],
    evo=["N: Phase I uses uptime checks and simple thresholds", "I: SLOs for key journeys", "E: Async SLIs (event lag)", "E: Per-service SLOs + budgets", "E: Regional/city SLOs", "E: Global rollups"],
    ideas={"now": ["Uptime checks"], "next": ["Burn alerts"], "adv": ["Automated canary analysis on SLIs"], "rej": ["Paging on CPU"]})

# ======================================================================= Resilience Toolkit
comp(id="resilience", domain="reliability", name="Resilience Toolkit (Timeouts, Retries, Breakers, Bulkheads, Backpressure)", tag="Reliability · Patterns", phase="II", kind="Library + platform capability",
     biz="Keeps one failing part from taking down the whole ride flow.",
     eng="Standardized timeouts and deadline propagation, retry budgets, circuit breakers, bulkheads and load shedding/backpressure, provided as a library with sane defaults.",
     deploy="Library (Resilience4j wrappers) from Phase II; mesh-level policies (IV); adaptive concurrency (V).", data_own="Policy defaults.",
     up=["observability"], down=["payments", "maps-gateway", "notifications", "dispatch", "routing-eta"], ext=[],
     interfaces="`Resilient.call(dependency, deadline, fn)`; annotations; mesh retry/timeout config.",
     problem="Cascading failures: slow dependencies exhaust threads, retries amplify outages, overload collapses throughput.",
     fr=["Timeouts everywhere", "Deadline propagation", "Retries with budget/jitter", "Breakers per dependency", "Bulkheads (pools)", "Load shedding by priority"], nfr=["No unbounded waits", "Retry amplification ≤ 1.2×", "Graceful degradation documented per dependency"],
     workload="Every remote call.", success="Partial failures stay partial.", failure="Cascading outages.",
     derive="Each remote call needs a budget derived from the caller's deadline. Retries only for idempotent calls and within a budget. Isolation per dependency (bulkheads) and fast failure (breakers). Overload needs admission control (shed lowest priority first).",
     owns=["Library", "Defaults", "Patterns"], not_owns=["Per-service policy choices"], sync=["Wraps calls"], **{"async": ["Metrics"]},
     boundary_why="Patterns must be uniform to be effective. One library plus mesh config gives that.",
     hld=("""flowchart LR
  CALL["outbound call"] --> DL["deadline check"] --> BH["bulkhead (pool)"] --> CB["circuit breaker"] --> RT["retry (budgeted)"] --> TO["timeout"] --> DEP["dependency"]
  IN["inbound"] --> LS["load shedder (priority)"] --> APP["handler"]""", "Outbound protection chain plus inbound shedding."),
     seq=("""sequenceDiagram
  participant A as Caller (deadline 800ms)
  participant L as Library
  participant D as Dependency
  A->>L: call (remaining 800ms)
  L->>D: try 1 (timeout 300ms)
  D--xL: timeout
  L->>L: budget ok? jitter 50ms
  L->>D: try 2 (timeout 300ms)
  D-->>L: ok""", "Retry within deadline."),
     subdeps=[("load-shedding", "resilience-library")],
     flow="Outbound calls pass through deadline, bulkhead, breaker, retry and timeout. Inbound requests are admitted by priority and concurrency limits.",
     data="Policy configs per dependency.",
     rel=[["Defaults", "Timeouts required; retries off by default for non-idempotent."]], sec=[["DoS", "Shedding protects from overload attacks too."]],
     adrs=[A("Retry budgets", "II", "Retry storms.", [("Fixed retries", "Amplify 3×"), ("Budget (10% of requests)", "Chosen")], "Budget.", "Bounded amplification.", "Some requests not retried.", "N/A")],
     qa=[Q("Reliability", "Why can retries make an outage worse?", "If a dependency is overloaded, every caller retrying 3× quadruples its load, and with multiple layers retrying, amplification multiplies (3 layers × 3 retries = 27×). Budgets (retry at most 10% extra), jitter, breakers and retrying only at one layer prevent this.", "")],
     impl_order=["resilience-library", "load-shedding"], pkg="com.atlas.resilience (Resilient, Deadline, RetryBudget, PriorityShedder)",
     tests=[T("Chaos", "Dependency latency 5 s", "Caller p99 bounded; breaker opens"), T("Load", "2× capacity", "Low priority shed; critical served")],
     evo=[("N", "Phase I: timeouts on HTTP clients only", "—", "—", "—"), ("I", "Library with breakers/retries/bulkheads", "—", "—", "Provider failures"), ("E", "Consumer-side backpressure", "—", "—", "Async"),
          ("E", "Mesh-level policies, deadline propagation", "—", "—", "Services"), ("E", "Adaptive concurrency limits", "—", "—", "Scale"), ("E", "Region-level shedding", "—", "—", "Global")],
     ideas={"now": ["Timeouts"], "next": ["Breakers"], "adv": ["Adaptive concurrency"], "rej": ["Retries at every layer"]})

sub(id="resilience-library", comp="resilience", name="Timeouts, Retries & Circuit Breakers Library", phase="II", cat="Reliability · Client-side",
    resp="Wrap every outbound call with deadline-aware timeouts, budgeted jittered retries for idempotent operations, circuit breakers and bulkheads, with metrics.",
    inp="calls with dependency name and deadline", out="results or fast failures", deps="Resilience4j, Observability", cons="All services", own="policies",
    problem="Uniform protection without each team re-implementing it.", without="Inconsistent, cascading failures.",
    guar=["No call without timeout", "Retries only if marked idempotent and budget allows", "Breaker per dependency with metrics"], nong=["Dependency health"],
    usecase="Maps provider slows. Breaker opens after 50% failures, calls fail fast to the fallback, and threads aren't exhausted.",
    derive="- Deadline in context (gRPC deadline / header).\n- Retry budget as token bucket: success deposits 0.1 tokens, a retry consumes 1.",
    conc="Thread-safe policy objects; bulkhead semaphores.", consistency="Per-instance breaker state (acceptable).", idem="Library only retries operations declared idempotent.", order="Not applicable: wraps individual calls.",
    restart="Breakers reset closed (fast re-detection).", scale="In-process, so cost is per call (microseconds). Breaker and bulkhead state is per instance, so it scales with the fleet automatically.", arch="Resilience4j decorators composed in fixed order (Bulkhead → CircuitBreaker → Retry → TimeLimiter) via a `Resilient` facade with registry per dependency.",
    modules=[["Deadline", "Propagation"], ["RetryBudget", "Token bucket"], ["Decorators", "Composition"], ["Metrics", "Per dependency"]],
    d_arch=("""flowchart LR
  F["facade"] --> BH["Bulkhead"] --> CB["CircuitBreaker"] --> RB["Retry+Budget"] --> TL["TimeLimiter"] --> CALL["call"]""", "Composition order."),
    d_seq=("""sequenceDiagram
  participant C as Code
  participant R as Resilient
  C->>R: call("maps", deadline, fn, idempotent)
  R->>R: breaker open → fallback
  R-->>C: fallback result""", "Fast failure."),
    d_state=("""stateDiagram-v2
  [*] --> Closed
  Closed --> Open: failure rate ≥ 50% (min 20 calls)
  Open --> HalfOpen: 30 s
  HalfOpen --> Closed: 5 probes ok
  HalfOpen --> Open""", "Circuit breaker."),
    d_flow=("""flowchart LR
  D["deadline 800ms"] --> T1["timeout min(300, remaining)"]""", "Deadline-aware timeouts."),
    d_fail=("""flowchart TB
  O["dependency overloaded"] --> B["budget exhausted → no retries"] --> CB["breaker opens"]""", "Storm prevention."),
    sql="-- Config (YAML): resilience.dependencies.maps.timeout=300ms, retry.max=1, breaker.failureRate=50",
    data="Config only.", api="""<T> T call(String dependency, Deadline d, boolean idempotent, Supplier<T> fn, Function<Throwable,T> fallback)""",
    mech=[("Retry budget", "Limits retries to a fraction of total traffic so retries can't multiply load during outages."), ("Full jitter", "sleep = random(0, min(cap, base·2^n)) desynchronizes retry waves.")],
    code="""public <T> T call(String dep, Deadline d, boolean idem, Supplier<T> fn, Function<Throwable, T> fb) {
    Supplier<T> s = Decorators.ofSupplier(fn).withBulkhead(bh(dep)).withCircuitBreaker(cb(dep))
        .withRetry(idem && budget(dep).tryAcquire() ? retry(dep) : Retry.ofDefaults("none")).decorate();
    try { return CompletableFuture.supplyAsync(s).orTimeout(Math.min(timeout(dep), d.remainingMs()), MILLISECONDS).join(); }
    catch (Exception e) { return fb.apply(e); }
}""", cx="O(1).",
    fail=[F("Misconfigured timeout > caller deadline", "Lint", "Wasted work", "Deadline clamp", "N/A")],
    alts=[["Mesh-only policies", "Complement", "No code", "Uniform HTTP/gRPC"]],
    adrs=[A("Library + mesh", "IV", "Coverage.", [("Library only", "Per language"), ("Both", "Chosen")], "Both.", "Coverage.", "Double config.", "N/A")],
    qa=[Q("Reliability", "Where should retries happen: client, gateway, or service?", "At exactly one layer per call chain, normally the layer closest to the failure that knows idempotency (the direct caller), with budgets. Mesh retries only for connection failures. Clients retry user actions with idempotency keys.", "")],
    tests=[T("Chaos", "Latency injection", "Timeouts honored"), T("Unit", "Non-idempotent", "No retry")],
    evo=["N: Phase I uses HTTP client timeouts only", "I: Library", "E: Consumer backoff", "E: Deadlines + mesh", "E: Adaptive", "U: No change needed"],
    ideas={"now": ["Timeouts"], "next": ["Budgets"], "adv": ["Hedged requests"], "rej": ["Infinite retries"]})

sub(id="load-shedding", comp="resilience", name="Load Shedding, Bulkheads & Backpressure", phase="II", cat="Reliability · Admission control",
    resp="Protect services under overload by admitting work by priority, isolating resource pools, and propagating backpressure to producers.",
    inp="incoming requests/messages, resource utilization", out="admitted work, rejections (429/503), slowed consumers", deps="Metrics", cons="All services", own="priority classes, limits",
    problem="When demand exceeds capacity, throughput collapses unless work is rejected early and selectively.", without="Congestion collapse during peaks.",
    guar=["Critical traffic (SOS, trip transitions, payments capture) admitted first", "Queues bounded", "Rejections fast (< 5 ms)"], nong=["Serving all traffic during overload"],
    usecase="New Year's Eve: request rate 4× capacity in one city. Product previews and history are shed (served cached or 503), ride requests are admitted up to the concurrency limit, and trip transitions always pass.",
    derive="- Concurrency limit (Little's law) instead of rate.\n- Priority tiers.\n- Adaptive limit (gradient: increase when latency stable, decrease when rising).\n- Bounded queues + consumer pause.",
    conc="Atomic counters per priority class.", consistency="Per-instance decisions.", idem="A rejection has no side effects, so the client retries later.", order="Priority order, then arrival order.",
    restart="Limits recomputed quickly.", scale="Per-instance admission. Limits adapt per node, so capacity scales with replicas and shedding stays local and fast.", arch="Servlet/Netty filter with priority classification (route + header) and adaptive concurrency limiter (Netflix concurrency-limits style). Separate thread pools per dependency class (bulkheads). Kafka consumers pause partitions when downstream is saturated.",
    modules=[["Classifier", "Priority"], ["AdaptiveLimiter", "Gradient2"], ["Bulkheads", "Pools"], ["ConsumerBackpressure", "Pause/resume"]],
    d_arch=("""flowchart LR
  IN["requests"] --> CL["Classifier"] --> AL["AdaptiveLimiter (per priority)"] --> APP["handler pools (bulkheads)"]
  AL -->|reject| R503["429/503 fast"]""", "Admission control."),
    d_seq=("""sequenceDiagram
  participant C as Client
  participant L as Limiter
  participant H as Handler
  C->>L: GET /history (low priority)
  L-->>C: 503 retry-after 5
  C->>L: POST /trips/77/complete (critical)
  L->>H: admitted""", "Priority shedding."),
    nostate="Counters and limits rather than lifecycle.",
    d_flow=("""flowchart LR
  L["latency trend"] --> G["gradient"] --> LIM["new limit"]""", "Adaptive limit."),
    d_fail=("""flowchart TB
  M["misclassification"] --> C["critical shed"] --> T["tests per route class"]""", "Classification tests."),
    sql="-- Config: priorities by route; e.g. /v1/sos=CRITICAL, /v1/trips/*/complete=CRITICAL, /v1/products=LOW",
    data="Config only.", api="""Response: 503 {code:"OVERLOADED", retry_after_s:5}""",
    mech=[("Little's law", "concurrency = throughput × latency. Limiting in-flight requests bounds latency and keeps throughput at capacity instead of collapsing."), ("Backpressure in consumers", "Pause partitions when the downstream pool is full, which leaves lag in Kafka instead of an OOM.")],
    code="""if (!limiter.forClass(classify(req)).tryAcquire()) { res.setStatus(503); res.setHeader("Retry-After", "5"); return; }""", cx="O(1).",
    fail=[F("Limit too low", "Rejections at low load", "Errors", "Adaptive tuning", "N/A")],
    alts=[["Autoscaling only", "Insufficient", "Too slow", "Gradual growth"]],
    adrs=[A("Priority classes", "II", "Peaks.", [("FIFO shedding", "Sheds critical"), ("Priority", "Chosen")], "Priorities.", "Critical flows survive.", "Classification upkeep.", "N/A")],
    qa=[Q("Architectural judgment", "Rate limiting vs backpressure vs load shedding?", "Rate limiting caps a client's rate (fairness). Backpressure slows producers when consumers can't keep up (flow control within the system). Load shedding drops excess work at the overloaded component (self-protection). A robust system uses all three at different points.", "")],
    tests=[T("Load", "4× traffic", "Critical success ≥ 99.9%")],
    evo=["N: Phase I relies on autoscaling-free headroom", "I: Bulkheads + bounded queues", "E: Consumer backpressure", "E: Priority shedding", "R: Adaptive concurrency", "E: Regional spillover"],
    ideas={"now": ["Bounded queues"], "next": ["Priorities"], "adv": ["Adaptive"], "rej": ["Unbounded queues"]})

# ======================================================================= Delivery & Capacity
comp(id="delivery-capacity", domain="reliability", name="Delivery, Capacity & Cost Management", tag="Operations · Engineering productivity", phase="I", kind="Platform capability",
     biz="Ships changes safely many times a day, keeps enough capacity for peaks, and keeps infrastructure cost proportional to business growth.",
     eng="CI/CD with automated tests and progressive delivery (canary, automated analysis, rollback), database migration discipline, capacity models per service, and cost attribution.",
     deploy="Single pipeline (I); per-service pipelines + canary (IV); automated analysis + capacity planning (V).", data_own="Pipelines, deployment records, capacity models, cost reports.",
     up=["observability"], down=[], ext=["CI system", "Argo CD/Rollouts", "Cloud billing"],
     interfaces="GitOps repos; deployment API; capacity dashboards.",
     problem="Bad deploys are the top cause of incidents. Capacity shortfalls during events and runaway costs follow growth.",
     fr=["Automated build/test", "Progressive delivery with auto-rollback", "Backward-compatible DB migrations", "Capacity forecasts", "Cost per trip tracking"], nfr=["Rollback < 5 min", "Deploy lead time < 1 h", "Peak headroom ≥ 30%"],
     workload="Phase IV: ~100 deploys/day.", success="Frequent safe deploys, no capacity incidents, cost per trip falling.", failure="Deploy-caused outages; event-day capacity incidents.",
     derive="Safety requires small changes plus canary verification on SLIs. Schema changes must be expand/contract to support old and new versions running together. Capacity = forecast peak demand × per-request cost + headroom.",
     owns=["Pipelines", "Release process", "Capacity models", "Cost attribution"], not_owns=["Service code"], sync=["N/A"], **{"async": ["Deploys", "Reports"]},
     boundary_why="Platform-owned delivery gives every team the same safety net.",
     hld=("""flowchart LR
  GIT["Git"] --> CI["CI: build, test, scan"] --> REG["Image registry"]
  REG --> CD["Argo Rollouts: canary"] --> K8S["Kubernetes"]
  CD --> AN["Canary analysis (SLIs)"] -->|fail| RB["Rollback"]
  MET["metrics + forecasts"] --> CAP["Capacity planning"] --> K8S
  BILL["billing"] --> COST["Cost per service/trip"]""", "Delivery plus capacity and cost loops."),
     seq=("""sequenceDiagram
  participant D as Dev
  participant CI
  participant CD
  participant M as Metrics
  D->>CI: merge
  CI->>CD: image v42
  CD->>CD: canary 5%
  CD->>M: compare error/latency vs baseline
  M-->>CD: ok
  CD->>CD: 25% → 100%""", "Progressive delivery."),
     subdeps=[("capacity-cost", "progressive-delivery")],
     flow="Merges produce artifacts, canaries are evaluated automatically, and promotions or rollbacks follow. Capacity and cost are reviewed with forecasts.",
     data="Deployment history; capacity model sheets as code.", rel=[["Rollback", "Automatic on SLI regression."]], sec=[["Supply chain", "Signed images (Sigstore), SBOM, dependency scanning."]],
     adrs=[A("Expand/contract migrations", "I", "Zero-downtime deploys.", [("Breaking migrations in one deploy", "Outages"), ("Expand/contract", "Chosen")], "Two-phase schema changes.", "Safe deploys.", "More steps.", "N/A")],
     qa=[Q("Operations", "How do you rename a column used by a running service without downtime?", "Expand: add the new column, write both, backfill. Migrate reads to the new column in a deploy. Contract: stop writing the old one and drop it in a later release. At every step, the old and new app versions both work.", "")],
     impl_order=["progressive-delivery", "capacity-cost"], pkg="platform/delivery (pipelines, rollout templates), platform/capacity (models)",
     tests=[T("Release", "Inject error in canary", "Auto rollback"), T("Capacity", "Load test at forecast peak × 1.3", "SLOs met")],
     evo=[("I", "Single pipeline, blue/green", "—", "Manual rollback", "Small team"), ("E", "Automated tests gate", "—", "—", "Reliability"), ("U", "No change needed", "—", "—", "—"),
          ("R", "Per-service GitOps + canary analysis", "—", "Auto rollback", "Many services"), ("E", "Capacity models, cost attribution", "—", "—", "Scale"), ("E", "Region-by-region rollouts", "—", "—", "Global")],
     ideas={"now": ["Expand/contract"], "next": ["Canary analysis"], "adv": ["Feature-flag-driven releases"], "rej": ["Friday big-bang deploys"]})

sub(id="progressive-delivery", comp="delivery-capacity", name="CI/CD & Progressive Delivery", phase="I", cat="Operations · Release safety",
    resp="Build, test and deploy every change through gated stages with canary analysis and automatic rollback.",
    inp="commits", out="deployed versions, rollback events", deps="CI, registry, Argo Rollouts, metrics", cons="All teams", own="pipelines",
    problem="Ship fast without breaking production.", without="Deploy-induced incidents.",
    guar=["Every deploy reversible within 5 min", "Canary evaluated on SLIs before full rollout", "Migrations backward compatible"], nong=["Bug-free code"],
    usecase="v42 canary shows +0.4% 5xx on trip transitions. Analysis fails, auto rollback, the author is notified with diff metrics.",
    derive="- Small batch size + automation.\n- Canary compares canary vs baseline pods on the same traffic.\n- Rollouts per region/AZ in sequence.",
    conc="One rollout per service at a time.", consistency="GitOps: desired state in Git.", idem="Re-applying manifests is idempotent.", order="Stages sequential.",
    restart="Rollout controller resumes from status.", scale="Per-service pipelines.", arch="CI (build, unit/integration/contract tests, SAST, image sign) → Argo CD sync → Argo Rollouts canary steps (5%, 25%, 50%, 100%) with AnalysisTemplates on Prometheus queries.",
    modules=[["CI", "Build/test/scan"], ["GitOps", "Desired state"], ["Rollouts", "Canary steps"], ["Analysis", "SLI comparison"]],
    d_arch=("""flowchart LR
  C["commit"] --> CI["CI"] --> IMG["signed image"] --> GO["GitOps repo"] --> AR["Argo Rollouts"] --> AN["Analysis"]""", "Pipeline."),
    d_seq=("""sequenceDiagram
  participant R as Rollouts
  participant P as Prometheus
  R->>R: setWeight 5%
  R->>P: error ratio canary vs stable (10 min)
  P-->>R: fail
  R->>R: abort → stable""", "Auto rollback."),
    d_state=("""stateDiagram-v2
  [*] --> Progressing
  Progressing --> Paused: analysis running
  Paused --> Progressing: pass
  Paused --> Aborted: fail
  Progressing --> Healthy""", "Rollout states."),
    d_flow=("""flowchart LR
  T["traffic"] --> S["stable 95%"] & C["canary 5%"]""", "Split."),
    d_fail=("""flowchart TB
  M["migration incompatible"] --> L["CI lint: forbid DROP/RENAME in same release"]""", "Static guard."),
    sql="-- Flyway migration example (expand step)\nALTER TABLE trip.trips ADD COLUMN pickup_place_id text;",
    data="Deployment records 1 year.", api="""kind: Rollout ... strategy: { canary: { steps: [ {setWeight: 5}, {pause: {duration: 10m}}, {analysis: {templates: [{templateName: error-rate}]}}, {setWeight: 50} ] } }""",
    mech=[("Canary analysis", "Statistical comparison of canary vs baseline SLIs over the same window. Comparing against the concurrent baseline cancels traffic seasonality.")],
    code="""# AnalysisTemplate
metrics: [{ name: error-rate, successCondition: "result[0] <= 0.001", provider: { prometheus: { query: "sum(rate(http_requests_total{code=~'5..',rollouts_pod_template_hash='{{args.canary-hash}}'}[5m])) / sum(rate(http_requests_total{rollouts_pod_template_hash='{{args.canary-hash}}'}[5m]))" } } }]""", cx="N/A.",
    fail=[F("Slow-burn bug past canary", "SLO burn", "Partial impact", "Manual rollback", "N/A")],
    alts=[["Blue/green", "Phase I", "Simple", "Few services"]],
    adrs=[A("Canary + analysis", "IV", "Deploy incidents.", [("Manual watch", "Unreliable"), ("Automated", "Chosen")], "Argo Rollouts.", "Safety.", "Setup.", "N/A")],
    qa=[Q("Operations", "Feature flags vs canaries?", "Canaries protect against bad *code* at the deployment level. Flags decouple *feature* exposure from deploys (dark launch, gradual enablement, kill switch). Use both: deploy dark via canary, then enable gradually via flags.", "")],
    tests=[T("Release", "Bad canary", "Rollback < 5 min")],
    evo=["I: Single pipeline + blue/green", "E: Test gates", "U: No change needed", "R: GitOps + canary analysis", "E: Region waves", "E: Global waves"],
    ideas={"now": ["Blue/green"], "next": ["Canary"], "adv": ["Automated bisect"], "rej": ["Manual deploy steps"]})

sub(id="capacity-cost", comp="delivery-capacity", name="Capacity Planning & Cost Management", phase="IV", cat="Operations · Efficiency",
    resp="Forecast peak load per service and city, provision headroom, run load tests, and attribute infrastructure cost to services and trips.",
    inp="traffic history, demand forecasts, event calendars, billing", out="capacity plans, autoscaling policies, cost reports", deps="Metrics, Demand forecasting, Billing exports", cons="Service owners, Finance", own="capacity models",
    problem="Peaks (New Year's Eve, concerts) must be absorbed, while cost per trip should fall with scale.", without="Outages on peak days; runaway bills.",
    guar=["Tier-1 services provisioned for forecast peak × 1.3", "Load test before known peaks", "Monthly cost per trip report"], nong=["Unforeseen viral spikes"],
    usecase="NYE forecast: 3.2× normal Friday peak in Mumbai. Dispatch shards pre-scaled, a load test at 4× was run a week before, and on the day p99 stays within SLO.",
    derive="- Per-service model: requests/trip × trips/s × CPU per request → cores.\n- Autoscaling handles variance, pre-scaling handles known events (autoscalers lag).\n- Cost tags per namespace.",
    conc="Planning artifacts are reviewed through pull requests. Only one pre-scale schedule per service is active at a time.", consistency="Reviewed monthly.", idem="Re-running models over the same inputs yields the same plan.", order="Not applicable: periodic planning.",
    restart="Not applicable: no runtime state, plans are documents and configs.", scale="Grows with services; automated models.", arch="Capacity models as code (Python), fed by metrics and forecasts, generate HPA/KEDA min replicas and pre-scale schedules. Cost via cloud billing exports joined with labels.",
    modules=[["Models", "Per service"], ["PreScaler", "Event schedules"], ["LoadTests", "k6/Gatling"], ["CostAttribution", "Labels → reports"]],
    d_arch=("""flowchart LR
  FC["demand forecast"] --> CM["capacity models"] --> HPA["autoscaler mins / pre-scale"]
  BILL["billing"] --> CA["cost attribution"] --> RPT["cost/trip"]""", "Planning loops."),
    d_seq=("""sequenceDiagram
  participant P as Planner
  participant K as K8s
  P->>K: pre-scale dispatch-mumbai min=40 at 21:00 NYE
  K-->>P: scheduled""", "Pre-scaling."),
    nostate="Planning documents and configs.",
    d_flow=("""flowchart LR
  T["trips/s"] --> R["req/trip"] --> C["cpu/req"] --> N["cores"]""", "Model."),
    d_fail=("""flowchart TB
  U["forecast too low"] --> A["autoscale + load shedding protect"]""", "Defense in depth."),
    sql="-- Cost query: SELECT service, sum(cost) / sum(trips) FROM billing JOIN trips_by_day USING (day) GROUP BY service;",
    data="Reports retained.", api="Capacity dashboards; pre-scale schedules (KEDA cron scaler)",
    mech=[("Pre-scaling", "Autoscalers react after load arrives, and pods take minutes to become ready. Scheduled minimums for known peaks remove that lag.")],
    code="""cores = trips_per_s * req_per_trip * cpu_ms_per_req / 1000 / target_util""", cx="N/A.",
    fail=[F("Unplanned spike", "SLO burn", "Degradation", "Shed + scale", "N/A")],
    alts=[["Overprovision always", "Rejected", "Cost", "Tiny scale"]],
    adrs=[A("Capacity models at Phase IV", "IV", "Many services.", [("Ad-hoc", "Surprises"), ("Models", "Chosen")], "Models.", "Predictable.", "Effort.", "N/A")],
    qa=[Q("Cost", "What drives cost per trip down at Phase V?", "Right-sizing (requests vs limits), spot instances for stateless and batch work, tiered storage for breadcrumbs and logs, tail sampling of traces, caching to cut provider costs (maps, SMS), and in-house routing replacing per-call APIs.", "")],
    tests=[T("Load", "Pre-peak test", "SLOs at 1.3× forecast")],
    evo=["N: Phase I uses one oversized instance pair", "N: Basic autoscaling", "N: Basic autoscaling", "I: Models + load tests", "E: Cost attribution, spot", "E: Regional capacity"],
    ideas={"now": ["n/a"], "next": ["Cost per trip"], "adv": ["Carbon-aware scheduling of batch"], "rej": ["Untagged resources"]})

# ======================================================================= Disaster Recovery
comp(id="disaster-recovery", domain="reliability", name="Backup, Restore & Disaster Recovery", tag="Reliability · Resilience", phase="I", kind="Operational capability",
     biz="Ensures data is never permanently lost and the service comes back within defined times after disasters.",
     eng="Backups with point-in-time recovery, verified restores, multi-AZ replication, and region-level DR with defined RPO/RTO and regular drills.",
     deploy="Nightly backups + WAL archiving (I); multi-AZ HA (II); cross-region backups (IV); warm DR region (V); multi-region active (VI).", data_own="Backups, DR runbooks, drill reports.",
     up=["observability"], down=["global-regions"], ext=["Object storage (cross-region)"],
     interfaces="Runbooks; restore automation; drill schedules.",
     problem="Backups that were never restored don't count. Region-wide failures and operator mistakes (DROP TABLE) happen.",
     fr=["PITR for all OLTP DBs", "Restore tests", "Cross-region copies", "DR failover runbooks", "Drills"], nfr=["RPO: ≤ 5 min (I) → ≤ seconds (VI)", "RTO: ≤ 4 h (I) → ≤ 15 min (VI)"],
     workload="All stateful systems.", success="Restores proven; drills pass.", failure="Unrecoverable data loss.",
     derive="Backups protect against logical errors (replicas copy mistakes too). PITR needs base backups + WAL. DR needs data in another region plus the ability to run there. Only drills prove both.",
     owns=["Backup policies", "Restore tooling", "DR process"], not_owns=["Application failover logic (Global regions)"], sync=["None"], **{"async": ["Backups", "Drills"]},
     boundary_why="DR is cross-cutting and needs central ownership with service participation.",
     hld=("""flowchart LR
  PG[("Primary DB")] -->|WAL| ARC[("WAL archive (object storage)")]
  PG -->|base backup nightly| ARC
  ARC -->|replicate| ARC2[("other region")]
  REST["Restore automation"] --> ARC
  DRILL["Drills"] --> REST""", "Backups, archives, cross-region copies and drills."),
     seq=("""sequenceDiagram
  participant O as Operator
  participant R as Restore tool
  participant S as Storage
  O->>R: PITR trips DB to 10:41:30
  R->>S: base backup + WAL to 10:41:30
  R-->>O: restored instance (verify checksums)""", "Point-in-time restore."),
     subdeps=[("dr-drills", "backup-restore")],
     flow="Continuous WAL archiving and nightly base backups, copied cross-region. Weekly automated restore tests and quarterly DR drills.",
     data="Backups encrypted with KMS; retention 35 days PITR, monthly snapshots 1 year.",
     rel=[["Verification", "Automated restore + checksum + row-count checks."]], sec=[["Encryption", "KMS keys per region; backups immutable (object lock)."]],
     adrs=[A("Immutable backups (object lock)", "II", "Ransomware/operator error.", [("Mutable", "Risky"), ("Object lock", "Chosen")], "WORM.", "Safety.", "Storage cost.", "N/A")],
     qa=[Q("Reliability", "Replication vs backup: why both?", "Replication protects availability against node/AZ loss but faithfully copies mistakes (a bad DELETE replicates instantly). Backups with PITR protect durability against logical corruption by restoring to before the mistake. Different failure classes need different mechanisms.", "")],
     impl_order=["backup-restore", "dr-drills"], pkg="platform/dr (pgBackRest config, restore jobs, runbooks)",
     tests=[T("Restore", "Weekly automated", "Pass"), T("Drill", "Region evacuation (VI)", "RTO met")],
     evo=[("I", "Nightly + WAL archive", "Object storage", "Manual restore test monthly", "Durability"), ("E", "Multi-AZ HA", "Sync standby", "Automated restore tests", "Reliability"), ("U", "No change needed", "—", "—", "—"),
          ("E", "Cross-region backups", "—", "Per-service RTO/RPO", "Services"), ("R", "Warm DR region", "Async replication", "DR drills", "Scale"), ("R", "Multi-region active with regional failover", "—", "Quarterly evacuations", "Global")],
     ideas={"now": ["WAL archiving"], "next": ["Restore automation"], "adv": ["Chaos-driven DR"], "rej": ["Untested backups"]})

sub(id="backup-restore", comp="disaster-recovery", name="Backup & Point-in-Time Restore", phase="I", cat="Durability · Operations",
    resp="Continuously back up every stateful store, support point-in-time restore, and verify restores automatically.",
    inp="DB WAL, snapshots", out="backups, restored instances, verification reports", deps="pgBackRest/WAL-G, object storage, KMS", cons="On-call, DR", own="backup policies",
    problem="Recover from logical corruption and catastrophic loss with minimal data loss.", without="Permanent data loss.",
    guar=["RPO ≤ 5 min for OLTP (WAL archive)", "Weekly verified restore per DB", "Backups immutable for retention"], nong=["Instant restore of huge DBs"],
    usecase="An engineer runs a bad migration deleting 30% of saved_places at 10:42. PITR to 10:41:30 on a side instance, the missing rows are copied back by script, and the incident is closed with no user-visible loss.",
    derive="- Base backups + continuous WAL → any point in time.\n- Restore to a side instance for surgical recovery.\n- Verification by automated restore + checks.",
    conc="Backup tools coordinate with DB.", consistency="Restore point consistent (WAL replay).", idem="Restores repeatable.", order="WAL replay order.",
    restart="Backup jobs resume.", scale="Incremental backups; parallel restore.", arch="pgBackRest: full weekly + diff daily + WAL archive to object storage (encrypted, object-locked), cross-region copy. Restore pipeline: provision → restore → verify → report.",
    modules=[["BackupJobs", "Full/diff/WAL"], ["Copier", "Cross-region"], ["RestoreVerifier", "Weekly"]],
    d_arch=("""flowchart LR
  DB[("DB")] --> BR["pgBackRest"] --> OS[("object storage (lock)")] --> OS2[("DR region copy")]
  RV["RestoreVerifier"] --> OS""", "Backup flow."),
    d_seq=("""sequenceDiagram
  participant V as Verifier
  participant S as Storage
  participant T as Temp DB
  V->>S: fetch latest + WAL
  V->>T: restore
  V->>T: checks (row counts vs prod ±, checksums)
  V-->>V: report pass""", "Verification."),
    nostate="Backups are artifacts with retention, not lifecycles.",
    d_flow=("""flowchart LR
  WAL["WAL segments"] --> A["archive"] --> R["replay to T"]""", "PITR."),
    d_fail=("""flowchart TB
  A["archive gap"] --> AL["alert on WAL archive lag > 5 min"]""", "Archive monitoring."),
    sql="-- Recovery target: restore_command + recovery_target_time = '2026-11-02 10:41:30+05:30'",
    data="35 days PITR; monthly 1 year.", api="Runbook: restore-pitr.sh <cluster> <timestamp> <target>",
    mech=[("WAL-based PITR", "Replaying the write-ahead log from a base backup up to a timestamp reconstructs the exact state at that moment.")],
    code="pgbackrest --stanza=trips --type=time \"--target=2026-11-02 10:41:30\" --target-action=promote restore", cx="Restore time ∝ data size.",
    fail=[F("Backup corruption", "Verification", "Unusable backup", "Previous backup", "N/A")],
    alts=[["Managed DB backups", "Viable", "Less ops", "Managed DBs"]],
    adrs=[A("Weekly automated restore tests", "II", "Trust.", [("Manual occasional", "Unreliable"), ("Automated", "Chosen")], "Automated.", "Proven backups.", "Compute cost.", "N/A")],
    qa=[Q("Reliability", "How do you restore one table without rolling back the whole database?", "Restore to a side instance at the target time, extract the affected rows (by key), and apply them to production through a reviewed script or domain commands, respecting invariants (e.g. ledger entries are never rewritten; use correcting entries).", "")],
    tests=[T("Restore", "Weekly", "Pass")],
    evo=["I: Nightly + WAL", "E: Automated verification", "U: No change needed", "E: Cross-region copies", "E: Faster restores (incremental)", "E: Regional"],
    ideas={"now": ["WAL archive"], "next": ["Automation"], "adv": ["Logical backups for selective restore"], "rej": ["Replicas as backups"]})

sub(id="dr-drills", comp="disaster-recovery", name="DR Failover & Drills", phase="IV", cat="Resilience · Operations",
    resp="Define RPO/RTO per tier, maintain runbooks and automation for AZ and region failure, and prove them with scheduled drills.",
    inp="failure scenarios", out="drill reports, improved runbooks", deps="Backups, Global regions failover, Observability", cons="Leadership, On-call", own="runbooks, drill schedule",
    problem="Failover that's never practised fails when needed.", without="Long outages in real disasters.",
    guar=["Quarterly drills for tier-1", "Measured RTO/RPO vs targets", "Action items tracked"], nong=["Zero data loss in region failover (async replication)"],
    usecase="Quarterly drill: evacuate AZ-b. Dispatch shards fail over in 40 s, trip DB promotes its standby in 25 s, and two dashboards had stale alerts, which become action items.",
    derive="- Scenario catalog (AZ loss, region loss, DB corruption, Kafka loss, DNS failure).\n- Game days with explicit hypotheses and measurements.",
    conc="One drill at a time with change freeze.", consistency="Measured outcome: each drill records achieved RPO (replication lag at cut) and RTO against tier targets.", idem="Drills repeatable.", order="Scenario steps scripted.",
    restart="Drill abort procedure.", scale="Expand scope as maturity grows.", arch="Runbooks as code (automation where possible), drill calendar, chaos tooling (fault injection), and post-drill reviews.",
    modules=[["ScenarioCatalog", "What can fail"], ["Runbooks", "Automated steps"], ["ChaosTools", "Injection"], ["Reviews", "Action items"]],
    d_arch=("""flowchart LR
  SC["scenarios"] --> GD["game day"] --> CH["fault injection"] --> OBS["measure RTO/RPO"] --> RV["review"] --> RB["runbooks"]""", "Drill cycle."),
    d_seq=("""sequenceDiagram
  participant L as Drill lead
  participant C as Chaos tool
  participant S as Systems
  L->>C: block AZ-b
  S->>S: failover
  L->>L: record times
  L->>C: restore""", "Drill."),
    d_state=("""stateDiagram-v2
  [*] --> Planned
  Planned --> Running
  Running --> Aborted
  Running --> Completed
  Completed --> Reviewed""", "Drill lifecycle."),
    d_flow=("""flowchart LR
  T["targets"] --> M["measured"] --> G["gaps"] --> A["actions"]""", "Learning loop."),
    d_fail=("""flowchart TB
  D["drill causes real outage"] --> AB["abort criteria + blast radius limits"]""", "Safety."),
    sql="-- Drill reports stored in docs repo; metrics in observability.",
    data="Reports retained.", api="Runbooks: region-evacuate, az-evacuate, db-promote, kafka-cluster-failover",
    mech=[("Chaos engineering", "Inject real faults under control to verify hypotheses about resilience, instead of assuming them.")],
    code="# example: block traffic to AZ-b nodes\nkubectl cordon -l topology.kubernetes.io/zone=az-b && kubectl drain ...", cx="N/A.",
    fail=[F("Runbook outdated", "Drill failure", "Slow recovery", "Update + automate", "N/A")],
    alts=[["Tabletop only", "Insufficient", "No measurement", "Early phases"]],
    adrs=[A("Quarterly drills", "IV", "Confidence.", [("Annual", "Too rare"), ("Quarterly", "Chosen")], "Quarterly.", "Practised.", "Effort.", "N/A")],
    qa=[Q("Reliability", "What RPO is acceptable for trips during region failover?", "Seconds of async replication lag. In-flight trips lost in that window are reconstructed from device-side state (driver app holds the trip and breadcrumbs) and PSP records. Payments use idempotency keys, so replays don't double-charge. Synchronous cross-region replication would add 100+ ms to every write, which is not acceptable.", "")],
    tests=[T("Drill", "AZ evacuation", "RTO < 2 min")],
    evo=["N: Phase I uses a restore runbook only", "N: Multi-AZ automatic failover", "N: Multi-AZ automatic failover", "I: DR runbooks + drills", "E: Warm region drills", "R: Region evacuation drills"],
    ideas={"now": ["n/a"], "next": ["Chaos"], "adv": ["Continuous chaos"], "rej": ["Untested DR"]})

# ======================================================================= Global Regions
comp(id="global-regions", domain="global", name="Global Regions (Routing, Ownership, Replication, Failover)", tag="Global · Architecture", phase="VI", kind="Infrastructure (Phase VI)",
     biz="Serves riders on every continent with low latency, keeps each country's data where the law requires, and survives the loss of an entire region.",
     eng="Region-as-cell architecture: each city has a home region that owns its data and ride flow. Traffic is routed by city, data replicates asynchronously to a DR region, and failover moves city ownership with fencing.",
     deploy="Phase VI only; designed to keep every in-region component unchanged.", data_own="City→region ownership map, replication topology, failover state.",
     up=["admin-policy", "disaster-recovery", "identity"], down=["api-gateway", "dispatch", "trip", "payments"], ext=["Geo-DNS / anycast", "Cloud regions"],
     interfaces="Global control plane `GET /ownership/cities/{city}`; routing headers `x-atlas-city-region`; failover API.",
     problem="Cross-ocean latency breaks dispatch SLOs, laws require in-country data, and a single region is a continental single point of failure.",
     fr=["Route requests to the city's home region", "Keep a ride's data in one region", "Async replication to DR region", "Failover a region's cities with fencing", "Global identity and config"], nfr=["No cross-region calls on ride critical path", "Region failover ≤ 15 min", "RPO ≤ replication lag (seconds)"],
     workload="Phase VI: 5+ regions.", success="Local latency everywhere; survive region loss.", failure="Split brain; residency violations; global outage from a control-plane bug.",
     derive="Rides are local, so partition by city → region. A single writer per city at a time requires an ownership registry with epochs (fencing). Failover changes the owner and bumps the epoch, and writes from the old epoch are rejected.",
     owns=["Ownership map", "Routing", "Replication", "Failover orchestration"], not_owns=["In-region services"], sync=["Ownership lookups (cached)"], **{"async": ["Replication", "Failover"]},
     boundary_why="Keeps global concerns out of every service. Services only need to respect the city's epoch.",
     hld=("""flowchart TB
  U["User"] --> DNS["Geo-DNS"] --> EDGE["Nearest edge"]
  EDGE -->|city→region lookup| CP["Global control plane: ownership + epoch"]
  EDGE --> RA["Home region A"]
  RA --> DBA[("Region A DBs")]
  DBA -->|async replication| DBB[("DR region B")]
  FO["Failover orchestrator"] --> CP
  FO --> RB["Region B services (promote)"]""", "Edge routes by city ownership. Data replicates to DR. Failover flips ownership and epoch."),
     seq=("""sequenceDiagram
  participant R as Rider (in NYC, account EU)
  participant E as US edge
  participant C as Control plane (cached)
  participant US as US region
  R->>E: POST ride request (pickup NYC)
  E->>C: owner(NYC)
  C-->>E: us-east, epoch 7
  E->>US: forward (x-city-epoch 7)
  US->>US: full ride flow locally""", "Routing a traveller."),
     subdeps=[("regional-failover", "city-routing"), ("regional-failover", "cross-region-replication")],
     flow="The edge resolves the city's owner (cached). Requests carry the epoch, and services reject writes whose epoch doesn't match their region's current ownership. Replication is continuous. Failover is orchestrated with fencing.",
     data="`city_ownership(city, home_region, dr_region, epoch, state)` in a consensus-backed global store, cached everywhere.",
     rel=[["Control plane outage", "Regions use cached ownership."], ["Split brain", "Epoch fencing in DB writes."]], sec=[["Residency", "Replication topology respects residency (EU→EU DR)."]],
     adrs=[A("City as the unit of regional ownership", "VI", "Locality of rides.", [("User-home-region", "Cross-region dispatch"), ("City-home-region", "Chosen")], "City ownership.", "Local ride path.", "Travelling users read profile from global directory.", "N/A")],
     qa=[Q("Global architecture", "How do you prevent split brain when region A is partitioned but alive?", "Ownership changes require the global control plane (consensus) to bump the city's epoch to B. Region A's services check their epoch lease. When they can't renew it with the control plane within the lease time, they stop accepting writes for those cities (self-fencing). Writes also carry the epoch, and the DB rejects stale epochs. So A stops writing before B starts, at the cost of a brief unavailability window.", "")],
     impl_order=["city-routing", "cross-region-replication", "regional-failover"], pkg="global/ (control plane, edge routing filter, failover orchestrator)",
     tests=[T("Drill", "Region evacuation", "≤ 15 min; no split-brain writes"), T("Partition", "Isolate region A from control plane", "A self-fences after lease")],
     evo=[("N", "Single region (Phase I)", "—", "—", "Not needed"), ("N", "Single region", "—", "—", "—"), ("N", "Single region", "—", "—", "—"), ("N", "Single region, multi-AZ", "Cross-region backups", "—", "—"), ("N", "Warm DR region only (no active traffic)", "Async replication", "Manual failover", "—"),
          ("I", "Region cells with city ownership", "Global control plane", "Epoch fencing, drills", "Multi-continent")],
     ideas={"now": ["Design city ids and partition keys early (cheap)"], "next": ["n/a"], "adv": ["Active-active per city with CRDTs (rejected for money)"], "rej": ["Global synchronous database for everything"]})

sub(id="city-routing", comp="global-regions", name="Geo Routing & City Ownership", phase="VI", cat="Global · Routing",
    resp="Route every request to the region that owns the relevant city, using a cached global ownership map with epochs.",
    inp="request + location/city hint", out="routed request with city and epoch headers", deps="Global control plane", cons="All regional services", own="city_ownership",
    problem="Find the owning region quickly and consistently, even during control-plane outages.", without="Writes in the wrong region; latency.",
    guar=["Requests for a city reach its current owner", "Epoch attached for fencing", "Cached map usable if control plane down"], nong=["Instant propagation of changes (≤ seconds)"],
    usecase="Rider at Heathrow taps request. The edge maps pickup → city LON → eu-west epoch 3 and forwards.",
    derive="- City from pickup coordinates (geofence lookup at edge).\n- Ownership map is small (thousands of cities), so cache fully at every edge with watch-based updates.",
    conc="Map updates are atomic snapshot swaps.", consistency="Eventual at edges; fencing ensures safety.", idem="Lookups are pure reads with no side effects.", order="Epoch numbers monotonic.",
    restart="Edges load snapshot.", scale="Tiny map; CPU-only lookups.", arch="Control plane (etcd/Spanner) holds ownership. Edges watch for changes, and a routing filter resolves the city and adds headers.",
    modules=[["CityResolver", "Point → city"], ["OwnershipCache", "Watch-based"], ["RouterFilter", "Forward + headers"]],
    d_arch=("""flowchart LR
  REQ["request"] --> CR["CityResolver"] --> OC["OwnershipCache"] --> RF["RouterFilter"] --> REG["region"]
  CP["control plane"] -->|watch| OC""", "Edge routing."),
    d_seq=("""sequenceDiagram
  participant E as Edge
  participant C as Cache
  E->>C: owner(LON)
  C-->>E: eu-west, epoch 3
  E->>E: forward + headers""", "Lookup."),
    nostate="A cached map. Ownership states are managed by failover.",
    d_flow=("""flowchart LR
  P["pickup"] --> CITY["city"] --> OWN["region, epoch"]""", "Resolution."),
    d_fail=("""flowchart TB
  CP["control plane down"] --> C["cached map"]""", "Resilience."),
    sql="CREATE TABLE global.city_ownership (city text PRIMARY KEY, home_region text NOT NULL, dr_region text NOT NULL, epoch bigint NOT NULL, state text NOT NULL);",
    data="Global, replicated by consensus.", api="""x-atlas-city: LON
x-atlas-city-epoch: 3""",
    mech=[("Watch-based cache", "Edges subscribe to changes and swap snapshots, so lookups are local reads.")],
    code="""Owner o = ownership.get(cityResolver.resolve(req.pickup())); req.header("x-atlas-city-epoch", o.epoch()); forward(o.region(), req);""", cx="O(1).",
    fail=[F("Stale cache after failover", "Epoch mismatch error from region", "Retry after refresh", "Refresh + retry", "No wrong writes")],
    alts=[["Route by user home", "Rejected", "Cross-region dispatch", "Never"]],
    adrs=[A("Edge-resolved ownership", "VI", "Latency.", [("Region forwards", "Extra hop"), ("Edge resolves", "Chosen")], "Edge.", "One hop.", "Edge complexity.", "N/A")],
    qa=[Q("Global", "A trip starts in one city and ends in another owned by a different region. Who owns it?", "The pickup city's region owns the trip for its whole life. Dropoff in another region's city is just a coordinate. Analytics replicate summaries globally.", "")],
    tests=[T("Routing", "Every city", "Correct region")],
    evo=["N: Single region in Phase I", "N: Single region", "N: Single region", "N: Single region", "N: City→shard only", "I: City→region routing"],
    ideas={"now": ["Embed city in every key"], "next": ["n/a"], "adv": ["Anycast with per-city steering"], "rej": ["User-home routing"]})

sub(id="cross-region-replication", comp="global-regions", name="Cross-Region Replication & Residency-Aware Topology", phase="V", cat="Global · Data",
    resp="Replicate each region's operational data asynchronously to its designated DR region, respecting residency constraints, and monitor replication lag.",
    inp="WAL/CDC streams per region", out="replica databases and topics in DR region", deps="DB replication, Kafka MirrorMaker, residency policy", cons="Regional failover, Global analytics", own="replication topology",
    problem="Keep a warm copy far away without adding latency to writes, and never replicate data outside its allowed jurisdiction.", without="Region loss = data loss; or residency violations.",
    guar=["Replication lag monitored with RPO alerts", "Topology only replicates to residency-compatible regions", "Replicas read-only until promotion"], nong=["Zero data loss (async)"],
    usecase="eu-west replicates to eu-central (EU residency). us-east replicates to us-west. India data stays in in-country regions.",
    derive="- Async physical replication for OLTP (low overhead).\n- Kafka mirroring for topics (consumer offsets translated).\n- Residency policy as data deciding pairs.",
    conc="Replication is single-writer-to-replica.", consistency="Asynchronous; lag seconds.", idem="Replication protocols are idempotent by LSN/offset.", order="Applied in log order.",
    restart="Replication resumes from LSN/offset.", scale="Per-DB streams; bandwidth planning.", arch="PostgreSQL streaming replication (cross-region standby) or managed equivalents; MirrorMaker 2 for Kafka; residency policy validated by a scanner.",
    modules=[["DbReplication", "Cross-region standbys"], ["TopicMirroring", "MM2"], ["ResidencyPolicy", "Allowed pairs"], ["LagMonitor", "RPO alerts"]],
    d_arch=("""flowchart LR
  A[("Region A primary")] -->|WAL async| B[("Region B standby")]
  KA[["Kafka A"]] -->|MM2| KB[["Kafka B (mirror)"]]
  RP["ResidencyPolicy"] -.-> A & KA""", "Replication topology."),
    d_seq=("""sequenceDiagram
  participant A as Primary A
  participant B as Standby B
  participant M as Monitor
  A->>B: WAL stream
  M->>B: replay lag?
  B-->>M: 1.8 s""", "Lag monitoring."),
    nostate="Replication streams have no business lifecycle.",
    d_flow=("""flowchart LR
  W["write"] --> LA["local commit"] --> WAL["WAL"] --> RB["replica"]""", "Async path."),
    d_fail=("""flowchart TB
  L["lag > RPO"] --> AL["alert; consider throttling batch writes"]""", "RPO protection."),
    sql="-- primary_conninfo for cross-region standby; monitor: SELECT now() - pg_last_xact_replay_timestamp();",
    data="Replicas follow primary retention.", api="Topology config (YAML) validated in CI against residency rules",
    mech=[("Asynchronous log shipping", "The primary commits locally and ships WAL. Replicas apply in order. Lag equals potential data loss on failover.")],
    code="""SELECT extract(epoch FROM now() - pg_last_xact_replay_timestamp()) AS lag_seconds;""", cx="Bandwidth ∝ write rate.",
    fail=[F("Network partition", "Lag growth", "RPO risk", "Alert", "Bounded by lag")],
    alts=[["Synchronous cross-region", "Rejected", "Latency", "Tiny critical data (ownership map uses consensus)"]],
    adrs=[A("Async replication", "V", "Latency.", [("Sync", "Slow writes"), ("Async", "Chosen")], "Async.", "Fast writes.", "RPO > 0.", "N/A")],
    qa=[Q("Privacy", "How do you prove no EU personal data reaches a US region?", "Topology config is validated against the residency policy in CI. A scanner samples data in each region for jurisdiction tags. Analytics exports are pseudonymized and aggregated, and logs are region-local.", "")],
    tests=[T("Lag", "Peak write load", "Lag < 5 s"), T("Residency", "Topology lint", "Invalid pair rejected")],
    evo=["N: Single region in Phase I", "N: Single region", "N: Single region", "N: Cross-region backups only", "I: Warm DR replication", "E: Residency-aware multi-region topology"],
    ideas={"now": ["n/a"], "next": ["n/a"], "adv": ["Logical replication for selective tables"], "rej": ["Sync cross-ocean writes"]})

sub(id="regional-failover", comp="global-regions", name="Regional Failover with Fencing", phase="VI", cat="Global · Resilience",
    resp="Move ownership of a failed region's cities to their DR region safely (no split brain), promote replicas, redirect traffic, and reconcile in-flight state.",
    inp="region health, operator decision", out="new ownership epochs, promoted databases, routing changes", deps="Control plane, Replication, Routing, Reconciliation jobs", cons="All", own="failover state",
    problem="Fail over quickly without two regions writing the same city's data.", without="Long outages or corrupted data.",
    guar=["Old region self-fences before new region accepts writes", "Epoch increments monotonically", "Post-failover reconciliation of in-flight trips and payments"], nong=["Zero data loss"],
    usecase="eu-west outage: operator triggers failover for 140 EU cities. The control plane bumps epochs, eu-west's leases expire (self-fenced), eu-central promotes replicas, edges route there, and in-flight trips are reconstructed from driver apps and PSP data.",
    derive="- Leases + epochs give fencing.\n- Promotion only after the lease expiry window.\n- Reconciliation for writes lost in lag.",
    conc="Control plane serializes ownership changes (consensus).", consistency="Single writer per city at any time.", idem="Failover steps idempotent (epoch target).", order="Steps: fence → wait lease → promote → route → reconcile.",
    restart="Orchestrator resumes from recorded step.", scale="Per-city batches.", arch="Failover orchestrator (workflow) operating per city group: bump epoch in control plane, wait max lease TTL, promote DR databases, flip routing, then run reconciliation (trips from driver apps, payments from PSP idempotency keys).",
    modules=[["HealthDetector", "Region health signals"], ["Orchestrator", "Ordered steps"], ["Promoter", "DB/Kafka promotion"], ["Reconciler", "In-flight repair"]],
    d_arch=("""flowchart LR
  HD["HealthDetector"] --> OPS["operator approval"] --> OR["Orchestrator"]
  OR --> CP["Control plane epoch++"] --> W["wait lease TTL"] --> PR["Promoter"] --> RT["Routing"] --> RC["Reconciler"]""", "Ordered failover."),
    d_seq=("""sequenceDiagram
  participant O as Orchestrator
  participant C as Control plane
  participant A as Region A
  participant B as Region B
  O->>C: set owner(LON)=B, epoch 4
  A--xC: lease renew fails → stop writes (self-fence)
  O->>O: wait lease TTL (30 s)
  O->>B: promote DB, accept epoch 4
  O->>O: routing updated
  O->>B: reconcile in-flight""", "Fenced failover."),
    d_state=("""stateDiagram-v2
  [*] --> Normal
  Normal --> Fencing
  Fencing --> Promoting
  Promoting --> Serving_DR
  Serving_DR --> Failback: region restored
  Failback --> Normal""", "City ownership during failover."),
    d_flow=("""flowchart LR
  E3["epoch 3 writes (A)"] -.->|rejected after fence| X["✗"]
  E4["epoch 4 writes (B)"] --> OK["accepted"]""", "Fencing."),
    d_fail=("""flowchart TB
  P["promotion fails"] --> M["manual runbook; keep fenced (unavailable) rather than split brain"]""", "Prefer unavailability to inconsistency."),
    sql="""-- every regional write path checks epoch (example)
UPDATE trip.trips SET state=:to WHERE id=:id AND :epoch = (SELECT epoch FROM local.city_epoch WHERE city=:city);""",
    data="Failover logs retained.", api="""POST /global/failover {cities:[...], target_region, reason} -> workflow id""",
    mech=[("Self-fencing via leases", "A region may write for a city only while it holds an unexpired ownership lease from the control plane. Partitioned regions lose leases and stop, so the new owner waits one lease TTL before writing."), ("Reconciliation from clients and PSPs", "Lost in-flight updates are rebuilt from device state (driver app holds the trip), payment idempotency keys and PSP records.")],
    code="""public void failover(List<String> cities, String target) {
    long epoch = controlPlane.reassign(cities, target);     // consensus write
    sleep(leaseTtl.plusSeconds(5));                          // old owner self-fenced by now
    promoter.promote(target, cities);
    routing.refresh(cities);
    reconciler.start(cities, epoch);
}""", cx="O(cities).",
    fail=[F("Old region still writing", "Epoch mismatch", "Rejected writes", "Fencing", "No split brain"), F("Lost writes in lag", "Reconciliation", "Some updates missing", "Rebuild from clients/PSP", "Bounded")],
    alts=[["Automatic failover", "Risky", "Fast but false positives", "Only with strong health consensus"], ["Active-active per city", "Rejected", "Conflicts on money", "Never for ledger"]],
    adrs=[A("Operator-approved failover", "VI", "False positives costly.", [("Fully automatic", "Risky"), ("Approved + automated steps", "Chosen")], "One-click approved.", "Safety.", "Human latency (minutes).", "Automate once drills show reliable detection.")],
    qa=[Q("Global architecture", "After failback to region A, how do you avoid losing writes made in B?", "Failback is another ownership change. Fence B (epoch++), let replication B→A catch up to zero lag (B was primary, A becomes standby during the outage and is re-seeded), then promote A and route. No writes are lost because failback waits for zero lag, unlike emergency failover.", "")],
    tests=[T("Drill", "Region failover", "≤ 15 min; zero stale-epoch writes"), T("Partition", "Control-plane isolation", "Self-fence")],
    evo=["N: Single region in Phase I", "N: Single region", "N: Single region", "N: Single region", "N: Manual DR runbook only", "I: Fenced orchestrated failover"],
    ideas={"now": ["n/a"], "next": ["n/a"], "adv": ["Automatic failover with quorum health"], "rej": ["DNS flip without fencing"]})

# ======================================================================= Privacy Infrastructure
comp(id="privacy", domain="global", name="Privacy Infrastructure (Erasure, PII Protection, Residency)", tag="Compliance · Privacy", phase="II", kind="Platform capability",
     biz="Honours users' rights (access, deletion), protects personal data, and keeps data where laws require.",
     eng="A data-subject-request (DSR) orchestrator fanning out to every data owner, field-level encryption/tokenization for PII, retention enforcement, and residency guardrails.",
     deploy="Manual DSR runbook (I); orchestrator + per-service handlers (II–III); catalog-driven (IV); regional (VI).", data_own="DSR cases, PII encryption keys (via KMS), retention policies.",
     up=["data-governance", "identity"], down=["rider-profile", "location-history", "event-pipeline", "payments", "support"], ext=["KMS"],
     interfaces="`POST /v1/privacy/requests` (export/delete); internal `ErasureHandler` contract per service; events `ErasureRequested`, `ErasureCompleted`.",
     problem="Personal data spreads across dozens of services, logs, lakes and backups. Deletion must be complete yet respect legal retention (finance, safety).",
     fr=["Access/export requests", "Deletion requests within 30 days", "Legal-hold exceptions", "Field-level encryption", "Retention enforcement"], nfr=["DSR completion ≤ 30 days", "Proof of completion per system"],
     workload="DSRs ≈ 0.01%/month of users.", success="Complete, provable compliance.", failure="Fines; trust loss.",
     derive="Completeness requires a registry of every system holding personal data (catalog + handler registration). Fan-out with acknowledgements per handler. Legal retention means anonymization or minimization instead of deletion for some records. Backups: crypto-shredding (delete per-user keys) or expiry.",
     owns=["DSR orchestration", "PII crypto tooling", "Retention policy registry"], not_owns=["Each system's deletion logic (owners implement handlers)"], sync=["DSR intake"], **{"async": ["Fan-out", "Verification"]},
     boundary_why="Central orchestration ensures completeness. Owners implement deletions because only they know their data.",
     hld=("""flowchart LR
  U["User"] --> IN["DSR intake (verified)"] --> ER["Erasure orchestrator"]
  CAT["Catalog: systems with PII"] --> ER
  ER -->|ErasureRequested| H1["Rider handler"] & H2["Location handler"] & H3["Lake handler"] & H4["Support handler"]
  H1 & H2 & H3 & H4 -->|ErasureCompleted| ER --> PROOF["Completion report"]
  KMS["per-user keys"] -->|crypto-shred| BK["backups"]""", "Orchestrated fan-out with per-system proof."),
     seq=("""sequenceDiagram
  participant U as User
  participant O as Orchestrator
  participant R as Rider svc
  participant L as Lake
  U->>O: delete my account
  O->>O: verify identity, check obligations (balance, disputes)
  O->>R: ErasureRequested(user)
  O->>L: ErasureRequested(user)
  R-->>O: completed (anonymized trips, deleted profile)
  L-->>O: completed (row deletes + snapshot expiry)
  O-->>U: confirmation""", "Deletion."),
     subdeps=[("pii-protection", "erasure-orchestrator")],
     flow="Verified requests start a durable workflow that fans out to registered handlers, tracks acknowledgements and deadlines, escalates missing ones, and produces a completion report.",
     data="`dsr_cases(id, user, type, state, due_at)`, `dsr_tasks(case_id, system, state, completed_at, evidence)`.",
     rel=[["Durability", "Workflow engine; retries; escalation."]], sec=[["Verification", "Strong auth before DSR."], ["Minimization", "Exports exclude other users' data."]],
     adrs=[A("Handler contract per system", "II", "Completeness.", [("Central deletes", "Unsafe"), ("Handlers", "Chosen")], "Contract + registry.", "Owner expertise.", "Coordination.", "N/A")],
     qa=[Q("Privacy", "How do you delete a user from backups?", "Two options. (1) Retention: backups expire within 35 days, and the DSR response documents that backup copies are deleted on expiry and never restored into production without re-applying erasures (an erasure log is replayed after any restore). (2) Crypto-shredding: PII fields encrypted with per-user keys, so deleting the key renders all copies unreadable. Phase IV adopts (2) for high-sensitivity fields.", "")],
     impl_order=["erasure-orchestrator", "pii-protection"], pkg="com.atlas.privacy (DsrIntake, ErasureWorkflow, ErasureHandler SPI, FieldCrypto)",
     tests=[T("Completeness", "Seed user across systems; delete", "No PII found by scanner"), T("Legal hold", "User with dispute", "Deletion deferred with notice")],
     evo=[("N", "Phase I runs a manual runbook + SQL scripts with audit", "—", "—", "Low volume"), ("I", "Orchestrator + handlers", "DSR tables", "Deadlines", "GDPR scale"), ("E", "Event-based fan-out", "—", "—", "Events"),
          ("E", "Catalog-driven registry; field crypto", "—", "Crypto-shredding", "Many systems"), ("E", "Automated verification scanners", "—", "—", "Scale"), ("E", "Regional DSR handling, residency guardrails", "—", "—", "Global")],
     ideas={"now": ["Runbook + audit"], "next": ["Orchestrator"], "adv": ["Privacy-preserving analytics (DP)"], "rej": ["Soft-delete flags only"]})

sub(id="erasure-orchestrator", comp="privacy", name="Data Subject Request (Erasure/Export) Orchestrator", phase="II", cat="Compliance · Workflow",
    resp="Verify, track and fan out access and deletion requests to every system holding the user's data, enforce deadlines and legal holds, and produce proof of completion.",
    inp="verified DSRs, handler registry, legal holds", out="per-system tasks, completion reports, exports", deps="Workflow engine, Catalog, Identity, Support (holds)", cons="Users, Compliance", own="dsr_cases, dsr_tasks",
    problem="Complete, timely, provable erasure across a distributed system.", without="Incomplete deletions, regulatory breaches.",
    guar=["Every registered system acknowledges or escalates within SLA", "Legal holds evaluated before deletion", "Completion report per case"], nong=["Deleting data under legal retention"],
    usecase="Rider requests deletion. The balance is zero and there are no open disputes, so 14 systems complete within 5 days. Finance records are kept minimized (pseudonymous id) as legally required.",
    derive="- Durable workflow per case with tasks per handler.\n- Handlers idempotent (re-runnable).\n- Registry from catalog (systems tagged with user-linked PII).",
    conc="One open case per user per type.", consistency="Case completes when all tasks done.", idem="Handlers idempotent by case id.", order="Identity deletion last (so other handlers can still resolve ids).",
    restart="Workflow durable.", scale="Low volume, wide fan-out.", arch="Temporal workflow: verify → obligations check → fan out ErasureRequested → wait for all ErasureCompleted (timeouts → escalate) → identity tombstone → report.",
    modules=[["Intake", "Verification"], ["Obligations", "Balance, disputes, holds"], ["FanOut", "Events per handler"], ["Tracker", "Acks, deadlines"], ["Reporter", "Proof"]],
    d_arch=("""flowchart LR
  IN["Intake"] --> OB["Obligations"] --> FO["FanOut"] --> H["handlers"] --> TR["Tracker"] --> RP["Reporter"]""", "Workflow."),
    d_seq=("""sequenceDiagram
  participant W as Workflow
  participant H as Handler
  W->>H: ErasureRequested(case 9, user u)
  H->>H: delete/anonymize (idempotent)
  H-->>W: ErasureCompleted(case 9, evidence)
  W->>W: all done → identity tombstone → report""", "Fan-out and completion."),
    d_state=("""stateDiagram-v2
  [*] --> Received
  Received --> Verified
  Verified --> Blocked: obligations/hold
  Blocked --> Verified: resolved
  Verified --> InProgress
  InProgress --> Completed
  InProgress --> Escalated: task overdue""", "Case lifecycle."),
    d_flow=("""flowchart LR
  REG["catalog registry"] --> T["tasks"] --> E["evidence"] --> R["report"]""", "Proof chain."),
    d_fail=("""flowchart TB
  H["handler down"] --> R["retry; escalate at SLA"]""", "Escalation."),
    sql="""CREATE TABLE privacy.dsr_cases (id uuid PRIMARY KEY, user_id uuid NOT NULL, type text NOT NULL, state text NOT NULL, due_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE privacy.dsr_tasks (case_id uuid, system text, state text NOT NULL, evidence jsonb, completed_at timestamptz, PRIMARY KEY(case_id, system));""",
    data="Case records retained as proof (minimized).", api="""interface ErasureHandler { ErasureEvidence erase(UUID userId, UUID caseId); ExportBundle export(UUID userId); }""",
    mech=[("Registry-driven completeness", "Tasks are generated from the catalog's list of systems with user-linked PII. A new system that registers PII is automatically included.")],
    code="""for (String sys : registry.systemsWithPii()) tasks.create(caseId, sys);
events.publish(new ErasureRequested(caseId, userId));
Workflow.await(Duration.ofDays(25), () -> tasks.allDone(caseId));""", cx="O(systems).",
    fail=[F("Missing handler", "Registry check", "Incomplete", "Escalate to owner", "Tracked")],
    alts=[["Manual tickets per team", "Phase I", "Simple", "Few systems"]],
    adrs=[A("Identity deleted last", "II", "Other handlers need ids.", [("Identity first", "Breaks fan-out"), ("Last", "Chosen")], "Last.", "Completeness.", "Longer case.", "N/A")],
    qa=[Q("Privacy", "Trips are financial records. How can they be 'deleted'?", "Anonymize: unlink rider identity (replace rider_id with an irreversible pseudonym), remove addresses and precise routes, and keep amounts, dates and city for financial and tax obligations. The ledger keeps account ids that no longer resolve to a person.", "")],
    tests=[T("Completeness", "Seeded user", "All systems complete"), T("Hold", "Open dispute", "Blocked")],
    evo=["N: Phase I uses a manual runbook", "I: Orchestrator", "E: Event fan-out", "E: Catalog-driven", "E: Automated verification", "E: Regional"],
    ideas={"now": ["Runbook"], "next": ["Orchestrator"], "adv": ["Self-service export portal"], "rej": ["Soft delete only"]})

sub(id="pii-protection", comp="privacy", name="PII Protection & Residency Guardrails", phase="IV", cat="Security · Data protection",
    resp="Encrypt or tokenize sensitive fields with per-user keys, enforce masking in tools and logs, and block cross-jurisdiction data flows.",
    inp="PII fields, residency policy", out="ciphertext/tokens, masked views, policy violations", deps="KMS, Catalog, Service mesh egress policies", cons="All services handling PII", own="key hierarchy, policies",
    problem="Limit blast radius of breaches, make erasure possible in copies, and keep data in-jurisdiction.", without="Breaches expose plaintext everywhere; residency leaks.",
    guar=["Sensitive fields encrypted at application level", "Deleting a user key renders their encrypted fields unreadable everywhere", "Egress to non-compliant regions blocked"], nong=["Protection against a fully compromised running service with key access"],
    usecase="A lake export accidentally includes the phone column. It's ciphertext without a key grant, so no exposure. Erasure deletes the user key, so old backups containing the phone are unreadable.",
    derive="- Envelope encryption: per-user data key encrypted by KMS master key.\n- Deterministic HMAC for lookup fields (phone) separate from encryption.\n- Egress policies in mesh by destination region.",
    conc="Key creation per user idempotent.", consistency="Keys in a strongly consistent key store.", idem="Re-encrypting with the same key version is a no-op.", order="Key versions monotonic.",
    restart="Key cache rebuilt from store; KMS for unwrap.", scale="Data keys cached in memory (LRU) to avoid KMS per call.", arch="FieldCrypto library (AES-GCM) with per-user DEKs wrapped by regional KMS keys, stored in a key table. Masking in admin tools by default. Mesh egress policies + CI checks for residency.",
    modules=[["FieldCrypto", "Encrypt/decrypt"], ["KeyStore", "Per-user DEKs (wrapped)"], ["Masking", "Tools/logs"], ["EgressPolicy", "Residency"]],
    d_arch=("""flowchart LR
  SVC["service"] --> FC["FieldCrypto"] --> KS[("user_keys (wrapped)")]
  KS --> KMS["regional KMS"]
  SVC --> EG["mesh egress policy"]""", "Envelope encryption + egress."),
    d_seq=("""sequenceDiagram
  participant S as Service
  participant K as KeyStore
  participant M as KMS
  S->>K: get DEK(user)
  K->>M: unwrap
  M-->>K: DEK
  S->>S: AES-GCM encrypt(phone)""", "Encrypting a field."),
    d_state=("""stateDiagram-v2
  [*] --> Active
  Active --> Rotated: new version
  Active --> Shredded: erasure""", "User key lifecycle."),
    d_flow=("""flowchart LR
  PT["plaintext"] --> CT["ciphertext + key id"] --> STORE["DB/lake/backup"]""", "Ciphertext everywhere."),
    d_fail=("""flowchart TB
  K["KMS unavailable"] --> C["cached DEKs (TTL) continue; new users delayed"]""", "Caching."),
    sql="CREATE TABLE privacy.user_keys (user_id uuid PRIMARY KEY, wrapped_dek bytea NOT NULL, kms_key_id text NOT NULL, version int NOT NULL, shredded_at timestamptz);",
    data="Keys shredded on erasure.", api="""String encrypt(UUID user, String plaintext); String decrypt(UUID user, String ciphertext)""",
    mech=[("Crypto-shredding", "Deleting the per-user key makes every copy of their ciphertext (replicas, lake, backups) permanently unreadable, giving erasure without rewriting immutable stores.")],
    code="""Cipher c = Cipher.getInstance("AES/GCM/NoPadding"); c.init(ENCRYPT_MODE, dek(user), new GCMParameterSpec(128, iv)); byte[] ct = c.doFinal(pt);""", cx="O(field size).",
    fail=[F("Key shredded but needed for legal hold", "Hold check before shred", "Data loss", "Holds block shredding", "N/A")],
    alts=[["DB-level encryption only", "Insufficient", "Doesn't protect exports/backups", "Baseline"], ["Tokenization vault", "Viable", "Central detokenization", "Payments"]],
    adrs=[A("Per-user keys for high-sensitivity fields", "IV", "Erasure in backups.", [("Global key", "No shredding"), ("Per-user", "Chosen")], "Per-user DEKs.", "Erasure-friendly.", "Key mgmt overhead.", "N/A")],
    qa=[Q("Security", "How do you search by phone number if it's encrypted?", "Store a separate keyed hash (HMAC with a secret key) of the normalized phone for equality lookups. Encryption protects the value, and the HMAC allows lookups without decryption. The HMAC key is rotated with re-hashing.", "")],
    tests=[T("Erasure", "Shred key", "Old backup restored → fields unreadable"), T("Residency", "Egress to US from EU service", "Blocked")],
    evo=["N: Phase I relies on DB encryption at rest", "N: DB encryption + log redaction", "N: Same", "I: Field crypto + per-user keys", "E: Masking everywhere, scanners", "E: Regional KMS + egress guardrails"],
    ideas={"now": ["Log redaction"], "next": ["Field crypto"], "adv": ["Confidential computing for analytics"], "rej": ["Plaintext PII in lake"]})
