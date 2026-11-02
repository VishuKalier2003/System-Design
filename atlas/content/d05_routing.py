from model import comp, sub, A, Q, F, T

comp(id="maps-gateway", domain="routing", name="Maps Gateway (Geocoding & Providers)", tag="Geo · Integration", phase="I", kind="Anti-corruption layer → service (Phase IV)",
     biz="Turns what riders type ('Phoenix Mall') into coordinates and coordinates into readable addresses, using external map providers reliably and affordably.",
     eng="A provider-agnostic facade with caching, quota management and failover over paid, rate-limited external map APIs.",
     deploy="Module (I); service (IV) shared by all callers so caching and quotas are global.", data_own="geocode cache, place cache, provider quota counters, provider configs.",
     up=["resilience"], down=["rider-profile", "ride-request", "routing-eta", "receipts", "support"], ext=["Google Maps / Mapbox / HERE", "OSM Nominatim (self-hosted, Phase V)"],
     interfaces="`autocomplete(q, bias)`, `geocode(placeRef)`, `reverseGeocode(lat,lng)`; REST for apps via BFF.",
     problem="Provider calls cost money per request, add 50–300 ms latency, have quotas and outages, and have terms that restrict caching. Every domain calling them directly multiplies cost and couples us to one vendor.",
     fr=["Autocomplete with location bias", "Place details → coordinates", "Reverse geocoding for pins", "Provider failover", "Cost/quota accounting"], nfr=["Autocomplete p95 < 150 ms", "Cache hit ≥ 60% for reverse geocode", "No single provider dependency for core flow"],
     workload="≈ 5 autocomplete calls per ride request; reverse geocode per pin drop; Phase V ≈ 3K req/s.", success="Fast, correct addresses at controlled cost.", failure="Riders can't enter destinations; cost overruns; ToS violations.",
     derive="Callers want domain types, not vendor JSON, so an anti-corruption layer. Calls repeat heavily (popular places, nearby pins), so caching within the provider's ToS limits. Providers fail, so a breaker plus secondary provider. Sessions (autocomplete keystrokes) are billed per session, so pass session tokens.",
     owns=["Provider integration", "Caching", "Quota/cost accounting", "Failover"], not_owns=["Routing/ETA (own graph from Phase V)", "Saved places"], sync=["All lookups"], **{"async": ["Cost reports", "Cache warmers for top places"]},
     boundary_why="One gateway means one place for keys, quotas, caching and vendor swaps.",
     hld=("""flowchart LR
  C["Callers"] --> MG["Maps gateway API"]
  MG --> GC["Geocoding & autocomplete"]
  MG --> RG["Reverse geocode cache"]
  GC & RG --> PR["Provider router (failover, quotas)"]
  PR --> P1["Provider A"] & P2["Provider B"] & OSM["Self-hosted OSM (P5)"]
  GC & RG --> CACHE[("Redis cache")]""", "The gateway routes to providers behind a cache. The router owns failover and quota decisions."),
     seq=("""sequenceDiagram
  participant A as App
  participant G as Gateway
  participant C as Cache
  participant P as Provider
  A->>G: autocomplete("phoe", near 18.52,73.85, session s1)
  G->>C: get(key)
  C-->>G: miss
  G->>P: autocomplete (session s1)
  P-->>G: predictions
  G-->>A: [Phoenix Marketcity, ...]""", "Autocomplete path."),
     subdeps=[("geocoding", "provider-router")],
     flow="Requests are normalised and cached where permitted, with a provider router choosing the provider and enforcing quotas and breakers. Responses are mapped to internal `Place` types.",
     data="Redis: `rgeo:{h3 res10}` → address (TTL 30 days, within ToS); `ac:{prefix}:{h3 res6}:{lang}` → predictions (TTL 1 day). DB: `provider_usage(day, provider, api, count, cost)`.",
     rel=[["Timeouts", "Autocomplete 400 ms; geocode 800 ms."], ["Failover", "Breaker per provider/API; secondary provider."], ["Degradation", "If all fail: saved places + recent destinations + manual pin drop still work."]],
     sec=[["Keys", "Provider API keys in secrets manager; restricted by IP/referrer."], ["Privacy", "Queries sent to providers are minimal (no user ids)."]],
     adrs=[A("Single gateway for all map provider calls", "I", "Cost and vendor coupling.", [("Direct calls from modules", "Rejected"), ("Gateway", "Chosen")], "All calls via gateway.", "Central caching/quotas/failover.", "Gateway is critical path for address entry.", "N/A")],
     qa=[Q("Cost", "Map costs are 8% of revenue in a new city. What do you do?", "Measure per API: autocomplete sessions, place details and reverse geocodes. Then apply: session tokens (bill per session, not per keystroke), debounce keystrokes client-side (250 ms), larger reverse-geocode cache granularity (H3 res 10 ≈ 15 m), place-details only on selection, and self-hosted OSM reverse geocoding for non-display uses (Phase V). Expect a 50–70% reduction.", "Switching provider wholesale risks quality regressions. A/B test per city.")],
     impl_order=["provider-router", "geocoding"], pkg="""com.atlas.maps
├── api      (MapsController)
├── geocode  (AutocompleteService, ReverseGeocodeService, PlaceMapper)
└── provider (ProviderRouter, GoogleAdapter, MapboxAdapter, QuotaTracker)""",
     tests=[T("Failure", "Provider A 100% errors", "Breaker opens; B serves; latency < 2× baseline"), T("Cost", "Replay 1 day of queries", "Provider calls ≤ 40% of requests")],
     evo=[("I", "Module calling one provider", "Redis cache", "Timeouts", "Pilot"), ("E", "Same", "Cache tuning", "Breaker + secondary provider", "Outages"), ("U", "No change needed", "—", "—", "—"),
          ("R", "Maps service", "Shared cache cluster", "Quota mgmt", "Many callers"), ("E", "Self-hosted OSM for reverse geocoding", "Own geocoder index", "Fallback chain", "Cost"), ("E", "Regional providers (local map quality)", "—", "—", "Global")],
     ideas={"now": ["Session tokens"], "next": ["Self-hosted reverse geocoder"], "adv": ["Learned pickup-point suggestions"], "rej": ["Caching provider data beyond ToS"]})

sub(id="geocoding", comp="maps-gateway", name="Geocoding, Autocomplete & Reverse Geocoding", phase="I", cat="Integration · Caching",
    resp="Convert text to places and coordinates, and coordinates to display addresses, with caching and location bias.",
    inp="query text + bias point + session token; lat/lng", out="predictions, Place{lat,lng,address}, address string", deps="Provider router, Redis", cons="Apps (via BFF), Saved places, Receipts", own="geocode caches",
    problem="Fast, relevant address resolution at a fraction of naive provider cost.", without="Slow destination entry; huge bills.",
    guar=["Results mapped to provider-independent Place type", "Cache respects provider ToS TTLs", "Location-biased results"], nong=["Correctness of provider data"],
    usecase="Pin dropped at 18.5204,73.8567: H3 res-10 key hit, '12 FC Road, Pune' returned in 3 ms.",
    derive="- Reverse geocode results are stable for nearby points, so key the cache by a fine spatial cell (H3 res 10 ≈ 15 m edge).\n- Autocomplete relevance depends on area and language, so key by prefix + coarse cell + language.",
    conc="Cache stampede on popular key: single-flight per key within an instance; `SET NX` lock across instances.", consistency="Cache is eventually consistent with provider (TTL).", idem="Reads are idempotent; cache fill is idempotent.", order="Responses for stale keystrokes are discarded client-side using a request sequence.",
    restart="Cache survives app restarts (Redis).", scale="Redis cluster; hit rates dominate cost.", arch="Read-through cache in front of the provider router with request coalescing.",
    modules=[["AutocompleteService", "Prefix normalisation, bias, sessions"], ["ReverseGeocodeService", "H3-keyed cache"], ["PlaceMapper", "Vendor → Place"], ["SingleFlight", "Coalesce concurrent misses"]],
    d_arch=("""flowchart LR
  REQ["request"] --> N["normalize key"] --> C[("Redis")]
  C -->|miss| SF["single-flight"] --> PR["Provider router"] --> MAP["PlaceMapper"] --> C""", "Read-through with coalescing."),
    d_seq=("""sequenceDiagram
  participant A as App
  participant R as ReverseGeocode
  participant C as Cache
  participant P as Router
  A->>R: reverse(18.5204,73.8567)
  R->>C: get rgeo:8a608b2...
  alt hit
    C-->>R: address
  else miss
    R->>P: reverse(lat,lng)
    P-->>R: address
    R->>C: set (TTL 30d)
  end
  R-->>A: address""", "Reverse geocoding with cache."),
    nostate="Stateless request/response with cache.",
    d_flow=("""flowchart LR
  LL["lat,lng"] --> H3["h3 res10"] --> KEY["rgeo:cell:lang"]""", "Cache keys."),
    d_fail=("""flowchart TB
  PF["all providers down"] --> FB["return coordinates-only label 'Dropped pin'"]""", "Degrade to coordinates."),
    sql="-- Redis only; usage accounting table:\nCREATE TABLE maps.provider_usage (day date, provider text, api text, calls bigint, cost_micros bigint, PRIMARY KEY(day, provider, api));",
    data="Cache entries TTL per ToS.", api="""GET /v1/places/autocomplete?q=&lat=&lng=&session= -> [{place_ref, title, subtitle}]
GET /v1/places/{place_ref}?session= -> {lat,lng,address}
GET /v1/places/reverse?lat=&lng= -> {address, place_ref?}""",
    mech=[("Single-flight", "The first miss for a key creates a future, and concurrent requests for the same key await it, so one provider call serves N requests."), ("Spatial cache keys", "Snapping to H3 cells turns near-identical coordinates into one key, giving high hit rates.")],
    code="""public CompletableFuture<Address> reverse(double lat, double lng, String lang) {
    String key = "rgeo:" + h3.latLngToCellAddress(lat, lng, 10) + ":" + lang;
    return cache.get(key).thenCompose(hit -> hit != null ? completedFuture(hit)
        : inflight.computeIfAbsent(key, k -> router.reverse(lat, lng, lang)
            .thenApply(a -> { cache.set(k, a, Duration.ofDays(30)); inflight.remove(k); return a; })));
}""", cx="O(1).",
    fail=[F("Provider outage", "Breaker", "Slower/secondary results", "Failover", "None"), F("Stampede", "Miss spike", "Provider quota burn", "Single-flight + lock", "None")],
    alts=[["Client-side provider SDK", "Rejected", "No caching/cost control", "Map tiles only"], ["Self-hosted geocoder only", "Rejected", "Quality for POIs", "Reverse geocode at P5"]],
    adrs=[A("H3 res-10 reverse cache", "I", "Pins repeat.", [("Exact coordinates", "Low hit"), ("Res 10 cells", "Chosen")], "Res-10 keys.", "High hit rate, ≈15 m accuracy.", "Address may be for neighbour building.", "If complaints, res 11.")],
    qa=[Q("Correctness", "Typing fast produces out-of-order autocomplete responses. Who fixes that?", "The client tags each request with an incrementing sequence and renders only responses with sequence ≥ last rendered. The server can't fix ordering across independent HTTP requests.", "")],
    tests=[T("Unit", "Nearby pins same cell", "One provider call"), T("Concurrency", "100 parallel misses same key", "1 provider call")],
    evo=["I: Cached provider calls", "E: Failover provider", "U: No change needed", "E: In Maps service", "E: Self-hosted reverse geocoder", "E: Regional providers"],
    ideas={"now": ["Session tokens"], "next": ["Popular place prewarming"], "adv": ["Pickup point recommendations"], "rej": ["No cache"]})

sub(id="provider-router", comp="maps-gateway", name="Provider Router (Failover & Quotas)", phase="II", cat="Reliability · External integration",
    resp="Choose which map provider serves each call based on health, quota, cost and market quality, with breakers and failover.",
    inp="normalized map calls", out="provider responses mapped to internal types", deps="Provider adapters, Resilience toolkit", cons="Geocoding, Routing (provider ETA in Phase I–IV)", own="provider configs, quota counters",
    problem="Providers fail, throttle and differ in quality per market. Callers must not care.", without="Outage when the single provider fails; quota overruns.",
    guar=["No call to a provider with an open breaker", "Daily quota caps enforced", "Per-market preference honoured"], nong=["Identical results across providers"],
    usecase="Provider A returns 429s at 18:00. Its breaker opens and calls route to B for 60 s, then half-open probes restore A.",
    derive="- Health signals are per provider and API, so a breaker per (provider, api).\n- Quotas are global across instances, so shared counters.\n- Preference is per market, so config.",
    conc="Quota counters: Redis INCRBY with daily key; soft limits allow slight overshoot.", consistency="Approximate quotas (acceptable).", idem="Pure routing decision; retries go to the next provider.", order="Each call is routed independently, so there is nothing to order.",
    restart="Breaker state rebuilds from fresh traffic; counters in Redis.", scale="Stateless; per-instance breakers + shared quotas.",
    arch="`ProviderRouter.call(api, market, request)` iterates the market's ordered provider list, skipping open breakers and exhausted quotas, calling via adapter with a timeout.",
    modules=[["ProviderConfig", "Per-market order, quotas"], ["Breakers", "Resilience4j per provider/api"], ["QuotaTracker", "Redis counters"], ["Adapters", "Vendor-specific clients"]],
    d_arch=("""flowchart LR
  CALL["call(api, market)"] --> CFG["ProviderConfig"] --> LOOP["for provider in order"]
  LOOP --> BR{"breaker closed?"} --> QT{"quota left?"} --> AD["Adapter (timeout)"]
  QT --> RQ[("Redis quotas")]""", "Ordered fallthrough."),
    d_seq=("""sequenceDiagram
  participant R as Router
  participant A as ProviderA
  participant B as ProviderB
  R->>A: call (400ms timeout)
  A-->>R: 429
  R->>R: breaker A records failure
  R->>B: call
  B-->>R: ok""", "Failover on error."),
    d_state=("""stateDiagram-v2
  [*] --> Closed
  Closed --> Open: failure rate > 50% in 20 calls
  Open --> HalfOpen: after 60 s
  HalfOpen --> Closed: probes succeed
  HalfOpen --> Open: probe fails""", "Breaker state per provider/API."),
    d_flow=("""flowchart LR
  CALLS["calls"] --> CNT["usage counters"] --> COST["daily cost report"]""", "Usage accounting."),
    d_fail=("""flowchart TB
  ALL["all breakers open"] --> DEG["return degraded error; callers use fallbacks"]""", "Total provider failure is a defined degraded mode."),
    sql="""CREATE TABLE maps.provider_config (market text, api text, provider text, priority int, daily_quota bigint, PRIMARY KEY(market, api, provider));""",
    data="Config edited by ops; versioned.", api="""<T> T call(MapApi api, String market, Function<ProviderAdapter, T> fn)""",
    mech=[("Circuit breaker", "Counts failures in a sliding window. Above the threshold it opens, rejecting calls fast. After a cool-down it lets a few probes through (half-open) to test recovery."), ("Quota counters", "`INCR maps:quota:{provider}:{api}:{yyyymmdd}` with 2-day TTL. The router skips a provider above its soft cap.")],
    code="""for (ProviderAdapter p : config.order(api, market)) {
    if (!breakers.of(p, api).tryAcquirePermission() || quota.exhausted(p, api)) continue;
    try { T r = timeouts.of(api).executeCallable(() -> fn.apply(p)); breakers.of(p, api).onSuccess(); quota.incr(p, api); return r; }
    catch (Exception e) { breakers.of(p, api).onError(e); }
}
throw new AllProvidersUnavailable(api);""", cx="O(providers).",
    fail=[F("Primary throttling", "429 rate", "Latency", "Failover", "None"), F("Quota exhausted early", "Counter", "Secondary used", "Alert finance", "None")],
    alts=[["Single provider", "Phase I", "Simple", "Pilot"], ["Parallel hedged calls", "Advanced", "Lower tail latency, double cost", "Critical calls only"]],
    adrs=[A("Ordered failover per market", "II", "Quality varies by market.", [("Global order", "Rejected"), ("Per-market order", "Chosen")], "Config per market.", "Best quality per market.", "More config.", "N/A")],
    qa=[Q("Reliability", "Should failover retry the same request on provider B after A timed out at 400 ms?", "Only for idempotent reads (all map calls are), and only within the caller's deadline. If A consumed 400 ms of an 800 ms budget, B gets the remaining 400 ms minus margin. Deadline propagation prevents failover from exceeding the caller's SLO.", "")],
    tests=[T("Failure", "Provider A down", "B serves"), T("Unit", "Breaker half-open probe fails", "Open again")],
    evo=["N: Single provider in Phase I", "I: Router with breakers and secondary", "U: No change needed", "E: Shared quotas across Maps service fleet", "E: OSM self-hosted in chain", "E: Regional providers"],
    ideas={"now": ["Deadline-aware failover"], "next": ["Cost-aware routing"], "adv": ["Quality scoring from user corrections"], "rej": ["Retrying non-idempotent provider calls"]})

# ======================================================================= Routing & ETA
comp(id="routing-eta", domain="routing", name="Routing & ETA", tag="Geo · Core intelligence", phase="I", kind="Logical component → service with in-house road graph (Phase V)",
     biz="Tells riders when the car arrives and when they'll reach the destination, gives drivers turn-by-turn routes, and gives pricing and dispatch accurate travel times.",
     eng="Shortest-path and travel-time computation over a road graph with live traffic, at very high query rates (dispatch computes ETAs for ~20 candidates per request), plus ML correction.",
     deploy="Provider directions API (I–III); hybrid with in-house OSRM-like engine (IV); in-house graph + traffic + ML ETA (V); regional graphs (VI).",
     data_own="Road graph builds, traffic speed tables, ETA model versions.", up=["maps-gateway", "location-ingest", "applied-models"], down=["dispatch", "pricing", "trip-tracking", "ride-request"], ext=["Directions APIs (I–IV)", "Traffic data providers"],
     interfaces="`eta(from, to, departAt)`, `etaMatrix(origins[], dest)`, `route(from, to)`; gRPC from Phase IV.",
     problem="Dispatch needs many-to-one ETAs in < 100 ms. Pricing needs route distance/time for estimates. Riders need trustworthy arrival times. Provider APIs are too slow and costly at Phase V volumes.",
     fr=["Point-to-point route + ETA", "Many-to-one ETA matrix for dispatch", "Live traffic adjustment", "Rerouting on deviation", "ML-corrected ETAs"], nfr=["Matrix (20×1) p99 < 100 ms", "ETA error (MAPE) < 15% pickup", "Graph refresh weekly; traffic every 1–5 min"],
     workload="Phase V: ≈ 500 req/s × 20 candidates = 10K ETA pairs/s plus tracking refreshes ≈ 30K/s.", success="ETA within ±2 min for most pickups; dispatch picks truly-nearest drivers.", failure="Riders wait longer than promised; wrong driver chosen; fares misestimated.",
     derive="Shortest path on a large graph needs preprocessing (contraction hierarchies) for millisecond queries. Travel time = Σ segment length / speed, where speed comes from live traffic, so customizable CH separates topology preprocessing from weight updates. Residual errors (turns, pickups, signals) are learnable, so an ML correction on top.",
     owns=["Road graph", "Path computation", "Traffic speeds", "ETA serving"], not_owns=["Geocoding (Maps gateway)", "Candidate selection (Dispatch)", "Model training (ML platform)"], sync=["ETA and route queries"], **{"async": ["Graph builds", "Traffic aggregation from matched segments", "ETA accuracy monitoring"]},
     boundary_why="Routing is a computational service with its own data (graph) and scaling. It doesn't need business data, which keeps it reusable and cacheable.",
     hld=("""flowchart LR
  DSP["Dispatch"] -->|etaMatrix| ES["ETA service"]
  PRC["Pricing"] -->|route| RC["Route calculation"]
  ES --> RC
  RC --> G[("CH road graph (in memory)")]
  TI["Traffic integration"] -->|segment speeds| G
  MM["Matched segments stream"] --> TI
  ES --> ML["ETA ML correction"]
  RC -.->|Phase I-IV fallback| PROV["Directions provider"]""", "The route engine computes the base path and time over a traffic-weighted graph. The ETA service adds ML correction and serves dispatch. Traffic speeds come from our own matched GPS segments."),
     seq=("""sequenceDiagram
  participant D as Dispatch
  participant E as ETA service
  participant R as Route engine
  participant M as ML model
  D->>E: etaMatrix(20 drivers → pickup)
  E->>R: many-to-one CH query
  R-->>E: base times
  E->>M: correct(features)
  M-->>E: adjusted times
  E-->>D: ETAs (s)""", "Dispatch ETA path."),
     subdeps=[("eta-service", "route-calculation"), ("route-calculation", "traffic-integration")],
     flow="Queries arrive at the ETA service, which calls the route engine for base paths and times, then applies model correction. Traffic integration continuously reweights the graph. Graph builds are blue/green swapped.",
     data="Graph: nodes/edges from OSM (+ licensed data), built into CH files per region (GBs). Traffic: `segment_speeds(segment_id, time_bucket, speed)` live table in memory + historical profiles in the lake.",
     rel=[["Fallback", "If in-house engine fails: historical-speed estimates; Phase I–IV provider."], ["Hedging", "Hedged requests to a second replica after p95 latency."], ["Graph swap", "Blue/green load, validated with golden routes."]],
     sec=[["Abuse", "Rate limits on public route endpoints."], ["Data", "Traffic derived from aggregated, anonymized driver speeds."]],
     adrs=[A("Build in-house routing at Phase IV–V", "IV", "Provider cost and latency at 10K+ pairs/s.", [("Provider forever", "Rejected: cost/latency"), ("OSRM/Valhalla-based engine", "Chosen"), ("Fully custom engine", "Rejected: unnecessary")],
             "Self-hosted CH engine on OSM + own traffic.", "Cost, latency, control.", "Map data quality and ops ownership.", "If a market's OSM quality is poor → licensed data or provider for that market.")],
     qa=[Q("Performance", "Dispatch needs ETAs from 20 drivers to one pickup within 100 ms. How?", "Use a many-to-one query: run one backward search from the pickup on the CH graph and meet forward searches from all 20 origins (bucket-based many-to-many CH). This costs about the same as a few point-to-point queries. Snap origins to graph nodes using their current matched segment. The ML correction is a batched model call (single inference over 20 rows).", "20 provider calls in parallel cost 20× and have tail latency of the slowest.")],
     impl_order=["route-calculation", "traffic-integration", "eta-service"], pkg="""com.atlas.routing
├── graph   (GraphLoader, CchGraph, Snapper)
├── engine  (PointToPoint, ManyToOne, Rerouter)
├── traffic (SpeedAggregator, WeightCustomizer)
└── eta     (EtaService, EtaCorrector, EtaAccuracyMonitor)""",
     tests=[T("Accuracy", "Replay 1 week of trips", "Pickup ETA MAPE < 15%"), T("Load", "10K pairs/s", "p99 < 100 ms"), T("Failure", "Graph swap with corrupted build", "Validation rejects; old graph stays")],
     evo=[("I", "Provider directions API", "Cache by (cell, cell, hour)", "Timeouts", "Fast to ship"), ("E", "Provider + failover", "—", "Breaker; fallback heuristic", "Outages"), ("U", "No change needed", "—", "—", "—"),
          ("R", "Self-hosted OSRM-style engine + provider fallback", "OSM graph", "Replicas", "Cost & latency"), ("R", "CCH with live traffic + ML correction", "Streaming segment speeds", "Hedging", "Accuracy & 30K q/s"), ("E", "Regional graphs", "—", "—", "Global")],
     ideas={"now": ["Cache provider ETAs by cell pair + hour"], "next": ["Own traffic from GPS"], "adv": ["Graph neural network ETA"], "rej": ["Straight-line ETAs for dispatch"]})

sub(id="route-calculation", comp="routing-eta", name="Route Calculation Engine", phase="I", cat="Algorithm · Graph search",
    resp="Compute shortest-time paths and many-to-one travel times over the road graph with current weights.",
    inp="origin(s), destination, departure time, weights", out="path (segments), distance, base duration", deps="Road graph, Traffic weights", cons="ETA service, Pricing, Driver navigation, Rerouting", own="Graph builds",
    problem="Shortest-path on a continent-scale graph (hundreds of millions of edges) in milliseconds, with weights that change every few minutes.",
    without="Seconds-long Dijkstra queries; dependence on providers.", guar=["Paths respect turn restrictions and one-ways", "Query p99 < 20 ms point-to-point", "Weights updated without full rebuild"], nong=["Optimality under future traffic (time-dependent routing only approximated)"],
    usecase="Pricing asks route(Koregaon Park → Airport): 9.8 km, 24 min base. The rider's estimate uses it.",
    derive="- Dijkstra explores millions of nodes per query, too slow.\n- Contraction hierarchies preprocess node importance and add shortcuts. Bidirectional upward searches then touch only ~1K nodes.\n- Traffic changes weights, which breaks shortcut validity. Customizable CH separates metric-independent ordering from a fast (seconds) weight customization.",
    conc="Graph is immutable per version. Queries share read-only memory, and new weights produce a new customized version swapped atomically.", consistency="Each query uses one consistent weight version.", idem="Pure computation: identical inputs and weight version give identical outputs.", order="Weight versions are monotonically increasing, and the engine only swaps forward.",
    restart="Load graph files from object storage (mmap). Warm-up ~1–2 min per region.", scale="Read-only replicas behind a load balancer. Memory ~10–30 GB per large region.",
    arch="Phase I–III: provider directions API wrapped in the same interface. Phase IV: OSRM (MLD/CH) self-hosted. Phase V: Customizable CH. Metric-independent preprocessing weekly, customization with live speeds every 2–5 min, queries against the latest customization.",
    modules=[["GraphBuilder", "OSM → graph → node ordering (weekly)"], ["Customizer", "Apply segment speeds → shortcut weights"], ["QueryEngine", "Bidirectional CH, many-to-one buckets"], ["Snapper", "Point → nearest edge (R-tree)"]],
    d_arch=("""flowchart LR
  OSM[("OSM extract")] --> GB["GraphBuilder (weekly)"] --> ORD[("ordering + topology")]
  SPD["segment speeds"] --> CU["Customizer (2-5 min)"] --> W[("weights vN")]
  ORD & W --> QE["QueryEngine"]
  REQ["route/eta"] --> SN["Snapper"] --> QE""", "Topology is preprocessed weekly and weights every few minutes. Queries use both."),
    d_seq=("""sequenceDiagram
  participant C as Caller
  participant S as Snapper
  participant Q as QueryEngine
  C->>S: snap(origin), snap(dest)
  S-->>Q: edge ids + offsets
  Q->>Q: forward upward search / backward upward search
  Q->>Q: meet at min(df+db), unpack shortcuts
  Q-->>C: path, distance, duration""", "Bidirectional CH query."),
    nostate="Stateless queries over immutable versioned graph data.",
    d_flow=("""flowchart LR
  OSM["OSM"] --> G["graph"] --> CH["hierarchy"] --> Q["queries"]
  TRAF["speeds"] --> CU["customize"] --> Q""", "Two preprocessing pipelines feed queries."),
    d_fail=("""flowchart TB
  B["bad build"] --> V["golden-route validation fails"] --> K["keep previous version"]
  N["node OOM"] --> R["replicas serve; autoscale"]""", "Validation gates graph releases."),
    sql="-- Graph data is binary files in object storage: s3://atlas-graphs/{region}/{build_id}/{topology,ordering,weights_vN}",
    data="Builds retained 4 weeks for rollback.", api="""rpc Route(RouteRequest{origin, destination, depart_at}) returns (RouteResponse{segments, distance_m, duration_s, polyline})
rpc ManyToOne(ManyToOneRequest{origins[], destination}) returns (Times{duration_s[]})""",
    mech=[("Contraction hierarchies", "Order nodes by importance and contract them one by one, adding shortcut edges that preserve shortest distances. A query runs Dijkstra only upward in the hierarchy from both ends and meets at the top, touching a few hundred to a few thousand nodes."),
          ("Customizable CH", "The node order depends only on topology. Shortcut weights are recomputed bottom-up with new speeds in seconds, so live traffic works without full preprocessing."), ("Many-to-one buckets", "One backward search from the target stores distances in buckets at visited nodes. Forward searches from each origin scan buckets, so total cost ≈ one search per origin over a small upward space.")],
    code="""// Pseudocode: bidirectional upward CH
int best = INF;
PQ f = new PQ(src), b = new PQ(dst);
while (!f.isEmpty() || !b.isEmpty()) {
    if (min(f.peekKey(), b.peekKey()) >= best) break;
    relaxUpward(f, distF); relaxUpward(b, distB);
    for (int v : touched) best = Math.min(best, distF[v] + distB[v]);
}
return unpackShortcuts(meetingNode);""", cx="Query ~O(k log k), k ≈ 10^3 nodes; preprocessing O(n log n)-ish, hours weekly.",
    fail=[F("Snapping to wrong side of divided road", "Heading mismatch", "Longer ETA", "Use heading in snapping", "None"), F("Weight version stale", "Customizer lag", "Less accurate ETAs", "Alert; historical profile fallback", "None")],
    alts=[["Provider API", "Phase I–III", "No ops", "Low volume"], ["A* with landmarks (ALT)", "Viable", "No heavy preprocessing", "Small graphs"], ["Plain Dijkstra", "Rejected", "Too slow", "Never"]],
    adrs=[A("Customizable CH", "V", "Live traffic + speed.", [("Static CH + rebuild", "Rebuild too slow for traffic"), ("CCH", "Chosen"), ("MLD (OSRM)", "Phase IV")], "CCH on own engine.", "Seconds-level weight updates.", "Engineering depth required.", "N/A")],
    qa=[Q("Correctness", "How are turn restrictions handled in a node-based graph?", "Use an edge-based graph: nodes represent directed road segments and edges represent allowed turns, each with a turn cost. Restricted turns have no edge. It's larger (~3× edges) but exact, and CH works the same way on it.", "")],
    tests=[T("Correctness", "Golden routes (1K pairs) vs reference", "Identical paths"), T("Load", "Many-to-one 20×1", "p99 < 20 ms"), T("Recovery", "Graph rollback", "< 5 min")],
    evo=["I: Provider API wrapper", "E: Failover provider", "U: No change needed", "R: Self-hosted OSRM (MLD)", "R: In-house CCH with live weights", "E: Regional graphs"],
    ideas={"now": ["Interface independent of provider"], "next": ["Self-hosting"], "adv": ["Time-dependent routing"], "rej": ["Building a map from scratch"]})

sub(id="traffic-integration", comp="routing-eta", name="Traffic Integration", phase="IV", cat="Stream · Data fusion",
    resp="Estimate current speed on every road segment from our own matched driver GPS (plus optional provider feeds) and publish weights for routing.",
    inp="matched segment traversals (from map matching), provider traffic feeds", out="segment speeds per time bucket, historical profiles", deps="Map matching stream", cons="Route calculation (customizer), ETA ML features", own="segment_speeds",
    problem="Routing with free-flow speeds underestimates rush-hour ETAs by 2×. We have hundreds of thousands of probes (drivers) generating speed observations.", without="Systematically wrong ETAs and dispatch choices.",
    guar=["Segment speeds refreshed every ≤ 5 min where probes exist", "Fallback to historical profile (weekday/hour) when sparse", "Outlier probes (stopped for pickup) excluded"], nong=["Incident detection accuracy"],
    usecase="An accident blocks a ring road. Probe speeds on 12 segments drop to 5 km/h within 3 minutes, routes divert, and ETAs rise for affected trips.",
    derive="- Observation = (segment, traversal time). Speed = length / time.\n- Few probes per segment, so a robust aggregate (median) over a sliding window, blended with the historical prior by probe count (Bayesian shrinkage).\n- Pickups and drop-offs create fake slowness, so exclude traversals with stops at trip boundaries.",
    conc="Keyed by segment in stream processing.", consistency="Windowed, eventually consistent.", idem="Window aggregation is deterministic on replay with event-time windows.", order="Event-time windows with 2-minute allowed lateness.",
    restart="Flink checkpoints.", scale="Keys = segments with traffic (~millions per region); throughput = traversals/s (~50K).",
    arch="Flink job: map-matched traversals → filter (stop-affected, implausible) → keyed by segment → 5-min sliding window median → blend with historical prior → publish to compacted topic `segment-speeds` → Customizer consumes. Nightly batch updates historical profiles.",
    modules=[["TraversalFilter", "Exclude stops/outliers"], ["WindowedMedian", "Per segment"], ["PriorBlender", "Shrink to historical by count"], ["ProfileBuilder", "Nightly weekday×hour profiles"]],
    d_arch=("""flowchart LR
  MM[["matched traversals"]] --> TF["TraversalFilter"] --> WM["WindowedMedian (5m)"] --> PB["PriorBlender"] --> OUT[["segment-speeds (compacted)"]]
  HP[("historical profiles")] --> PB
  LAKE[("lake")] --> PRB["ProfileBuilder (nightly)"] --> HP
  OUT --> CU["Route customizer"]""", "Live medians blended with historical priors."),
    d_seq=("""sequenceDiagram
  participant S as Stream
  participant W as Window
  participant B as Blender
  participant C as Customizer
  S->>W: traversal(seg 991, 42 s)
  W->>W: median over 5 min = 38 s (n=6)
  W->>B: speed 9 km/h, n=6
  B-->>C: blended speed 11 km/h""", "One segment update."),
    nostate="Windowed aggregation state rather than an entity lifecycle.",
    d_flow=("""flowchart LR
  T["traversal times"] --> M["median"] --> S["speed"] --> BL["w·live + (1-w)·hist, w=n/(n+k)"] --> W["weights"]""", "Shrinkage weighting by sample count."),
    d_fail=("""flowchart TB
  J["stream job down"] --> H["customizer uses last speeds, decaying to historical after 15 min"]""", "Stale live data decays toward the prior."),
    sql="-- Historical profiles in lake (Iceberg): segment_profiles(segment_id, weekday, hour, p50_speed, n)",
    data="Live speeds ephemeral (compacted topic); profiles retained 2 years.", api="""topic segment-speeds key=segment_id value={speed_kmh, n, window_end, source}""",
    mech=[("Median in sliding windows", "The median is robust to a single stopped probe, where a mean would be skewed."), ("Bayesian shrinkage", "w = n/(n+k). With few observations, trust the historical prior. With many, trust live data.")],
    code="""double blended(double live, int n, double hist) { double w = n / (n + K); return w * live + (1 - w) * hist; }""", cx="O(log w) per observation with order-statistic structures.",
    fail=[F("Sparse probes at night", "Low n", "Noisy live", "Shrinkage to prior", "None"), F("Job lag", "Watermark lag", "Stale traffic", "Decay to historical", "None")],
    alts=[["Provider traffic only", "Phase IV start", "Cost, licensing", "Sparse markets"], ["Mean speed", "Rejected", "Outlier-sensitive", "Never"]],
    adrs=[A("Own probe-based traffic", "IV", "We have the densest probe fleet in our cities.", [("Buy traffic", "Cost"), ("Own probes + prior", "Chosen")], "Probe traffic with priors.", "Fresh and free.", "Coverage gaps off-network.", "Blend provider feed in sparse markets.")],
    qa=[Q("Privacy", "Does traffic estimation leak individual drivers' movements?", "Outputs are per-segment aggregates over windows with a minimum probe count (k ≥ 3) before using live values. Individual traversals are never published, and raw traversals live only inside the stream job.", "")],
    tests=[T("Unit", "One stopped probe among 5", "Median unaffected"), T("Integration", "Replay incident day", "Speeds drop within 5 min")],
    evo=["N: Provider ETAs include traffic in Phase I", "N: Provider ETAs include traffic", "N: Provider ETAs include traffic", "I: Batch 5-min aggregation from matched segments", "R: Flink streaming with priors", "E: Regional jobs"],
    ideas={"now": ["n/a before IV"], "next": ["Incident detection"], "adv": ["Predictive traffic 30 min ahead"], "rej": ["Publishing individual traversals"]})

sub(id="eta-service", comp="routing-eta", name="ETA Service (with ML Correction)", phase="I", cat="Serving · Prediction",
    resp="Serve pickup and trip ETAs to dispatch, riders, pricing and tracking, correcting route-engine estimates with a learned model and caching aggressively.",
    inp="origins/destination, time, context (city, weather, event)", out="ETA seconds + confidence interval", deps="Route calculation, Applied Models (ETA model), Feature store", cons="Dispatch, Pricing, Trip tracking, Rider app", own="ETA cache, accuracy metrics",
    problem="Graph ETAs miss pickup delays, signals and local effects. Callers need fast, calibrated ETAs at high volume.", without="Biased ETAs and wrong dispatch choices.",
    guar=["Returns within deadline or falls back to base ETA", "Logs prediction + actual for accuracy monitoring", "Monotone non-negative ETAs"], nong=["Exact arrival times"],
    usecase="Base ETA 6 min. The model adds +1.5 min (school zone at 15:00, rain), and the rider sees 7–8 min. Actual: 7.6 min.",
    derive="- Residual = actual − base is predictable from features (time, area, weather, driver behaviour), so a gradient-boosted model on the residual.\n- Dispatch latency budget is tight, so batched inference, feature cache, and deadline fallback to base.",
    conc="Stateless serving.", consistency="Model version pinned per request; logged.", idem="Pure computation for a given model version and inputs: the same request yields the same ETA.", order="Requests are independent. Tracking refreshes only show the latest response.",
    restart="Loads model from registry at start.", scale="Horizontal. Batch inference amortizes overhead.", arch="ETA = base (route engine) + model residual, served by a thin Java service calling the model server (or an embedded ONNX model) with features from the online feature store.",
    modules=[["BaseEta", "Route engine call"], ["FeatureFetcher", "Online features"], ["Corrector", "Model inference (batched)"], ["Calibrator", "Prediction intervals"], ["AccuracyLogger", "Prediction/actual pairs"]],
    d_arch=("""flowchart LR
  C["caller"] --> ES["EtaService"] --> BE["BaseEta"] --> RE["Route engine"]
  ES --> FF["FeatureFetcher"] --> FS[("online features")]
  ES --> CR["Corrector (ONNX)"]
  ES --> AL["AccuracyLogger"] --> K[["eta-predictions"]]""", "Base plus residual, with logging for monitoring."),
    d_seq=("""sequenceDiagram
  participant D as Dispatch
  participant E as ETA
  participant R as Route
  participant M as Model
  D->>E: etaMatrix(20) deadline 80ms
  E->>R: many-to-one
  R-->>E: base[20]
  E->>M: infer batch[20]
  alt within deadline
    M-->>E: residual[20]
  else timeout
    E->>E: residual = 0
  end
  E-->>D: eta[20]""", "Deadline-aware correction."),
    nostate="Stateless prediction service.",
    d_flow=("""flowchart LR
  P["prediction"] --> LOG[["eta-predictions"]] --> J["join with actual arrival"] --> MET["MAPE by city/hour"] --> RETRAIN["training data"]""", "Closed loop for monitoring and retraining."),
    d_fail=("""flowchart TB
  M["model server slow"] --> B["base ETA only"]
  F["feature store down"] --> D["defaults for missing features"]""", "Fallback to the base ETA is always available."),
    sql="-- Prediction log in lake: eta_predictions(request_id, kind, base_s, predicted_s, model_version, features_hash, ts) joined later with actuals.",
    data="Logs retained 1 year for training.", api="""rpc Eta(EtaRequest{origins[], destination, context}) returns (EtaResponse{eta_s[], p10_s[], p90_s[], model_version})""",
    mech=[("Residual modelling", "Learning the correction on top of a physics-based base is more data-efficient and degrades gracefully: with no model, you still have base ETAs."), ("Deadline fallback", "The service enforces the caller's deadline: if correction isn't ready, return the base result instead of making dispatch wait.")],
    code="""public List<Eta> etas(List<LatLng> origins, LatLng dest, Deadline dl) {
    int[] base = route.manyToOne(origins, dest);
    double[] resid = model.inferAsync(features.batch(origins, dest)).completeOnTimeout(zeros(base.length), dl.remainingMs() - 5, MILLISECONDS).join();
    return IntStream.range(0, base.length).mapToObj(i -> Eta.of(Math.max(0, base[i] + resid[i]))).toList();
}""", cx="O(origins).",
    fail=[F("Model drift", "MAPE alert", "Biased ETAs", "Rollback model version", "None"), F("Timeout", "Deadline", "Base ETA", "Fallback", "None")],
    alts=[["Pure ML end-to-end", "Advanced", "Less robust", "Very data-rich markets"], ["No correction", "Phase I", "Simple", "Pilot"]],
    adrs=[A("Residual model over base engine", "V", "Accuracy.", [("Base only", "Biased"), ("Residual model", "Chosen")], "Base + GBM residual.", "Robust, interpretable.", "Feature pipeline needed.", "N/A")],
    qa=[Q("ML", "Should the rider-facing ETA be the model mean or a pessimistic quantile?", "Show a range (p10–p90) or a slightly pessimistic point estimate (≈p60). Late arrivals annoy riders more than early ones. Dispatch should rank on the mean, because it optimizes expected wait. Different consumers, different statistics.", "")],
    tests=[T("Unit", "Model timeout", "Base ETA returned"), T("Accuracy", "Shadow model vs prod", "Promote only if MAPE improves ≥ 3%")],
    evo=["I: Provider ETA passthrough", "E: Cache ETAs by cell pair", "E: Prediction logging", "E: Own base ETA", "R: ML residual correction + intervals", "E: Regional models"],
    ideas={"now": ["Log predictions vs actuals from day one"], "next": ["Residual model"], "adv": ["GNN ETA"], "rej": ["Showing optimistic ETAs to boost conversion"]})
