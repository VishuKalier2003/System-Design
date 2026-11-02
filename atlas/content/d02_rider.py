from model import comp, sub, A, Q, F, T

comp(id="rider-profile", domain="rider", name="Rider Profile & Account", tag="Customer · Core", phase="I", kind="Logical component (inside Rider service from Phase IV)",
     biz="Holds who the rider is to the business: name, photo, language, saved places, preferences, consents and account status. Every rider surface reads it.",
     eng="A low-write, read-heavy, cache-friendly aggregate with strict privacy obligations (consent, export, erasure) and an account lifecycle that other domains must respect.",
     deploy="Module `rider` in monolith; part of the Rider service (with saved places and consent) from Phase IV; regional placement in Phase VI.",
     data_own="rider_profiles, saved_places, rider_preferences, consent_records, rider_account_status.",
     up=["identity", "privacy"], down=["ride-request", "pricing", "notifications", "support", "trip"], ext=["Image CDN"],
     interfaces="REST `/v1/riders/me`, `/v1/riders/me/places`, `/v1/riders/me/consents`; internal `RiderQuery.getSummary(riderId)`; events `RiderProfileUpdated`, `RiderAccountStatusChanged`.",
     problem="Every rider-facing flow needs consistent rider data, while privacy law requires purpose-bound consent, exportability and erasure. Account status (active, restricted, deleted) must gate actions across domains.",
     fr=["Create profile on first verified login", "Edit name, photo, language, email", "Save/edit up to 20 places (home, work, custom)", "Manage preferences (quiet ride, temperature, accessibility)", "Record and withdraw consents (marketing, location sharing, data sharing)", "Account lifecycle: active, restricted, pending deletion, deleted"],
     nfr=["Read p95 < 30 ms (cached)", "Writes p95 < 150 ms", "Consent changes effective for marketing within 5 min", "Erasure completed within 30 days (GDPR)"],
     workload="Reads ≈ 20× writes. Phase IV: ≈2K profile reads/s; writes ≈20/s.", success="Profile always present for a verified rider; consent respected everywhere.", failure="Marketing sent without consent; deleted rider data persists; restricted rider can still book.",
     derive="Profile data is personal data, so it needs a purpose for each field. Consent is a legal record, so it is append-only with timestamps and version of terms. Account status is read by many domains, so it is published as an event and also queryable. Reads dominate, so a cache with explicit invalidation on write.",
     owns=["Profile fields", "Saved places", "Preferences", "Consent records", "Rider account status"], not_owns=["Credentials (Identity)", "Payment methods (Payments vault)", "Trip history (Trip)", "Ratings given by drivers (Trust)"],
     sync=["Get/update profile", "Places CRUD", "Consent grant/withdraw"], **{"async": ["`RiderProfileUpdated` to search/support caches", "`RiderAccountStatusChanged` to dispatch/payments", "Erasure fan-out (Privacy)"]},
     boundary_why="Separating profile from identity means erasure can remove personal data while identity keeps a tombstone that prevents re-use abuse. Payment methods stay out for PCI scope reasons.",
     hld=("""flowchart LR
  APP["Rider app"] --> API["Rider API"]
  API --> PS["Profile store"] & SP["Saved places"] & CP["Consent & preferences"]
  PS & SP & CP --> DB[("rider schema")]
  API --> C[("cache")]
  PS -->|status events| BUS["events"]
  PRIV["Privacy erasure"] --> PS & SP & CP
  ID["Identity UserRegistered"] --> PS""", "Three subcomponents share one schema and one API surface. Account status changes are published for other domains to enforce."),
     seq=("""sequenceDiagram
  participant ID as Identity
  participant RP as Rider profile
  participant App
  ID->>RP: UserRegistered(user_id, role=rider)
  RP->>RP: create profile (status ACTIVE) idempotently
  App->>RP: PATCH /riders/me {name, language}
  RP->>RP: validate, update with version check
  RP-->>App: 200 profile (new version)""", "Profile creation is event-driven (in-process in Phase I). Edits use optimistic locking."),
     state=("""stateDiagram-v2
  [*] --> Active
  Active --> Restricted: risk/policy action
  Restricted --> Active: cleared
  Active --> PendingDeletion: user requests deletion
  PendingDeletion --> Active: cancelled within 14 days
  PendingDeletion --> Deleted: erasure complete
  Deleted --> [*]""", "Rider account status. `Restricted` blocks new ride requests but allows support and payments for outstanding balances."),
     subdeps=[("saved-places", "profile-store"), ("consent-preferences", "profile-store")],
     flow="Requests hit the Rider API, which authorizes via ownership guard (`me`), reads through cache, writes with optimistic locking, and publishes events through the outbox (Phase III). Erasure requests from Privacy run each subcomponent's erase handler and confirm completion.",
     data="`rider_profiles(user_id PK, display_name, email, language, photo_key, status, version)`, `saved_places(id, user_id, label, lat, lng, address, place_id)`, `rider_preferences(user_id, prefs jsonb)`, `consent_records(id, user_id, purpose, granted, terms_version, source, recorded_at)` (append-only). All keyed by user_id; Phase VI: rows live in the rider's home region.",
     er="""erDiagram
  RIDER_PROFILES ||--o{ SAVED_PLACES : has
  RIDER_PROFILES ||--|| RIDER_PREFERENCES : has
  RIDER_PROFILES ||--o{ CONSENT_RECORDS : records""",
     rel=[["Cache", "Read-through Redis, TTL 10 min, invalidated on write (delete key after commit)."], ["Idempotency", "Profile creation keyed by user_id (`ON CONFLICT DO NOTHING`)."], ["Degradation", "If profile store is down, ride booking proceeds with cached summary; edits fail."]],
     sec=[["Access", "Only `me` via ownership; support via RBAC with audit."], ["PII", "Email encrypted; photos in private bucket with signed URLs."], ["Privacy", "Consent purposes enumerated; erasure handler per table."]],
     adrs=[A("Consent as append-only records", "I", "Legal proof of consent at a point in time.", [("Boolean flags on profile", "Rejected: no history/proof"), ("Append-only records + current view", "Chosen")], "Append-only `consent_records`; current state derived (latest per purpose).", "Auditable.", "Slightly more complex reads (materialized current view).", "N/A")],
     qa=[Q("Data consistency", "A rider is restricted by fraud while a ride request is in flight. Which wins?", "Ride Request reads rider status synchronously at intake (strongly consistent in Phase I–III via the same DB or a direct call). Requests accepted before the restriction proceed. Fraud can additionally cancel in-flight requests via a command if the restriction is severe. From Phase IV, status is cached in Ride Request with event-driven invalidation plus a TTL of 60 s, accepting at most a 60 s window, which fraud closes by issuing explicit cancels for severe cases.", "A synchronous status call on every request couples availability to the rider service.")],
     impl_order=["profile-store", "consent-preferences", "saved-places"], pkg="""com.atlas.rider
├── profile   (ProfileController, ProfileService, RiderProfile, AccountStatus)
├── places    (SavedPlaceService)
├── consent   (ConsentService, ConsentRecord, PreferenceService)
└── privacy   (RiderErasureHandler)""",
     tests=[T("Integration", "UserRegistered delivered twice", "One profile"), T("Privacy", "Erasure request", "All rider rows removed or anonymized; confirmation sent"), T("Concurrency", "Two edits same version", "One 409")],
     evo=[("I", "Module in monolith", "rider schema", "Optimistic locking; unique constraints", "Correctness"), ("E", "Same", "Redis cache", "Cache invalidation on write", "Read load"),
          ("E", "Same", "Events via outbox", "Idempotent consumers", "Other domains need status"), ("R", "Rider service (profile+places+consent)", "Own DB", "SLO 99.95%", "Team ownership; isolation"),
          ("U", "No change needed: workload modest", "—", "—", "—"), ("R", "Regional placement by home region", "Portable subset replicated globally", "Residency", "Data residency")],
     ideas={"now": ["Single API for profile summary used by drivers (first name + photo only)"], "next": ["Profile completeness nudges"], "adv": ["Federated profile across business and personal accounts"], "rej": ["Storing payment methods in profile"]})

sub(id="profile-store", comp="rider-profile", name="Profile Store & Account Lifecycle", phase="I", cat="Domain · CRUD + lifecycle",
    resp="Store and serve rider profile fields and enforce the rider account lifecycle (active, restricted, pending deletion, deleted).",
    inp="UserRegistered, profile edits, status commands (risk, privacy)", out="profile reads, RiderAccountStatusChanged events", deps="Identity, Cache", cons="Ride Request, Support, Notifications, Driver app (summary)", own="rider_profiles",
    problem="Provide a consistent rider record and a single authoritative account status that every other domain can trust.",
    without="Each domain invents its own notion of a 'blocked' rider, and inconsistent enforcement follows.",
    guar=["One profile per rider user", "Status transitions only along the state machine", "Status changes published (at-least-once)"], nong=["Credential state (Identity)", "Real-time propagation before Phase III (in-process reads instead)"],
    usecase="Fraud restricts rider R for chargeback abuse. Status → Restricted, event published. Ride Request rejects R's next request with ACCOUNT_RESTRICTED and shows the support link.",
    derive="- Status must have one owner, so here, with commands from other domains (risk, privacy) instead of direct writes.\n- Lost updates are possible when app and support edit simultaneously, so a version column.\n- Reads dominate, so a cache, but status must not be served stale for long, so invalidate on change.",
    conc="Optimistic locking: `UPDATE ... SET ..., version=version+1 WHERE user_id=? AND version=?`. Status commands use a conditional transition `WHERE status IN (allowed_from)`.",
    consistency="Strong in DB. Cache is read-your-writes for the editor (cache deleted after commit). Other readers are eventually consistent within TTL or event latency.",
    idem="Creation keyed on user_id. Status commands carry command_id stored in a processed-commands table.", order="Status events include `status_version`; consumers ignore events with a lower version.",
    restart="DB-backed; outbox ensures events after crash.", scale="Single table keyed by user_id; caching handles reads; partition not needed until Phase VI placement.",
    arch="Spring service with `ProfileService` (edits), `AccountStatusService` (state machine) and a read-through `ProfileCache`. Status transitions are validated by a transition table rather than scattered if-statements.",
    modules=[["ProfileService", "Validated edits with version"], ["AccountStatusService", "Transition table, command dedup, event emission"], ["ProfileCache", "Read-through, delete-on-write"], ["SummaryView", "Minimal projection for drivers (first name, photo, rating)"]],
    d_arch=("""flowchart LR
  API["Rider API"] --> PSV["ProfileService"] --> DB[("rider_profiles")]
  RISK["Risk"] -->|RestrictRider cmd| AS["AccountStatusService"] --> DB
  AS -->|outbox| EV["RiderAccountStatusChanged"]
  API --> PC["ProfileCache"] --> DB""", "Edits and status commands are separate entry points into the same aggregate."),
    d_seq=("""sequenceDiagram
  participant R as Risk
  participant S as AccountStatusService
  participant DB
  R->>S: RestrictRider(cmd_id, rider, reason)
  S->>DB: insert processed_command(cmd_id) ON CONFLICT DO NOTHING
  S->>DB: UPDATE status=RESTRICTED, status_version+1 WHERE status='ACTIVE'
  S->>DB: insert outbox(RiderAccountStatusChanged)
  S-->>R: ok""", "Command handling: dedup, conditional transition and event, all in one transaction."),
    d_state=("""stateDiagram-v2
  [*] --> ACTIVE
  ACTIVE --> RESTRICTED
  RESTRICTED --> ACTIVE
  ACTIVE --> PENDING_DELETION
  RESTRICTED --> PENDING_DELETION: allowed after balance settled
  PENDING_DELETION --> ACTIVE: cancel within 14d
  PENDING_DELETION --> DELETED
  DELETED --> [*]""", "The transition table encoded in `AccountStatusService`."),
    d_flow=("""flowchart LR
  E["edit request"] --> V["validate (length, email format)"] --> W["write + version"] --> X["delete cache key"] --> O["outbox event"]""", "Write path ordering. The cache is deleted after commit so a concurrent reader cannot repopulate stale data before commit."),
    d_fail=("""flowchart TB
  C["cache down"] --> DB["read DB directly; shed non-critical reads"]
  O["event relay down"] --> L["events delayed; outbox retains; consumers catch up"]""", "Both failures degrade latency, not correctness."),
    sql="""CREATE TABLE rider.rider_profiles (
  user_id uuid PRIMARY KEY, display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 60),
  email_enc bytea, language text NOT NULL DEFAULT 'en', photo_key text,
  status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','RESTRICTED','PENDING_DELETION','DELETED')),
  status_version int NOT NULL DEFAULT 0, version int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE rider.processed_commands (command_id uuid PRIMARY KEY, processed_at timestamptz NOT NULL DEFAULT now());""",
    data="Single row per rider. Deleted riders keep a tombstone row (`status=DELETED`, PII nulled) so late events don't recreate them.",
    api="""GET   /v1/riders/me                 -> {display_name, language, photo_url, status, version}
PATCH /v1/riders/me  If-Match: <version> {display_name?, language?, email?} -> 200 | 409 VERSION_CONFLICT
internal: RiderSummary getSummary(UUID riderId)    // first name, photo, rating
command:  RestrictRider{command_id, rider_id, reason, until?} / UnrestrictRider / BeginDeletion
event:    RiderAccountStatusChanged{rider_id, status, status_version, reason, occurred_at}""",
    mech=[("Optimistic locking via If-Match", "The client sends the version it read, and the update succeeds only if unchanged. Conflicts are rare for profiles, so this beats locking."), ("Tombstones", "Keeping a status=DELETED row with PII removed stops replayed UserRegistered events from resurrecting a deleted account.")],
    code="""@Transactional
public void apply(StatusCommand cmd) {
    if (!processed.markIfNew(cmd.id())) return;              // dedup
    RiderStatus to = cmd.targetStatus();
    int n = repo.transition(cmd.riderId(), Transitions.allowedFrom(to), to);
    if (n == 0) throw new IllegalTransitionException(cmd);
    outbox.add(new RiderAccountStatusChanged(cmd.riderId(), to, repo.statusVersion(cmd.riderId())));
}""", cx="O(1).",
    fail=[F("Concurrent edits", "409 on version", "One edit rejected", "Client refetches and reapplies", "No lost update"), F("Duplicate restrict command", "processed_commands hit", "None", "Ignored", "Single transition"),
          F("Illegal transition (delete while restricted with balance)", "IllegalTransition", "Command rejected", "Caller settles balance first", "None")],
    alts=[["Last-write-wins edits", "Rejected", "Silent lost updates from support", "Single-editor fields"], ["Event-sourced profile", "Rejected", "Overkill for CRUD", "If full history needed for audit"]],
    adrs=[A("Status owned here, changed via commands", "I", "Multiple domains want to block riders.", [("Each domain keeps its own block flag", "Rejected: inconsistent"), ("Central status via commands", "Chosen")], "Commands with reasons; one status.", "Single truth, auditable reasons.", "Status reasons multiplex (need a reasons list).", "If multiple concurrent restrictions need tracking → restrictions table with active set.")],
    qa=[Q("Data modeling", "Two different teams restrict a rider for different reasons; one lifts theirs. Is the rider unrestricted?", "With a single status column, yes, which is wrong. The robust design keeps a `rider_restrictions(rider_id, source, reason, active)` table, and status RESTRICTED holds while any restriction is active. Lifting one restriction only clears that source's row. Phase II adopts this once Support and Risk both restrict.", "A single column is fine while only one team restricts.")],
    tests=[T("Unit", "ACTIVE → DELETED directly", "Rejected"), T("Concurrency", "Parallel edits", "Exactly one 200"), T("Integration", "Restrict → ride request", "ACCOUNT_RESTRICTED")],
    evo=["I: Table + transition table + in-process status reads", "E: Restrictions table with multiple sources; cache", "E: Status events via outbox; consumers cache status", "E: In Rider service; gRPC summary endpoint", "U: No change needed", "R: Regional rows; global status replicated for cross-region requests"],
    ideas={"now": ["Restrictions table early if two teams restrict"], "next": ["Self-service appeal for restrictions"], "adv": ["Status as CRDT across regions"], "rej": ["Hard delete without tombstone"]})

sub(id="saved-places", comp="rider-profile", name="Saved Places", phase="I", cat="Domain · CRUD",
    resp="Let riders save, label and reuse locations (home, work, favourites) with geocoded coordinates.",
    inp="place create/update/delete, geocoder results", out="place list for pickup/destination suggestions", deps="Maps gateway (geocoding)", cons="Rider app, Ride Request (destination shortcut)", own="saved_places",
    problem="Typing addresses is slow and error-prone. Saved places speed up booking and improve pickup accuracy.",
    without="Repeated geocoding costs and worse pickup accuracy.", guar=["≤ 1 Home and ≤ 1 Work per rider", "≤ 20 places", "Coordinates stored with source and accuracy"], nong=["Addresses stay valid forever (re-geocode on staleness)"],
    usecase="Ana saves 'Home' as a pin on her building's side gate. Every ride home uses the exact pin instead of the geocoder's street centroid.",
    derive="- Store the coordinate the user confirmed, not just the address string. The pin is the source of truth.\n- Uniqueness of Home/Work is an invariant, enforced with a partial unique index.\n- Places are personal location data (sensitive), so they must be erasable and excluded from analytics unless aggregated.",
    conc="Partial unique index on (user_id, label) where label in ('HOME','WORK'); concurrent creates resolve via constraint.", consistency="Strong, single row.", idem="Create with client-generated id (UUID) → `ON CONFLICT (id) DO NOTHING`.",
    order="Single-writer (the rider); last update wins with version check.", restart="Stateless service.", scale="≈5 rows/rider; trivial.",
    arch="CRUD service with validation (count limit, label uniqueness) and asynchronous enrichment (reverse-geocode the pin to a display address if not provided).",
    modules=[["PlaceService", "CRUD + limits"], ["PlaceEnricher", "Reverse geocode for display string"]],
    d_arch=("""flowchart LR
  APP["Rider app"] --> PS["PlaceService"] --> DB[("saved_places")]
  PS -->|async| EN["PlaceEnricher"] --> MG["Maps gateway"]""", "Saving is fast. Enrichment happens asynchronously."),
    d_seq=("""sequenceDiagram
  participant A as App
  participant P as PlaceService
  participant M as Maps
  A->>P: POST /places {id, label:HOME, lat, lng}
  P->>P: check limit and uniqueness
  P-->>A: 201
  P->>M: reverseGeocode(lat,lng) async
  M-->>P: "12 Rua X"
  P->>P: update display_address""", "Create, then enrich."),
    nostate="Places have no lifecycle beyond create/update/delete.",
    d_flow=("""flowchart LR
  PIN["confirmed pin"] --> DB[("saved_places")] --> SUG["booking suggestions"]
  DB -.->|never raw| AN["analytics"]""", "Exact places never flow to analytics. Only coarse aggregates do."),
    d_fail=("""flowchart TB
  G["geocoder down"] --> S["save with coordinates only; enrich later"]""", "Saving never depends on the geocoder."),
    sql="""CREATE TABLE rider.saved_places (
  id uuid PRIMARY KEY, user_id uuid NOT NULL, label text NOT NULL, custom_name text,
  lat double precision NOT NULL, lng double precision NOT NULL, display_address text, place_ref text,
  version int NOT NULL DEFAULT 0, updated_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX one_home_work ON rider.saved_places(user_id, label) WHERE label IN ('HOME','WORK');
CREATE INDEX places_by_user ON rider.saved_places(user_id);""",
    data="Deleted on erasure. No retention beyond account lifetime.", api="""GET /v1/riders/me/places -> [{id,label,name,lat,lng,address}]
POST /v1/riders/me/places {id,label,lat,lng,name?} -> 201 | 409 LABEL_TAKEN | 422 LIMIT_REACHED
PUT/DELETE /v1/riders/me/places/{id}""",
    mech=[("Client-generated ids", "Make create idempotent under retries without an idempotency-key table."), ("Limit check under concurrency", "`SELECT count(*) ... FOR UPDATE` on the rider's profile row serialises place creation per rider so the 20-limit holds.")],
    code="""@Transactional
public Place create(UUID rider, PlaceCmd c) {
    profiles.lockForUpdate(rider);
    if (repo.countByUser(rider) >= 20) throw new LimitReached();
    return repo.insertIgnoreConflict(c.toEntity(rider));
}""", cx="O(1).",
    fail=[F("Duplicate create retry", "Same id", "None", "Insert ignored, return existing", "Single row"), F("Geocoder failure", "Enricher error", "No display address", "Retry with backoff", "Coordinates intact")],
    alts=[["Store only place_id from provider", "Rejected", "Provider lock-in and ToS limits", "Never"], ["Client-side only storage", "Rejected", "Lost on reinstall", "Offline mode cache"]],
    adrs=[A("Pin coordinate is source of truth", "I", "Geocoded centroids are inaccurate for pickups.", [("Address string", "Rejected"), ("Pin + optional address", "Chosen")], "Store confirmed pin.", "Accurate pickups.", "Address display may lag.", "N/A")],
    qa=[Q("Privacy", "Can analytics use saved home locations to model demand?", "Not directly. Exact home locations are highly sensitive. Analytics receives places snapped to H3 resolution 7 (≈5 km²) with k-anonymity thresholds (cells with < 20 riders suppressed), and only for riders with analytics consent.", "Raw locations under access control still risks re-identification.")],
    tests=[T("Concurrency", "21 parallel creates", "Exactly 20 succeed"), T("Unit", "Second HOME", "409"), T("Privacy", "Erasure", "Places deleted")],
    evo=["I: CRUD table", "U: No change needed", "E: PlaceSaved event for personalization", "U: No change needed: part of Rider service", "E: Personalized pickup suggestions from places", "E: Regional storage"],
    ideas={"now": ["Pin confirmation UI"], "next": ["Suggest saving frequent destinations"], "adv": ["Shared family places"], "rej": ["Unlimited places"]})

sub(id="consent-preferences", comp="rider-profile", name="Consent & Preferences", phase="I", cat="Privacy · Compliance",
    resp="Record legally valid consents per purpose and store ride preferences, and expose the current state to every consumer that must honour it.",
    inp="grant/withdraw actions, terms versions, preference edits", out="current consent view, ConsentChanged events, preferences", deps="Privacy (purposes catalog)", cons="Notifications (marketing), Analytics, Driver app (preferences), Experimentation", own="consent_records, rider_preferences",
    problem="Marketing, data sharing and location-sharing uses require explicit, provable, withdrawable consent. Preferences must reach the driver.",
    without="Regulatory fines; marketing to users who opted out.", guar=["Every consent decision is an immutable record with terms version and source", "Withdrawal takes effect for marketing sends within 5 minutes", "Current state is derivable at any past time"], nong=["Consent for strictly necessary processing (not consent-based)"],
    usecase="Rider withdraws marketing consent in settings. A promo campaign running 3 minutes later skips them because the notification service checks the current consent view.",
    derive="- Legal proof needs history, so append-only records.\n- Consumers need fast current state, so a materialized 'current consent' view updated in the same transaction.\n- Withdrawal must propagate quickly, so events plus a check at send time, never only at segment time.",
    conc="Insert-only records; current view upserted with `WHERE recorded_at < new.recorded_at` to tolerate out-of-order client submissions.", consistency="Strong in store; consumers check synchronously at send time (Phase I–II) or via event-maintained cache with ≤ 5 min staleness (Phase III+).",
    idem="Client sends decision_id; duplicates ignored.", order="Decisions carry client timestamp + server receipt time. The latest server receipt wins, and the view upsert ignores older ones.",
    restart="All state is in PostgreSQL. A crash between insert and view upsert is impossible (one transaction), and consumers rebuild caches from ConsentChanged replay.", scale="Writes rare; reads at campaign send time can be large (millions), so a bulk consent check API with bitmap export for campaign targeting.",
    arch="Two tables: append-only `consent_records` and `consent_current` (one row per user × purpose), written in one transaction. Preferences are a JSON document validated against a schema.",
    modules=[["ConsentLedger", "Append-only decisions"], ["ConsentView", "Current state per purpose"], ["PreferenceService", "Validated JSON prefs"], ["BulkCheck", "Campaign-scale lookups"]],
    d_arch=("""flowchart LR
  APP["Settings"] --> CL["ConsentLedger"] --> R[("consent_records")]
  CL --> CV["ConsentView"] --> V[("consent_current")]
  NOTIF["Notifications"] -->|check at send| CV
  CL -->|ConsentChanged| EV["events"]""", "Records plus current view, both written together."),
    d_seq=("""sequenceDiagram
  participant A as App
  participant C as ConsentLedger
  participant N as Notifications
  A->>C: POST /consents {purpose: marketing, granted:false}
  C->>C: insert record + upsert current (tx)
  C-->>A: 200
  N->>C: isAllowed(user, marketing)?
  C-->>N: false""", "Withdrawal and an enforcement check."),
    nostate="Consent per purpose is a two-valued current state (granted/withdrawn) derived from records. The history table is the real model.",
    d_flow=("""flowchart LR
  D["decision"] --> R[("records")] --> V[("current")] --> CON["consumers"]
  R --> AUD["audit export"]""", "History serves audit. The view serves enforcement."),
    d_fail=("""flowchart TB
  C["consent service down at send time"] --> F["fail closed: skip marketing send"]""", "Marketing fails closed. Transactional messages (receipts) don't need consent."),
    sql="""CREATE TABLE rider.consent_records (id uuid PRIMARY KEY, user_id uuid NOT NULL, purpose text NOT NULL,
  granted boolean NOT NULL, terms_version text NOT NULL, source text NOT NULL, recorded_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE rider.consent_current (user_id uuid, purpose text, granted boolean NOT NULL, recorded_at timestamptz NOT NULL, PRIMARY KEY(user_id, purpose));
CREATE TABLE rider.rider_preferences (user_id uuid PRIMARY KEY, prefs jsonb NOT NULL, version int NOT NULL DEFAULT 0);""",
    data="Records retained for the statute of limitations (e.g. 6 years) even after account deletion, minimised to user tombstone id + purpose + decision. Preferences deleted on erasure.",
    api="""GET  /v1/riders/me/consents -> [{purpose, granted, terms_version, recorded_at}]
POST /v1/riders/me/consents {decision_id, purpose, granted, terms_version}
internal: boolean isAllowed(UUID user, Purpose p);  BitSet allowedAmong(List<UUID> users, Purpose p)
event ConsentChanged{user_id, purpose, granted, recorded_at}""",
    mech=[("Append-only ledger + materialized view", "The ledger proves past consent. The view gives O(1) checks. Writing both in one transaction keeps them consistent."), ("Fail-closed enforcement", "Marketing sends require a positive check, so an outage means no marketing, which is the legally safe failure.")],
    code="""@Transactional
public void record(UUID user, ConsentDecision d) {
    if (!records.insertIfNew(d)) return;
    current.upsertIfNewer(user, d.purpose(), d.granted(), d.recordedAt()); // WHERE consent_current.recorded_at < EXCLUDED.recorded_at
}""", cx="O(1).",
    fail=[F("Out-of-order decisions from offline client", "Older timestamp", "None", "View upsert ignores older", "Latest decision holds"), F("Consumer cache stale", "Event lag", "Marketing within 5 min of withdrawal", "Send-time check for marketing", "Bounded staleness")],
    alts=[["Third-party consent management platform", "Viable", "Faster compliance", "Many jurisdictions"], ["Flags on profile", "Rejected", "No proof", "Never"]],
    adrs=[A("Check at send time, not just at segmentation", "I", "Campaign segments are built hours earlier.", [("Segment-time only", "Rejected"), ("Send-time check", "Chosen")], "Notification service checks consent per send (bulk).", "Withdrawal honoured promptly.", "Extra lookups at send.", "N/A")],
    qa=[Q("Compliance", "Why keep consent records after the user is deleted?", "To defend against claims that marketing was sent without consent. Records are minimised to a pseudonymous tombstone id, purpose, decision and timestamp, with retention documented as a legal obligation.", "Deleting everything removes proof.")],
    tests=[T("Unit", "Grant then older withdraw arrives", "Remains granted"), T("Integration", "Withdraw then campaign", "No send"), T("Load", "Bulk check 1M users", "< 30 s via bitmap export")],
    evo=["I: Records + current view", "E: Bulk check API for campaigns", "E: ConsentChanged events; consumer caches", "U: No change needed: inside Rider service", "E: Consent bitmap exported to experimentation/analytics", "R: Jurisdiction-specific purposes per region"],
    ideas={"now": ["Purpose catalog owned by Privacy"], "next": ["Consent receipts emailed"], "adv": ["IAB TCF integration for ads"], "rej": ["Pre-ticked consents"]})
