from model import comp, sub, A, Q, F, T

# ======================================================================= Product Catalog
comp(id="product-catalog", domain="pricing", name="Product Catalog & Ride Discovery", tag="Discovery · Read-heavy", phase="I", kind="Logical component (inside Pricing service from Phase IV)",
     biz="Shows the rider which ride options exist at their location right now (UberX, XL, Black, Auto, Moto), with capacity, nearby availability and an ETA preview.",
     eng="A per-city product configuration plus a fast preview aggregator that joins config, supply density, ETA and price estimates into one response.",
     deploy="Module (I); part of Pricing service (IV); preview aggregation in Rider BFF.", data_own="products, city_products (enablement, capacity, rules), category mapping.",
     up=["geo-index", "routing-eta", "pricing", "fleet-vehicle"], down=["ride-request", "pricing", "dispatch"], ext=[],
     interfaces="`GET /v1/products?lat&lng`; internal `ProductCatalog.forCity(city)`.",
     problem="Products differ per city and change often (launches, regulations). The home screen must show only valid options with useful previews within ~300 ms.",
     fr=["Configure products per city/geofence", "Map vehicle categories to products", "Preview: nearby car count/ETA per product", "Hide unavailable products"], nfr=["Preview p95 < 300 ms", "Config change live < 1 min"],
     workload="Every app open + destination entry; Phase V ≈ 20K req/s at peak.", success="Riders see accurate options quickly.", failure="Options shown that can't be fulfilled; slow home screen.",
     derive="Config is small and slow-changing, so cache it in memory with versioned reloads. Previews are expensive joins, so parallel fan-out with deadlines and graceful omission.",
     owns=["Product definitions", "City enablement", "Category→product mapping"], not_owns=["Prices (Pricing)", "Driver positions (Geo)"], sync=["Products + preview"], **{"async": ["Config change events"]},
     boundary_why="Catalog is configuration owned by ops and product. Previews are an aggregation concern and live in the BFF.",
     hld=("""flowchart LR
  APP["Rider app"] --> BFF["Rider BFF"]
  BFF --> CAT["Vehicle categories & city products"]
  BFF --> PRE["Ride options preview"]
  PRE --> GEO["Geo index counts"] & ETA["ETA"] & PRC["Fare estimator"]""", "Config plus parallel preview fan-out."),
     seq=("""sequenceDiagram
  participant A as App
  participant B as BFF
  participant C as Catalog
  participant G as Geo
  participant E as ETA
  A->>B: products(lat,lng)
  B->>C: forCity(PUN, point)
  C-->>B: [X, XL, Auto]
  par
    B->>G: counts per category
    B->>E: nearest ETA per category
  end
  B-->>A: options with previews""", "Preview fan-out."),
     subdeps=[("ride-options-preview", "vehicle-categories")],
     flow="Config is resolved for the point's city and geofences, then previews are fetched in parallel with a 250 ms deadline. Products with no supply show 'no cars nearby' rather than being hidden, if enabled.",
     data="`products(id, name, capacity, vehicle_categories[])`, `city_products(city, product_id, enabled, geofence_rules, sort_order, version)`.",
     rel=[["Deadlines", "Each preview call 150 ms; missing parts omitted."], ["Caching", "Config in memory; reload on version change."]], sec=[["Abuse", "Rate-limited; preview positions jittered."]],
     adrs=[A("Config in memory with versioned reload", "I", "Tiny, hot data.", [("DB per request", "Wasteful"), ("In-memory + version poll", "Chosen")], "Cache with version.", "Fast.", "≤ 60 s staleness.", "N/A")],
     qa=[Q("Product", "Should products with zero nearby drivers be hidden?", "Show them as 'no cars nearby' unless the product is unavailable in the area. Hiding causes confusion and hides demand signals, while showing lets requests express demand, which surge and supply planning use.", "")],
     impl_order=["vehicle-categories", "ride-options-preview"], pkg="""com.atlas.catalog
├── config  (ProductCatalog, CityProducts)
└── preview (OptionsPreviewService)""",
     tests=[T("Integration", "Disable product in city", "Gone from response within 60 s"), T("Failure", "ETA service timeout", "Options returned without ETA")],
     evo=[("I", "Module", "Tables", "—", "Pilot"), ("E", "Same", "Config cache", "Deadlines", "Latency"), ("U", "No change needed", "—", "—", "—"), ("R", "Pricing service + BFF preview", "—", "Fan-out deadlines", "Services"), ("E", "Precomputed per-cell previews", "Cache by H3 res 8", "—", "20K req/s"), ("E", "Regional catalogs", "—", "—", "Global")],
     ideas={"now": ["Versioned config"], "next": ["Personalized ordering"], "adv": ["Dynamic product bundles"], "rej": ["Client-hardcoded products"]})

sub(id="vehicle-categories", comp="product-catalog", name="Vehicle Categories & City Products", phase="I", cat="Configuration",
    resp="Define products, map vehicle categories to them, and enable or disable them per city and zone.",
    inp="ops configuration edits", out="resolved product list for a point", deps="Geofencing", cons="Preview, Ride Request validation, Dispatch filtering, Pricing", own="products, city_products",
    problem="One authoritative definition of which products exist where, used identically by app, request validation, dispatch and pricing.", without="App shows XL but dispatch can't fulfil it, or pricing has no rate card.",
    guar=["A product is requestable only if enabled for the pickup's city/zone", "Each product maps to ≥ 1 vehicle category", "Config changes are versioned"], nong=["Supply availability"],
    usecase="Ops enables 'Auto' only inside the old-city geofence. Riders outside don't see it, and requests for it outside are rejected with PRODUCT_UNAVAILABLE.",
    derive="- Config is read everywhere and changes rarely, so a versioned snapshot distributed to readers.\n- Zone rules depend on geofences, so resolve through the geofence service.",
    conc="Edits via admin with optimistic locking; publish increments global version.", consistency="Readers converge within poll interval (≤ 60 s).", idem="Publishing the same version is a no-op.", order="Version numbers monotonic.",
    restart="Snapshot loaded at boot from DB.", scale="Tiny data; replicated in every reader.", arch="Admin writes → DB → version bump → readers poll version and reload snapshot.",
    modules=[["CatalogAdmin", "Validated edits"], ["SnapshotLoader", "Poll + atomic swap"], ["Resolver", "Point → enabled products"]],
    d_arch=("""flowchart LR
  OPS["Ops"] --> AD["CatalogAdmin"] --> DB[("catalog tables + version")]
  SL["SnapshotLoader"] --> DB
  SL --> SN["in-memory snapshot"]
  Q["resolve(point)"] --> RS["Resolver"] --> SN & GF["Geofences"]""", "Admin-to-snapshot pipeline."),
    d_seq=("""sequenceDiagram
  participant R as Reader
  participant DB
  loop every 30s
    R->>DB: SELECT version
    alt changed
      R->>DB: load snapshot
      R->>R: swap reference
    end
  end""", "Versioned reload."),
    nostate="Configuration records are versioned, not stateful entities.",
    d_flow=("""flowchart LR
  E["edit"] --> V["validate (rate card exists, categories exist)"] --> P["publish version"]""", "Cross-checks prevent enabling a product without a rate card."),
    d_fail=("""flowchart TB
  BAD["bad config"] --> RB["rollback to previous version"]""", "Versioned rollback."),
    sql="""CREATE TABLE catalog.city_products (city text, product_id text, enabled boolean NOT NULL, zone_ids uuid[], sort_order int, PRIMARY KEY(city, product_id));
CREATE TABLE catalog.catalog_version (id int PRIMARY KEY DEFAULT 1, version bigint NOT NULL, published_at timestamptz NOT NULL);""",
    data="History of versions kept for audit.", api="""List<Product> resolve(LatLng p)  // enabled products at point
boolean requestable(String productId, LatLng pickup)""",
    mech=[("Copy-on-write snapshot", "Readers hold an immutable snapshot reference. Reload builds a new one and swaps the reference atomically, so reads never take locks.")],
    code="""public List<Product> resolve(LatLng p) {
    var s = snapshot.get(); var city = cities.of(p); var zones = geofences.containing(p.lat(), p.lng());
    return s.products(city).stream().filter(cp -> cp.enabled() && cp.zoneMatch(zones)).map(CityProduct::product).toList();
}""", cx="O(products).",
    fail=[F("DB down", "Reload fails", "Stale snapshot served", "Retry", "Bounded staleness")],
    alts=[["Feature flags for products", "Viable", "Fast toggles", "Experiments"], ["Hardcoded", "Rejected", "Deploy per change", "Never"]],
    adrs=[A("Validation across catalog and pricing on publish", "II", "Products without rate cards break requests.", [("No cross-check", "Rejected"), ("Validate", "Chosen")], "Publish requires rate card.", "Prevents broken launches.", "Coupling at publish time.", "N/A")],
    qa=[Q("Consistency", "A product is disabled while a rider is mid-request for it. Outcome?", "Requests validated before disable proceed. Validation happens at request creation, and dispatch doesn't re-check catalog. The disable affects only new requests, which keeps in-flight behaviour predictable.", "")],
    tests=[T("Unit", "Zone-only product outside zone", "Not resolved"), T("Integration", "Publish without rate card", "Rejected")],
    evo=["I: Tables + in-memory snapshot", "E: Zone rules", "E: CatalogChanged events", "U: No change needed: inside Pricing service", "U: No change needed", "E: Regional catalogs"],
    ideas={"now": ["Publish validation"], "next": ["Scheduled launches"], "adv": ["Per-segment products"], "rej": ["Client-side config"]})

sub(id="ride-options-preview", comp="product-catalog", name="Ride Options Preview", phase="II", cat="Aggregation · Latency",
    resp="Assemble, per enabled product, nearby car count, nearest ETA and an indicative price for the home and destination screens.",
    inp="rider point (+destination)", out="option cards", deps="Catalog, Geo index, ETA, Fare estimator", cons="Rider app", own="preview cache",
    problem="Combine several services into one fast response, degrading gracefully.", without="Slow home screen or empty options when one dependency stalls.",
    guar=["Response within 300 ms p95", "Missing parts omitted, never blocking"], nong=["Binding prices (quotes are separate)"],
    usecase="Rider opens app: X (4 cars, 3 min), XL (1 car, 7 min), Auto (no cars). Destination entered → indicative prices appear.",
    derive="- Fan-out in parallel with per-call deadlines.\n- Previews for nearby riders are near-identical, so cache by (H3 res-8 cell, product) for 10 s.",
    conc="Stateless; cache fill single-flight.", consistency="Previews may be ≤ 10 s stale.", idem="Read-only aggregation: repeating it returns the same cached result within 10 s.", order="Independent requests; the client shows the latest response.",
    restart="Stateless: a restarted BFF instance starts with an empty local cache and refills from Redis or the backends.", scale="Cell-level caching collapses load in dense areas.", arch="BFF aggregator using CompletableFuture fan-out with timeouts and a Redis/cache layer keyed by cell.",
    modules=[["Aggregator", "Parallel fan-out"], ["CellCache", "10 s cache per cell × product"], ["Jitter", "Displayed car positions jittered"]],
    d_arch=("""flowchart LR
  REQ["preview"] --> CC["CellCache"]
  CC -->|miss| AG["Aggregator"] --> G["Geo"] & E["ETA"] & P["Pricing"]""", "Cached aggregator."),
    d_seq=("""sequenceDiagram
  participant B as BFF
  participant G as Geo
  participant E as ETA
  B->>G: counts (150ms)
  B->>E: nearest ETAs (150ms)
  G-->>B: counts
  E--xB: timeout
  B-->>B: options without ETA""", "Partial response."),
    nostate="Stateless aggregation.", d_flow=("""flowchart LR
  P["point"] --> C["cell"] --> K["cache key cell:product"] --> V["card"]""", "Cache key."),
    d_fail=("""flowchart TB
  D["dependency slow"] --> O["omit field"]""", "Graceful omission."),
    sql="-- Cache only (Redis): preview:{h3res8}:{product} TTL 10s", data="Ephemeral.", api="""GET /v1/products?lat=&lng=&dest_lat?=&dest_lng?= -> [{product, capacity, cars_nearby?, eta_s?, price_range?}]""",
    mech=[("Scatter-gather with deadlines", "Start all calls, then wait until a deadline. Late results are dropped, so total latency ≈ the deadline rather than the sum of calls.")],
    code="""var counts = geo.countsAsync(cell).completeOnTimeout(Map.of(), 150, MILLISECONDS);
var etas = eta.nearestAsync(cell).completeOnTimeout(Map.of(), 150, MILLISECONDS);
return counts.thenCombine(etas, (c, e) -> products.stream().map(p -> Card.of(p, c.get(p), e.get(p))).toList());""", cx="O(products).",
    fail=[F("Geo down", "Timeout", "No counts", "Omit", "None")],
    alts=[["Sequential calls", "Rejected", "Latency sums", "Never"], ["Precompute per cell", "Phase V", "Cheaper at scale", "High QPS"]],
    adrs=[A("Cell-level cache", "V", "QPS.", [("No cache", "Load"), ("10 s per cell", "Chosen")], "Cache.", "Load collapse.", "Staleness.", "N/A")],
    qa=[Q("Privacy", "Why jitter car positions on the home screen?", "Exact positions of idle drivers let anyone track drivers (stalking, competitor analysis). Showing approximate positions (±100 m, rotated ids) keeps the 'cars nearby' signal without exposing individuals.", "")],
    tests=[T("Failure", "ETA timeout", "Response < 300 ms without ETA"), T("Load", "10K req/s one cell", "1 backend fan-out per 10 s")],
    evo=["N: Phase I app shows a static product list without previews", "I: Aggregator with deadlines", "U: No change needed", "E: Moves to BFF", "E: Cell cache", "U: No change needed: regional BFFs"],
    ideas={"now": ["Deadlines"], "next": ["Prefetch on app foreground"], "adv": ["Server push of preview updates"], "rej": ["Exact idle positions"]})

# ======================================================================= Pricing Engine
comp(id="pricing", domain="pricing", name="Pricing Engine", tag="Money · Core", phase="I", kind="Logical component → deployable service (Phase IV)",
     biz="Tells the rider what the trip will cost before they book (an upfront price they can trust), balances supply and demand with surge, and explains every price later.",
     eng="Deterministic fare computation from versioned rate cards, route estimates and multipliers, producing signed, time-limited quotes that ride requests must reference, with a complete audit record.",
     deploy="Module (I); Pricing service (IV); surge as stream job (V).", data_own="rate_cards, quotes, surge_multipliers, pricing_audit.",
     up=["routing-eta", "geo-index", "product-catalog", "promotions", "experimentation"], down=["ride-request", "fare-finalization", "receipts", "support"], ext=[],
     interfaces="`POST /v1/quotes`, internal `validateQuote(quoteId, signature)`, events `QuoteIssued`, `SurgeUpdated`.",
     problem="Riders expect an upfront price, and the price shown must be the price charged (within policy). Prices depend on route, time, demand, promotions and experiments, and every one must be reproducible for disputes and regulators.",
     fr=["Fare estimate per product", "Upfront quote with expiry", "Surge per zone", "Apply promotions", "Audit trail per quote", "Price experiments"], nfr=["Quote p95 < 250 ms", "Quote reproducible from stored inputs", "Surge updates within 1 min (V: 30 s)"],
     workload="≈ 3 quotes per request (product switching); Phase V ≈ 1,500 quotes/s.", success="Charged = quoted for > 98% of trips; pricing explainable.", failure="Rider charged more than quoted; tampered quotes; unexplained prices.",
     derive="A quote is a promise, so store it with all inputs and sign it so clients can't alter it. Rate cards change, so version them and pin the version in the quote. Surge must be bounded and smooth, so computed centrally per zone with caps.",
     owns=["Rate cards", "Quote issuance and validation", "Surge multipliers", "Pricing audit"], not_owns=["Final fare after trip (Fare finalization uses pricing rules)", "Promotion budgets (Promotions)"], sync=["Quote", "Validate quote"], **{"async": ["Surge computation", "Audit export"]},
     boundary_why="Pricing owns the computation and rules. Fare finalization owns applying them to actual trip data, with the same library to avoid divergence.",
     hld=("""flowchart LR
  APP["Rider"] --> FE["Fare estimator / quote"]
  FE --> RC[("rate cards vN")]
  FE --> RT["Routing: distance/time"]
  FE --> SG["Surge engine"]
  FE --> PR["Promotions"]
  FE --> AU["Pricing audit"]
  FE --> QS[("quotes (signed)")]
  RR["Ride request"] -->|validate quote| FE
  SG --> SM[("surge per H3 res7")]""", "The quote combines rate card, route, surge and promotions, and is stored, signed and audited."),
     seq=("""sequenceDiagram
  participant A as App
  participant P as Pricing
  participant R as Routing
  participant S as Surge
  A->>P: POST /quotes {pickup, dest, product}
  P->>R: route(pickup, dest)
  P->>S: multiplier(cell(pickup))
  P->>P: compute with rate card v12
  P->>P: store quote + audit, sign
  P-->>A: {quote_id, price, expires_at, sig}""", "Quote issuance."),
     state=("""stateDiagram-v2
  [*] --> Issued
  Issued --> Used: referenced by ride request
  Issued --> Expired: after 5 min
  Used --> [*]
  Expired --> [*]""", "Quote lifecycle."),
     subdeps=[("fare-estimator", "surge-engine"), ("fare-estimator", "pricing-audit")],
     flow="Quotes are computed synchronously, then persisted with full inputs and signed. Ride Request validates the quote id and signature and marks it used atomically. Surge is computed out of band and read from cache.",
     data="`rate_cards(id, version, city, product, base, per_km, per_min, min_fare, booking_fee, effective_from)`, `quotes(id, rider_id, product, inputs jsonb, price_minor, currency, rate_card_version, surge, expires_at, used_by_request)`, `surge_multipliers(cell, product, multiplier, computed_at)`.",
     rel=[["Fallback", "Routing down → estimate from straight-line × detour factor, flagged non-upfront (metered)."], ["Surge stale", "Use last value up to 5 min, then 1.0."]],
     sec=[["Tamper", "Quotes signed (HMAC) and stored server-side; client price never trusted."], ["Fairness", "Surge caps; no personal-data-based price discrimination (policy)."]],
     adrs=[A("Upfront quotes stored server-side and referenced by id", "I", "Promise integrity.", [("Client sends price", "Rejected"), ("Server-stored quote id", "Chosen")], "Quote id + HMAC.", "Tamper-proof, auditable.", "Storage for every quote (most unused).", "N/A")],
     qa=[Q("Correctness", "Rider gets a quote at 1.2× surge, waits 4 minutes, surge becomes 2.0×, then books. Price?", "The quote is honoured if unexpired (5 min TTL): 1.2×. That's the purpose of an upfront price. After expiry the app requests a new quote and shows the change. The expiry bounds how stale a promise can be.", "Re-pricing at booking breaks trust.")],
     impl_order=["fare-estimator (+ rate cards)", "pricing-audit", "surge-engine"], pkg="""com.atlas.pricing
├── ratecard (RateCard, RateCardRepository)
├── quote    (QuoteService, QuoteSigner, FareCalculator)
├── surge    (SurgeReader, SurgeComputer)
└── audit    (PricingAuditWriter)""",
     tests=[T("Correctness", "Recompute stored quote from inputs", "Identical price"), T("Security", "Modified quote signature", "Rejected"), T("Concurrency", "Same quote used by 2 requests", "One succeeds")],
     evo=[("I", "Module; rate cards + quotes", "PG", "Signed quotes", "Upfront pricing"), ("E", "Same", "Rate-card cache", "Routing fallback", "Reliability"), ("E", "Same", "QuoteIssued events", "Audit export", "Analytics"),
          ("R", "Pricing service", "Own DB; quote TTL store", "SLO", "Isolation"), ("R", "Stream surge; experiment-aware pricing", "Redis surge cache", "Caps", "Scale"), ("E", "Regional pricing", "Currency/tax per region", "—", "Global")],
     ideas={"now": ["Shared FareCalculator library"], "next": ["Price explanations in app"], "adv": ["ML-based upfront pricing"], "rej": ["Personalized prices by willingness-to-pay"]})

sub(id="fare-estimator", comp="pricing", name="Fare Estimator & Upfront Quotes", phase="I", cat="Money · Computation",
    resp="Compute a price per product from rate card, route estimate, surge, fees, taxes and promotions, and issue signed, time-limited quotes.",
    inp="pickup, destination, product, rider, time", out="quote {id, price, breakdown, expires_at, signature}", deps="Rate cards, Routing, Surge, Promotions, Audit", cons="Rider app, Ride Request, Fare finalization (same calculator)", own="quotes, rate_cards",
    problem="Produce a correct, reproducible, tamper-proof price promise.", without="Disputes and fraud.",
    guar=["Money in integer minor units", "Deterministic: same inputs → same price", "Quote usable once, before expiry", "Breakdown sums exactly to total"], nong=["Final fare equals quote if trip deviates beyond policy (route change, stops)"],
    usecase="Quote for UberX 9.8 km / 24 min: base ₹50 + 9.8×₹12 + 24×₹1.5 = ₹203.6 → surge 1.2 → ₹244.32 → booking fee ₹10 → tax 5% → ₹267 (rounded per city rule).",
    derive="- Floating-point money causes rounding errors, so use integer minor units and an explicit rounding mode at defined steps.\n- Reproducibility requires storing inputs and the rate card version.\n- Tamper-proofing needs a server-side store plus a signature for cheap stateless pre-validation.",
    conc="Quote 'use' is `UPDATE quotes SET used_by_request=? WHERE id=? AND used_by_request IS NULL AND expires_at > now()`.", consistency="Strong for quote state.", idem="Quote creation is not idempotent (each is a new promise), but the client can reuse an unexpired quote. Use is idempotent for the same request id.",
    order="The calculation is a pure function of explicit inputs, so arrival order doesn't matter.", restart="Stateless computation; quotes in DB.", scale="Quotes table grows quickly (~1.5K/s at Phase V): TTL store (Redis) for unused + PG for used (Phase IV).",
    arch="`QuoteService` gathers inputs (route, surge, promos) in parallel, calls the pure `FareCalculator`, persists the quote and audit record in one transaction, and signs.",
    modules=[["InputGatherer", "Route, surge, promo eligibility (parallel)"], ["FareCalculator", "Pure function → breakdown"], ["QuoteStore", "Persist, use-once"], ["QuoteSigner", "HMAC over (id, price, expiry, rider)"]],
    d_arch=("""flowchart LR
  REQ["quote request"] --> IG["InputGatherer"] --> RT["Routing"] & SG["Surge"] & PR["Promotions"]
  IG --> FC["FareCalculator (pure)"] --> QS["QuoteStore"] --> DB[("quotes + audit")]
  QS --> SGN["QuoteSigner"]""", "Gather inputs, compute purely, persist, sign."),
    d_seq=("""sequenceDiagram
  participant RR as RideRequest
  participant Q as QuoteStore
  RR->>Q: use(quote_id, sig, request_id)
  Q->>Q: verify HMAC
  Q->>Q: UPDATE used_by_request WHERE NULL AND not expired
  alt 1 row
    Q-->>RR: price locked
  else
    Q-->>RR: QUOTE_EXPIRED_OR_USED
  end""", "Using a quote."),
    d_state=("""stateDiagram-v2
  [*] --> Issued
  Issued --> Used
  Issued --> Expired""", "Quote states."),
    d_flow=("""flowchart LR
  RC["rate card v12"] --> C["calc"]
  RT["9.8km/24min"] --> C
  S["surge 1.2"] --> C
  P["promo -₹50"] --> C
  C --> B["breakdown lines (minor units)"] --> T["total"]""", "Explicit breakdown lines."),
    d_fail=("""flowchart TB
  R["routing down"] --> E["estimate range, metered fare (no upfront)"]
  S["surge stale >5m"] --> ONE["use 1.0"]""", "Degraded pricing modes are explicit and shown to the rider."),
    sql="""CREATE TABLE pricing.quotes (
  id uuid PRIMARY KEY, rider_id uuid NOT NULL, product text NOT NULL, city text NOT NULL,
  price_minor bigint NOT NULL CHECK (price_minor >= 0), currency char(3) NOT NULL,
  rate_card_id uuid NOT NULL, surge numeric(4,2) NOT NULL, breakdown jsonb NOT NULL, inputs jsonb NOT NULL,
  expires_at timestamptz NOT NULL, used_by_request uuid UNIQUE, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE pricing.rate_cards (id uuid PRIMARY KEY, city text, product text, base_minor bigint, per_km_minor bigint, per_min_minor bigint,
  min_fare_minor bigint, booking_fee_minor bigint, tax_bps int, rounding text, effective_from timestamptz, UNIQUE(city, product, effective_from));""",
    data="Unused quotes expire; purge after 7 days (Phase IV: Redis TTL). Used quotes retained with trip records (7 years financial).", api="""POST /v1/quotes {pickup, destination, product, promo_code?} -> 201 {quote_id, price:{amount_minor, currency}, breakdown[], expires_at, signature}
internal: QuoteUse use(UUID quoteId, String sig, UUID requestId)""",
    mech=[("Integer money + banker's rounding at defined steps", "All arithmetic in minor units (long), with fractional per-km rates in 'micro-units' and rounding only at final line items. This ensures breakdown lines sum to the total."), ("HMAC signature", "Lets the request path reject tampered quotes before a DB lookup, and binds a quote to a rider id so it can't be shared.")],
    code="""public Breakdown calculate(RateCard rc, RouteEstimate r, BigDecimal surge, List<Discount> d) {
    long distanceFare = Math.round(r.distanceM() / 1000.0 * rc.perKmMinor());
    long timeFare = Math.round(r.durationS() / 60.0 * rc.perMinMinor());
    long subtotal = Math.max(rc.minFareMinor(), rc.baseMinor() + distanceFare + timeFare);
    long surged = new BigDecimal(subtotal).multiply(surge).setScale(0, RoundingMode.HALF_EVEN).longValueExact();
    long afterPromo = Math.max(0, surged + rc.bookingFeeMinor() - Discount.total(d, surged));
    long tax = Math.round(afterPromo * rc.taxBps() / 10_000.0);
    return Breakdown.of(rc, distanceFare, timeFare, surged - subtotal, d, tax, rc.round(afterPromo + tax));
}""", cx="O(1).",
    fail=[F("Two requests use same quote", "UNIQUE used_by_request", "Second rejected", "New quote", "Single use"), F("Rate card changes mid-quote", "Pinned version", "None", "Quote uses pinned card", "Reproducible")],
    alts=[["Metered pricing only", "Phase I alternative", "Simple; less trust", "Markets requiring meters"], ["Quote JWT without DB", "Rejected", "Can't mark used", "Never"]],
    adrs=[A("Integer minor units", "I", "Money correctness.", [("double", "Rejected"), ("BigDecimal everywhere", "Viable, slower"), ("long minor units + BigDecimal for multipliers", "Chosen")], "long minor units.", "Exact sums.", "Care with currencies without minor units (JPY).", "N/A")],
    qa=[Q("Correctness", "How do you make sure the final fare uses the same logic as the estimate?", "Both use the same `FareCalculator` library and the same pinned rate-card version. Fare finalization calls it with actual distance and time when the trip deviates beyond tolerance, and otherwise charges the quote. A property test compares estimator and finalizer outputs for identical inputs.", "")],
    tests=[T("Property", "Breakdown lines sum", "Always equals total"), T("Unit", "Min fare", "Applied when subtotal below"), T("Concurrency", "Parallel use", "One success")],
    evo=["I: Quotes in PG; FareCalculator", "E: Rate-card cache; routing fallback", "E: QuoteIssued events", "R: Pricing service; unused quotes in Redis TTL", "E: Experiment-aware rate cards", "E: Multi-currency/tax per region"],
    ideas={"now": ["Pure calculator library"], "next": ["Breakdown explanations in receipt"], "adv": ["Route-based upfront pricing with ML"], "rej": ["Floating-point money"]})

sub(id="surge-engine", comp="pricing", name="Surge (Dynamic Pricing) Engine", phase="II", cat="Algorithm · Market balancing",
    resp="Compute a bounded, smooth price multiplier per zone and product from real-time demand (requests, app opens) and supply (available drivers).",
    inp="demand signals per cell, available supply per cell, ETA, policy caps", out="multiplier per (H3 res-7 cell, product)", deps="Geo index counts, Ride Request events, Experimentation", cons="Fare estimator, Driver app (heatmaps)", own="surge_multipliers",
    problem="When demand exceeds supply, waits explode and no one gets a ride. Price increases ration demand and attract drivers, but they must be fair, bounded and stable.", without="Unserved demand at peaks; or erratic pricing anger.",
    guar=["Multiplier within [1.0, cap] per city policy", "Changes smoothed (max step per interval)", "Emergency caps (disasters) enforced immediately"], nong=["Market-clearing optimality"],
    usecase="Concert ends: demand in 3 cells jumps 6× while supply is 1.5×. Multiplier rises from 1.0 to 1.8 over 3 minutes (step cap), drivers move in, and the multiplier decays as balance returns.",
    derive="- Imbalance ratio = demand / supply per cell over a window.\n- Map ratio → multiplier with a monotone curve, capped.\n- Neighbouring cells smoothed (spatial smoothing) to avoid sharp boundaries.\n- Rate-limit changes to avoid oscillation (temporal smoothing).",
    conc="Single writer per city (scheduled job or stream task).", consistency="Readers see the latest published snapshot; quotes record the value used.", idem="Recomputing for the same window gives the same result.", order="Windows processed in event-time order; late events within allowed lateness.",
    restart="Phase II: scheduled job reads counts from DB/Redis. Phase V: Flink with checkpoints.", scale="Cells × products per city; small compute, large input stream.",
    arch="Phase II: a job every 60 s per city: count requests in the last 5 min per res-7 cell and available drivers per cell, compute ratio → curve → spatial smoothing (k-ring average) → temporal step cap → write to Redis. Phase V: Flink sliding windows emitting every 30 s.",
    modules=[["DemandCounter", "Requests + eyeballs per cell"], ["SupplyCounter", "Available drivers per cell (geo counts)"], ["Curve", "ratio → multiplier"], ["Smoother", "Spatial + temporal"], ["PolicyCaps", "City/emergency caps"]],
    d_arch=("""flowchart LR
  RQ["request events"] --> DC["DemandCounter"]
  GEO["geo counts"] --> SC["SupplyCounter"]
  DC & SC --> CV["Curve"] --> SM["Smoother"] --> PC["PolicyCaps"] --> R[("Redis surge:{city}")]
  R --> FE["Fare estimator"]""", "Count, map, smooth, cap, publish."),
    d_seq=("""sequenceDiagram
  participant J as SurgeJob
  participant D as Demand
  participant S as Supply
  participant R as Redis
  J->>D: counts last 5m per cell
  J->>S: available per cell
  J->>J: ratio→curve→smooth→cap
  J->>R: HSET surge:PUN cell→mult (versioned)""", "Per-interval computation."),
    nostate="Multipliers are recomputed values. The temporal smoother uses the previous value as an input but has no lifecycle.",
    d_flow=("""flowchart LR
  D["demand 120"] --> RAT["ratio = 120/40 = 3"]
  S["supply 40"] --> RAT
  RAT --> M["curve(3) = 1.9"] --> SP["k-ring avg 1.8"] --> T["step cap +0.3 → 1.3"] --> CAP["≤ city cap 2.5"]""", "Worked example."),
    d_fail=("""flowchart TB
  J["job fails"] --> STALE["readers use last value ≤ 5 min, then 1.0"]
  S["supply signal missing"] --> NO["skip cell (keep previous)"]""", "Failure biases toward lower prices, never runaway surges."),
    sql="""CREATE TABLE pricing.surge_history (city text, cell bigint, product text, multiplier numeric(4,2), demand int, supply int, computed_at timestamptz,
  PRIMARY KEY(city, cell, product, computed_at));""",
    data="Live values in Redis; history in PG (partitioned daily) → lake for analysis and regulatory reporting.", api="""BigDecimal multiplier(String city, long cell, String product)   // from Redis snapshot
event SurgeUpdated{city, version, cells:[{cell, product, multiplier}]}""",
    mech=[("Monotone response curve", "m = 1 + α·max(0, ratio − θ)^β, capped. θ is the balance threshold, and α and β are tuned via experiments."), ("Spatial smoothing", "Average with k-ring neighbours (weighted) so moving 100 m doesn't change price 2×, which also reduces gaming."), ("Temporal step limit", "|m_t − m_{t−1}| ≤ δ prevents oscillation between overreaction and correction.")],
    code="""double target = Math.min(cap, 1 + alpha * Math.pow(Math.max(0, demand / Math.max(1.0, supply) - theta), beta));
double smoothed = kRingWeightedAvg(cell, target);
double next = prev + Math.max(-delta, Math.min(delta, smoothed - prev));
return BigDecimal.valueOf(next).setScale(1, RoundingMode.HALF_UP);""", cx="O(cells × k²) per interval.",
    fail=[F("Demand spike from bots", "Eyeballs without requests", "False surge", "Use requests not app opens; bot filtering", "None"), F("Disaster event", "Ops trigger", "Price gouging risk", "Emergency cap 1.0", "Immediate")],
    alts=[["No surge (fixed pricing + queue)", "Viable policy", "Long waits", "Regulated markets"], ["Optimization-based pricing", "Advanced", "Better market clearing", "Rich demand models"]],
    adrs=[A("Ratio curve with smoothing", "II", "Need simple, explainable surge.", [("ML pricing", "Too early"), ("Curve + smoothing", "Chosen")], "Curve per city.", "Explainable.", "Tuning.", "Phase V: ML demand forecasts adjust θ.")],
    qa=[Q("Gaming", "Drivers collectively go offline to trigger surge. How do you detect and counter?", "Detect correlated offline transitions in a cell followed by online transitions after surge rises (coordinated pattern). Counter by computing supply including drivers who went offline in the last N minutes nearby, damping surge for cells with anomalous supply drops, and flagging accounts for review.", "")],
    tests=[T("Unit", "Ratio below θ", "1.0"), T("Simulation", "Synthetic demand spike", "No oscillation; converges"), T("Policy", "Emergency cap", "All cells 1.0 within one interval")],
    evo=["N: Phase I uses fixed rate cards only", "I: Scheduled job per city", "E: Demand from request events stream", "E: Experimented curves", "R: Flink sliding windows, 30 s", "E: Regional jobs"],
    ideas={"now": ["Caps"], "next": ["Forecast-informed surge"], "adv": ["Driver-side incentive surge"], "rej": ["Personal surge per rider"]})

sub(id="pricing-audit", comp="pricing", name="Pricing Audit Trail", phase="I", cat="Compliance · Explainability",
    resp="Record every price decision with all inputs, versions and outputs so any price can be explained and reproduced later.",
    inp="quote computations, final fare computations", out="immutable audit records, explanations", deps="Fare estimator, Fare finalization", cons="Support, Regulators, Finance, Pricing analytics", own="pricing_audit",
    problem="Disputes and regulators ask 'why was this price X?' months later.", without="Unexplainable prices, so refunds by default and regulatory risk.",
    guar=["Every quote and final fare has an audit record", "Records are immutable", "Recompute yields identical price"], nong=["Real-time analytics (lake does that)"],
    usecase="Regulator asks for the surge applied to all airport trips on 31 Dec. Audit records give multiplier, rate card and cell per trip.",
    derive="- Immutability: append-only with hash chaining for tamper evidence.\n- Reproducibility: store inputs and code version (calculator version).",
    conc="Append-only inserts.", consistency="Written in the same transaction as the quote.", idem="Keyed by quote id.", order="Per quote, records are append-only and versioned.",
    restart="Committed with the quote, so no separate recovery is needed.", scale="Same volume as quotes; partition by day; offload to lake after 90 days.",
    arch="`PricingAuditWriter` inserts `(quote_id, kind, inputs, outputs, rate_card_id, calculator_version, prev_hash, hash)`. Daily job verifies the hash chain and exports to the lake.",
    modules=[["AuditWriter", "Append with hash"], ["Verifier", "Daily chain verification"], ["Explainer", "Human-readable breakdown"]],
    d_arch=("""flowchart LR
  FE["Fare estimator"] --> AW["AuditWriter"] --> DB[("pricing_audit (partitioned)")]
  V["Verifier daily"] --> DB
  SUP["Support"] --> EX["Explainer"] --> DB""", "Append, verify, explain."),
    d_seq=("""sequenceDiagram
  participant S as Support
  participant E as Explainer
  participant C as Calculator
  S->>E: explain(trip)
  E->>E: load audit record
  E->>C: recompute(inputs, rate card)
  C-->>E: same price
  E-->>S: breakdown + 'recomputed ✔'""", "Explanation with recompute check."),
    nostate="Append-only records.", d_flow=("""flowchart LR
  I["inputs"] --> H["hash(prev_hash || record)"] --> R[("record")]""", "Hash chaining."),
    d_fail=("""flowchart TB
  M["chain mismatch"] --> AL["security incident"]""", "Tamper evidence."),
    sql="""CREATE TABLE pricing.pricing_audit (id bigserial, quote_id uuid NOT NULL, kind text NOT NULL, inputs jsonb NOT NULL, outputs jsonb NOT NULL,
  rate_card_id uuid NOT NULL, calculator_version text NOT NULL, prev_hash bytea, hash bytea NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, created_at)) PARTITION BY RANGE (created_at);""",
    data="Retention 7 years (financial). Partitions older than 90 days archived to the lake (Parquet) and dropped.", api="""Explanation explain(UUID quoteOrTrip)""",
    mech=[("Hash chaining", "Each record includes the previous record's hash, so altering any record breaks every later hash. This is tamper-evident, though not tamper-proof."), ("Calculator versioning", "Code changes are versioned so old prices can be recomputed with the code version used at the time.")],
    code="""byte[] hash = sha256(concat(prevHash, canonicalJson(inputs), canonicalJson(outputs)));""", cx="O(1).",
    fail=[F("Audit insert fails", "Tx rollback", "Quote fails", "Retry", "No quote without audit")],
    alts=[["Logs only", "Rejected", "Not queryable/immutable", "Never"], ["Event sourcing pricing", "Overkill", "—", "—"]],
    adrs=[A("Audit in the same transaction", "I", "No price without explanation.", [("Async audit", "Rejected: gaps"), ("Same tx", "Chosen")], "Same tx.", "Completeness.", "Write amplification.", "N/A")],
    qa=[Q("Scale", "Hash chaining serialises inserts. Is that a bottleneck at 1.5K quotes/s?", "A single global chain would be. Use chains per (city, day partition, shard), with each shard serialised and shards independent, and verify per chain. Throughput scales with shards.", "")],
    tests=[T("Security", "Modify one record", "Verifier flags"), T("Correctness", "Recompute 10K random quotes", "100% identical")],
    evo=["I: Audit table in same tx", "E: Daily verification", "E: Export to lake", "E: Per-shard chains", "U: No change needed", "E: Regional retention rules"],
    ideas={"now": ["Calculator version field"], "next": ["Rider-facing explanation"], "adv": ["Merkle roots anchored externally"], "rej": ["Mutable audit records"]})

# ======================================================================= Promotions
comp(id="promotions", domain="pricing", name="Promotions & Coupons", tag="Money · Growth", phase="II", kind="Logical component (inside Pricing service from Phase IV)",
     biz="Runs discounts, referral credits and coupon codes to acquire and retain riders, within fixed budgets and without abuse.",
     eng="Eligibility evaluation, atomic redemption against per-user and global budgets, and settlement into the ledger.",
     deploy="Module (II); within Pricing service (IV); budget counters sharded (V).", data_own="campaigns, coupons, redemptions, promo budgets.",
     up=["risk-fraud", "experimentation", "consent-preferences"], down=["pricing", "ledger", "fare-finalization"], ext=[],
     interfaces="`applicablePromotions(rider, context)`, `reserve(promo, rider, quote)`, `commit/release(reservation)`.",
     problem="Budgets must never be overspent, a coupon must not be used twice, and abusers create fake accounts to farm promotions.",
     fr=["Create campaigns with rules", "Coupon codes (single/multi-use)", "Per-user limits", "Global budget caps", "Reserve at quote, commit at trip completion"], nfr=["Eligibility p95 < 30 ms", "Zero budget overspend beyond 0.1%"],
     workload="Evaluated on every quote; redemptions ≈ 10–30% of trips during campaigns.", success="Campaign goals met within budget.", failure="Budget blowouts; promo abuse rings.",
     derive="Promotions are applied at quote time but money is spent only when a trip completes, which needs a reservation step (reserve → commit/release). Budgets are shared counters under concurrency, so atomic decrement.",
     owns=["Campaigns and rules", "Redemptions", "Budgets"], not_owns=["Fraud scoring (Risk)", "Ledger entries (Ledger, on commit)"], sync=["Eligibility", "Reserve"], **{"async": ["Commit/release on trip events", "Budget alerts"]},
     boundary_why="Promotions change prices but have their own lifecycle and abuse model, so they are separate from rate cards.",
     hld=("""flowchart LR
  FE["Fare estimator"] --> EL["Campaign eligibility"] --> CR[("campaigns")]
  FE --> RS["Coupon redemption (reserve)"] --> B[("budgets + redemptions")]
  TRIP["TripCompleted / Cancelled"] --> RS
  RS -->|commit| LED["Ledger promo expense"]
  RISK["Risk score"] --> EL""", "Eligibility at quote, reservation against budget, commit on completion."),
     seq=("""sequenceDiagram
  participant P as Pricing
  participant R as Redemption
  participant T as Trip events
  P->>R: reserve(promo, rider, quote)
  R-->>P: reservation (amount)
  T->>R: TripCompleted(trip, quote)
  R->>R: commit reservation
  R->>R: ledger entry promo expense""", "Two-phase redemption."),
     subdeps=[("coupon-redemption", "promo-campaigns")],
     flow="Eligibility filters campaigns, reservation holds budget, and trip outcome commits or releases. Expired reservations are released by a sweeper.",
     data="`campaigns(id, rules jsonb, budget_minor, per_user_limit, starts, ends)`, `coupons(code, campaign_id, max_uses)`, `redemptions(id, campaign_id, rider_id, quote_id, amount_minor, state, expires_at)`, `campaign_budget(campaign_id, reserved_minor, spent_minor, budget_minor)`.",
     rel=[["Atomic budgets", "Conditional update on budget row (PG), sharded counters (V)."], ["Reservation expiry", "Sweeper releases after quote expiry + trip timeout."]],
     sec=[["Abuse", "Device/payment fingerprint limits; risk score gate."], ["Codes", "Unguessable codes for single-use; rate limits on code attempts."]],
     adrs=[A("Reserve/commit/release", "II", "Price at quote, spend at completion.", [("Spend at quote", "Rejected: abandoned quotes burn budget"), ("Spend at completion without reserve", "Rejected: overspend"), ("Reserve/commit", "Chosen")], "Two-phase.", "No overspend.", "Reservations hold budget temporarily.", "N/A")],
     qa=[Q("Concurrency", "A campaign has ₹10,000 left and 500 riders apply ₹50 promos in the same second. How do you avoid overspend?", "Reserve with `UPDATE campaign_budget SET reserved = reserved + :amt WHERE id = :c AND spent + reserved + :amt <= budget`. Row-level locking serialises updates, and once the budget is exhausted updates return 0 rows and the promo isn't applied. At Phase V, hot campaigns use N sharded budget rows (budget split across shards) to remove the single-row bottleneck, with rebalancing of leftovers.", "Checking then updating in two steps races.")],
     impl_order=["promo-campaigns", "coupon-redemption"], pkg="""com.atlas.promotions
├── campaign   (CampaignService, RuleEvaluator)
└── redemption (RedemptionService, BudgetRepository, ReservationSweeper)""",
     tests=[T("Concurrency", "1,000 parallel reserves on small budget", "Spent+reserved ≤ budget"), T("Integration", "Trip cancelled", "Reservation released")],
     evo=[("N", "No promotions in pilot", "—", "—", "Not needed"), ("I", "Module", "PG budgets", "Atomic updates", "Growth campaigns"), ("E", "Same", "Trip events drive commit", "Idempotent consumers", "Events"),
          ("E", "Inside Pricing service", "—", "Risk gate", "Abuse"), ("R", "Sharded budget counters", "Redis/PG shards", "Rebalancing", "Mega-campaigns"), ("E", "Regional campaigns", "Currency", "—", "Global")],
     ideas={"now": ["Reservation model"], "next": ["Referral programs with fraud checks"], "adv": ["Uplift-model targeting"], "rej": ["Unlimited-use public codes"]})

sub(id="promo-campaigns", comp="promotions", name="Campaigns & Eligibility Rules", phase="II", cat="Rules engine",
    resp="Define campaigns with targeting rules and evaluate which promotions apply to a rider and trip context.",
    inp="rider attributes, trip context, risk score, consent", out="applicable promotions ranked by value", deps="Risk, Consent, Experimentation", cons="Fare estimator, Redemption", own="campaigns, coupons",
    problem="Targeted promotions with many rule types, evaluated fast on every quote.", without="Hardcoded discounts, slow launches.",
    guar=["Only active campaigns within dates/geo apply", "Per-user limits respected", "High-risk riders excluded"], nong=["Budget availability (Redemption checks)"],
    usecase="Campaign 'NEWRIDER50': first 3 trips, Pune, UberX, max ₹50. A new rider's quote shows −₹50.",
    derive="- Rules are data → small rule DSL (JSON) evaluated in-process.\n- Campaigns are few (~hundreds), so load all active ones in memory.",
    conc="Campaign edits versioned; in-memory snapshot swap.", consistency="Snapshot ≤ 60 s stale.", idem="Evaluation is pure: same rider context and snapshot yield the same promotions.", order="Snapshot versions monotonic, so readers never move backwards.",
    restart="Reload snapshot.", scale="O(active campaigns) per quote; index by city.", arch="Rule evaluator over a JSON predicate tree; campaigns indexed by city/product.",
    modules=[["CampaignStore", "CRUD + versions"], ["RuleEvaluator", "Predicate tree"], ["Ranker", "Best value / stacking rules"]],
    d_arch=("""flowchart LR
  ADM["Marketing UI"] --> CS["CampaignStore"] --> SN["snapshot"]
  Q["quote ctx"] --> RE["RuleEvaluator"] --> SN
  RE --> RK["Ranker"]""", "In-memory evaluation."),
    d_seq=("""sequenceDiagram
  participant P as Pricing
  participant E as Evaluator
  P->>E: applicable(rider ctx)
  E->>E: filter by city/product/date
  E->>E: evaluate rules (trip_count<3, risk<0.7)
  E-->>P: [NEWRIDER50]""", "Evaluation."),
    d_state=("""stateDiagram-v2
  [*] --> Draft
  Draft --> Scheduled
  Scheduled --> Active
  Active --> Paused
  Paused --> Active
  Active --> Exhausted: budget spent
  Active --> Ended""", "Campaign lifecycle."),
    d_flow=("""flowchart LR
  R["rules JSON"] --> P["parsed predicate"] --> E["evaluate(ctx)"]""", "Rule pipeline."),
    d_fail=("""flowchart TB
  B["bad rule"] --> V["schema validation on save"]""", "Validation at save time."),
    sql="""CREATE TABLE promotions.campaigns (id uuid PRIMARY KEY, name text, city text[], products text[], rules jsonb NOT NULL, discount jsonb NOT NULL,
  per_user_limit int, budget_minor bigint, starts_at timestamptz, ends_at timestamptz, status text, version int);""",
    data="Campaigns retained for finance reporting.", api="""List<Promotion> applicable(RiderContext ctx, QuoteContext q)""",
    mech=[("Predicate trees", "Rules like {all:[{lt:['trip_count',3]},{in:['city',['PUN']]}]} compile to closures evaluated against a context map.")],
    code="""Predicate<Ctx> compile(JsonNode n) { return switch (n.fieldNames().next()) {
  case "all" -> stream(n.get("all")).map(this::compile).reduce(Predicate::and).orElse(c -> true);
  case "lt" -> c -> c.num(n.get("lt").get(0).asText()) < n.get("lt").get(1).asDouble();
  default -> throw new UnknownRule(n); }; }""", cx="O(rules).",
    fail=[F("Rule exception", "Evaluation error", "Campaign skipped", "Alert", "None")],
    alts=[["Drools", "Viable", "Powerful, heavy", "Complex rules"], ["Hardcoded", "Rejected", "Slow launches", "Never"]],
    adrs=[A("JSON rule DSL", "II", "Marketing needs flexibility.", [("Drools", "Heavy"), ("JSON DSL", "Chosen")], "DSL.", "Simple, safe.", "Limited expressiveness.", "If rules outgrow → CEL.")],
    qa=[Q("Fairness", "Can promotions target based on phone model (iPhone users pay less)?", "Policy says no to targeting on sensitive or proxy attributes for price differences. Allowed attributes are tenure, trip count, city, product and campaign opt-in. A rule linter enforces an allow-list of attributes.", "")],
    tests=[T("Unit", "Expired campaign", "Not applicable"), T("Unit", "Rule allow-list violation", "Save rejected")],
    evo=["N: No promotions in pilot", "I: DSL + snapshot", "E: Events for analytics", "E: Experiment integration", "E: Uplift targeting", "E: Regional"], ideas={"now": ["Attribute allow-list"], "next": ["CEL"], "adv": ["Uplift models"], "rej": ["Sensitive attribute targeting"]})

sub(id="coupon-redemption", comp="promotions", name="Coupon Redemption & Budget Control", phase="II", cat="Concurrency · Money",
    resp="Reserve, commit and release promotion amounts atomically against per-user limits and global budgets.",
    inp="reserve(promo, rider, quote), TripCompleted/Cancelled", out="reservations, committed redemptions, ledger promo entries", deps="Campaigns, Ledger, Trip events", cons="Fare estimator, Fare finalization", own="redemptions, campaign_budget",
    problem="Budget and usage limits under high concurrency, with spend tied to trip outcome.", without="Overspend, double use.",
    guar=["spent + reserved ≤ budget", "Per-user uses ≤ limit (committed + reserved)", "Each reservation ends committed or released"], nong=["Exact budget utilization (reservations may expire unused)"],
    usecase="Rider reserves ₹50 at quote. Trip completes and the reservation is committed with a ledger entry: promo expense ₹50, rider receivable reduced.",
    derive="- Two counters (reserved, spent) on the budget row; conditional update.\n- Per-user limit via count of active and committed redemptions under a unique index per (campaign, rider, use_no).",
    conc="Budget row conditional update. Per-user: insert redemption with `use_no` = next, unique (campaign, rider, use_no) within limit.", consistency="Strong: budget counters and redemption rows change in one PostgreSQL transaction, guarded by CHECK constraints.", idem="Reserve keyed by quote_id (unique). Commit/release keyed by redemption id + state check.", order="Commit after release (or vice versa) resolved by state machine: only from RESERVED.",
    restart="Sweeper releases expired reservations.", scale="Hot campaign row → sharded budget rows at Phase V.", arch="Transactional service with a state machine per redemption and sweeper.",
    modules=[["Reserver", "Budget + user-limit checks"], ["Committer", "Commit on TripCompleted; ledger"], ["Releaser", "Release on cancel/expiry"], ["Sweeper", "Expiry"]],
    d_arch=("""flowchart LR
  Q["quote"] --> RV["Reserver"] --> DB[("budget, redemptions")]
  TC["TripCompleted"] --> CM["Committer"] --> DB
  CM --> LED["Ledger"]
  TX["TripCancelled"] --> RL["Releaser"] --> DB
  SW["Sweeper"] --> RL""", "Reservation lifecycle."),
    d_seq=("""sequenceDiagram
  participant P as Pricing
  participant R as Reserver
  participant DB
  P->>R: reserve(c, rider, quote, 50)
  R->>DB: UPDATE budget SET reserved+=50 WHERE spent+reserved+50<=budget
  R->>DB: INSERT redemption(quote unique, use_no)
  DB-->>R: ok
  R-->>P: reserved""", "Reserve transaction."),
    d_state=("""stateDiagram-v2
  [*] --> RESERVED
  RESERVED --> COMMITTED: trip completed
  RESERVED --> RELEASED: cancelled / expired
  COMMITTED --> REVERSED: refund""", "Redemption lifecycle."),
    d_flow=("""flowchart LR
  R["reserve +50 reserved"] --> C["commit: reserved-50, spent+50"] --> L["ledger: promo_expense 50"]""", "Counter movements."),
    d_fail=("""flowchart TB
  L["lost TripCompleted"] --> REC["reconciliation: completed trips with RESERVED redemptions"]""", "Reconciliation closes event gaps."),
    sql="""CREATE TABLE promotions.campaign_budget (campaign_id uuid PRIMARY KEY, budget_minor bigint NOT NULL, reserved_minor bigint NOT NULL DEFAULT 0, spent_minor bigint NOT NULL DEFAULT 0,
  CHECK (reserved_minor >= 0 AND spent_minor + reserved_minor <= budget_minor));
CREATE TABLE promotions.redemptions (id uuid PRIMARY KEY, campaign_id uuid NOT NULL, rider_id uuid NOT NULL, use_no int NOT NULL, quote_id uuid UNIQUE NOT NULL,
  amount_minor bigint NOT NULL, state text NOT NULL, expires_at timestamptz NOT NULL, UNIQUE (campaign_id, rider_id, use_no));""",
    data="Redemptions retained 7 years.", api="""Reservation reserve(UUID campaign, UUID rider, UUID quote, long amount)
void commit(UUID quote, UUID trip)   // idempotent
void release(UUID quote)             // idempotent""",
    mech=[("CHECK constraint as last line of defence", "Even if application logic is wrong, the database rejects states where spent + reserved > budget."), ("use_no slotting", "Per-user limit becomes a unique constraint: the n-th use takes slot n ≤ limit, so concurrent attempts can't exceed it.")],
    code="""@Transactional
public Reservation reserve(UUID c, UUID rider, UUID quote, long amt) {
    if (budget.tryReserve(c, amt) == 0) throw new BudgetExhausted();
    int useNo = redemptions.nextUseNo(c, rider);
    if (useNo > campaigns.limit(c)) throw new UserLimitReached();
    return redemptions.insert(c, rider, useNo, quote, amt);   // unique(campaign,rider,use_no) + unique(quote)
}""", cx="O(1).",
    fail=[F("Concurrent same-user reserves", "Unique violation", "One fails", "Retry with next quote", "Limit held"), F("Lost completion event", "Reconciliation", "Reservation stuck", "Commit via reconciliation", "Eventually correct")],
    alts=[["Redis DECR budget", "Phase V option", "Faster", "Very hot campaigns, with PG reconciliation"], ["Spend at quote", "Rejected", "Wastes budget", "Never"]],
    adrs=[A("Sharded budget rows at Phase V", "V", "National campaigns hit one row.", [("Single row", "Bottleneck"), ("N shards", "Chosen")], "Split budget across N rows; pick random shard; rebalance.", "Throughput.", "Fragmented leftovers.", "N/A")],
    qa=[Q("Correctness", "Trip completes but the actual fare is lower than the discount. What's committed?", "Commit min(reserved amount, eligible fare portion). Release the remainder back to the budget (reserved −= full, spent += actual). The ledger records the actual discount.", "")],
    tests=[T("Concurrency", "Budget race", "Never exceeds"), T("Unit", "Commit twice", "Idempotent"), T("Recovery", "Expired reservation", "Released by sweeper")],
    evo=["N: No promotions in pilot", "I: PG reserve/commit/release", "E: Event-driven commit + reconciliation", "U: No change needed", "R: Sharded budgets", "E: Regional budgets"],
    ideas={"now": ["CHECK constraints"], "next": ["Reconciliation dashboard"], "adv": ["Budget pacing across day"], "rej": ["Read-then-write budget checks"]})
