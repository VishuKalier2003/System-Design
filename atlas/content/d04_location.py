from model import comp, sub, A, Q, F, T

# ======================================================================= Location Ingestion
comp(id="location-ingest", domain="location", name="Location Ingestion & GPS Processing", tag="Geo · High throughput", phase="I", kind="Logical component → first extracted service (Phase III)",
     biz="Receives drivers' GPS positions every few seconds so riders see cars move, dispatch finds the nearest driver and fares are calculated correctly.",
     eng="The highest-write-rate path in the system: validate, authenticate, de-noise and route location updates to the geo index, trip tracking and history at up to 500K updates/s.",
     deploy="Endpoint in monolith (Phase I–II); separate ingest service (Phase III); gateways + Kafka + Flink (Phase V); per region (Phase VI).",
     data_own="Raw update stream; latest-position cache; filter state per driver.",
     up=["identity", "driver-supply"], down=["geo-index", "trip-tracking", "location-history", "fare-finalization", "safety", "event-pipeline"], ext=[],
     interfaces="`POST /v1/locations:batch` (Phase I–IV), bidirectional gRPC stream (Phase V); Kafka topic `driver-locations` keyed by driver_id (Phase III) → by H3 res-5 cell for geo consumers (Phase V).",
     problem="Mobile GPS is noisy (±5–50 m, jumps in urban canyons), devices batch and resend over flaky links, and volume grows linearly with online drivers × frequency. Downstream consumers need clean, ordered positions within seconds.",
     fr=["Accept batched updates from driver apps (online/on-trip)", "Validate/authenticate (driver identity, plausibility)", "Filter noise and outliers", "Snap to road on trip (map matching)", "Fan out to geo index, tracking, history"],
     nfr=["Ingest-to-index freshness p95 < 2 s", "Throughput: 10/s (I) → 500K/s (VI)", "Loss tolerance: occasional loss OK for idle drivers, < 0.1% gaps on trip", "Battery/data-friendly client protocol"],
     workload="Every online driver: 1 update/4 s (on trip: 1/2 s). Phase V: 60K/s steady, 150K/s peak.", success="Fresh, plausible positions everywhere they're needed.", failure="Stale cars on rider maps; dispatch to far drivers; wrong fares from GPS jumps.",
     derive="Updates are small, frequent and individually low-value but collectively critical, so batch on the client, process as a stream, and avoid synchronous DB writes per update. Ordering matters per driver, not globally. Noise is physical, so filtering must use motion models (speed, heading).",
     owns=["Update intake and validation", "Noise filtering", "Map matching for on-trip tracks", "Fan-out"], not_owns=["Spatial index (Geo index)", "Long-term storage (Location history)", "Trip state (Trip)"],
     sync=["Batch ingest ack"], **{"async": ["All fan-out to consumers"]},
     boundary_why="Ingestion is separated from indexing because they scale on different axes (bytes/s vs query/s) and fail differently. A slow index must not stall ingestion, and a buffer between them absorbs the mismatch.",
     hld=("""flowchart LR
  DA["Driver app<br/>(batch every 4s)"] -->|HTTPS / gRPC stream| IG["Ingest gateway"]
  IG --> V["validate + authenticate"]
  V --> GF["GPS filter"]
  GF --> MM["Map matching (on trip)"]
  GF -->|latest position| GEO["Geo index"]
  MM --> TRK["Trip tracking"]
  MM --> HIS["Location history"]
  IG -.->|Phase III+| K[["Kafka driver-locations"]]""", "Gateway accepts batches. The filter removes noise. On-trip points are map-matched. Results fan out to the index (latest only), tracking (live) and history (all on-trip points). From Phase III a Kafka topic decouples the stages."),
     seq=("""sequenceDiagram
  participant D as Driver app
  participant G as Ingest gateway
  participant F as Filter
  participant X as Geo index
  participant T as Tracking
  D->>G: batch [p1..p3] seq 120-122
  G->>G: auth (JWT), dedup by (driver, seq)
  G-->>D: ack up to 122
  G->>F: points
  F->>X: latest accepted point
  F->>T: on-trip points""", "Ack is returned before fan-out. The client keeps unacked points and resends them."),
     subdeps=[("gps-filter", "ingest-gateway"), ("map-matching", "gps-filter")],
     flow="Points enter through the gateway with per-driver sequence numbers, are deduplicated and acknowledged, filtered in per-driver state, and dispatched to consumers. In Phase V the pipeline is gateway → Kafka → Flink (filter + map match) → sinks.",
     data="No OLTP tables. Phase I–II: latest position in `driver_positions(driver_id PK, lat, lng, heading, speed, ts)` and on-trip breadcrumbs in Location History. Phase III+: Kafka topic retention 24 h. Filter state per driver lives in memory (Phase I–IV) or Flink keyed state (Phase V).",
     rel=[["Backpressure", "Gateway sheds idle-driver updates first (lower frequency) when downstream lags; on-trip updates prioritized."], ["Client resend", "Unacked points buffered on device (up to 10 min) and resent with sequence numbers."], ["Idempotency", "Dedup by (driver_id, seq)."]],
     sec=[["Spoofing", "Mock-location flags, plausibility (speed > 250 km/h), attestation; signals to fraud."], ["Privacy", "Driver location is personal data; precise history access limited; retention bounded."]],
     adrs=[A("Client batching with sequence numbers", "I", "Battery and flaky networks.", [("One request per point", "Rejected: battery/overhead"), ("Batch + seq + ack", "Chosen")], "Batch every 4 s; per-driver monotonically increasing seq; server acks highest contiguous seq.", "Efficient, loss-recoverable, dedupable.", "Up to 4 s extra latency for idle drivers.", "When live tracking needs < 1 s latency → stream protocol (Phase V).")],
     qa=[Q("Performance", "At 150K updates/s, why not write each update to PostgreSQL?", "150K row writes/s with indexes is beyond a single primary and wasteful: most points are only needed as 'latest position' (overwritten seconds later) or as on-trip breadcrumbs (append-only, read rarely). The design keeps latest positions in memory (geo index), appends on-trip points to a write-optimized store (wide-column with TTL), and uses Kafka as the durable buffer. PostgreSQL only sees trip-level summaries.", "Time-series DBs (TimescaleDB) can absorb more, but still pay for indexing data that's mostly discarded.")],
     impl_order=["ingest-gateway", "gps-filter", "map-matching"], pkg="""com.atlas.location.ingest
├── gateway (LocationBatchController, SeqTracker, Admission)
├── filter  (KalmanFilter, OutlierRules, DriverFilterState)
└── match   (HmmMapMatcher, RoadGraphClient)""",
     tests=[T("Load", "150K points/s synthetic", "p95 freshness < 2 s; no loss on trip"), T("Failure", "Geo index down 5 min", "Ingest continues; backlog drains"), T("Correctness", "Duplicate batch resend", "No duplicate points downstream")],
     evo=[("I", "Endpoint in monolith", "Latest position table; trip points table", "Seq dedup", "Pilot"), ("E", "Same; Redis for latest positions", "Redis GEO", "Shedding idle updates", "≈75/s"),
          ("R", "Ingest service + Kafka", "Topic keyed by driver", "Consumers independent", "≈750/s and many consumers"), ("E", "Horizontally scaled gateways", "Partition count sized for 10K/s", "SLO on freshness", "≈6K/s"),
          ("R", "gRPC streaming gateways + Flink", "Kafka keyed by H3 res-5", "Checkpointed state", "60–150K/s"), ("E", "Per-region pipelines", "Region-local topics", "Region isolation", "Global")],
     ideas={"now": ["Seq numbers from day one"], "next": ["Adaptive frequency (lower when stationary)"], "adv": ["Edge pre-filtering on device"], "rej": ["MQTT broker for drivers: weak ops tooling at our scale vs gRPC streams"]})

sub(id="ingest-gateway", comp="location-ingest", name="Location Ingest Gateway", phase="I", cat="Throughput · Edge",
    resp="Authenticate driver devices, accept batched or streamed location points, deduplicate by sequence, acknowledge, apply admission control and hand points to the processing stage.",
    inp="point batches {seq, lat, lng, accuracy, speed, heading, device_ts}", out="acks; accepted points to the filter / Kafka", deps="Identity (JWT), Supply (driver state for priority)", cons="GPS filter", own="per-driver last-acked seq",
    problem="Absorb a very high rate of small, unreliable, possibly duplicated writes from mobile devices, and acknowledge quickly without losing on-trip data.",
    without="Lost or duplicated points, overloaded downstream, battery-draining clients.", guar=["A point acknowledged is durably handed off (Phase III+: in Kafka)", "No duplicate (driver, seq) forwarded", "On-trip traffic prioritized over idle"], nong=["Ordering across drivers", "Delivery of points older than 10 min (dropped)"],
    usecase="A driver passes through a tunnel for 90 s. The app buffers 45 points. On exit it sends them in 2 batches, the gateway acks, and tracking backfills the path.",
    derive="- Acks must reflect durable hand-off, or the client discards data that's then lost, so ack after Kafka produce (acks=all) from Phase III.\n- Dedup needs per-driver state: the highest contiguous seq is enough (points arrive mostly in order).\n- Admission control must favour on-trip drivers, which needs the driver's state (cached).",
    conc="Per-driver seq tracking is single-writer if traffic for a driver is routed consistently (sticky by driver_id at the LB or stream). Otherwise use Redis `SET seq IF greater` via Lua.", consistency="Per-driver monotonic acceptance.",
    idem="Points with seq ≤ last-accepted are dropped and acked (idempotent resend).", order="Out-of-order points within a batch are sorted by seq. Late points (seq gap filled later) are forwarded with a late flag, and consumers decide.",
    restart="Gateway is stateless apart from seq cache (Redis). Losing it causes at most duplicate forwarding, which the downstream filter dedups again.", scale="Stateless horizontal gateways. Phase V: gRPC streams pinned per driver connection, ≈20K streams per node.",
    arch="Phase I: Spring controller `POST /v1/locations:batch` writes to the in-process filter. Phase III: a Netty/Spring WebFlux service producing to Kafka with `acks=all, enable.idempotence=true`, keyed by driver_id. Phase V: bidirectional gRPC stream (server pushes config such as update frequency, client pushes points).",
    modules=[["AuthFilter", "JWT + device binding"], ["SeqTracker", "Last contiguous seq per driver"], ["Admission", "Priority by driver state; shed idle under backpressure"], ["Producer", "Kafka idempotent producer"]],
    d_arch=("""flowchart LR
  D["Driver app"] -->|batch/stream| LB["L4/L7 LB (sticky driver)"] --> GW["Gateway"]
  GW --> AU["AuthFilter"] --> SQ["SeqTracker"] --> AD["Admission"] --> PR["Producer"] --> K[["driver-locations"]]
  SQ --> R[("Redis seq")]
  AD --> SC["Supply state cache"]""", "Stateless gateway with small per-driver dedup state."),
    d_seq=("""sequenceDiagram
  participant D as Driver
  participant G as Gateway
  participant K as Kafka
  D->>G: batch seq 300..305
  G->>G: drop seq ≤ 299
  G->>K: produce (acks=all)
  K-->>G: ok
  G-->>D: ack 305
  Note over D: discard buffered ≤ 305""", "Ack after durable produce."),
    nostate="Per-driver state is a single integer (last seq), not a lifecycle.",
    d_flow=("""flowchart LR
  P["point"] --> V["plausibility: lat/lng range, accuracy < 100m, ts within 10 min"] --> S["seq dedup"] --> K[["topic"]]""", "Cheap validation before any downstream cost."),
    d_fail=("""flowchart TB
  KF["Kafka unavailable"] --> NA["no ack; client buffers & retries with backoff"]
  OV["downstream lag > threshold"] --> SH["shed idle driver updates (reduce freq via stream config)"]""", "Unacked data stays on the device. Overload reduces idle update frequency first."),
    sql="-- No relational tables. Redis: `seq:{driver_id}` → last contiguous seq (TTL 1h).",
    data="Kafka topic `driver-locations`: partitions = 2× expected peak / 5K msgs per partition, 24 h retention, Avro schema with schema registry.",
    api="""POST /v1/locations:batch  (Bearer driver JWT)
{ "points":[{"seq":301,"lat":18.5204,"lng":73.8567,"acc":8.0,"spd":11.2,"hdg":92,"ts":1730540000123}], "trip_id":"…"? }
-> 200 {"acked_seq":305, "next_interval_ms":4000}
gRPC (P5): rpc Stream(stream LocationBatch) returns (stream ServerControl)""",
    api_notes="`next_interval_ms` lets the server tune client frequency (backpressure, battery). `trip_id` is advisory. The authoritative trip association comes from Supply state.",
    mech=[("Idempotent Kafka producer", "Producer sequence numbers let brokers discard retries of the same batch, preventing broker-level duplicates when the gateway retries."), ("Server-driven frequency", "Lowering `next_interval_ms` for idle drivers under load reduces volume at the source, a form of backpressure that works across the network.")],
    code="""public Mono<Ack> ingest(DriverId d, LocationBatch b) {
    long last = seq.lastAcked(d);
    List<Point> fresh = b.points().stream().filter(p -> p.seq() > last).sorted(comparingLong(Point::seq)).toList();
    if (fresh.isEmpty()) return Mono.just(new Ack(last, interval(d)));
    return producer.send(d, fresh)                     // acks=all
        .then(Mono.fromRunnable(() -> seq.advance(d, fresh.getLast().seq())))
        .thenReturn(new Ack(fresh.getLast().seq(), interval(d)));
}""", cx="O(batch size).",
    fail=[F("Kafka outage", "Produce errors", "No acks; device buffers", "Retry; clients resend", "No loss within 10 min buffer"), F("Gateway crash after produce, before ack", "Client timeout", "Duplicate resend", "Seq dedup at gateway/filter", "No duplicate effect"),
          F("Thundering reconnect after outage", "Connection spike", "Gateway overload", "Jittered client reconnect; admission", "None")],
    alts=[["MQTT", "Rejected", "Broker ops + custom auth", "IoT-like fleets"], ["WebSockets", "Viable", "Fine for tracking push; gRPC better typed", "Web clients"], ["UDP", "Rejected", "Lossy; no TLS simplicity", "Never"]],
    adrs=[A("Ack after durable hand-off", "III", "Avoid silent loss.", [("Ack on receipt", "Rejected: loss on crash"), ("Ack after Kafka acks=all", "Chosen")], "Durable before ack.", "No loss for acked points.", "+5–10 ms latency.", "N/A")],
    qa=[Q("Reliability", "During a 10-minute Kafka outage, what is lost?", "Nothing that matters: devices buffer unacked points up to 10 minutes and resend. Geo-index freshness degrades (drivers age out as stale after 45 s, so dispatch shrinks supply) and tracking shows last-known positions. After recovery, a burst of resends arrives, absorbed by admission control and partition headroom. Points older than 10 min are dropped by validation. On-trip breadcrumbs older than that are reconstructed from map matching between surrounding points.", "Writing to a local disk queue on the gateway adds complexity and only moves the loss window.")],
    tests=[T("Unit", "Resend seq already acked", "Acked, not forwarded"), T("Load", "50K streams per node", "CPU < 70%"), T("Failure", "Kafka broker loss", "No acked-point loss (acks=all, ISR ≥ 2)")],
    evo=["I: REST batch in monolith", "E: Redis seq tracking; shedding", "R: Separate service producing to Kafka", "E: Horizontal scale; sticky routing", "R: gRPC streams; server-driven frequency", "E: Regional gateways"],
    ideas={"now": ["Seq + ack protocol"], "next": ["Adaptive intervals"], "adv": ["QUIC transport for mobile handover"], "rej": ["Per-point HTTP requests"]})

sub(id="gps-filter", comp="location-ingest", name="GPS Noise Filter", phase="I", cat="Algorithm · Signal processing",
    resp="Reject implausible points and smooth noisy GPS into a best-estimate position, speed and heading per driver.",
    inp="accepted points per driver (ordered by seq)", out="filtered points with confidence", deps="Ingest gateway", cons="Geo index, Map matching, Fraud (anomalies)", own="per-driver filter state",
    problem="Raw GPS jumps hundreds of metres in urban canyons and drifts when stationary. Using raw points makes cars jump on maps, inflates distance-based fares and misleads dispatch.",
    without="Fare overcharges from zig-zag tracks; drivers 'teleporting'; poor ETAs.", guar=["Points implying speed > 250 km/h from last accepted are rejected", "Stationary drift suppressed (no distance accumulation while still)", "Output monotonic in time per driver"], nong=["Lane-level accuracy", "Correct road attribution (map matching does that)"],
    usecase="A driver waits at a light in a high-rise district. Raw GPS wanders in a 60 m radius. The filter reports a stationary position with zero speed, so no fare distance accrues.",
    derive="- Physical motion is continuous, so a motion model (constant velocity) plus measurement noise (reported accuracy) leads to a Kalman filter.\n- Gross outliers break Kalman, so gate on physically impossible speed first.\n- Stationary detection: low speed + accuracy-scaled displacement threshold.",
    conc="State per driver accessed by one thread at a time (partition by driver).", consistency="Per-driver sequential processing.", idem="Points with seq ≤ last processed are skipped (state stores last seq).", order="Late points (older ts than state) are not fed to the filter. They go to history only, flagged late.",
    restart="Phase I–IV: state lost on restart, re-converges within ~3 points (acceptable). Phase V: Flink keyed state checkpointed.", scale="O(1) per point; CPU-light. Scales with partitions keyed by driver.",
    arch="Pipeline per point: **validate → outlier gate → Kalman update → stationary detector → emit**. Each driver has a small state object: last state vector [lat, lng, v_lat, v_lng], covariance, last ts and seq.",
    modules=[["OutlierGate", "Implied speed, acceleration, accuracy thresholds"], ["KalmanFilter", "2D constant-velocity model in local ENU metres"], ["StationaryDetector", "Speed < 1 m/s for 3 points → hold position"], ["StateStore", "Per-driver state map (Phase V: Flink keyed state)"]],
    d_arch=("""flowchart LR
  IN["points (keyed by driver)"] --> OG["OutlierGate"] --> KF["Kalman update"] --> SD["StationaryDetector"] --> OUT["filtered point"]
  ST[("per-driver state")] <--> OG & KF & SD
  OG -->|rejected| AN["anomaly stream (fraud)"]""", "Per-driver stateful pipeline. Rejections go to fraud for spoofing analysis."),
    d_seq=("""sequenceDiagram
  participant I as Input
  participant G as OutlierGate
  participant K as Kalman
  participant S as Stationary
  I->>G: point p (acc 12m)
  G->>G: implied speed from last = 31 m/s ok
  G->>K: predict(dt) then update(p, R=acc^2)
  K->>S: estimate (speed 0.4 m/s)
  S-->>I: emit held position, speed 0""", "One point through the filter."),
    d_state=("""stateDiagram-v2
  [*] --> Uninitialized
  Uninitialized --> Tracking: first good point
  Tracking --> Stationary: speed<1 m/s ×3
  Stationary --> Tracking: displacement > 3σ
  Tracking --> Uninitialized: gap > 120 s""", "Filter mode per driver. A long gap resets the state rather than predicting across it."),
    d_flow=("""flowchart LR
  LL["lat,lng"] --> ENU["project to local metres"] --> KF["filter"] --> LL2["back to lat,lng"]""", "Filtering in a local metric frame avoids degree-based distortions."),
    d_fail=("""flowchart TB
  SP["spoofed teleport"] --> R["rejected by gate"] --> F["fraud signal"]
  L["state lost"] --> RE["re-init on next point"]""", "Rejection protects downstream, and state loss self-heals."),
    sql="-- No relational data. State object (≈100 bytes/driver) in memory or Flink RocksDB keyed state.", data="Ephemeral state; filtered points flow on.",
    api="""interface GpsFilter { Optional<FilteredPoint> accept(DriverId d, RawPoint p); }
record FilteredPoint(double lat, double lng, double speedMps, double headingDeg, double confidence, long ts, boolean stationary) {}""",
    mech=[("Kalman filter", "Predict: x' = F·x, P' = F·P·Fᵀ + Q (process noise grows with dt). Update: K = P'·Hᵀ(H·P'·Hᵀ + R)⁻¹, x = x' + K(z − H·x'). R comes from the device's reported accuracy, so precise fixes move the estimate more than poor ones."),
          ("Speed gating", "Reject if haversine(prev, p)/dt > 70 m/s, or if accuracy > 100 m. This removes gross jumps before they corrupt the filter."), ("Hysteresis for stationary", "Enter stationary after 3 slow points, and exit only when displacement exceeds 3σ of accuracy. This prevents drift accumulation.")],
    code="""public Optional<FilteredPoint> accept(DriverId d, RawPoint p) {
    FilterState s = states.computeIfAbsent(d, k -> FilterState.init(p));
    if (p.seq() <= s.lastSeq() || p.ts() <= s.lastTs()) return Optional.empty();
    double dt = (p.ts() - s.lastTs()) / 1000.0;
    if (dt > 120) { states.put(d, FilterState.init(p)); return Optional.of(FilteredPoint.of(p)); }
    if (Geo.haversine(s.lat(), s.lng(), p.lat(), p.lng()) / dt > 70 || p.accuracy() > 100) { anomalies.report(d, p); return Optional.empty(); }
    s.predict(dt); s.update(p.toEnu(s.origin()), p.accuracy() * p.accuracy());
    return Optional.of(stationary.apply(s, p));
}""", cx="O(1) per point (4×4 matrix ops).",
    fail=[F("Urban canyon multipath", "Accuracy high, jumps", "Possible wrong position", "Gate + Kalman weighting", "Smoothed"), F("Long tunnel gap", "dt > 120 s", "Filter would extrapolate wrongly", "Reset state", "Trip distance via map matching across gap"),
          F("Out-of-order points", "ts ≤ last", "Possible regression", "Skip for filter; send to history", "Monotonic output")],
    alts=[["Moving average", "Rejected", "Lags and ignores accuracy", "Display-only smoothing"], ["Particle filter", "Advanced", "Better non-linear handling, costlier", "Indoor/complex terrains"], ["Raw points", "Rejected", "Noise", "Never"]],
    adrs=[A("Kalman with speed gating", "I", "Need cheap, robust smoothing.", [("No filter", "Rejected"), ("Kalman + gate", "Chosen")], "Constant-velocity Kalman in ENU with outlier gate.", "Well understood, O(1).", "Tuning Q per city.", "If map-matching quality issues persist → combine with HMM output.")],
    qa=[Q("Correctness", "Why not just let map matching handle noise?", "Map matching runs only on on-trip points and is expensive. Geo-index positions for idle drivers (most points) need cheap de-noising, and map matching itself works better on pre-filtered input with fewer outliers to explain.", "")],
    tests=[T("Unit", "Teleport 2 km in 2 s", "Rejected; anomaly emitted"), T("Unit", "Stationary jitter 30 m for 5 min", "Distance accumulated < 5 m"), T("Property", "Shuffled seq input", "Output ts strictly increasing")],
    evo=["I: In-process filter with in-memory state", "U: No change needed", "E: Runs in ingest service consumers", "U: No change needed", "R: Flink keyed process function with checkpointed state", "E: Regional jobs"],
    ideas={"now": ["Use device accuracy as R"], "next": ["Fuse accelerometer data"], "adv": ["Learned noise models per device model"], "rej": ["Server-side dropping of all low-accuracy points: loses data in canyons"]})

sub(id="map-matching", comp="location-ingest", name="Map Matching", phase="III", cat="Algorithm · Geospatial",
    resp="Snap on-trip GPS tracks to the most probable sequence of road segments, producing an accurate path and distance for fares, ETAs and safety.",
    inp="filtered on-trip points, road graph", out="matched path (segment ids, offsets), matched distance", deps="Road network (Routing)", cons="Fare finalization, Trip tracking, Routing (traffic speeds), Safety (route deviation)", own="matched path per trip",
    problem="Even filtered GPS can sit on the wrong parallel road or skip corners. Fares based on straight-line point distances under- or over-count.",
    without="Fare disputes; wrong traffic speed estimates; missed route deviations.", guar=["Matched path is connected on the road graph", "Distance computed along matched path", "Gaps bridged by shortest path between matched endpoints"], nong=["Lane-level accuracy"],
    usecase="A trip through a flyover/underpass junction: raw points alternate between the levels. HMM matching chooses the consistent elevated road using transition probabilities.",
    derive="- Each point has several candidate road segments (emission probability by distance).\n- Consecutive choices must be connected with plausible route length vs straight distance (transition probability).\n- The most likely sequence of hidden states gives a hidden Markov model, solved with Viterbi.\n- Online use needs a sliding window (fixed-lag) to emit results with bounded delay.",
    conc="Per-trip sequential processing (keyed by trip_id).", consistency="Fixed-lag output: a point's match is final after K subsequent points (K=5).", idem="Reprocessing the same points yields the same path (deterministic Viterbi).", order="Late points within the window are inserted; later than the window, they are ignored for matching.",
    restart="Phase III: window rebuilt from breadcrumbs. Phase V: Flink keyed state.", scale="Candidate search via spatial index of road segments (R-tree). ≈ 0.2 ms/point. Scales with on-trip drivers only.",
    arch="Online HMM matcher (fixed-lag Viterbi) per trip: **candidate generation (segments within 50 m) → emission (Gaussian on perpendicular distance) → transition (exponential on |route_dist − great_circle_dist|) → Viterbi window → emit finalized segments**. Gaps > 60 s are bridged by a shortest-path query.",
    modules=[["CandidateFinder", "R-tree lookup of nearby segments"], ["ProbabilityModel", "Emission σ≈5–10 m, transition β tuned"], ["FixedLagViterbi", "Window of K points"], ["GapBridger", "Shortest path across gaps"], ["DistanceAccumulator", "Distance along matched path"]],
    d_arch=("""flowchart LR
  P["on-trip filtered points"] --> CF["CandidateFinder"] --> RT[("road R-tree")]
  CF --> PM["ProbabilityModel"] --> VT["FixedLagViterbi"]
  VT --> GB["GapBridger"] --> RG["Road graph shortest path"]
  VT --> DA["DistanceAccumulator"] --> OUT["matched segments + distance"]""", "Standard HMM map matching made online with a fixed-lag window."),
    d_seq=("""sequenceDiagram
  participant P as Point stream
  participant V as Viterbi
  participant C as Candidates
  participant O as Output
  P->>C: point k
  C-->>V: segments s1..s4 with emission probs
  V->>V: update path scores with transitions from k-1
  V->>O: finalize point k-5 (best path back-pointer)""", "Each new point finalizes the point K steps back."),
    nostate="Per-trip state is the Viterbi window (scores and back-pointers), a data structure rather than a lifecycle.",
    d_flow=("""flowchart LR
  PTS["points"] --> SEG["segment ids + offsets"] --> DIST["matched km"] --> FARE["fare"]
  SEG --> SPEED["segment speeds"] --> TRAFFIC["traffic model"]""", "Matched output feeds fares and traffic estimation."),
    d_fail=("""flowchart TB
  G["no candidates (off-road / new road)"] --> RAW["fallback: filtered straight-line distance, flag trip"]
  B["window broken (gap)"] --> SP["bridge via shortest path"]""", "Fallbacks are flagged for fare review rather than silently trusted."),
    sql="""-- Phase III: matched output stored per trip
CREATE TABLE location.trip_matched_path (trip_id uuid PRIMARY KEY, segments bigint[] NOT NULL, distance_m int NOT NULL,
  fallback_used boolean NOT NULL DEFAULT false, matched_at timestamptz NOT NULL);""",
    data="Matched path retained with trip records (fare evidence) for 3 years; raw points per Location History retention.", api="""interface MapMatcher { MatchedPath match(TripId t, List<FilteredPoint> pts); }  // batch
Stream: on-trip points -> MatchedSegment{trip_id, segment_id, enter_ts, exit_ts, distance_m}""",
    mech=[("Viterbi algorithm", "Dynamic programming over candidates: score(k, s) = max over s' of score(k−1, s') + log T(s'→s) + log E(p_k | s). Keep back-pointers, and the best final state traced back gives the path. Complexity O(n·c²) with c≈4 candidates."),
          ("Fixed-lag smoothing", "After K further points the best path through point k rarely changes, so finalize then. This bounds latency (K × 2 s) and memory.")],
    code="""double[] next = new double[cands.size()];
for (int j = 0; j < cands.size(); j++) {
    double best = Double.NEGATIVE_INFINITY; int arg = -1;
    for (int i = 0; i < prev.size(); i++) {
        double t = prevScore[i] + logTransition(prev.get(i), cands.get(j), gcDist);
        if (t > best) { best = t; arg = i; }
    }
    next[j] = best + logEmission(point, cands.get(j)); back[k][j] = arg;
}""", cx="O(points × candidates²); candidates ≈ 4.",
    fail=[F("Road graph missing new road", "No candidates / high fallback rate per area", "Distance underestimated", "Fallback + map data update", "Fare review flag"), F("Matcher lag", "Window lag metric", "Late tracking polish", "Scale consumers", "Final distance computed at trip end in batch")],
    alts=[["Provider snap-to-roads API", "Phase I–II choice", "Per-call cost", "Low volumes"], ["Nearest segment per point", "Rejected", "Wrong on parallel roads", "Never"]],
    adrs=[A("In-house HMM from Phase III", "III", "Provider cost scales per point.", [("Provider API", "Phase I–II"), ("In-house HMM", "Chosen at III")], "OSM-based road graph + HMM.", "Cost and control.", "Map data maintenance.", "If map quality in a market is poor → provider fallback per market.")],
    qa=[Q("Correctness", "Should the final fare use online fixed-lag output or a batch re-match at trip end?", "Batch re-match at trip end over the full track (full Viterbi, no lag constraint) is more accurate and costs little once per trip. Online output serves live tracking and rough ETAs. The fare uses the batch result, and both are stored so disputes can compare.", "")],
    tests=[T("Unit", "Parallel service road", "Matched to main road consistent with heading"), T("Integration", "Recorded city tracks with ground truth", "Segment accuracy > 97%"), T("Failure", "60 s tunnel gap", "Bridged path through tunnel")],
    evo=["N: Phase I–II use provider snap-to-roads at trip end only", "N: Same, still provider-based", "I: In-house HMM consumer on Kafka", "E: Batch re-match at trip end for fares", "R: Flink job; segment speeds feed traffic", "E: Regional road graphs"],
    ideas={"now": ["n/a before III"], "next": ["Traffic speeds from matched segments"], "adv": ["Learned transition models"], "rej": ["Nearest-segment snapping"]})

# ======================================================================= Geospatial Index
comp(id="geo-index", domain="location", name="Geospatial Index & Proximity Search", tag="Geo · Hot path", phase="I", kind="Logical component → deployable service (Phase IV) → sharded in-memory index (Phase V)",
     biz="Answers 'which available drivers are near this point?' in milliseconds, and 'is this point inside the airport zone / service area?'.",
     eng="A continuously updated spatial index of driver positions with availability attributes, plus a geofence store, supporting k-nearest/radius queries under heavy write load.",
     deploy="PostGIS query in monolith (I); Redis GEO (II–III); Geo service (IV); H3-sharded in-memory index fed by stream (V); per region (VI).",
     data_own="Latest driver positions + availability flags + category; geofence polygons.", up=["location-ingest", "driver-supply", "fleet-vehicle"], down=["dispatch", "product-catalog", "pricing", "trip-tracking"], ext=["H3 library"],
     interfaces="`nearbyDrivers(point, radius, filters, limit)`, `driversInCells(cells)`, `geofencesContaining(point)`; Phase V gRPC `Geo.Nearby`.",
     problem="Dispatch needs candidates near a pickup from a set of drivers whose positions change every few seconds. Supply/demand per area feeds surge. Geofences (airports, restricted zones) change rules.",
     fr=["Upsert driver position + availability", "Radius / kNN search with filters (category, available)", "Count drivers per cell (supply)", "Geofence containment"],
     nfr=["Query p99 < 20 ms", "Freshness < 5 s", "Writes: up to 500K/s (VI)", "Stale entries excluded after 45 s"], workload="Writes = location rate; reads = dispatch candidate searches + rider 'cars nearby' previews (≈ 10× requests).",
     success="Candidate lists reflect reality within seconds.", failure="Candidates far away or ghosts; index overload stalls dispatch.",
     derive="Spatial queries need a structure where nearby points share keys: geohash, S2 or H3 cells. Hexagonal H3 gives uniform neighbour distances (all 6 neighbours equidistant), which suits radius approximation with k-rings. Writes dominate and are overwrites, so in-memory structures beat disk indexes. Partitioning by cell makes geography the shard key.",
     owns=["Latest position index", "Cell membership", "Geofences"], not_owns=["Driver state transitions (Supply)", "Ranking (Dispatch)"], sync=["Nearby queries", "Geofence lookups"], **{"async": ["Position updates from stream", "Availability changes from Supply events"]},
     boundary_why="The index is a derived, rebuildable view of Location + Supply. It owns no source of truth, so it can be sharded, dropped and rebuilt freely.",
     hld=("""flowchart LR
  LOC["filtered positions"] --> UPD["index updater"]
  SUP["DriverStatusChanged"] --> UPD
  UPD --> IDX["H3 cell index<br/>cell → {driver: pos, flags, ts}"]
  DSP["Dispatch"] -->|nearby(p, r)| PQ["Proximity search"] --> IDX
  CAT["Catalog/ETA preview"] --> PQ
  GF["Geofence service"] --> POLY[("polygons + cell cover")]
  PRC["Pricing / Dispatch rules"] --> GF""", "Updates flow in from location and supply. Queries read cell buckets. Geofences are precomputed as cell covers for O(1) lookup."),
     seq=("""sequenceDiagram
  participant D as Dispatch
  participant P as Proximity
  participant I as Index
  D->>P: nearby(18.52,73.85, r=3km, cat=UberX, available)
  P->>P: cells = kRing(h3(p, res 8), k=4)
  P->>I: fetch buckets(cells)
  I-->>P: 37 drivers
  P->>P: filter (fresh, available, cat), sort by haversine, top 20
  P-->>D: candidates""", "Proximity query via k-ring of hexagons."),
     subdeps=[("proximity-search", "h3-cell-index"), ("geofencing", "h3-cell-index")],
     flow="Writers update the driver's cell bucket (moving between buckets on cell change). Readers compute the cell cover of the search circle and scan buckets. The index is rebuilt from the latest-position stream on restart.",
     data="Phase I: `driver_positions(driver_id PK, geom geography(Point), available, category, updated_at)` with GiST index. Phase II–III: Redis GEO sorted sets per city/category. Phase V: in-memory `Map<cell, Map<driverId, Entry>>` per shard, shards owning sets of H3 res-5 parent cells.",
     rel=[["Rebuild", "Index is derived; rebuild from Kafka (latest per driver via compacted topic) in seconds."], ["Staleness", "Entries carry ts; queries exclude > 45 s."], ["Hot cells", "Phase V splits hot parent cells across replicas."]],
     sec=[["Privacy", "Rider-facing 'cars nearby' returns jittered positions, never driver ids."], ["Abuse", "Rate-limit nearby queries (competitor scraping)."]],
     adrs=[A("H3 hexagonal cells as the spatial key", "II", "Need uniform neighbourhoods and a natural shard key.", [("Geohash", "Rejected: edge discontinuities and uneven neighbour distances"), ("S2", "Viable"), ("H3", "Chosen")], "H3 res 8 (≈0.74 km²) for buckets, res 5 for sharding, res 7 for surge.", "Uniform k-ring radius approximation; hierarchical parent/child for sharding.", "Hexagons don't perfectly nest (approximate parent containment).", "If polygon coverage precision matters more → S2.")],
     qa=[Q("Scaling", "Why not keep using PostGIS at Phase V?", "At 60K+ position writes/s, each update rewrites a row and its GiST entry and generates WAL, which saturates a primary and replication. The workload is 'latest value wins' with no durability need (rebuildable), which suits an in-memory structure. PostGIS remains right for geofence polygons and analytics, where data changes slowly.", "Sharding PostGIS by city postpones the limit but keeps paying WAL cost for ephemeral data.")],
     impl_order=["h3-cell-index", "proximity-search", "geofencing"], pkg="""com.atlas.geo
├── index     (CellIndex, Entry, IndexUpdater)
├── search    (ProximitySearch, KRingCover)
├── geofence  (GeofenceStore, CellCover, PointInPolygon)
└── shard     (ShardMap, Rebalancer)  // Phase V""",
     tests=[T("Load", "100K updates/s + 5K queries/s per shard", "Query p99 < 20 ms"), T("Correctness", "Driver crossing cell boundary", "Appears exactly once"), T("Recovery", "Shard restart", "Rebuilt from compacted topic < 30 s")],
     evo=[("I", "PostGIS ST_DWithin in monolith", "GiST index", "DB durability", "Simplest correct"), ("R", "Redis GEO per city", "GEOADD/GEOSEARCH", "Rebuildable", "Write load + latency"),
          ("E", "Fed by Kafka consumers", "Compacted latest-position topic", "Rebuild from topic", "Event-driven"), ("R", "Geo service with H3 buckets", "In-memory per city", "Replicas per city", "Isolation + latency"),
          ("R", "H3-sharded index cluster with hot-cell splits", "Shard map", "Shard failover", "60–150K/s"), ("E", "Per-region index clusters", "—", "Region isolation", "Global")],
     ideas={"now": ["Exclude stale entries at query time"], "next": ["Cell counts for supply metrics"], "adv": ["GPU kNN for batch matching"], "rej": ["Elasticsearch geo for hot path: refresh interval adds latency and write cost"]})

sub(id="h3-cell-index", comp="geo-index", name="H3 Cell Index (Driver Position Store)", phase="II", cat="Data structure · In-memory index",
    resp="Maintain, for every H3 cell, the set of drivers currently in it with their latest position, availability, category and timestamp.",
    inp="filtered positions, status changes", out="cell buckets for queries; per-cell counts", deps="H3 library, Kafka (Phase III+)", cons="Proximity search, Geofencing, Surge (counts)", own="In-memory index",
    problem="Support millions of position overwrites per minute and fast neighbourhood reads, with drivers moving between cells.",
    without="Dispatch queries scan all drivers in a city (O(n)) or hammer a disk index.", guar=["Each driver appears in exactly one cell bucket", "Entries reflect latest accepted position (by ts)", "Index rebuildable from stream"], nong=["Durability (derived data)"],
    usecase="Driver moves from cell A to B: entry removed from A and inserted in B atomically from the reader's perspective. A query covering both never sees the driver twice.",
    derive="- Point → cell is O(1) with H3 `latLngToCell`.\n- Moving drivers need a reverse map driver → current cell to remove the old entry.\n- Concurrent reads during writes favour concurrent maps with per-driver single-writer updates.",
    conc="Updates partitioned by driver (single writer per driver via Kafka partition → consumer thread). Readers use ConcurrentHashMap views. A move does insert-new then remove-old, and readers dedupe by driver id during query (cheap).",
    consistency="Eventually consistent with the location stream (≤ seconds). Per-driver monotonic by ts.", idem="Upserting the same (driver, ts) twice is a no-op; older ts ignored.", order="Older-ts updates dropped (per-driver last ts).",
    restart="Rebuild by consuming the compacted `driver-latest` topic from the beginning (one record per driver), ≈ 250K records in seconds.", scale="Memory ≈ 100 B/driver → 250K drivers ≈ 25 MB per city cluster. CPU bound by update rate. Shard by res-5 parent cell in Phase V.",
    arch="Phase II: Redis `GEOADD drivers:{city}:{category}` with availability encoded by separate sets. Phase IV+: Java service holding `ConcurrentHashMap<Long cell, ConcurrentHashMap<UUID, Entry>>` + `ConcurrentHashMap<UUID, Long> driverCell`, fed by Kafka consumers. Counts per cell are maintained incrementally.",
    modules=[["IndexUpdater", "Apply position/status updates"], ["CellBuckets", "cell → drivers"], ["DriverCellMap", "driver → cell"], ["CellCounters", "available counts per category"], ["Rebuilder", "Bootstrap from compacted topic"]],
    d_arch=("""flowchart LR
  K1[["driver-latest (compacted)"]] --> RB["Rebuilder"]
  K2[["filtered positions"]] --> UP["IndexUpdater"]
  K3[["DriverStatusChanged"]] --> UP
  UP --> CB["CellBuckets"] & DC["DriverCellMap"] & CC["CellCounters"]
  RB --> CB""", "Two maps and counters, fed by streams."),
    d_seq=("""sequenceDiagram
  participant U as Updater
  participant DC as DriverCellMap
  participant CB as CellBuckets
  U->>U: cell = h3(lat,lng,8)
  U->>DC: old = put(driver, cell)
  U->>CB: bucket(cell).put(driver, entry)
  alt old != cell
    U->>CB: bucket(old).remove(driver)
  end""", "Move between cells. Insert happens before remove, so a driver is never missing from both."),
    nostate="Entries are values overwritten by newer timestamps. Availability state is owned by Supply and mirrored as a flag.",
    d_flow=("""flowchart LR
  POS["pos(lat,lng,ts)"] --> CELL["h3 res8"] --> BUCKET["bucket[cell][driver]=entry"]
  ST["status"] --> FLAG["entry.available"]
  BUCKET --> CNT["counts[cell][category]"]""", "Two independent inputs update the same entry."),
    d_fail=("""flowchart TB
  N["node crash"] --> RP["replica serves; restarted node rebuilds from compacted topic"]
  L["consumer lag"] --> ST["staleness filter hides old entries; alert on lag"]""", "Rebuild and staleness filtering are the recovery tools."),
    sql="""-- Phase I equivalent (PostGIS):
CREATE TABLE geo.driver_positions (driver_id uuid PRIMARY KEY, pos geography(Point,4326) NOT NULL,
  available boolean NOT NULL, category text NOT NULL, city text NOT NULL, updated_at timestamptz NOT NULL);
CREATE INDEX driver_pos_gist ON geo.driver_positions USING gist (pos) WHERE available;""",
    data="In-memory only from Phase II. The compacted Kafka topic keyed by driver_id is the durable snapshot.", api="""void upsertPosition(UUID driver, double lat, double lng, long ts)
void setAvailability(UUID driver, boolean available, String category, long statusVersion)
Collection<Entry> bucket(long cell)
int availableCount(long cell, String category)""",
    mech=[("H3 indexing", "`latLngToCell(lat, lng, 8)` maps to a 64-bit cell id. Res 8 hexagons have ≈461 m edge, so a k-ring of k=4 covers ≈3 km radius."), ("Compacted topic as snapshot", "Kafka log compaction keeps the latest record per key, so replaying it reconstructs the current position of every driver without a database.")],
    code="""public void upsertPosition(UUID d, double lat, double lng, long ts) {
    long cell = h3.latLngToCell(lat, lng, 8);
    Entry e = new Entry(d, lat, lng, ts, availability.getOrDefault(d, Availability.OFFLINE));
    buckets.computeIfAbsent(cell, c -> new ConcurrentHashMap<>()).merge(d, e, (o, n) -> n.ts() > o.ts() ? n : o);
    Long old = driverCell.put(d, cell);
    if (old != null && old != cell) { var b = buckets.get(old); if (b != null) b.remove(d); }
}""", cx="O(1) per update.",
    fail=[F("Node loss", "Health check", "Queries to that shard fail over to replica", "Rebuild", "Seconds of staleness"), F("Out-of-order update", "ts check", "None", "Ignore older", "Monotonic")],
    alts=[["Redis GEO", "Phase II–III", "Simple, durable-ish", "Until per-city write rate exceeds one Redis node"], ["Quadtree", "Viable", "Adaptive density", "Highly non-uniform density"], ["Geohash buckets", "Rejected", "Edge effects", "Never"]],
    adrs=[A("Move from Redis GEO to in-process H3 maps at Phase IV", "IV", "Network hop per query and single-thread Redis per city limit.", [("Redis Cluster GEO", "Hot city still on one shard"), ("In-process H3", "Chosen")], "In-memory index in Geo service.", "Sub-ms reads, horizontal by city.", "We own rebuild/replication.", "N/A")],
    qa=[Q("Concurrency", "Could a query see the same driver in two cells during a move?", "Yes, briefly, because insert precedes remove. Proximity search dedupes by driver id and keeps the entry with the newest ts. Doing remove-then-insert would instead risk the driver missing from both, which is worse for dispatch.", "")],
    tests=[T("Concurrency", "1M random moves with concurrent queries", "No driver missing; duplicates deduped"), T("Recovery", "Rebuild from topic", "Index equals pre-crash state")],
    evo=["N: Phase I uses PostGIS (see Proximity search)", "I: Redis GEO sets per city/category", "E: Fed from Kafka; compacted latest topic", "R: In-process H3 maps in Geo service", "E: Sharded by res-5 parent; hot-cell replicas", "E: Regional"],
    ideas={"now": ["Compacted latest-position topic"], "next": ["Per-cell counters for surge"], "adv": ["Off-heap storage"], "rej": ["Durable DB index for ephemeral positions"]})

sub(id="proximity-search", comp="geo-index", name="Proximity Search (kNN / Radius)", phase="I", cat="Algorithm · Geospatial query",
    resp="Return the nearest available drivers to a point, filtered by category and freshness, as candidates for dispatch and previews.",
    inp="point, radius, filters, limit", out="candidate list (driver, position, straight-line distance, ts)", deps="Cell index", cons="Dispatch candidate generation, Catalog previews", own="No data",
    problem="Turn a geometric question (within r of p) into a fast lookup over the cell index, with correct handling of boundaries and staleness.",
    without="Dispatch can't find drivers fast.", guar=["All fresh available drivers within r are considered (k-ring covers the circle)", "Results sorted by great-circle distance", "Bounded latency via result caps"], nong=["Road distance or ETA (Routing)", "Ranking (Dispatch)"],
    usecase="Rider at a mall requests UberX. Search r=3 km returns 20 nearest fresh available UberX drivers. Dispatch then computes ETAs for those 20.",
    derive="- A circle of radius r is covered by the k-ring with k = ceil(r / (√3·edge)).\n- Bucket scan + exact haversine filter removes false positives.\n- Expanding rings stop early when enough candidates are found (kNN).",
    conc="Read-only over concurrent maps.", consistency="Reads may be up to a few seconds stale.", idem="Pure query; repeating it has no side effects.", order="No inputs to order: the query reads a snapshot of the index.",
    restart="Stateless; relies on index availability.", scale="Cost ∝ cells × drivers per cell. Hot areas cap per-cell scan and expand rings progressively.",
    arch="Phase I: PostGIS `ST_DWithin(pos, point, r) ORDER BY pos <-> point LIMIT n`. Phase II–III: Redis `GEOSEARCH ... BYRADIUS r km ASC COUNT n`. Phase IV+: progressive k-ring scan over H3 buckets.",
    modules=[["CellCover", "k-ring for radius"], ["BucketScanner", "Collect + filter fresh/available/category"], ["Ranker", "Haversine sort, top-n"], ["Expander", "Grow k until n found or r max"]],
    d_arch=("""flowchart LR
  Q["nearby(p,r,f,n)"] --> CC["CellCover kRing"] --> BS["BucketScanner"] --> IDX["Cell index"]
  BS --> RK["Ranker top-n"] --> OUT["candidates"]
  RK -->|< n| EX["Expander k+1"] --> CC""", "Progressive ring expansion."),
    d_seq=("""sequenceDiagram
  participant D as Dispatch
  participant S as Search
  participant I as Index
  D->>S: nearby(p, 3km, UberX, 20)
  loop k = 1..4 until 20 found
    S->>I: buckets(ring k)
  end
  S-->>D: 20 sorted candidates""", "Expanding rings stop as soon as enough candidates are found."),
    nostate="A pure query over index state.", d_flow=("""flowchart LR
  P["pickup"] --> C["h3 cell"] --> R["ring cells"] --> E["entries"] --> F["filter fresh/avail/cat"] --> H["haversine ≤ r"] --> S["sort, top n"]""", "The filtering pipeline."),
    d_fail=("""flowchart TB
  T["timeout (hot area)"] --> P["return partial best-so-far"]
  Z["zero results"] --> W["widen to r_max, then 'no cars' UX"]""", "Partial results beat timeouts."),
    sql="""-- Phase I query
SELECT driver_id, ST_Distance(pos, ST_MakePoint(:lng,:lat)::geography) AS d
FROM geo.driver_positions
WHERE available AND category = :cat AND updated_at > now() - interval '45 seconds'
  AND ST_DWithin(pos, ST_MakePoint(:lng,:lat)::geography, :radius_m)
ORDER BY pos <-> ST_MakePoint(:lng,:lat)::geography LIMIT :n;""",
    data="No owned data.", api="""rpc Nearby(NearbyRequest{lat,lng,radius_m,category,limit,max_age_s}) returns (NearbyResponse{repeated Candidate{driver_id,lat,lng,distance_m,ts}})""",
    mech=[("k-ring cover", "All cells within k steps form a hexagonal disc. With edge length e, the disc fully contains a circle of radius ≈ k·√3·e/2·… (computed with a safety margin of one ring), so no driver inside r is missed."), ("Haversine distance", "Great-circle distance d = 2R·asin(√(sin²(Δφ/2) + cosφ₁cosφ₂ sin²(Δλ/2))), exact enough for ranking candidates before routing.")],
    code="""public List<Candidate> nearby(LatLng p, int radiusM, String cat, int n, Duration maxAge) {
    long origin = h3.latLngToCell(p.lat(), p.lng(), 8);
    PriorityQueue<Candidate> best = new PriorityQueue<>(comparingDouble(Candidate::distance).reversed());
    for (int k = 0; k <= kFor(radiusM); k++) {
        for (long cell : h3.gridRing(origin, k)) for (Entry e : index.bucket(cell))
            if (e.available() && e.category().equals(cat) && e.fresh(maxAge)) {
                double d = Geo.haversine(p, e.pos());
                if (d <= radiusM) { best.add(new Candidate(e, d)); if (best.size() > n) best.poll(); }
            }
        if (best.size() >= n && minDistanceOfRing(k + 1) > best.peek().distance()) break;
    }
    return best.stream().sorted(comparingDouble(Candidate::distance)).toList();
}""", cx="O(cells·m + m log n), m = drivers scanned.",
    fail=[F("Index shard unavailable", "RPC error", "No candidates for that city", "Replica failover; dispatch retries", "None"), F("Dense hot spot", "Scan time metric", "Slow query", "Per-cell scan caps; early stop", "Slightly approximate top-n")],
    alts=[["PostGIS kNN", "Phase I", "Simple, durable", "< 1K writes/s"], ["Redis GEOSEARCH", "Phase II–III", "Fast", "One city per node limit"], ["R-tree in memory", "Viable", "Better for non-uniform", "Few, large moving objects"]],
    adrs=[A("Early termination ring expansion", "IV", "Dense areas.", [("Fixed radius scan", "Wasteful"), ("Expanding rings", "Chosen")], "Stop when ring min distance > nth best.", "Exact top-n with less scanning.", "Slightly more code.", "N/A")],
    qa=[Q("Correctness", "Why is straight-line distance acceptable for candidate generation when roads matter?", "Candidate generation only needs high recall. Taking 20 straight-line-nearest drivers almost always includes the ETA-best few. Dispatch then computes road ETAs for those 20 (expensive) and ranks. Rivers and highways can break this, so candidate counts are larger near known barriers (configured per geofence).", "Computing ETA for every driver in 3 km is too expensive.")],
    tests=[T("Unit", "Driver at exactly r", "Included"), T("Property", "Brute-force vs ring search", "Same top-n"), T("Load", "Stadium cell with 2K drivers", "p99 < 20 ms")],
    evo=["I: PostGIS kNN query", "R: Redis GEOSEARCH", "U: No change needed: same query, index now fed by Kafka", "R: H3 ring search in Geo service", "E: Cross-shard queries for border cells", "U: No change needed: regional instances"],
    ideas={"now": ["Freshness filter"], "next": ["Barrier-aware candidate counts"], "adv": ["Learned candidate generation"], "rej": ["Full-city scans"]})

sub(id="geofencing", comp="geo-index", name="Geofencing", phase="II", cat="Geospatial · Rules",
    resp="Store polygons for zones (service areas, airports, restricted roads, event venues) and answer which zones contain a point, quickly.",
    inp="polygons from ops, points from queries", out="zone ids for a point; enter/exit events for drivers (airport queues)", deps="Admin & Policy (zone editing)", cons="Ride Request (service area), Pricing (airport fees), Dispatch (airport queue), Safety", own="geofences, cell covers",
    problem="Many rules depend on 'is this point in zone Z' at high QPS, and some need enter/exit events.",
    without="Rides accepted outside service areas, missing airport fees, no airport FIFO queue.", guar=["Containment answers exact at polygon boundary (final point-in-polygon check)", "Zone versions: changes take effect atomically"], nong=["Sub-metre precision"],
    usecase="A driver enters the airport waiting lot polygon. An `EnteredZone(airport-lot)` event places them in the airport FIFO queue that dispatch uses for airport pickups.",
    derive="- Point-in-polygon per query is O(vertices). Precompute a cell cover per polygon (cells fully inside vs boundary cells).\n- Fully-inside cells answer immediately, and boundary cells need an exact test.\n- Enter/exit requires per-driver previous zone set, so a diff on update.",
    conc="Zone set versioned. Readers use an immutable snapshot swapped atomically.", consistency="New zone versions propagate to all nodes within 60 s; each node is internally consistent (snapshot).", idem="Enter events deduped per (driver, zone, visit_id).", order="Driver updates processed in ts order per driver; enter/exit diff uses latest.",
    restart="Zones loaded from DB at boot; driver zone membership recomputed from first position.", scale="Cover lookup O(1). Polygons ≈ thousands per city.",
    arch="`GeofenceStore` (PostGIS source of truth) → `CoverBuilder` (H3 res-9 polyfill with interior/boundary classification) → immutable `ZoneSnapshot` in each Geo node. `ZoneTracker` computes enter/exit diffs per driver position.",
    modules=[["GeofenceStore", "Versioned polygons (PostGIS)"], ["CoverBuilder", "Interior/boundary cell sets"], ["ZoneSnapshot", "cell → zones, atomic swap"], ["ZoneTracker", "Enter/exit diff per driver"]],
    d_arch=("""flowchart LR
  OPS["Ops zone editor"] --> GS[("geofences PostGIS")] --> CB["CoverBuilder"] --> SN["ZoneSnapshot (per node)"]
  POS["driver positions"] --> ZT["ZoneTracker"] --> SN
  ZT -->|Entered/Exited| EV["events"]
  Q["containing(point)"] --> SN""", "Precomputed covers serve point queries and drive enter/exit tracking."),
    d_seq=("""sequenceDiagram
  participant Q as Caller
  participant S as Snapshot
  Q->>S: containing(lat,lng)
  S->>S: cell = h3(p, 9)
  alt cell interior to zone Z
    S-->>Q: [Z]
  else boundary cell
    S->>S: exact point-in-polygon
    S-->>Q: [Z] or []
  end""", "Interior cells skip the exact test."),
    d_state=("""stateDiagram-v2
  [*] --> Outside
  Outside --> Inside: position in zone
  Inside --> Outside: position out of zone for 2 consecutive points""", "Per (driver, zone) membership with exit debounce."),
    d_flow=("""flowchart LR
  POLY["polygon"] --> FILL["polyfill res 9"] --> INT["interior cells"] & BND["boundary cells"] --> MAP["cell → zones"]""", "Cover construction."),
    d_fail=("""flowchart TB
  BAD["invalid polygon edit"] --> V["validation rejects (self-intersection)"]
  PROP["snapshot propagation lag"] --> OLD["old version served ≤ 60s"]""", "Edits are validated before publication."),
    sql="""CREATE TABLE geo.geofences (id uuid, version int, city text NOT NULL, kind text NOT NULL,
  boundary geography(Polygon,4326) NOT NULL, attrs jsonb NOT NULL DEFAULT '{}', active boolean NOT NULL,
  PRIMARY KEY (id, version));
CREATE INDEX geofences_gist ON geo.geofences USING gist(boundary) WHERE active;""",
    data="Versions retained for audit (which fee applied when).", api="""List<ZoneRef> containing(double lat, double lng)
event EnteredZone{driver_id, zone_id, visit_id, ts} / ExitedZone{...}""",
    mech=[("Polyfill + interior classification", "Cells whose all vertices lie inside the polygon are interior. Others intersecting the polygon are boundary. Most points fall in interior cells, so the exact test is rare."), ("Immutable snapshot swap", "Build the new map off to the side, then swap a single reference. Readers never see a half-built index.")],
    code="""public List<ZoneRef> containing(double lat, double lng) {
    ZoneSnapshot s = snapshot.get();
    long cell = h3.latLngToCell(lat, lng, 9);
    List<ZoneRef> out = new ArrayList<>(s.interior(cell));
    for (Zone z : s.boundary(cell)) if (z.polygon().contains(lat, lng)) out.add(z.ref());
    return out;
}""", cx="O(1) typical; O(v) for boundary cells.",
    fail=[F("Bad zone published", "Spike in out-of-area rejections", "Riders blocked", "Rollback to previous version", "Versioned"), F("Snapshot build OOM", "Build failure", "Old snapshot kept", "Alert", "None")],
    alts=[["PostGIS ST_Contains per query", "Phase II", "Simple", "Low QPS"], ["S2 coverings", "Viable", "Better polygon fit", "Precision needs"]],
    adrs=[A("Precomputed H3 covers", "IV", "High QPS containment.", [("Per-query PostGIS", "Rejected at scale"), ("Covers", "Chosen")], "Interior/boundary covers.", "O(1) typical.", "Rebuild on edit.", "N/A")],
    qa=[Q("Correctness", "A driver's GPS jitters across the airport-lot boundary. How do you prevent queue flapping?", "Debounce exit: require two consecutive outside points, or 30 s outside, before emitting ExitedZone. Keep the queue position during the debounce. Use the filtered position, not raw.", "")],
    tests=[T("Unit", "Point on boundary", "Exact test applied"), T("Integration", "Edit polygon", "New version within 60 s"), T("Unit", "Jitter across boundary", "No exit within debounce")],
    evo=["N: Phase I hardcodes the service area as one polygon checked in SQL", "I: Geofence table + ST_Contains", "E: Enter/exit events", "R: Covers in Geo service", "E: Event-venue zones scheduled", "E: Regional zone stores"],
    ideas={"now": ["Versioned zones"], "next": ["Scheduled zones (events)"], "adv": ["Dynamic zones from demand clustering"], "rej": ["Zones encoded in client apps"]})

# ======================================================================= Location History
comp(id="location-history", domain="location", name="Location History & Retention", tag="Geo · Storage", phase="I", kind="Storage component",
     biz="Keeps trip routes for fares, receipts, disputes and safety investigations, and deletes location data when it is no longer needed.",
     eng="An append-heavy, read-rarely store of on-trip breadcrumbs with strict retention, access controls and cost-tiered storage.",
     deploy="Table in monolith (I–III); wide-column store + object storage tiers (V).", data_own="trip_breadcrumbs, downsampled archives.",
     up=["location-ingest"], down=["fare-finalization", "support", "safety", "receipts", "applied-models"], ext=["Object storage"],
     interfaces="`appendPoints(trip, points)`, `getTrack(trip, resolution)`; batch export to lake (anonymized).",
     problem="Trip tracks are evidence for fares and safety, but location history is highly sensitive personal data and voluminous.",
     fr=["Append on-trip points", "Read full track by trip", "Downsample after 90 days", "Delete per retention/erasure"], nfr=["Write throughput = on-trip location rate", "Track read p95 < 500 ms", "Retention enforced automatically"],
     workload="Phase V: ≈ 30K on-trip points/s; reads ≈ trips with disputes (< 1%).", success="Every completed trip has a track; nothing kept longer than policy.", failure="Missing evidence in disputes; privacy violations from over-retention.",
     derive="Writes are append-only and keyed by trip, and reads fetch a whole trip, so partition by trip_id, clustering by ts. Age-based tiers favour TTL and compaction to cheaper storage.",
     owns=["Breadcrumb storage", "Retention enforcement"], not_owns=["Idle-driver positions (not stored beyond index)", "Fare computation"], sync=["Track read"], **{"async": ["Appends", "Downsampling", "Archival", "Deletion"]},
     boundary_why="Retention and access rules for location are special, so a dedicated store keeps those rules in one place.",
     hld=("""flowchart LR
  MM["Matched on-trip points"] --> BS["Breadcrumb store"]
  BS --> HOT[("Hot: PG partitions / Cassandra TTL")]
  RET["Retention & downsampling"] --> HOT
  RET --> COLD[("Cold: object storage, downsampled")]
  FARE["Fare / Support / Safety"] -->|getTrack| BS""", "Hot store for recent trips, cold tier for downsampled history, retention jobs moving and deleting."),
     seq=("""sequenceDiagram
  participant S as Support agent
  participant H as History
  S->>H: getTrack(trip 77) [authz: ticket]
  H->>H: audit access
  H-->>S: points (hot or cold tier)""", "Audited access."),
     subdeps=[("retention-downsampling", "breadcrumb-store")],
     flow="Points are appended as they arrive. Reads are audited. A retention job moves 90-day-old tracks to the cold tier at reduced resolution and deletes per policy.",
     data="Phase I: `trip_breadcrumbs(trip_id, seq, ts, lat, lng, speed)` partitioned monthly. Phase V: Cassandra table `PRIMARY KEY ((trip_id), ts)` with TTL 90 days. Cold: Parquet per day in object storage (encrypted).",
     rel=[["Durability", "Hot store replicated (RF=3)."], ["Idempotency", "Primary key (trip_id, seq) dedups resends."]],
     sec=[["Access", "Only fare service (system), support with ticket, safety team; all audited."], ["Privacy", "Retention: full resolution 90 days, downsampled 3 years for disputes/legal, then deleted."]],
     adrs=[A("Monthly partitions then wide-column", "I", "Append-only, time-bounded.", [("Single table", "Rejected: retention deletes are expensive"), ("Partitions (drop old)", "Chosen I–IV"), ("Cassandra TTL", "Chosen V")], "Partition-drop retention.", "Cheap deletes.", "Partition management.", "N/A")],
     qa=[Q("Privacy", "How do you honour an erasure request when tracks are evidence for financial records?", "Separate data. Financial records keep fare, distance and timestamps. Tracks are anonymized: unlinked from the rider id and coarsened to H3 res-7 cells, or deleted if no dispute or legal hold exists. A legal hold flag blocks deletion where required, with a documented reason.", "")],
     impl_order=["breadcrumb-store", "retention-downsampling"], pkg="""com.atlas.location.history
├── store     (BreadcrumbRepository, TrackReader)
└── retention (Downsampler, Archiver, RetentionJob)""",
     tests=[T("Privacy", "Track older than policy", "Deleted"), T("Load", "30K points/s", "Write p99 < 20 ms")],
     evo=[("I", "PG table", "Monthly partitions", "Dedup PK", "Evidence"), ("U", "No change needed", "—", "—", "—"), ("E", "Consumer of location topic", "—", "Idempotent writes", "Kafka"), ("E", "Read replicas", "—", "Audited access", "Support volume"),
          ("R", "Cassandra hot + object storage cold", "TTL", "RF=3", "30K/s"), ("E", "Regional stores", "In-region", "Residency", "Global")],
     ideas={"now": ["Audit every read"], "next": ["Downsampling"], "adv": ["Differentially private analytics exports"], "rej": ["Storing idle-driver history"]})

sub(id="breadcrumb-store", comp="location-history", name="Trip Breadcrumb Store", phase="I", cat="Storage · Append-only",
    resp="Durably append on-trip location points keyed by trip and serve whole tracks.",
    inp="on-trip points (filtered/matched)", out="tracks", deps="Ingest pipeline", cons="Fare finalization, Support, Safety, Receipts (map image)", own="trip_breadcrumbs",
    problem="Store a continuous high-rate stream of points cheaply and retrieve a trip's points in order.", without="No fare evidence or safety reconstruction.",
    guar=["Points deduped by (trip, seq)", "Ordered retrieval by ts", "Durable replication"], nong=["Points for non-trip time"],
    usecase="A rider disputes a fare. Support loads the track and sees a detour around a closed road (map overlay), and the fare is upheld.",
    derive="- Queries are always 'all points of trip X', so trip_id is the partition key and ts the clustering key.\n- Writes are idempotent by key.",
    conc="Append-only with primary-key upsert; no conflicts.", consistency="Read-after-write per partition in PG. Cassandra: LOCAL_QUORUM writes/reads.", idem="PK upsert on (trip_id, seq).", order="Retrieval sorts by ts; arrival order irrelevant.",
    restart="Consumer offsets committed after writes (at-least-once + idempotent).", scale="Phase V: Cassandra scales linearly; ≈ 30K writes/s fine on a 6-node cluster.",
    arch="Phase I–IV: PostgreSQL range-partitioned table by month. Phase V: Kafka consumer writing to Cassandra in micro-batches.",
    modules=[["Appender", "Batch insert"], ["TrackReader", "Ordered fetch, optional downsample on read"]],
    d_arch=("""flowchart LR
  K[["on-trip points"]] --> AP["Appender (batched)"] --> DB[("trip_breadcrumbs")]
  TR["TrackReader"] --> DB""", "Simple append and read paths."),
    d_seq=("""sequenceDiagram
  participant C as Consumer
  participant DB
  C->>DB: INSERT batch ON CONFLICT DO NOTHING
  C->>C: commit offset""", "At-least-once with idempotent insert."),
    nostate="Append-only rows have no lifecycle beyond retention handled by the retention subcomponent.",
    d_flow=("""flowchart LR
  P["points"] --> B["batch 500"] --> W["write"] --> R["read by trip"]""", "Batching reduces per-write overhead."),
    d_fail=("""flowchart TB
  DBD["store down"] --> LAG["consumer lag grows; Kafka retains 24h"] --> CATCH["catch up"]""", "Kafka buffers outages."),
    sql="""CREATE TABLE location.trip_breadcrumbs (trip_id uuid, seq int, ts timestamptz NOT NULL, lat double precision, lng double precision,
  speed real, PRIMARY KEY (trip_id, seq, ts)) PARTITION BY RANGE (ts);
CREATE TABLE location.trip_breadcrumbs_2026_11 PARTITION OF location.trip_breadcrumbs FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
-- Phase V (CQL): CREATE TABLE breadcrumbs (trip_id uuid, ts timestamp, seq int, lat double, lng double, PRIMARY KEY ((trip_id), ts, seq)) WITH default_time_to_live = 7776000;""",
    data="Partitioned monthly; PK includes ts for partition routing.", api="""void append(UUID trip, List<Point> pts)
Track getTrack(UUID trip, Resolution r)""",
    mech=[("Partition pruning", "Range partitions let the planner touch only relevant months, and dropping a partition deletes a month instantly."), ("Micro-batching", "Batching 500 points per write amortizes round trips.")],
    code="""jdbc.batchUpdate("INSERT INTO location.trip_breadcrumbs(trip_id,seq,ts,lat,lng,speed) VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING", batch);""", cx="O(batch).",
    fail=[F("Store outage", "Write errors", "Lag", "Kafka buffer; retry", "No loss within retention"), F("Duplicate delivery", "PK conflict", "None", "Ignored", "Exact")],
    alts=[["Time-series DB", "Viable", "TimescaleDB compression", "If ad-hoc time queries needed"], ["Object storage only", "Rejected for hot", "Read latency", "Cold tier"]],
    adrs=[A("Cassandra at Phase V", "V", "30K/s append-only.", [("PG sharding", "Possible but costly"), ("Cassandra", "Chosen")], "Wide-column with TTL.", "Linear writes.", "New datastore ops.", "N/A")],
    qa=[Q("Performance", "Why include ts in the PostgreSQL primary key?", "Declarative partitioning requires the partition key in every unique constraint. Including ts lets the PK be enforced per partition. Dedup still works because a resent point has the same (trip, seq, ts).", "")],
    tests=[T("Unit", "Resent batch", "No duplicates"), T("Load", "Partition rollover at month boundary", "No write errors")],
    evo=["I: Partitioned PG table", "U: No change needed", "E: Kafka consumer writer", "E: Read replicas for support", "R: Cassandra with TTL", "E: Regional clusters"],
    ideas={"now": ["Pre-create partitions"], "next": ["Read-side downsampling"], "adv": ["Columnar compression"], "rej": ["JSON blobs per trip updated in place"]})

sub(id="retention-downsampling", comp="location-history", name="Retention & Downsampling", phase="II", cat="Privacy · Data lifecycle",
    resp="Enforce location retention policy: downsample tracks after 90 days, archive to cold storage, delete after the legal period, and honour erasure and legal holds.",
    inp="policy config, clock, erasure requests, legal holds", out="archived downsampled tracks, deletions, retention audit", deps="Breadcrumb store, Privacy, object storage", cons="Compliance audits", own="retention_runs, legal_holds",
    problem="Location data grows endlessly and is highly sensitive. Keeping it beyond need is a legal and security liability.", without="Unbounded cost and regulatory exposure.",
    guar=["No full-resolution track older than 90 days unless under legal hold", "No track older than 3 years", "Every run auditable"], nong=["Immediate deletion (runs daily)"],
    usecase="Nightly run: November 2026 partition tracks are downsampled (1 point/30 s, Douglas–Peucker simplified), written to Parquet in cold storage, and the partition is dropped.",
    derive="- Downsampling must preserve route shape for disputes, so line simplification (Douglas–Peucker with 15 m tolerance).\n- Holds must override deletion, so check holds before drop and copy held tracks to a hold store.",
    conc="One retention run at a time (advisory lock / scheduler leader).", consistency="Archive written and verified (checksum) before deletion.", idem="Runs keyed by partition; re-running skips completed steps.", order="Steps are ordered within a run: archive → verify → delete.",
    restart="Run state persisted per partition step; resumes at the first incomplete step.", scale="Batch over partitions; parallelized by day.",
    arch="Scheduled job: for each partition past threshold, **copy held tracks → downsample → write Parquet → verify → drop partition**. Erasure requests delete or anonymize specific trips across tiers.",
    modules=[["PolicyConfig", "Thresholds per region"], ["Downsampler", "Douglas–Peucker"], ["Archiver", "Parquet writer + checksum"], ["HoldManager", "Legal holds"], ["RunLedger", "Step tracking"]],
    d_arch=("""flowchart LR
  SCH["Scheduler (leader)"] --> RJ["RetentionJob"]
  RJ --> HM["HoldManager"] --> HS[("held tracks")]
  RJ --> DS["Downsampler"] --> AR["Archiver"] --> OBJ[("cold Parquet")]
  RJ --> DROP["drop partition"]
  RJ --> RL[("retention_runs")]""", "A resumable, ordered batch pipeline."),
    d_seq=("""sequenceDiagram
  participant J as Job
  participant H as Holds
  participant A as Archiver
  participant DB
  J->>H: copy held trips of partition
  J->>A: downsample + write parquet
  A-->>J: checksum ok
  J->>DB: DROP PARTITION
  J->>DB: record run complete""", "Archive and verify before delete."),
    d_state=("""stateDiagram-v2
  [*] --> Pending
  Pending --> HoldsCopied
  HoldsCopied --> Archived
  Archived --> Verified
  Verified --> Dropped
  Dropped --> [*]""", "Per-partition run steps."),
    d_flow=("""flowchart LR
  T["full track 1pt/2s"] --> DP["Douglas–Peucker 15m"] --> C["~1pt/30s"] --> P[("Parquet")]""", "Downsampling ratio ≈ 15×."),
    d_fail=("""flowchart TB
  X["crash after archive before drop"] --> R["resume: verify then drop"]
  V["verify fails"] --> K["keep partition; alert"]""", "Never delete without a verified archive."),
    sql="""CREATE TABLE location.retention_runs (partition_name text PRIMARY KEY, step text NOT NULL, archive_uri text, checksum text, updated_at timestamptz NOT NULL);
CREATE TABLE location.legal_holds (trip_id uuid PRIMARY KEY, reason text NOT NULL, placed_by uuid NOT NULL, until date);""",
    data="Cold archive deleted after 3 years by object lifecycle rules.", api="""POST /internal/legal-holds {trip_id, reason, until}
Job: retention-daily (02:00 local)""",
    mech=[("Douglas–Peucker simplification", "Recursively keep the point farthest from the line between endpoints if its distance exceeds tolerance ε. Shape is preserved within ε."), ("Step ledger", "Persisting each step makes the job idempotent and resumable, the same idea as a saga log.")],
    code="""List<Point> simplify(List<Point> pts, double eps) {
    if (pts.size() < 3) return pts;
    int idx = 0; double dmax = 0;
    for (int i = 1; i < pts.size() - 1; i++) { double d = Geo.crossTrack(pts.get(i), pts.getFirst(), pts.getLast()); if (d > dmax) { dmax = d; idx = i; } }
    if (dmax <= eps) return List.of(pts.getFirst(), pts.getLast());
    var left = simplify(pts.subList(0, idx + 1), eps); var right = simplify(pts.subList(idx, pts.size()), eps);
    return Stream.concat(left.stream().limit(left.size() - 1), right.stream()).toList();
}""", cx="O(n log n) average.",
    fail=[F("Crash mid-run", "Run ledger incomplete", "Partition retained", "Resume", "No loss"), F("Archive corruption", "Checksum mismatch", "Not dropped", "Re-archive", "Safe")],
    alts=[["Row-level DELETE", "Rejected", "Bloat, slow", "Erasure of single trips"], ["Keep everything", "Rejected", "Legal risk", "Never"]],
    adrs=[A("Archive-verify-delete ordering", "II", "Avoid data loss.", [("Delete then archive", "Rejected"), ("Archive, verify, delete", "Chosen")], "Strict ordering with ledger.", "Safe.", "Slower.", "N/A")],
    qa=[Q("Compliance", "How do you prove to an auditor that retention works?", "Retention runs are recorded with partition, step, checksum and timestamps. A monthly report lists the oldest full-resolution and the oldest cold data per region, and an automated check alerts if either exceeds policy. Legal holds are listed with reasons and owners.", "")],
    tests=[T("Recovery", "Kill job after archive", "Next run drops after verify"), T("Unit", "Simplify straight line", "2 points"), T("Privacy", "Held trip", "Copied to hold store before drop")],
    evo=["N: Phase I keeps 90 days and drops partitions manually", "I: Automated job with ledger", "U: No change needed", "E: Erasure integration", "R: Cassandra TTL + object lifecycle rules", "E: Region-specific policies"],
    ideas={"now": ["Run ledger"], "next": ["Automated audit report"], "adv": ["Privacy-preserving aggregates replace raw history"], "rej": ["Indefinite retention for ML"]})
