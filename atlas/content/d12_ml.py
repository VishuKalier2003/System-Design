from model import comp, sub, A, Q, F, T

# ======================================================================= Feature Store
comp(id="feature-store", domain="ml", name="Feature Store", tag="ML · Data", phase="IV", kind="Platform capability",
     biz="Gives every model (ETA, fraud, matching, pricing) the same trustworthy features in training and in production, so models behave in production as they did offline.",
     eng="Feature definitions computed once (batch and streaming), materialized to an offline store for point-in-time-correct training and an online store for millisecond serving.",
     deploy="Introduced Phase IV (Feast-like on Redis/Cassandra + Iceberg); streaming features Phase V.", data_own="Feature definitions, offline feature tables, online feature values.",
     up=["event-pipeline", "data-governance"], down=["risk-fraud", "routing-eta", "dispatch", "pricing", "ml-platform"], ext=[],
     interfaces="`get_online_features(entity_keys, feature_refs)`; `get_historical_features(entity_df, features)`; registry of feature views.",
     problem="Without a shared store, each team re-implements features differently for training (SQL) and serving (Java), causing training/serving skew and leakage (future data in training).",
     fr=["Declarative feature definitions", "Batch + streaming materialization", "Point-in-time joins for training", "Online lookup < 10 ms", "Freshness monitoring"], nfr=["Online p99 < 10 ms at 50K lookups/s", "Freshness per feature SLO"],
     workload="Phase V: 50K online lookups/s (risk, ETA, dispatch).", success="Same feature value offline and online; fast lookups.", failure="Skew, leakage, stale features.",
     derive="Training needs feature values *as of* each label time, so time-versioned offline storage and as-of joins. Serving needs the latest value fast, so a key-value online store. One definition generates both, which prevents skew.",
     owns=["Feature registry", "Materialization", "Stores"], not_owns=["Raw data (pipeline)", "Models"], sync=["Online lookups"], **{"async": ["Materialization jobs/streams"]},
     boundary_why="Features are shared assets across models. Centralizing removes duplicate pipelines and skew.",
     hld=("""flowchart LR
  REG["Feature registry (definitions)"] --> BJ["Batch materialization (Spark)"] & SJ["Stream materialization (Flink)"]
  LAKE[("lake")] --> BJ --> OFF[("offline store: Iceberg")] & ON[("online store: Redis/Cassandra")]
  K[["event streams"]] --> SJ --> ON & OFF
  TR["Training"] -->|point-in-time join| OFF
  SV["Model serving"] -->|lookup| ON""", "One definition, two stores."),
     seq=("""sequenceDiagram
  participant R as Risk service
  participant O as Online store
  R->>O: get(rider:r1, [trips_7d, chargebacks_90d, device_accounts])
  O-->>R: values + timestamps
  R->>R: model.score(features)""", "Online lookup."),
     subdeps=[("feature-serving", "feature-pipelines")],
     flow="Definitions drive both pipelines. Online values carry timestamps for freshness checks. Training uses as-of joins against the offline store.",
     data="Offline: `features.<view>(entity_key, event_ts, feature cols)` in Iceberg. Online: Redis hash `fv:{view}:{entity}` → values + ts.",
     rel=[["Freshness", "Per-feature max age; stale → default + metric."], ["Fallback", "Online store down → model defaults or degraded policy."]], sec=[["PII", "Features governed by catalog tags."], ["Access", "Per-view ACLs."]],
     adrs=[A("Adopt a feature store at Phase IV", "IV", "Multiple models with shared features.", [("Per-model pipelines", "Skew"), ("Feature store", "Chosen")], "Feast-style.", "Consistency.", "Platform ops.", "N/A")],
     qa=[Q("ML", "What is point-in-time correctness and why does it matter?", "For a training example at time t (e.g. a ride request), features must use only data available before t. A naive join with today's feature values leaks the future (e.g. a chargeback that happened later), inflating offline accuracy and failing in production. As-of joins pick, per entity, the latest feature row with event_ts ≤ t.", "")],
     impl_order=["feature-pipelines", "feature-serving"], pkg="""ml/features (definitions as code, Python)
com.atlas.features (Java online client)""",
     tests=[T("Correctness", "As-of join on synthetic data", "No future values"), T("Load", "50K lookups/s", "p99 < 10 ms")],
     evo=[("N", "No ML in pilot", "—", "—", "—"), ("N", "Heuristics only", "—", "—", "—"), ("N", "Per-model batch features", "—", "—", "First models"),
          ("I", "Feature store with batch features", "Iceberg + Redis", "Freshness SLOs", "Multiple models"), ("E", "Streaming features", "Flink", "—", "Real-time fraud/ETA"), ("E", "Regional online stores", "—", "Residency", "Global")],
     ideas={"now": ["n/a"], "next": ["Streaming features"], "adv": ["Embedding store"], "rej": ["Separate training/serving code"]})

sub(id="feature-pipelines", comp="feature-store", name="Feature Pipelines (Batch & Streaming)", phase="IV", cat="ML · Data engineering",
    resp="Compute feature values from lake tables and event streams according to registered definitions and write them to offline and online stores.",
    inp="lake tables, Kafka streams, definitions", out="feature rows (offline), latest values (online)", deps="Spark/Flink, Iceberg, Redis", cons="Feature serving, Training", own="materialization jobs",
    problem="Compute the same feature consistently in batch and streaming, with freshness guarantees.", without="Inconsistent features.",
    guar=["Offline rows timestamped by event time", "Online values never older than freshness SLO (else flagged)", "Backfills reproducible"], nong=["Feature usefulness"],
    usecase="`rider.trips_7d` computed nightly in batch. `rider.requests_10m` computed in Flink sliding windows, written to Redis every 30 s and to offline for training.",
    derive="- Batch: daily aggregation jobs.\n- Streaming: windowed aggregations keyed by entity.\n- Dual-write offline so training sees the same values that serving saw.",
    conc="One materialization job per view.", consistency="Online eventually consistent; offline snapshot per run.", idem="Writes keyed by (entity, event_ts) and upserts.", order="Event-time windows with watermarks.",
    restart="Flink checkpoints; batch reruns.", scale="Partitioned by entity key.", arch="Definitions (Python DSL) compile to Spark SQL (batch) and Flink jobs (stream). Sinks: Iceberg (offline) + Redis (online).",
    modules=[["DefinitionCompiler", "DSL → jobs"], ["BatchJobs", "Spark"], ["StreamJobs", "Flink"], ["Sinks", "Iceberg, Redis"]],
    d_arch=("""flowchart LR
  DEF["definitions"] --> DC["DefinitionCompiler"] --> BJ["Spark jobs"] & SJ["Flink jobs"]
  BJ & SJ --> OFF[("offline")] & ON[("online")]""", "Compile once, materialize twice."),
    d_seq=("""sequenceDiagram
  participant K as Kafka
  participant F as Flink
  participant R as Redis
  participant I as Iceberg
  K->>F: RideRequested(r1)
  F->>F: window count 10m = 3
  F->>R: HSET fv:rider:r1 requests_10m 3 ts
  F->>I: append (r1, ts, 3)""", "Streaming feature."),
    nostate="Pipelines produce values. State is window state inside the stream job.",
    d_flow=("""flowchart LR
  E["events"] --> W["windows"] --> V["values"] --> S["stores"]""", "Flow."),
    d_fail=("""flowchart TB
  J["stream job down"] --> ST["online values age; serving flags stale → defaults"]""", "Staleness handling."),
    sql="""-- offline view example
CREATE TABLE features.rider_activity (rider_id string, event_ts timestamp, trips_7d int, requests_10m int) USING iceberg PARTITIONED BY (days(event_ts));""",
    data="Offline retention 2 years.", api="""feature_view(name="rider_activity", entities=["rider"], features=[Count("trips", window="7d"), Count("requests", window="10m", stream=True)], ttl="1d")""",
    mech=[("Dual-sink materialization", "Writing the exact streaming values to the offline store makes training data match what production saw.")],
    code="""DataStream<RequestEvent> s = env.fromSource(kafka, wm, "requests");
s.keyBy(RequestEvent::riderId).window(SlidingEventTimeWindows.of(Time.minutes(10), Time.seconds(30))).aggregate(new CountAgg()).sinkTo(redisSink);""", cx="O(events).",
    fail=[F("Backfill mismatch", "Offline vs online diff checks", "Skew", "Fix definition", "N/A")],
    alts=[["Batch only", "Phase IV start", "Simpler", "Non-real-time features"]],
    adrs=[A("Definitions as code", "IV", "Consistency.", [("Ad-hoc SQL", "Drift"), ("DSL", "Chosen")], "DSL.", "Single source.", "DSL limits.", "N/A")],
    qa=[Q("ML", "How do you detect training/serving skew?", "Log online feature values at inference (sampled) and compare their distributions with offline values for the same entities and times. Alert on divergence (PSI > 0.2).", "")],
    tests=[T("Consistency", "Online vs offline sample", "Equal within tolerance")],
    evo=["N: No feature store in Phase I", "N: No feature store", "N: Per-model SQL", "I: Batch pipelines", "E: Streaming", "E: Regional"],
    ideas={"now": ["n/a"], "next": ["Streaming"], "adv": ["On-demand features"], "rej": ["Copy-pasted feature code"]})

sub(id="feature-serving", comp="feature-store", name="Online Feature Serving", phase="IV", cat="ML · Low latency",
    resp="Return the latest feature values for given entities in milliseconds, with freshness metadata and defaults.",
    inp="entity keys + feature refs", out="feature vectors", deps="Online store (Redis Cluster/Cassandra)", cons="Risk scoring, ETA, Dispatch ranking", own="online store layout",
    problem="Low-latency, high-throughput feature retrieval with graceful degradation.", without="Slow or failing models.",
    guar=["p99 < 10 ms", "Stale values flagged", "Missing features get defined defaults"], nong=["Feature correctness beyond pipeline"],
    usecase="Dispatch ranks 20 drivers: one pipelined Redis call fetches 20 × 5 features in 3 ms.",
    derive="- Batch lookups (MGET/pipelines).\n- Co-locate a view's features per entity in one hash.",
    conc="Read-only lookups; writes come only from pipelines, so readers see whole hash values atomically per key.", consistency="Eventual: values lag their pipelines by seconds (streaming) or hours (batch), and timestamps expose the lag.", idem="Read-only lookups have no side effects.", order="Values carry timestamps; consumers check freshness.",
    restart="Client library stateless.", scale="Redis Cluster sharded by entity.", arch="Java client library with pipelined Redis hash reads, local LRU for hot static features, defaults and freshness checks.",
    modules=[["Client", "Batch get"], ["FreshnessCheck", "Max age"], ["Defaults", "Per feature"]],
    d_arch=("""flowchart LR
  SVC["service"] --> CL["Client"] --> RC[("Redis Cluster")]
  CL --> LRU["local LRU"]""", "Client library."),
    d_seq=("""sequenceDiagram
  participant D as Dispatch
  participant C as Client
  participant R as Redis
  D->>C: get(drivers[20], [p_accept_inputs])
  C->>R: pipeline HMGET ×20
  R-->>C: values
  C-->>D: vectors (+stale flags)""", "Batch lookup."),
    nostate="A read path over key-value data. Feature values have timestamps but no lifecycle states.",
    d_flow=("""flowchart LR
  K["keys"] --> P["pipelined reads"] --> V["vectors"]""", "Batching."),
    d_fail=("""flowchart TB
  R["Redis shard down"] --> D["defaults; model degraded mode"]""", "Degraded mode."),
    sql="-- Redis: HSET fv:rider_activity:{rider_id} trips_7d 12 requests_10m 3 _ts 1730540000",
    data="TTL per view.", api="""Map<String, FeatureVector> get(List<String> entityKeys, List<String> features)""",
    mech=[("Pipelining", "Sends many commands without waiting for each reply, which collapses N round trips into ~1.")],
    code="""List<Object> res = redis.executePipelined((RedisCallback<Object>) c -> { keys.forEach(k -> c.hashCommands().hMGet(k.getBytes(), fields)); return null; });""", cx="O(keys).",
    fail=[F("Hot key", "Latency on one shard", "Slow", "Local LRU for hot static features", "None")],
    alts=[["Cassandra online store", "Viable", "Larger datasets", "> memory budget"]],
    adrs=[A("Redis Cluster", "IV", "Latency.", [("Cassandra", "Higher p99"), ("Redis", "Chosen")], "Redis.", "Fast.", "Memory cost.", "Cassandra for large views.")],
    qa=[Q("Reliability", "Feature store is down. What do models do?", "Each model declares defaults and a degraded policy: risk falls back to rules, ETA to base ETA, ranking to ETA-only. The client returns defaults with a stale flag, and callers decide.", "")],
    tests=[T("Load", "50K/s", "p99 < 10 ms"), T("Failure", "Shard down", "Defaults returned")],
    evo=["N: No feature store in Phase I", "N: No feature store", "N: Features computed inline", "I: Redis online store", "E: Hot-key LRU", "E: Regional"],
    ideas={"now": ["n/a"], "next": ["LRU"], "adv": ["Embedded stores"], "rej": ["SQL queries at inference"]})

# ======================================================================= ML Platform
comp(id="ml-platform", domain="ml", name="ML Platform (Training, Registry, Serving, Monitoring)", tag="ML · Platform", phase="III", kind="Platform capability",
     biz="Lets data scientists ship models (ETA, fraud, demand, matching) safely and quickly, and catches models that go wrong in production.",
     eng="Reproducible training pipelines, a model registry with lineage and approval, scalable low-latency serving with shadow/canary deployment, and monitoring for drift and performance.",
     deploy="Notebook + batch scoring (III); registry + serving (IV); full MLOps with streaming monitoring (V).", data_own="Model artifacts, registry metadata, prediction logs.",
     up=["feature-store", "event-pipeline", "experimentation"], down=["applied-models", "routing-eta", "risk-fraud", "dispatch", "pricing"], ext=["GPU/CPU training clusters", "Model server (Triton/KServe)"],
     interfaces="Registry API (register, promote), inference gRPC `Predict`, prediction logging topic.",
     problem="Models degrade silently, deployments are risky, and reproducibility is hard. Each team building its own serving stack is costly.",
     fr=["Pipelines (data → train → evaluate)", "Registry with versions, metrics, lineage", "Approval gates", "Serving with autoscaling", "Shadow/canary", "Drift and performance monitoring"], nfr=["Inference p99 < 20 ms for tabular models", "Rollback < 5 min", "Training reproducible from registry record"],
     workload="Phase V: ~10 production models, ~50K predictions/s.", success="Fast, safe model iteration.", failure="Bad model in production unnoticed.",
     derive="Reproducibility needs code + data snapshot + parameters recorded. Safety needs a staged rollout with automatic metrics comparison. Silent failures need monitoring of inputs (drift) and outputs vs labels.",
     owns=["Training infra", "Registry", "Serving", "Monitoring"], not_owns=["Model semantics (applied teams)", "Features (Feature store)"], sync=["Predict"], **{"async": ["Training", "Monitoring"]},
     boundary_why="A shared platform standardizes safety mechanisms across models.",
     hld=("""flowchart LR
  FS[("offline features")] --> TP["Training pipeline"] --> REG["Model registry"]
  REG -->|approved| MS["Model serving"]
  SVC["Services"] -->|Predict| MS --> FSO[("online features")]
  MS --> PL[["prediction logs"]] --> MON["Monitoring: drift, accuracy"]
  MON -->|alert/rollback| REG""", "Train, register, serve, monitor, with a loop back."),
     seq=("""sequenceDiagram
  participant D as DS
  participant P as Pipeline
  participant R as Registry
  participant S as Serving
  D->>P: run training (code sha, snapshot id)
  P->>R: register v14 (metrics, lineage)
  D->>R: request promotion
  R->>S: deploy v14 shadow
  S-->>R: shadow metrics ok
  R->>S: canary 10% → 100%""", "Model release."),
     subdeps=[("model-serving", "training-registry")],
     flow="Pipelines produce registered artifacts. Promotion goes through shadow and canary gates. Serving logs predictions. Monitoring joins with labels and triggers rollback.",
     data="Registry: `models(name, version, artifact_uri, code_sha, data_snapshot, params, metrics, stage)`. Prediction logs in lake.",
     rel=[["Rollback", "Previous stage version kept warm."], ["Degradation", "Callers have non-ML fallbacks."]], sec=[["Artifacts", "Signed; serving verifies signature."], ["Access", "Promotion requires approvals."]],
     adrs=[A("Shadow → canary promotion", "IV", "Risky deploys.", [("Direct deploy", "Risky"), ("Shadow + canary", "Chosen")], "Staged.", "Safety.", "Slower releases.", "N/A")],
     qa=[Q("ML", "How do you know the fraud model is degrading when labels take 60 days?", "Monitor leading indicators: input drift (PSI on key features), output drift (score distribution shift), decision-rate changes, and early proxy labels. Alert on drift beyond thresholds and evaluate fully when labels mature.", "")],
     impl_order=["training-registry", "model-serving"], pkg="""ml/pipelines (Python, Airflow/Kubeflow)
ml/registry (MLflow)
serving (KServe/Triton configs)""",
     tests=[T("Reproducibility", "Retrain from registry record", "Same metrics ±ε"), T("Rollback", "Promote bad model", "Auto rollback on guardrail")],
     evo=[("N", "No ML in pilot", "—", "—", "—"), ("N", "Heuristics", "—", "—", "—"), ("I", "Batch training + scoring", "Lake", "Manual review", "First models"),
          ("E", "Registry + online serving", "Model server", "Shadow/canary", "Online models"), ("E", "Streaming monitoring, autoscaling", "—", "Auto-rollback", "Scale"), ("E", "Regional serving", "—", "—", "Global")],
     ideas={"now": ["n/a"], "next": ["Registry"], "adv": ["Feature/model co-versioning"], "rej": ["Models deployed from notebooks"]})

sub(id="training-registry", comp="ml-platform", name="Training Pipelines & Model Registry", phase="III", cat="ML · MLOps",
    resp="Run reproducible training pipelines and record every model version with lineage, metrics and approval stage.",
    inp="feature snapshots, labels, code", out="model artifacts + registry entries", deps="Feature store offline, Orchestrator, Object storage", cons="Model serving, Applied models", own="registry",
    problem="Know exactly what each production model is and how to rebuild it.", without="Unreproducible, unauditable models.",
    guar=["Every registered model has code sha, data snapshot, params, metrics", "Promotion requires passing evaluation gates"], nong=["Model quality"],
    usecase="ETA model v14 trained on Iceberg snapshot 8812 with code abc123. Its MAPE of 11.8% beats v13's 12.4%, so it is eligible for shadow.",
    derive="- Iceberg snapshot ids pin data.\n- Pipelines as code (DAGs).\n- Registry stages (None → Staging → Production → Archived).",
    conc="Stage transitions with optimistic locking.", consistency="Registry strongly consistent.", idem="Registering the same run id is a no-op.", order="Version numbers monotonic.",
    restart="Pipeline steps resumable.", scale="Training compute scales with clusters.", arch="Airflow/Kubeflow DAG: extract (point-in-time) → train → evaluate vs champion → register (MLflow) → request promotion.",
    modules=[["Pipelines", "DAGs"], ["Evaluator", "Champion comparison"], ["Registry", "MLflow"], ["Approvals", "Gate"]],
    d_arch=("""flowchart LR
  DAG["Training DAG"] --> EX["extract PIT"] --> TR["train"] --> EV["evaluate vs champion"] --> RG["Registry"]""", "Pipeline."),
    d_seq=("""sequenceDiagram
  participant A as Airflow
  participant R as Registry
  A->>A: train on snapshot 8812
  A->>R: log run, metrics, artifact
  A->>R: register v14 (Staging)""", "Register."),
    d_state=("""stateDiagram-v2
  [*] --> None
  None --> Staging
  Staging --> Production
  Production --> Archived""", "Registry stages."),
    d_flow=("""flowchart LR
  SNAP["snapshot id"] & SHA["code sha"] & P["params"] --> M["model version"]""", "Lineage."),
    d_fail=("""flowchart TB
  F["evaluation fails"] --> S["stays in Staging"]""", "Gate."),
    sql="-- MLflow backend store tables (runs, params, metrics, registered_models, model_versions)",
    data="Artifacts retained for all production versions.", api="""mlflow.register_model(run_uri, "eta-model"); client.transition_model_version_stage("eta-model", 14, "Staging")""",
    mech=[("Data snapshot pinning", "Recording the Iceberg snapshot id lets anyone re-read the exact training data later (time travel).")],
    code="""with mlflow.start_run():
    df = fs.get_historical_features(entity_df, features, as_of_snapshot=8812)
    model = lgb.train(params, lgb.Dataset(df[X], df[y]))
    mlflow.log_params(params); mlflow.log_metric("mape", mape(model, valid)); mlflow.lightgbm.log_model(model, "model")""", cx="Training-dependent.",
    fail=[F("Snapshot expired", "Time-travel error", "Can't reproduce", "Retain snapshots for production models", "N/A")],
    alts=[["SageMaker/Vertex", "Viable", "Managed", "Cloud-native teams"]],
    adrs=[A("MLflow registry", "IV", "Open, common.", [("Custom", "Effort"), ("MLflow", "Chosen")], "MLflow.", "Standard.", "Ops.", "N/A")],
    qa=[Q("Governance", "Who can promote a pricing model to production?", "The model owner requests promotion. Automated gates (offline metrics, fairness checks, shadow results) must pass, and a second approver from pricing governance signs off. All of it is recorded in the registry.", "")],
    tests=[T("Reproducibility", "Re-run", "Same metrics")],
    evo=["N: No ML in Phase I", "N: Heuristics only", "I: Pipelines + registry", "E: Approvals", "E: Automated retraining", "E: Regional models"],
    ideas={"now": ["Snapshot pinning"], "next": ["Auto retraining"], "adv": ["Continuous training"], "rej": ["Unregistered models"]})

sub(id="model-serving", comp="ml-platform", name="Model Serving & Monitoring", phase="IV", cat="ML · Inference",
    resp="Serve model predictions with low latency and autoscaling, support shadow and canary rollouts, log predictions, and monitor drift and accuracy with automatic rollback.",
    inp="Predict requests, registry promotions, labels", out="predictions, logs, alerts", deps="Registry, Feature serving, Kafka", cons="ETA, Risk, Dispatch, Pricing, Demand", own="serving deployments, prediction logs",
    problem="Production inference is a reliability problem plus a statistics problem.", without="Slow or silently wrong predictions.",
    guar=["p99 < 20 ms (tabular)", "Shadow predictions never affect responses", "Guardrail breach triggers rollback"], nong=["Accuracy"],
    usecase="ETA v14 canary at 10%: MAPE on canary traffic 11.9% vs 12.4% control after 24 h, promoted. Later drift alert on weather feature, investigation finds a weather API format change.",
    derive="- Model server per model with autoscaling on CPU/QPS.\n- Router splits traffic by version.\n- Logs sampled predictions with features and model version.",
    conc="Stateless replicas.", consistency="Version pinned per request (logged).", idem="Predictions are pure functions of inputs and version.", order="Not applicable; labels are joined later by id.",
    restart="Replicas reload artifacts.", scale="Horizontal; batch inference per request (20 rows).", arch="KServe/Triton with an inference router (traffic split) → prediction log topic → monitoring jobs (PSI, accuracy when labels arrive) → alerts and auto-rollback via registry.",
    modules=[["Router", "Traffic split, shadow"], ["ModelServer", "Inference"], ["PredictionLogger", "Sampled logs"], ["Monitor", "Drift/accuracy"], ["AutoRollback", "Guardrails"]],
    d_arch=("""flowchart LR
  C["caller"] --> RT["Router"] --> V13["v13 (90%)"] & V14["v14 canary (10%)"]
  RT -.->|shadow copy| V15["v15 shadow"]
  V13 & V14 & V15 --> PL[["prediction logs"]] --> MON["Monitor"] --> AR["AutoRollback"]""", "Traffic split plus shadow."),
    d_seq=("""sequenceDiagram
  participant C as Caller
  participant R as Router
  participant M as Model
  participant L as Log
  C->>R: Predict(rows)
  R->>M: v14
  M-->>R: preds
  R->>L: log(sample)
  R-->>C: preds""", "Inference."),
    d_state=("""stateDiagram-v2
  [*] --> Shadow
  Shadow --> Canary
  Canary --> Live
  Canary --> RolledBack
  Live --> RolledBack: guardrail breach""", "Deployment stages."),
    d_flow=("""flowchart LR
  F["features"] --> P["prediction"] --> LOG["log"] --> J["join labels"] --> A["accuracy"]""", "Monitoring loop."),
    d_fail=("""flowchart TB
  S["server overload"] --> CB["caller timeout → fallback (non-ML)"]""", "Caller fallbacks."),
    sql="-- prediction logs in lake: predictions(model, version, request_id, features_hash, prediction, ts)",
    data="Logs 1 year.", api="""rpc Predict(PredictRequest{model, rows[]}) returns (PredictResponse{predictions[], version})""",
    mech=[("Population Stability Index", "PSI = Σ (a_i − e_i)·ln(a_i/e_i) over bins of a feature's distribution. PSI > 0.2 signals significant drift."), ("Shadow traffic", "Duplicate requests to the new version asynchronously and log outputs without using them, giving safe comparison on real traffic.")],
    code="""double psi = 0; for (int i = 0; i < bins; i++) psi += (a[i] - e[i]) * Math.log(a[i] / e[i]);""", cx="Model-dependent.",
    fail=[F("Bad canary", "Guardrail", "10% affected", "Rollback", "N/A"), F("Model server down", "Timeouts", "Fallback", "Autoscale/replicas", "N/A")],
    alts=[["Embedded models in services", "Viable", "Lowest latency", "Small models (ETA residual)"]],
    adrs=[A("Separate serving except tiny models", "IV", "Ops and safety.", [("All embedded", "Hard to roll out"), ("Server", "Chosen")], "Model server; ONNX embedding allowed for < 1 ms needs.", "Flexibility.", "Network hop.", "N/A")],
    qa=[Q("Reliability", "Should model inference be on the dispatch critical path?", "Yes, with a strict deadline and fallback. Dispatch calls with an 80 ms budget, and on timeout uses ETA-only ranking. Availability of dispatch never depends on ML availability.", "")],
    tests=[T("Load", "50K preds/s", "p99 < 20 ms"), T("Rollback", "Guardrail breach", "Rolled back < 5 min")],
    evo=["N: No ML in Phase I", "N: No ML serving", "N: Batch scoring only", "I: Online serving + canary", "E: Auto-rollback, streaming monitoring", "E: Regional"],
    ideas={"now": ["n/a"], "next": ["Auto-rollback"], "adv": ["GPU serving for deep models"], "rej": ["ML without fallback"]})

# ======================================================================= Applied Models
comp(id="applied-models", domain="ml", name="Applied Models (Demand Forecasting, Acceptance, ETA)", tag="ML · Intelligence", phase="III", kind="Logical models consumed by Routing, Pricing and Dispatch",
     biz="Predicts where demand will appear, which driver will accept, and how long trips take, so the marketplace positions supply and prices fairly.",
     eng="Domain models trained on platform data with specific evaluation metrics and production integration points, served via the ML platform.",
     deploy="Batch forecasts (III); online acceptance and ETA residual models (IV–V).", data_own="Model code, evaluation datasets, forecasts.",
     up=["ml-platform", "feature-store", "event-pipeline"], down=["pricing", "dispatch", "routing-eta", "driver-earnings"], ext=["Weather and events data"],
     interfaces="`DemandForecast(cell, horizon)`, `p_accept(driver, offer)`, `eta_residual(features)`.",
     problem="Heuristics leave value on the table: reactive surge, nearest-driver dispatch and graph-only ETAs.",
     fr=["Demand forecast per H3 res-7 cell, 15–60 min horizon", "Acceptance probability per offer", "ETA residual correction"], nfr=["Forecast MAPE targets per city", "Inference within callers' latency budgets"],
     workload="Forecasts every 5 min per cell; acceptance per offer; ETA per candidate.", success="Measurable lift in experiments.", failure="Biased or stale predictions harming the marketplace.",
     derive="Each model must answer a decision-relevant question with a metric aligned to the decision (wait time, completion), so models are evaluated in experiments, not just offline.",
     owns=["Model definitions and evaluation"], not_owns=["Serving infra", "Decisions (consuming domains)"], sync=["Predictions via serving"], **{"async": ["Forecast batches"]},
     boundary_why="Applied models are owned by product-aligned teams but built on the shared platform.",
     hld=("""flowchart LR
  FS[("features")] --> DF["Demand forecasting"] --> SRG["Surge / supply positioning"]
  FS --> AM["Acceptance model"] --> RANK["Dispatch ranking"]
  FS --> ETAM["ETA residual model"] --> ETA["ETA service"]""", "Three model families and their consumers."),
     seq=("""sequenceDiagram
  participant J as Forecast job
  participant S as Surge
  participant D as Driver app
  J->>J: forecast next 30 min per cell
  J->>S: expected demand (θ adjustment)
  J->>D: heatmap 'busy soon'""", "Forecast use."),
     subdeps=[("demand-forecasting", "acceptance-model")],
     flow="Batch and online predictions are consumed by domains, which keep non-ML fallbacks. Experiments validate impact.",
     data="Forecast table `demand_forecast(cell, horizon_min, ts, expected_requests, p10, p90)`.",
     rel=[["Fallback", "Consumers keep heuristic defaults."]], sec=[["Fairness", "Acceptance model excludes protected attributes and audits outcomes by area."]],
     adrs=[A("Experiment-gated adoption", "III", "Offline metrics mislead.", [("Ship on offline metrics", "Risky"), ("Experiment-gated", "Chosen")], "Switchbacks.", "Real impact.", "Slower.", "N/A")],
     qa=[Q("ML", "Why forecast demand instead of reacting to it?", "Drivers need 5–15 minutes to reposition. Reactive surge only starts moving supply after waits have already grown. Forecasts let surge pre-adjust and heatmaps guide drivers in advance, reducing peak wait times. Experiments measure the benefit.", "")],
     impl_order=["demand-forecasting", "acceptance-model"], pkg="ml/models/{demand,acceptance,eta}",
     tests=[T("Accuracy", "Backtest 8 weeks", "MAPE within target"), T("Impact", "Switchback", "Wait time reduced")],
     evo=[("N", "Heuristics in pilot", "—", "—", "—"), ("N", "Heuristics", "—", "—", "—"), ("I", "Batch demand forecast", "Lake", "—", "Data volume"), ("E", "Online acceptance, ETA residual", "Serving", "Fallbacks", "Platform"), ("E", "Streaming features, retraining", "—", "—", "Scale"), ("E", "Regional models", "—", "—", "Global")],
     ideas={"now": ["n/a"], "next": ["Acceptance"], "adv": ["RL dispatch"], "rej": ["Untested model launches"]})

sub(id="demand-forecasting", comp="applied-models", name="Demand Forecasting", phase="III", cat="ML · Time series",
    resp="Forecast ride requests per H3 cell for the next 15–60 minutes with uncertainty, for surge pre-adjustment, driver heatmaps and capacity planning.",
    inp="historical requests per cell/time, calendar, weather, events", out="forecasts with intervals", deps="Feature store, Event calendars", cons="Surge engine, Driver app heatmaps, Capacity planning", own="demand_forecast",
    problem="Anticipate demand so supply can move before waits explode.", without="Reactive, oscillating marketplace.",
    guar=["Forecasts refreshed every 5 min", "Intervals calibrated (p10–p90 coverage ~80%)"], nong=["Accuracy for unprecedented events"],
    usecase="Concert ends at 22:30. Forecast at 22:00 predicts 900 requests in 3 cells at 22:35, heatmaps light up for drivers and surge θ pre-adjusts slightly.",
    derive="- Strong seasonality (hour × weekday) plus exogenous events.\n- Gradient boosting with lag features per cell works well and is cheap.\n- Hierarchical reconciliation (cells sum to city).",
    conc="Batch job per city.", consistency="Each forecast run is a snapshot.", idem="Same inputs give the same forecast.", order="Newer runs supersede.",
    restart="Stateless batch run. A failed run is retried, and consumers keep the previous forecast meanwhile.", scale="Cells × horizons per city; parallel by city.", arch="Every 5 min: build features (lags, rolling means, calendar, weather, events) → LightGBM quantile models → reconcile → write table + publish.",
    modules=[["FeatureBuilder", "Lags, calendar, events"], ["Models", "Quantile GBMs"], ["Reconciler", "Hierarchical sums"], ["Publisher", "Table + topic"]],
    d_arch=("""flowchart LR
  FS["features"] --> MB["Models (q10,q50,q90)"] --> RC["Reconciler"] --> PUB["Publisher"] --> SRG["Surge"] & HM["Heatmaps"]""", "Pipeline."),
    d_seq=("""sequenceDiagram
  participant S as Scheduler
  participant F as Forecaster
  S->>F: run (city PUN)
  F->>F: predict 30 min × cells
  F-->>S: written""", "Run."),
    nostate="Forecast runs are snapshots.",
    d_flow=("""flowchart LR
  H["history"] --> L["lags"] --> M["model"] --> Y["forecast"]""", "Features to forecast."),
    d_fail=("""flowchart TB
  J["job fails"] --> U["consumers use previous run ≤ 15 min, then seasonal naive"]""", "Fallback chain."),
    sql="CREATE TABLE ml.demand_forecast (city text, cell bigint, horizon_min int, run_ts timestamptz, p10 real, p50 real, p90 real, PRIMARY KEY(city, cell, horizon_min, run_ts));",
    data="Forecasts retained 90 days for evaluation.", api="""topic demand-forecasts key=city value={run_ts, cells:[{cell, horizon, p10, p50, p90}]}""",
    mech=[("Quantile regression", "Training with pinball loss at τ = 0.1, 0.5, 0.9 yields prediction intervals directly."), ("Hierarchical reconciliation", "Scale cell forecasts so they sum to the city forecast, which is more accurate at aggregate level.")],
    code="""model_q50 = lgb.LGBMRegressor(objective="quantile", alpha=0.5).fit(X_train, y_train)""", cx="O(cells × features).",
    fail=[F("Unprecedented event", "Large residuals", "Wrong forecast", "Event calendar inputs; manual overrides", "N/A")],
    alts=[["Seasonal naive", "Baseline", "Simple", "Fallback"], ["Deep (TFT)", "Advanced", "Better for complex patterns", "Large data"]],
    adrs=[A("GBM with lags", "III", "Accuracy/cost.", [("Deep models", "Costly"), ("GBM", "Chosen")], "GBM.", "Good accuracy.", "Feature engineering.", "N/A")],
    qa=[Q("ML", "How do you evaluate forecasts fairly across small and large cells?", "Use weighted MAPE (WAPE = Σ|e| / Σy) per city and pinball loss for quantiles, and report coverage of intervals. Plain MAPE explodes on cells with tiny demand.", "")],
    tests=[T("Backtest", "Rolling origin 8 weeks", "WAPE < target")],
    evo=["N: Not needed for a pilot", "N: Seasonal averages", "I: GBM batch forecasts", "E: Events/weather features", "E: 5-min streaming refresh", "E: Regional"],
    ideas={"now": ["Seasonal naive baseline"], "next": ["Event calendars"], "adv": ["Deep models"], "rej": ["Forecast-driven surge without caps"]})

sub(id="acceptance-model", comp="applied-models", name="Offer Acceptance Model", phase="IV", cat="ML · Classification",
    resp="Predict the probability that a driver accepts a given offer, used by dispatch ranking to minimize expected rider wait.",
    inp="offer context (pickup distance, ETA, destination direction, time), driver features (recent acceptance, session length)", out="p_accept", deps="Feature serving, Model serving", cons="Driver ranking", own="model artifacts",
    problem="Declines cost 15 s each. Predicting them improves ranking.", without="More decline rounds.",
    guar=["Calibrated probabilities (reliability curve)", "Prediction within 80 ms batch", "No protected attributes"], nong=["Explaining individual human choices"],
    usecase="Driver near the end of a 10-hour shift and offer heading away from home → p = 0.25, so ranked below a fresher driver with p = 0.85 and ETA +40 s.",
    derive="- Binary classification on historical offers (accepted / not).\n- Calibration matters because the score is used in an expected-cost formula.\n- Features must exist at offer time (no leakage).",
    conc="Stateless inference.", consistency="Model version pinned.", idem="Pure prediction for given features and version.", order="Not applicable; each offer is scored independently.",
    restart="Serving replicas reload the pinned model version from the registry at start.", scale="Batch of ≤ 20 per request.", arch="GBM classifier + isotonic calibration, served online, with features from the store and context computed by dispatch.",
    modules=[["Training", "Offers dataset"], ["Calibration", "Isotonic"], ["Serving", "Batch predict"], ["FairnessAudit", "Outcome parity checks"]],
    d_arch=("""flowchart LR
  OFF["historical offers"] --> TR["train GBM"] --> CAL["calibrate"] --> REG["registry"] --> SV["serving"]
  DSP["Dispatch ranking"] --> SV""", "Train to serve."),
    d_seq=("""sequenceDiagram
  participant D as Dispatch
  participant M as Model
  D->>M: predict(20 candidates)
  M-->>D: p_accept[20]""", "Inference."),
    nostate="Stateless classifier.",
    d_flow=("""flowchart LR
  F["features at offer time"] --> P["p_accept"] --> S["score = eta + (1−p)·cost"]""", "Use in ranking."),
    d_fail=("""flowchart TB
  T["timeout"] --> H["historical acceptance rate as p"]""", "Fallback."),
    sql="-- Training set: offers joined with outcomes and point-in-time features",
    data="Training data 6 months rolling.", api="""rpc Predict(model="acceptance", rows[]) -> p[]""",
    mech=[("Isotonic calibration", "A monotone mapping from raw scores to observed acceptance frequencies, fitted on held-out data, makes p meaningful as a probability.")],
    code="""calibrated = CalibratedClassifierCV(gbm, method="isotonic", cv="prefit").fit(X_valid, y_valid)""", cx="O(rows).",
    fail=[F("Feedback loop (low-p drivers get fewer offers)", "Exposure skew", "Bias", "Exploration: small random share of offers", "N/A")],
    alts=[["Historical acceptance rate", "Phase III", "Simple", "Baseline"]],
    adrs=[A("Calibrated GBM", "IV", "Used in expected-cost.", [("Uncalibrated", "Wrong costs"), ("Calibrated", "Chosen")], "Calibrate.", "Correct trade-offs.", "Extra step.", "N/A")],
    qa=[Q("Fairness", "Could the model learn to avoid certain neighbourhoods?", "It predicts *driver* acceptance, which may encode drivers' avoidance of areas. Using it can reduce service there. Mitigations: monitor pickup ETA and fulfillment by area, cap the influence of p_accept, and add area-level fairness constraints in ranking.", "")],
    tests=[T("Calibration", "Reliability curve", "Within ±3%"), T("Fairness", "Fulfillment by area", "No significant degradation in experiments")],
    evo=["N: Not needed in pilot", "N: Not needed", "N: Historical rates", "I: Calibrated GBM online", "E: Streaming features, exploration", "E: Regional"],
    ideas={"now": ["n/a"], "next": ["Exploration"], "adv": ["Contextual bandits"], "rej": ["Protected attributes"]})
