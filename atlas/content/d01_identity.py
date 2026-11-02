from model import comp, sub, A, Q, F, T

# ======================================================================= Identity & Authentication
comp(id="identity", domain="identity", name="Identity & Authentication", tag="Security · Core", phase="I", kind="Logical component → deployable service (Phase IV)",
     biz="Lets riders and drivers sign up and sign in with a phone number, keeps them signed in safely across devices, and lets them recover access.",
     eng="Produces a verified principal (user id, roles, device, auth strength) for every request and manages the full credential lifecycle: OTP, tokens, sessions, devices, recovery and federation.",
     deploy="Module `identity` in the Phase I monolith; independent service with its own DB from Phase IV (on every request's path, strict SLO).",
     data_own="users, contact_points, otp_challenges, sessions, refresh_tokens, devices, recovery_cases, federated_links, signing keys (via KMS).",
     up=["notifications", "risk-fraud", "service-runtime"], down=["api-gateway", "rider-profile", "driver-onboarding", "authz", "support"], ext=["SMS OTP providers", "Apple / Google sign-in", "KMS/HSM"],
     interfaces="REST: `/v1/auth/otp`, `/v1/auth/otp/verify`, `/v1/auth/token/refresh`, `/v1/auth/logout`, `/v1/devices`; JWKS endpoint for token verification; events `UserRegistered`, `SessionRevoked`.",
     problem="Mobile users have no password and change devices and networks constantly. Attackers have phone-number lists, SIM-swap capability and bots. The platform must know who is calling on every request, in under a millisecond of verification cost, without a central lookup that becomes a bottleneck or outage point.",
     fr=["Register/sign in via phone OTP (email as secondary)", "Issue short-lived access tokens and rotating refresh tokens", "List and revoke sessions/devices", "Recover account when phone number is lost", "Sign in with Apple/Google (Phase IV)", "Step-up verification for risky actions (payout change)"],
     nfr=["Token verification at gateway: local, < 1 ms, no network call", "OTP send p95 < 3 s; verify p95 < 150 ms", "Availability 99.95% (Phase II) → 99.99% (Phase IV)", "Revocation effective within access-token TTL (≤ 10 min) and immediately for high-risk revokes", "OTP brute force: ≤ 5 attempts per challenge, ≤ 10 sends/number/day"],
     workload="Phase I: ~50 logins/day; Phase IV: ~300K token refreshes/hour; Phase VI: ~10M sessions active, 5K refresh/s peak; verification at every API call (≈50K req/s Phase V).",
     success="Every request carries a verifiable principal; account takeover rate stays below target; legitimate users rarely see friction.",
     failure="Account takeover, users locked out, gateway unable to verify tokens (total outage), OTP costs exploded by SMS pumping fraud.",
     derive="**Data:** a stable internal `user_id` separate from contact points (phone numbers get recycled by carriers), a record of each challenge, and a record of each long-lived session.\n\n**Operations:** challenge → verify → mint tokens; refresh; revoke; recover.\n\n**Invariants:** a verified contact point maps to at most one active user; a refresh token is usable once (rotation); a revoked session can never mint new access tokens.\n\n**Concurrency:** two devices verifying the same challenge, or two refreshes racing with the same refresh token, must resolve deterministically. **Scaling:** verification must be stateless (signed JWT) because it runs on every request. Issuance can be stateful because it is rare. **Security boundary:** signing keys never leave KMS, and the gateway only holds public keys.",
     owns=["Credentials and authentication factors", "User identifiers and contact-point uniqueness", "Sessions, refresh tokens, device registry", "Token signing and JWKS publication", "Account recovery cases"],
     not_owns=["Profile data (name, photo) → Rider Profile / Driver Onboarding", "Permissions model → Authorization", "Fraud decisions → Risk & Fraud (identity asks for a risk score)", "Message delivery → Notifications"],
     sync=["OTP request/verify", "Token refresh", "Session revoke", "JWKS fetch"], **{"async": ["`UserRegistered` event to profile modules", "OTP SMS via notification queue (Phase II)", "Session cleanup jobs", "Risk signals to fraud"]},
     boundary_why="Identity owns *who you are*. Profile owns *what you told us about yourself*. Splitting them lets profile data be deleted or edited without touching credentials, and keeps the security-critical surface small and auditable.",
     hld=("""flowchart LR
  APP["App"] -->|POST /auth/otp| OTP["OTP challenge mgr"]
  OTP -->|send code| NQ["Notification channel"]
  APP -->|POST /auth/otp/verify| OTP
  OTP -->|verified contact| UR["User registry"]
  UR --> TS["Token service"]
  TS -->|sign via| KMS[("KMS keys")]
  TS --> SR["Session & device registry"]
  APP -->|refresh| TS
  GW["API gateway"] -->|JWKS cache| TS
  REC["Account recovery"] --> UR & SR
  FED["Federation adapter (P4)"] --> UR
  UR & SR --> DB[("identity schema")]""",
          "Challenge, verify, mint. The OTP manager proves control of a contact point. The user registry maps it to a stable user. The token service mints a short access JWT plus a refresh token bound to a session row. The gateway verifies JWTs locally using cached public keys. Recovery and federation are alternative ways to prove identity, and they end in the same session-minting path."),
     seq=("""sequenceDiagram
  participant App
  participant ID as Identity
  participant N as Notifications
  participant DB as identity DB
  App->>ID: POST /v1/auth/otp {phone, device_id}
  ID->>ID: rate limit (number, device, IP)
  ID->>DB: insert otp_challenge (hash(code), expires +5m)
  ID->>N: send SMS (template OTP)
  ID-->>App: 202 {challenge_id}
  App->>ID: POST /v1/auth/otp/verify {challenge_id, code}
  ID->>DB: UPDATE challenge SET attempts+1 WHERE id AND status=PENDING
  alt code matches
    ID->>DB: upsert user by phone, insert session + refresh token
    ID-->>App: 200 {access_jwt(10m), refresh(30d)}
  else wrong or expired
    ID-->>App: 401 {attempts_left}
  end""", "The complete sign-in path. Rate limits run before any cost is incurred (SMS). The verify step increments attempts atomically, so parallel guesses cannot exceed the limit."),
     state=("""stateDiagram-v2
  [*] --> Unverified: first OTP sent
  Unverified --> Active: OTP verified
  Active --> Locked: risk lock / too many failures
  Locked --> Active: recovery completed
  Active --> Suspended: policy restriction
  Suspended --> Active: appeal accepted
  Active --> Deleted: erasure request
  Deleted --> [*]""", "Identity-level account states. Business restrictions (e.g. a driver being deactivated) live in their owning domains. Identity only tracks whether authentication is allowed at all."),
     subdeps=[("otp-auth", "token-service"), ("token-service", "session-registry"), ("account-recovery", "otp-auth"), ("account-recovery", "session-registry"), ("identity-federation", "token-service")],
     flow="**End to end:** a request enters the OTP manager, is rate-limited, persisted as a hashed challenge and sent through Notifications. Verification resolves the user, then the token service creates a session row and returns tokens. Every later API call is verified at the gateway without contacting Identity. Refresh returns to Identity at most every 10 minutes per device. Errors are typed (`OTP_EXPIRED`, `OTP_LOCKED`, `REFRESH_REUSED`) and do not reveal whether a number is registered.",
     data="**Entities:** `users(id, status)`, `contact_points(user_id, type, value_normalized, verified_at)` unique on active value, `otp_challenges`, `sessions`, `refresh_tokens(family_id)`, `devices`, `recovery_cases`, `federated_links`.\n\n**Transactions:** verify + user upsert + session insert are one transaction. **Retention:** challenges deleted after 24 h; sessions 90 days after expiry; audit of auth events 1 year. **Privacy:** phone stored normalized (E.164) and encrypted, with a keyed hash (HMAC) column for lookup. **Partitioning:** none until Phase V. Then sessions are hash-partitioned by user_id, and in Phase VI the global directory holds users and contact points while sessions stay regional.",
     er="""erDiagram
  USERS ||--o{ CONTACT_POINTS : has
  USERS ||--o{ SESSIONS : has
  SESSIONS ||--o{ REFRESH_TOKENS : rotates
  USERS ||--o{ DEVICES : uses
  SESSIONS }o--|| DEVICES : on
  USERS ||--o{ RECOVERY_CASES : opens
  USERS ||--o{ FEDERATED_LINKS : links""",
     rel=[["Timeouts", "SMS provider 3 s; DB 500 ms; KMS sign 200 ms with local signing-key cache (envelope: KMS-wrapped key held in memory)."], ["Retries", "OTP send retried once on a secondary provider (Phase II). Verify is never retried server-side."],
          ["Idempotency", "OTP request is idempotent per (phone, device) within 30 s and returns the same challenge. Refresh is idempotent within a 10 s grace window."], ["Degradation", "If Identity is down, existing access tokens keep working until expiry. Only new logins and refreshes fail."],
          ["Recovery", "Sessions and refresh tokens are in PostgreSQL. A JWKS cache at the gateway with stale-if-error lets it survive a 24 h Identity outage."]],
     sec=[["Authentication boundary", "Gateway verifies JWT (RS256/ES256), issuer, audience, expiry, `kid`."], ["Secrets", "Signing keys in KMS/HSM; rotated every 90 days with overlapping JWKS publication."],
          ["Abuse", "SMS pumping protection: per-prefix budgets, risk score before send, CAPTCHA/attestation (Play Integrity/App Attest)."], ["Threats", "SIM swap → step-up on carrier-change signal; token theft → short TTL + refresh rotation reuse detection; enumeration → uniform responses."],
          ["Audit", "Every auth event (login, refresh reuse, revoke, recovery) appended to an immutable audit log."]],
     adrs=[A("Stateless JWT access tokens + stateful rotating refresh tokens", "I", "Verification on every call vs. ability to revoke.",
             [("Opaque tokens with central introspection", "Rejected: introspection call on every request is a scaling bottleneck and an availability coupling."), ("Long-lived JWT only", "Rejected: unrevocable."), ("Short JWT + rotating refresh", "Chosen")],
             "Access JWT TTL 10 min; refresh token 30 days, single-use with family-based reuse detection.", "Local verification; revocation bounded by 10 min; theft of refresh token detected on reuse.",
             "Revocation is not instant. High-risk revocations push a deny-list entry (session id) to gateways (Phase II).", "If regulatory needs demand instant revocation everywhere, add a gateway deny-list stream (already designed) or shorten TTL.")],
     qa=[Q("Security", "How do you stop an attacker who stole a refresh token?",
           "Refresh tokens rotate on every use and belong to a *family* (one per session). When a token is used, it is marked used and a new one is issued. If a used token is presented again, either the attacker or the legitimate client is replaying it. Identity revokes the entire family (session), forcing re-login, and emits a `SessionRevoked` risk signal. The legitimate user loses at most one session, and the attacker's window is bounded by the first reuse.",
           "Binding tokens to device keys (DPoP / app attestation) also prevents use on another device but adds client complexity. It is introduced in Phase IV for drivers.", "Phase I: rotation + reuse detection. Phase IV: device-bound tokens for drivers. Phase VI: same, regional session stores."),
         Q("Global architecture", "Phone numbers must be unique worldwide but sessions should be regional. How?",
           "Split the data. `users` and `contact_points` move to a global directory with a single writer for uniqueness: a consensus-backed store (Spanner/CockroachDB) or a reservation protocol where the number's home region owns the uniqueness claim. Sessions, refresh tokens and OTP challenges stay in the region where the user signed in, because only that region needs them. Access-token verification uses globally replicated public keys.",
           "Eventual uniqueness with conflict resolution would allow two accounts per number for a while, which breaks recovery and fraud controls.", "Before Phase VI: one database, uniqueness is a unique index.")],
     impl_order=["contact normalization + users table", "otp-auth", "token-service + JWKS", "session-registry", "gateway verification filter", "account-recovery", "identity-federation (Phase IV)"],
     pkg="""com.atlas.identity
├── api          (AuthController, DeviceController, JwksController)
├── otp          (OtpService, OtpChallenge, OtpRepository, RateLimitPolicy)
├── token        (TokenService, JwtSigner, RefreshTokenRepository)
├── session      (SessionService, DeviceRegistry)
├── recovery     (RecoveryWorkflow)
├── federation   (OidcAdapter)  // Phase IV
└── events       (UserRegistered, SessionRevoked)""",
     impl_notes="Use Spring Security's resource-server support at the gateway, and a custom `TokenService` for issuance. All endpoints return the same error shape: `{code, message, retry_after?}`.",
     tests=[T("Concurrency", "50 parallel verifies with the right code on one challenge", "Exactly one session created; others get OTP_CONSUMED"), T("Security", "Refresh token reused after rotation", "Whole family revoked; audit event emitted"),
            T("Load", "2× expected peak refresh rate", "p95 < 100 ms, no DB connection exhaustion"), T("Failure", "KMS unavailable 10 min", "Signing continues with cached data key; alert fires")],
     evo=[("I", "Module in monolith; PostgreSQL; JWT + rotating refresh", "identity schema; SMS sync call", "Unique indexes, atomic attempt counter", "Correctness from day one"),
          ("E", "Same module; 2+ instances", "OTP send via queue; Redis rate limits; secondary SMS provider", "Breakers on SMS; gateway deny-list for urgent revokes", "Provider outages and SMS fraud"),
          ("E", "Same module", "Emits `UserRegistered`/`SessionRevoked` via outbox", "Idempotent consumers in profile/risk", "Multiple consumers of identity events"),
          ("R", "Extracted Identity service + federation", "Own DB; CDC; gRPC for internal lookups", "mTLS; device-bound tokens for drivers; 99.99% SLO", "Every request depends on it; separate ownership"),
          ("E", "Partitioned session store", "Sessions hash-partitioned; JWKS via CDN", "Risk-driven step-up", "≈5K refresh/s, bot pressure"),
          ("R", "Global directory + regional session stores", "Users/contact points global (consensus); sessions regional", "Region failover: users re-login in DR region if sessions not replicated", "Multi-region uniqueness and residency")],
     ideas={"now": ["Uniform error responses to block enumeration: cheap and important."], "next": ["Passkeys (WebAuthn) as an SMS alternative, cutting SMS cost and SIM-swap risk."],
            "adv": ["Continuous authentication from behavioural signals (typing/motion): high false-positive risk."], "rej": ["Passwords for riders: support burden and credential-stuffing surface without benefit over OTP+passkeys."]})

sub(id="otp-auth", comp="identity", name="OTP Authentication & Contact Verification", phase="I", cat="Security · Authentication",
    resp="Prove that the caller controls a phone number or email by sending a one-time code, and verify it under strict attempt and rate limits.",
    inp="phone/email, device id, client attestation, risk score", out="verified contact point → user_id, or a typed failure", deps="Notifications (SMS/email), Risk & Fraud (score), Redis (rate limits, Phase II)",
    cons="Token service, Account recovery, Driver onboarding (re-verify phone)", own="otp_challenges, contact_points.verified_at",
    problem="Users need to authenticate without passwords. The system must prove control of a contact point while resisting brute force, enumeration, SMS-pumping fraud and race conditions.",
    without="Either passwords (support load, credential stuffing) or unverified phone numbers (fake accounts, payment fraud, impossible recovery).",
    guar=["A code is valid for one challenge, at most 5 attempts, at most 5 minutes", "A challenge can be consumed at most once", "Responses do not reveal whether a number is registered", "Send rate per number/device/IP/prefix is bounded"],
    nong=["Does not prove the person is who they claim (KYC is driver onboarding)", "Does not protect against SIM swap by itself (needs risk signals)", "Delivery of the SMS is best-effort"],
    constraints="SMS cost ≈ $0.01–0.10 per message; carrier delivery 2–30 s; codes are 6 digits (10^6 space).",
    usecase="Priya installs the app, enters +91 98…, receives 482913, enters it within 40 s and is signed in. A bot hammering 10,000 numbers on the +882 premium prefix is cut off by the prefix budget after 20 sends.",
    derive="- Codes must be unguessable within the attempt budget. With 6 digits and 5 attempts, a guess succeeds with probability 5×10⁻⁶, which is acceptable.\n- The code must never be stored in plaintext, because a DB leak would allow logins. Store `HMAC(server_key, challenge_id||code)`.\n- Attempts must be counted atomically. Otherwise parallel guesses bypass the limit, which needs a conditional UPDATE.\n- Sends cost money, so rate limits must run *before* the send and be enforced across instances, which means a shared counter.",
    conc="Verification is `UPDATE otp_challenges SET attempts = attempts + 1 WHERE id = ? AND status = 'PENDING' AND attempts < 5 AND expires_at > now() RETURNING code_hash`. The row lock serialises parallel verifies. The successful verify then sets `status='CONSUMED'` in the same transaction as the session creation, so only one session is ever created.",
    consistency="Strong (single-row ACID) for the challenge. Rate-limit counters are approximate (Redis INCR with TTL), and occasional over-admission by one or two is acceptable.",
    idem="`POST /otp` with the same (phone, device) inside 30 s returns the existing challenge instead of sending a new SMS. Verify is not idempotent by design: a second verify of a consumed challenge returns `OTP_CONSUMED`, and the client then uses the tokens it already has.",
    order="SMS can arrive after the user requested a second code. Only the latest challenge for (phone, device) stays PENDING, older ones are marked SUPERSEDED, so a late old code fails with a clear message.",
    restart="All state is in PostgreSQL (challenge) and Redis (counters). After a crash, a pending challenge is still verifiable until expiry. Lost Redis counters reset limits, which is acceptable because the per-challenge attempt limit is in the DB.",
    scale="Writes are tiny (≈1 row per login). The bottleneck is SMS provider throughput and cost, not compute. Partition by user region in Phase VI. Rate-limit keys are naturally sharded in Redis Cluster.",
    arch="Synchronous REST handler inside Identity: **RateLimitPolicy → RiskCheck → ChallengeStore → CodeSender** for send, and **ChallengeStore.atomicAttempt → constant-time compare → consume + mint** for verify.\n\nCodes are generated with `SecureRandom`. The HMAC key lives in KMS-wrapped memory. In Phase I sending is a synchronous call to the notification module. From Phase II it is enqueued with high priority and the API returns 202 immediately.",
    modules=[["RateLimitPolicy", "Per-number (5/h,10/day), per-device, per-IP, per-country-prefix budgets"], ["ChallengeStore", "Create, supersede, atomic attempt, consume"], ["CodeGenerator", "SecureRandom 6-digit, HMAC hashing"], ["CodeSender", "Template rendering; channel choice (SMS, WhatsApp, voice fallback)"], ["VerifyHandler", "Constant-time compare; consume; hand off to Token service"]],
    d_arch=("""flowchart LR
  C["Client"] -->|POST /otp| RL["RateLimitPolicy"]
  RL -->|INCR keys| R[("Redis")]
  RL --> RK["Risk check"]
  RK --> CS["ChallengeStore"] --> PG[("otp_challenges")]
  CS --> SND["CodeSender"] -->|enqueue| NQ[["notifications queue"]]
  C -->|POST /otp/verify| VH["VerifyHandler"] --> CS
  VH -->|verified user_id| TS["Token service"]""", "Rate limits and risk run before anything costly. Only the ChallengeStore touches the challenge table, and verification hands off to the Token service on success."),
    d_seq=("""sequenceDiagram
  participant C as Client
  participant V as VerifyHandler
  participant DB as PostgreSQL
  participant T as TokenService
  C->>V: verify(challenge_id, code)
  V->>DB: UPDATE attempts+1 WHERE PENDING AND attempts<5 RETURNING code_hash
  alt no row
    V-->>C: 401 OTP_EXPIRED_OR_LOCKED
  else hash matches (constant time)
    V->>DB: UPDATE status=CONSUMED, upsert user/contact
    V->>T: mintSession(user_id, device)
    T-->>V: tokens
    V-->>C: 200 tokens
  else mismatch
    V-->>C: 401 OTP_INVALID attempts_left
  end""", "Verification path. The atomic UPDATE is the concurrency control: no row returned means expired, consumed or locked, and the client gets one generic code."),
    d_state=("""stateDiagram-v2
  [*] --> PENDING: send
  PENDING --> CONSUMED: correct code
  PENDING --> LOCKED: 5 wrong attempts
  PENDING --> EXPIRED: 5 min elapsed
  PENDING --> SUPERSEDED: newer challenge for same phone+device
  CONSUMED --> [*]
  LOCKED --> [*]
  EXPIRED --> [*]
  SUPERSEDED --> [*]""", "Challenge lifecycle. Every terminal state is final. A new code always means a new challenge."),
    d_flow=("""flowchart LR
  P["raw phone"] --> N["E.164 normalize"] --> H["HMAC lookup hash"]
  H --> RL["rate-limit keys"]
  N --> ENC["encrypt for storage"]
  CODE["SecureRandom code"] --> HC["HMAC(challenge,code)"] --> DB[("otp_challenges")]
  CODE --> SMS["SMS body (never logged)"]""", "The plaintext code exists only in memory and in the SMS body. It is never logged or persisted. Phone numbers are stored encrypted and looked up by keyed hash."),
    d_fail=("""flowchart TB
  S["send request"] --> P1{"SMS primary ok?"}
  P1 -->|yes| OK["202"]
  P1 -->|timeout or 5xx| BR["breaker counts failure"] --> P2{"secondary provider"}
  P2 -->|ok| OK
  P2 -->|fail| VO["offer voice/WhatsApp fallback"] --> OK2["202 with channel hint"]
  V["verify"] --> DBF{"DB available?"}
  DBF -->|no| E503["503 retry-after"]""", "Delivery failures fall back across providers and channels. A DB outage fails closed (503), never open."),
    sql="""CREATE TABLE identity.otp_challenges (
  id            uuid PRIMARY KEY,
  phone_hmac    bytea NOT NULL,
  device_id     text  NOT NULL,
  code_hash     bytea NOT NULL,
  status        text  NOT NULL CHECK (status IN ('PENDING','CONSUMED','LOCKED','EXPIRED','SUPERSEDED')),
  attempts      smallint NOT NULL DEFAULT 0,
  created_at    timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL
);
CREATE UNIQUE INDEX one_pending_per_device ON identity.otp_challenges (phone_hmac, device_id) WHERE status = 'PENDING';
CREATE INDEX otp_expiry ON identity.otp_challenges (expires_at) WHERE status = 'PENDING';""",
    data="One row per challenge. The partial unique index enforces 'one pending challenge per phone+device', so a new challenge must supersede the old one in the same transaction. Rows are purged after 24 h by a scheduled job. No partitioning needed until Phase VI (regional tables).",
    api="""POST /v1/auth/otp            {phone, channel?: "sms"|"voice"} -> 202 {challenge_id, resend_after_s}
POST /v1/auth/otp/verify     {challenge_id, code} -> 200 {access_token, refresh_token, user_id, is_new_user}
Errors: 429 OTP_RATE_LIMITED{retry_after} | 401 OTP_INVALID{attempts_left} | 401 OTP_EXPIRED_OR_LOCKED | 403 RISK_BLOCKED
Headers: X-Device-Id, X-Attestation (Play Integrity / App Attest token)""",
    api_notes="`is_new_user` tells the client to show onboarding. The same verify response is used for both registration and login, so there is no separate 'does this number exist' endpoint for attackers to enumerate.",
    mech=[("Atomic attempt counter", "A conditional UPDATE with RETURNING both increments and checks in one statement. PostgreSQL takes a row lock, so concurrent verifies serialise and the 6th attempt sees `attempts<5` false."),
          ("Keyed hashing (HMAC-SHA256)", "A plain hash of a 6-digit code is brute-forceable offline in milliseconds. Keying with a server secret makes a DB dump useless without the key."),
          ("Constant-time comparison", "`MessageDigest.isEqual` avoids leaking match prefixes via timing."), ("Sliding-window rate limits", "Redis `INCR` + `EXPIRE` per key for fixed windows. The daily cap uses a second key. Prefix budgets catch international revenue-share fraud.")],
    code="""@Transactional
public VerifyResult verify(UUID challengeId, String code, String deviceId) {
    Optional<byte[]> stored = repo.incrementAttempt(challengeId); // UPDATE ... RETURNING code_hash
    if (stored.isEmpty()) return VerifyResult.expiredOrLocked();
    byte[] candidate = hmac.sign(challengeId + ":" + code);
    if (!MessageDigest.isEqual(stored.get(), candidate)) {
        return VerifyResult.invalid(repo.attemptsLeft(challengeId));
    }
    repo.consume(challengeId);                 // status = CONSUMED
    UserId user = users.upsertVerifiedPhone(repo.phoneOf(challengeId));
    return VerifyResult.ok(tokenService.mintSession(user, deviceId));
}""",
    cx="O(1) per request; one indexed row read/write.",
    fail=[F("SMS provider outage", "Breaker open; delivery-receipt rate drops", "Users can't log in; existing sessions unaffected", "Failover to secondary provider; voice fallback", "None; challenge state unaffected"),
          F("Duplicate send taps", "Same (phone, device) within 30 s", "Extra SMS cost", "Return existing challenge", "None"),
          F("Parallel verify race", "Two requests same challenge", "Risk of double session", "Row lock + CONSUMED check", "Exactly one session"),
          F("DB outage", "Health check, 5xx", "New logins fail", "Fail closed; retry-after", "No partial state"),
          F("SMS pumping attack", "Spike in sends to premium prefixes; low conversion", "Cost burn", "Prefix budgets, attestation, risk block", "N/A")],
    alts=[["Magic links by email", "Secondary only", "Riders rarely check email mid-journey", "Desktop/business accounts"], ["TOTP authenticator apps", "Rejected for riders", "Too much friction", "Admin/ops staff (Authorization)"],
          ["Passkeys", "Next phase", "Cuts SMS cost and phishing", "Once device support > 90% of base"], ["Silent network auth (carrier APIs)", "Advanced", "Better UX, carrier dependent", "Markets with carrier support"]],
    adrs=[A("Store HMAC of code, not code or plain hash", "I", "DB compromise must not enable logins.", [("Plaintext", "Rejected"), ("SHA-256(code)", "Rejected: 10^6 space brute-forced"), ("HMAC with KMS key", "Chosen")],
            "HMAC-SHA256 with a KMS-managed key, rotated with a version prefix.", "Defeats offline brute force.", "Key loss invalidates in-flight challenges (≤5 min).", "If moving to provider-hosted verification (Twilio Verify), codes never touch our DB."),
          A("Synchronous send in Phase I, queued from Phase II", "II", "Request thread blocked on SMS latency.", [("Always sync", "Rejected at Phase II"), ("Queue with high priority", "Chosen")],
            "Enqueue to a dedicated high-priority notification queue; API returns 202.", "Isolates request threads from provider latency.", "Need delivery tracking to tell users when a send failed.", "If OTP send queue lag > 2 s p95.")],
    qa=[Q("Security", "How do you detect SMS pumping fraud (IRSF)?", "Track conversion (verified/sent) per country prefix and per number range in near real time. Legitimate traffic converts at about 70–90%, and pumping converts at about 0%. When conversion over a window drops below a threshold for a prefix, require attestation or CAPTCHA, then block. Daily per-prefix spend budgets cap the loss.", "Allow-listing countries is simple but blocks legitimate travellers.", "Phase V moves the conversion monitor to a streaming job with ML scores."),
        Q("Correctness", "A user requests a code, waits, requests another, then types the first code. What happens?", "The first challenge is SUPERSEDED when the second is created, so the first code fails with `OTP_EXPIRED_OR_LOCKED`. The client shows 'use the latest code'. This avoids two valid codes at once, which would double the guessing surface.", "Accepting any unexpired code is friendlier but raises the attacker's success probability."),
        Q("Privacy", "Should OTP codes appear in logs or traces?", "Never. The code is a credential. Logging filters redact `code` fields, SMS bodies are not logged by the notification service (only template id + message id), and traces carry the challenge id only.", "")],
    tests=[T("Unit", "Wrong code 5 times", "5th returns attempts_left=0; 6th returns OTP_EXPIRED_OR_LOCKED"), T("Concurrency", "20 parallel correct verifies", "One 200, nineteen 401"), T("Integration", "Send with primary SMS down", "Secondary used; 202"), T("Security", "Timing analysis of compare", "No statistically significant difference"), T("Load", "500 sends/s with 90% rate-limited", "Redis p99 < 5 ms; DB untouched for limited calls")],
    evo=["I: Sync SMS call; DB challenges; DB-based rate limit counters", "E: Redis rate limits; queued send; secondary provider", "E: Emits `ContactVerified`; risk score from fraud service before send", "E: Part of Identity service; attestation required for drivers", "E: Streaming pumping detection; passkeys offered", "E: Regional challenge stores; global contact-point uniqueness check via directory"],
    ideas={"now": ["Uniform response timing for send (registered vs not)"], "next": ["WhatsApp OTP in markets where it's cheaper and more reliable"], "adv": ["Carrier silent auth"], "rej": ["4-digit codes: 10× weaker for marginal UX gain"]})

sub(id="token-service", comp="identity", name="Token Service (JWT + Rotating Refresh)", phase="I", cat="Security · Token management",
    resp="Mint, rotate and revoke the access and refresh tokens that represent an authenticated session, and publish the public keys every verifier needs.",
    inp="verified user_id + device, refresh token, revoke commands", out="signed access JWT, refresh token, JWKS document, SessionRevoked events", deps="KMS, session registry, authorization (roles claim)",
    cons="API gateway, all services (claims), mobile apps", own="refresh_tokens, signing key metadata",
    problem="Every API request must be authenticated cheaply and without a central lookup, yet sessions must be revocable and stolen tokens containable.",
    without="Either a DB lookup on every request (bottleneck + outage coupling) or tokens that can never be revoked.",
    guar=["Access tokens expire within 10 minutes", "A refresh token can be redeemed once; reuse revokes the session family", "Verifiers can validate offline with published keys", "Key rotation never invalidates valid tokens"],
    nong=["Instant global revocation of access tokens (bounded by TTL unless deny-listed)", "Authorization decisions (claims are inputs, not decisions)"],
    usecase="A driver's phone is stolen. Support revokes the session: the refresh family is revoked, the session id is pushed to the gateway deny-list, and the thief's access token stops working within seconds.",
    derive="- Stateless verification requires asymmetric signatures (ES256). Verifiers need only the public key.\n- Revocation requires state somewhere, so keep it on the rare path (refresh) rather than the hot path (every request).\n- Refresh tokens are bearer secrets. Store only a hash, so a DB leak doesn't yield usable tokens.\n- Rotation with reuse detection turns a stolen token into a detectable event.",
    conc="Refresh is `UPDATE refresh_tokens SET used_at=now() WHERE token_hash=? AND used_at IS NULL RETURNING family_id`. Two concurrent refreshes with the same token: one wins. For the loser, if `used_at` is within a 10 s grace window and the request comes from the same device, return the same successor token (handles mobile retry races). Otherwise treat it as reuse and revoke the family.",
    consistency="Strong for refresh-token state (single primary). JWKS is eventually consistent: new keys are published 24 h before first use, so caches always have them.",
    idem="Refresh within the grace window from the same device is idempotent (returns the stored successor). Revoke is idempotent (revoking a revoked session is a no-op 204).",
    order="Revocation events to gateways may arrive late. The deny-list entry carries an expiry equal to max access TTL, so ordering doesn't matter: the union of entries is applied.",
    restart="Stateless apart from DB. Signing data keys are re-unwrapped from KMS on start, and if KMS is unavailable at boot the instance stays unready.",
    scale="Verification scales with gateway instances (CPU-only). Issuance at Phase VI is ≈5K refresh/s regionally, which hash-partitioned refresh_tokens handle easily.",
    arch="Spring service with **Signer** (ES256 via a KMS-wrapped data key cached in memory), **RefreshStore**, **RevocationPublisher** and a **JWKS endpoint** behind CDN caching.\n\nAccess JWT claims: `sub`, `sid` (session), `roles`, `amr` (auth methods), `acr` (strength), `iat`, `exp`, `kid`, `aud`, `region` (Phase VI).",
    modules=[["Signer", "ES256 signing with key versioning (`kid`)"], ["RefreshStore", "Hash-only storage, rotation, families"], ["RevocationPublisher", "Deny-list push to gateways (Redis pub/sub P2 → Kafka P3)"], ["JwksPublisher", "Current + next + previous keys"]],
    d_arch=("""flowchart LR
  APP["App"] -->|refresh| TS["TokenService"]
  TS --> RS["RefreshStore"] --> PG[("refresh_tokens")]
  TS --> SG["Signer"] -->|unwrap data key| KMS[("KMS")]
  TS --> RP["RevocationPublisher"] -->|deny sid| GW["Gateways"]
  GW -->|GET /.well-known/jwks.json| JW["JwksPublisher"]""", "The signer holds a data key unwrapped from KMS, so signing never makes a network call per token. Gateways pull JWKS and receive deny-list pushes."),
    d_seq=("""sequenceDiagram
  participant A as App
  participant T as TokenService
  participant DB as refresh_tokens
  A->>T: POST /token/refresh {rt}
  T->>DB: UPDATE used_at=now() WHERE hash=h(rt) AND used_at IS NULL RETURNING family
  alt updated
    T->>DB: INSERT successor (same family)
    T-->>A: 200 {access, refresh'}
  else already used within grace and same device
    T-->>A: 200 {stored successor}
  else reuse
    T->>DB: revoke family
    T-->>A: 401 REFRESH_REUSED
  end""", "Rotation path with grace-window handling for legitimate mobile retry races."),
    d_state=("""stateDiagram-v2
  [*] --> Issued
  Issued --> Used: redeemed once
  Used --> FamilyRevoked: reused outside grace
  Issued --> Expired: 30 days
  Issued --> FamilyRevoked: logout or admin revoke
  FamilyRevoked --> [*]
  Expired --> [*]""", "A refresh token's lifecycle. Revocation is per family, meaning per session."),
    d_flow=("""flowchart LR
  U["user_id, roles, device"] --> C["claims builder"] --> S["sign ES256"] --> AT["access JWT"]
  R["random 256-bit"] --> H["SHA-256"] --> DB[("refresh_tokens")]
  R --> RT["refresh token to client"]""", "Raw refresh tokens exist only on the client. The server stores only a SHA-256 hash, which is sufficient for a 256-bit random secret."),
    d_fail=("""flowchart TB
  K{"KMS reachable?"} -->|no, key cached| OK["keep signing with cached data key"]
  K -->|no, cold start| NR["instance not ready"]
  D{"DB down"} --> RF["refresh fails 503; access tokens still valid ≤10m"]
  L["signing key compromised"] --> ROT["emergency rotate; publish new kid; revoke old kid in JWKS"]""", "Failures degrade to 'no new tokens' and never to 'accept unverified tokens'."),
    sql="""CREATE TABLE identity.refresh_tokens (
  token_hash   bytea PRIMARY KEY,
  family_id    uuid NOT NULL REFERENCES identity.sessions(id),
  device_id    text NOT NULL,
  successor_hash bytea,
  issued_at    timestamptz NOT NULL DEFAULT now(),
  used_at      timestamptz,
  expires_at   timestamptz NOT NULL
);
CREATE INDEX rt_family ON identity.refresh_tokens(family_id);""",
    data="One row per issued refresh token. `successor_hash` supports the grace-window replay. Expired rows are purged daily. Phase V: hash-partition by family_id.",
    api="""POST /v1/auth/token/refresh {refresh_token} -> 200 {access_token, refresh_token, expires_in}
POST /v1/auth/logout   (Bearer)       -> 204   // revokes current session family
GET  /.well-known/jwks.json           -> {keys:[{kid, kty:EC, crv:P-256, x, y}]}  Cache-Control: max-age=3600
Event SessionRevoked {session_id, user_id, reason, revoked_at, deny_until}""",
    mech=[("Refresh-token family reuse detection", "All tokens of a session share family_id. Redeeming marks the token used and links a successor. Presenting a used token outside the grace window proves duplication, so the whole family is revoked."),
          ("Key rotation with overlap", "Keys move through next → current → previous. JWKS publishes all three. Tokens are signed with current, verifiers accept any published kid, and a key is removed only after max token TTL has passed."),
          ("Deny-list for urgent revocation", "Gateways hold a set of revoked session ids with TTL = access TTL. Checking is O(1) in-memory.")],
    code="""public TokenPair refresh(String raw, String deviceId) {
    byte[] h = sha256(raw);
    return tx.execute(s -> repo.markUsed(h)
        .map(fam -> issue(fam, deviceId, h))
        .orElseGet(() -> repo.findUsed(h)
            .filter(t -> t.deviceId().equals(deviceId) && t.usedAt().isAfter(now().minusSeconds(10)))
            .map(t -> reissueSuccessor(t))
            .orElseThrow(() -> { revokeFamilyOf(h); return new RefreshReusedException(); })));
}""", cx="O(1); one PK lookup + one insert.",
    fail=[F("Refresh token stolen and used first by attacker", "Legitimate client later presents used token", "Attacker had ≤ access TTL of access", "Family revoked; user re-logs in", "Session closed consistently"),
          F("Mobile retry after timeout", "Same token twice within grace from same device", "None", "Return stored successor", "Single successor"),
          F("KMS outage", "Unwrap errors", "New instances can't start", "Warm instances keep cached key; scale-in paused", "None"),
          F("Clock skew on verifiers", "Tokens rejected as not yet valid", "Spurious 401s", "30 s leeway on nbf/iat", "None")],
    alts=[["Opaque tokens + introspection", "Rejected", "Lookup on every request", "Very small internal tools"], ["PASETO", "Viable", "Safer defaults, less tooling", "If JWT library misuse becomes a problem"], ["Sessions in cookies", "Rejected", "Mobile apps", "Web admin portal"]],
    adrs=[A("ES256 over RS256", "I", "Token size and signing cost.", [("RS256", "Larger tokens"), ("ES256", "Chosen"), ("HS256", "Rejected: shared secret at every verifier")], "ES256 with KMS-held keys.", "Small signatures; public verification.", "Some legacy libraries weaker ECDSA support.", "If FIPS/HSM constraints require RSA.")],
    qa=[Q("Correctness", "Why is a 10-second grace window safe?", "The grace window applies only to the same device and returns the *same* stored successor. It doesn't mint a new branch. An attacker on another device can't use it, and an attacker on the same device already controls the session. It removes false positives from mobile network retries, which would otherwise log users out randomly.", "No grace window means occasional forced logouts. A longer window widens the replay race.")],
    tests=[T("Unit", "Rotate then reuse old token after 11 s", "401 and family revoked"), T("Concurrency", "Two parallel refreshes same token same device", "Both get identical successor"), T("Security", "Token signed with removed kid", "Rejected by gateway"), T("Recovery", "Kill instance during refresh", "Client retry within grace succeeds")],
    evo=["I: JWT ES256 + rotating refresh in PostgreSQL", "E: Gateway deny-list via Redis pub/sub", "E: SessionRevoked on Kafka; consumers in risk/support", "E: Device-bound tokens (DPoP) for drivers; JWKS via CDN", "E: Partitioned refresh store", "E: Regional issuers with region claim; global JWKS"],
    ideas={"now": ["`acr` claim for step-up enforcement"], "next": ["DPoP sender-constrained tokens"], "adv": ["Token exchange (RFC 8693) for service-to-service delegation"], "rej": ["24 h access tokens: revocation becomes meaningless"]})

sub(id="session-registry", comp="identity", name="Session & Device Registry", phase="I", cat="Security · Session management",
    resp="Record every signed-in session and device, let users and support list and revoke them, and supply device signals to risk.",
    inp="mint/revoke commands, device metadata, push tokens", out="sessions, device list, revocation events", deps="Token service, Risk & Fraud", cons="Settings screens, Support tools, Notifications (push tokens), Risk",
    own="sessions, devices",
    problem="Users and support need to see and terminate sessions, and fraud needs to know how many devices an account uses. Push notifications need to know where to send.",
    without="No 'log out other devices', no device-based fraud signal, push tokens scattered across services.",
    guar=["Every refresh family maps to exactly one session row", "Revoking a session prevents further refreshes", "A device's push token is unique to one active user"],
    nong=["Real-time presence (that's driver supply)", "Exact device identity (fingerprints can be spoofed)"],
    usecase="A rider sees 'iPhone 15 – Mumbai – active 2 min ago' and 'Pixel – Lagos – 3 days ago', taps revoke on the second, and that device is logged out at its next refresh.",
    derive="- A session is the unit of revocation and appears in the JWT as `sid`.\n- A device can host sessions of different users over time (shared phones), so the push token must move with the active user to avoid sending notifications to the wrong person.\n- last_seen updates on every request would be a write storm, so update on refresh only (≤ every 10 min).",
    conc="Push-token reassignment: `UPDATE devices SET user_id=? WHERE push_token=?` in the same transaction as session mint. Unique index on active push_token prevents two users. Revoke uses `UPDATE sessions SET revoked_at=now() WHERE id=? AND revoked_at IS NULL`.",
    consistency="Strong within identity DB. Downstream copies (risk) are eventually consistent via events.",
    idem="Revoke is idempotent. Device registration upserts on (user_id, device_id).", order="Device updates carry `updated_at`, and consumers keep the latest by timestamp.",
    restart="DB-backed; no in-memory state.", scale="Rows ≈ active sessions (10M at Phase VI). Hash-partitioned by user_id at Phase V; regional at Phase VI.",
    arch="CRUD-style module with a small number of invariant-enforcing operations: `mint`, `touch` (on refresh), `revoke`, `revokeAllExcept`, `registerPushToken`.",
    modules=[["SessionStore", "Create/revoke/list"], ["DeviceStore", "Upsert device, push token ownership"], ["ActivityTouch", "Updates last_seen on refresh only"], ["SignalEmitter", "New device / new country events to risk"]],
    d_arch=("""flowchart LR
  TS["TokenService"] -->|mint/touch| SS["SessionStore"]
  APP["Settings UI"] -->|list/revoke| SS
  SUP["Support tool"] -->|revoke| SS
  SS --> PG[("sessions, devices")]
  SS -->|SessionRevoked| EV["events"]
  DS["DeviceStore"] --> PG
  DS -->|NewDevice| RISK["Risk"]""", "One store for sessions and devices. Writes come from the token path and from humans (user, support). Signals flow out to risk."),
    d_seq=("""sequenceDiagram
  participant U as User app
  participant S as SessionStore
  participant T as TokenService
  participant G as Gateway
  U->>S: DELETE /v1/sessions/{sid}
  S->>S: UPDATE revoked_at WHERE id AND user_id = caller
  S->>T: revokeFamily(sid)
  S->>G: deny(sid, ttl 10m)
  S-->>U: 204""", "Self-service revoke. The `user_id = caller` predicate prevents revoking other users' sessions."),
    d_state=("""stateDiagram-v2
  [*] --> Active
  Active --> Idle: no refresh 7d
  Idle --> Active: refresh
  Active --> Revoked: user/support/reuse
  Idle --> Expired: 30d
  Revoked --> [*]
  Expired --> [*]""", "Session lifecycle. Idle is computed rather than stored."),
    d_flow=("""flowchart LR
  REQ["login/refresh"] --> META["device model, OS, app version, IP→geo"] --> SESS[("sessions")]
  SESS --> UI["device list UI"]
  SESS --> SIG["risk signals"]""", "Metadata is captured on login and refresh only."),
    d_fail=("""flowchart TB
  R["revoke"] --> DB{"DB ok"} -->|no| E["503, user retries"]
  DB -->|yes| P{"deny push ok"} -->|no| LATE["revocation effective at next refresh ≤10m"]""", "If the deny push fails, the guarantee falls back to the TTL bound."),
    sql="""CREATE TABLE identity.sessions (
  id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES identity.users(id),
  device_id text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(), ip_country char(2), revoked_at timestamptz, revoke_reason text);
CREATE INDEX sessions_user_active ON identity.sessions(user_id) WHERE revoked_at IS NULL;
CREATE TABLE identity.devices (
  user_id uuid NOT NULL, device_id text NOT NULL, platform text NOT NULL, model text, app_version text,
  push_token text, updated_at timestamptz NOT NULL, PRIMARY KEY (user_id, device_id));
CREATE UNIQUE INDEX push_token_unique ON identity.devices(push_token) WHERE push_token IS NOT NULL;""",
    data="Sessions retained 90 days after revoke/expiry for audit, then deleted. Devices deleted with the user on erasure.",
    api="""GET    /v1/sessions                  -> [{sid, device, last_seen, country, current:boolean}]
DELETE /v1/sessions/{sid}            -> 204
POST   /v1/sessions/revoke-others    -> 204
PUT    /v1/devices/{device_id}/push-token {token, platform} -> 204""",
    mech=[("Write coalescing for last_seen", "Updating on every request would cost one write per API call. Updating at refresh (≤ every 10 min) gives accuracy that's good enough at ≈1/100th the write cost."), ("Push-token handover", "A unique partial index plus a transactional reassign means a shared phone never receives the previous user's ride notifications.")],
    code="""@Transactional
public void registerPushToken(UserId u, String deviceId, String token) {
    devices.clearToken(token);                 // UPDATE devices SET push_token=NULL WHERE push_token=?
    devices.upsert(u, deviceId, token);        // ON CONFLICT (user_id, device_id) DO UPDATE
}""", cx="O(1).",
    fail=[F("Deny-list push fails", "Publish error metric", "Revoked token valid ≤ 10 min", "Retry publish; TTL bound", "Eventually revoked"), F("Concurrent push-token claims", "Unique violation", "One request fails", "Retry with clear-then-set in tx", "Single owner")],
    alts=[["Store sessions in Redis only", "Rejected", "Audit + durability needs", "Never for source of truth"], ["Track last_seen per request in Redis", "Next phase option", "More accurate activity", "If product needs live presence"]],
    adrs=[A("Session row per refresh family", "I", "Need a revocation unit.", [("Per device", "Rejected: multiple users per device"), ("Per refresh family", "Chosen")], "Session = family = `sid` claim.", "Clean revocation semantics.", "More rows than devices.", "N/A")],
    qa=[Q("Privacy", "Is storing IP country in sessions acceptable?", "Yes, with a stated purpose (security), country-level granularity only (not raw IP beyond 30 days), and inclusion in data-subject export. Raw IPs live in security logs with 30-day retention.", "Storing full IP history indefinitely is a GDPR purpose-limitation risk.")],
    tests=[T("Unit", "Revoke another user's session", "404"), T("Integration", "Shared phone, user B logs in", "Push token moves to B; A gets no pushes"), T("Load", "1M sessions list for heavy user (bots)", "List paginated, limit 50")],
    evo=["I: Sessions + devices tables", "E: Deny-list push via Redis", "E: Session events to risk via outbox", "U: Moves with Identity service; no design change needed", "E: Hash partitioned by user", "R: Regional session stores; device list aggregated across regions on read"],
    ideas={"now": ["Show approximate location on device list"], "next": ["Notify user on new-device login"], "adv": ["Risk-based session lifetimes"], "rej": ["Unlimited concurrent sessions for drivers: account sharing risk"]})

sub(id="account-recovery", comp="identity", name="Account Recovery", phase="II", cat="Security · Recovery",
    resp="Restore access for a user who lost their phone number or is locked out, without handing the account to an attacker.",
    inp="recovery request, alternate factors (email OTP, ID document, payment card last-4, trip history)", out="re-bound contact point + new session, or rejection", deps="OTP auth, Session registry, Risk, Support, Driver onboarding (ID docs)",
    cons="Users, Support agents", own="recovery_cases",
    problem="Phone numbers change and get recycled. A new owner of a recycled number must not inherit the old account, and the old owner must be able to move to a new number.",
    without="Support agents improvise identity checks, which is the classic social-engineering vector for account takeover.",
    guar=["Recovery requires ≥2 independent factors scored above threshold", "All sessions revoked and payout details frozen 72 h after recovery", "Every case is audited with decision reasons"],
    nong=["Instant recovery for high-value accounts (deliberate delay)", "Recovery without any prior factor (falls back to manual KYC)"],
    usecase="A driver's SIM is lost. They verify their new number by OTP, then prove the old account with email OTP plus a selfie match against their licence photo. The account is re-bound and payouts are frozen for 72 h.",
    derive="- Recovery is a long-running, multi-step process with human steps, which calls for a persistent case with explicit states.\n- Factors have different strengths, so scoring is additive with a threshold rather than boolean.\n- After recovery an attacker would act fast (change payout account), so there is a cooling-off period on sensitive actions.",
    conc="Only one open case per user: unique partial index. State transitions use optimistic locking (`version`).", consistency="Strong (single DB) for case state; sessions revoked in the same transaction as contact re-binding.",
    idem="Factor submissions keyed by (case_id, factor_type). Resubmission replaces the previous attempt up to a limit.", order="Steps are user-driven and sequential; out-of-order factor submissions are accepted, since scoring is order-independent.",
    restart="Case persisted. Timeouts are scheduled jobs (case expires after 7 days).", scale="Low volume (≈0.1% of users/month). Throughput is never the issue, abuse resistance is.",
    arch="A case-based state machine inside Identity. In Phase III it runs as a durable workflow (Temporal) because it waits on humans and vendors. Factor verifiers are pluggable (`EmailOtpFactor`, `SelfieMatchFactor`, `PaymentCardFactor`, `TripKnowledgeFactor`).",
    modules=[["CaseManager", "Create/advance/close cases"], ["FactorVerifiers", "Pluggable factor checks with strength scores"], ["DecisionPolicy", "Threshold + risk score → approve, reject or manual review"], ["CoolingOff", "Freeze payout changes and high-risk actions"]],
    d_arch=("""flowchart LR
  U["User"] --> CM["CaseManager"]
  CM --> FV["FactorVerifiers"]
  FV --> OTP["OTP auth"] & KYC["Selfie/ID vendor"] & PAY["Payment card check"]
  CM --> DP["DecisionPolicy"] --> RISK["Risk score"]
  DP -->|manual| SUP["Support queue"]
  CM --> SR["Session registry: revoke all"]
  CM --> PG[("recovery_cases")]""", "Factors are verified independently. A policy combines them with risk, and borderline cases go to humans."),
    d_seq=("""sequenceDiagram
  participant U as User
  participant C as CaseManager
  participant F as Factors
  participant P as Policy
  U->>C: start recovery (new verified phone)
  C-->>U: case_id, required factors
  U->>F: submit email OTP
  U->>F: submit selfie
  F->>C: factor results (scores)
  C->>P: decide(scores, risk)
  alt approve
    C->>C: rebind phone, revoke sessions, set cooling-off
    C-->>U: new session
  else manual
    C-->>U: under review (≤24h)
  end""", "Typical self-service recovery."),
    d_state=("""stateDiagram-v2
  [*] --> Open
  Open --> CollectingFactors
  CollectingFactors --> Approved: score ≥ threshold, low risk
  CollectingFactors --> ManualReview: borderline
  ManualReview --> Approved
  ManualReview --> Rejected
  CollectingFactors --> Expired: 7 days
  Approved --> [*]
  Rejected --> [*]
  Expired --> [*]""", "Recovery case lifecycle."),
    d_flow=("""flowchart LR
  F1["email OTP: +40"] --> S["score"]
  F2["selfie match: +50"] --> S
  F3["card last4+expiry: +30"] --> S
  F4["trip knowledge: +20"] --> S
  R["risk penalty"] --> S --> D{"≥80?"}""", "Additive factor scoring. Weights are configuration owned by the security team."),
    d_fail=("""flowchart TB
  V["KYC vendor down"] --> W["case waits, user notified"] --> M["manual review fallback after 24h"]
  A["attacker passes factors"] --> CO["cooling-off blocks payout change 72h"] --> N["notify old email + old phone"]""", "Even a successful attack is contained by the cooling-off period and notifications on old channels."),
    sql="""CREATE TABLE identity.recovery_cases (
  id uuid PRIMARY KEY, user_id uuid NOT NULL, new_phone_hmac bytea NOT NULL,
  status text NOT NULL, score int NOT NULL DEFAULT 0, factors jsonb NOT NULL DEFAULT '{}',
  decided_by text, decision_reason text, version int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL);
CREATE UNIQUE INDEX one_open_case ON identity.recovery_cases(user_id) WHERE status IN ('Open','CollectingFactors','ManualReview');""",
    data="Cases are retained 2 years (fraud investigations). Factor evidence (selfie) is stored in the KYC vendor or encrypted object storage, with only references kept here.",
    api="""POST /v1/recovery            {identifier: email|old_phone}  -> 202 {case_id, factors_required}
POST /v1/recovery/{id}/factors {type, payload}           -> 200 {score_ok:boolean, remaining}
GET  /v1/recovery/{id}                                    -> {status}
Event AccountRecovered {user_id, case_id, cooling_off_until}""",
    mech=[("Additive factor scoring", "Each factor contributes points weighted by strength and independence. Risk score subtracts. This avoids a brittle 'must have X and Y' rule and lets the security team tune weights."), ("Cooling-off window", "Sensitive actions (payout change, wallet transfer) check `cooling_off_until` and are blocked or require extra verification.")],
    code="""public Decision decide(RecoveryCase c, RiskScore risk) {
    int score = c.factorScores().values().stream().mapToInt(Integer::intValue).sum() - risk.penalty();
    if (score >= policy.approveAt() && risk.level() != HIGH) return Decision.APPROVE;
    if (score >= policy.reviewAt()) return Decision.MANUAL;
    return Decision.REJECT;
}""", cx="O(factors).",
    fail=[F("KYC vendor outage", "Breaker open", "Recovery delayed", "Queue case; manual fallback", "Case waits"), F("Social engineering of agent", "Agent overrides without factors", "ATO risk", "Agents cannot approve below reviewAt; dual approval for overrides", "Audit trail")],
    alts=[["Agent-driven recovery only", "Rejected", "Primary ATO vector", "Never"], ["Backup codes", "Next phase", "Strong but users lose them", "Driver accounts"]],
    adrs=[A("Cooling-off after recovery", "II", "Successful attackers act immediately.", [("No cooling-off", "Rejected"), ("72h freeze on payout changes", "Chosen")], "Freeze sensitive actions 72 h; notify old channels.", "Gives the real owner time to react.", "Legitimate users mildly delayed.", "If fraud data shows attacks waiting longer.")],
    qa=[Q("Security", "A recycled phone number's new owner logs in. Do they get the old account?", "No. Contact points record `verified_at`. If a number hasn't been re-verified by its account in more than N months and carrier signals show a port or recycle, OTP login with that number starts a *new* account and flags the old one. The old owner must use recovery. Login also requires device continuity or a second factor when the device is new and the number's last verification is old.", "Always linking to the old account is the recycled-number takeover bug.")],
    tests=[T("Unit", "Score 79 with low risk", "Manual review"), T("Concurrency", "Two cases opened simultaneously", "One rejected by unique index"), T("Security", "Payout change during cooling-off", "Blocked with RECOVERY_COOLING_OFF")],
    evo=["N: No recovery flow; support handles rare cases manually with audit", "I: Case state machine with email OTP + card factors", "R: Runs as Temporal workflow; KYC vendor integration", "E: Selfie match for drivers via onboarding docs", "E: ML risk model in decision", "E: Cases in user's home region; global contact rebind via directory"],
    ideas={"now": ["Notify old channels on every recovery"], "next": ["Trusted-contact recovery"], "adv": ["Passkey-based recovery"], "rej": ["Security questions: guessable/researchable"]})

sub(id="identity-federation", comp="identity", name="Identity Federation (OIDC Sign-in)", phase="IV", cat="Security · Federation",
    resp="Let users sign in with Apple/Google, and business customers with their corporate IdP, by linking external identities to internal users.",
    inp="OIDC ID tokens / authorization codes", out="linked or new user + session", deps="Token service, OTP auth (phone still required for riders)", cons="Apps, Business portal", own="federated_links",
    problem="Users want one-tap sign-in, and enterprises want SSO for employee ride programs. External identities must map safely to internal accounts.",
    without="Friction at signup, and no enterprise sales motion.",
    guar=["An external (issuer, subject) links to at most one user", "ID tokens are validated (signature, iss, aud, nonce, exp)", "Linking an existing account requires proof of both identities"],
    nong=["Email from IdP is not trusted as proof of an existing account unless `email_verified` and the IdP is authoritative for that domain"],
    usecase="An employee of Acme signs in through Okta SSO and is linked to their Uber account. Rides are billed to Acme's business profile.",
    derive="- Key on (iss, sub). Emails change, subjects don't.\n- Account-linking by email alone enables takeover through IdPs that don't verify email, so require an authenticated session plus the IdP proof to link.\n- Riders still need a phone for driver contact, so collect it after first federated login.",
    conc="Unique (issuer, subject). Link creation inside the session-mint transaction.", consistency="Strong: the link row and the session are written in one transaction, so a user can never hold a session from a link that was not persisted.", idem="Re-login with the same (iss, sub) finds the existing link.", order="N/A (request/response).",
    restart="Stateless apart from DB; IdP JWKS cached.", scale="Small; IdP JWKS fetches cached per issuer.",
    arch="An OIDC relying-party adapter (Spring Security OAuth2 client) normalises external claims into `ExternalIdentity(iss, sub, email, email_verified)`. A `LinkPolicy` decides link vs create vs require-step-up.",
    modules=[["OidcAdapter", "Code exchange, ID token validation, nonce/PKCE"], ["LinkPolicy", "Decide link/create/step-up"], ["EnterpriseIdpRegistry", "Per-tenant IdP config (Phase IV)"]],
    d_arch=("""flowchart LR
  APP["App"] -->|PKCE auth| IDP["Apple / Google / Okta"]
  APP -->|code| OA["OidcAdapter"] --> IDP
  OA --> LP["LinkPolicy"] --> FL[("federated_links")]
  LP --> TS["TokenService"]""", "Standard OIDC authorization-code flow with PKCE. Our tokens are minted only after link resolution."),
    d_seq=("""sequenceDiagram
  participant A as App
  participant I as IdP
  participant O as OidcAdapter
  participant L as LinkPolicy
  A->>I: authorize (PKCE, nonce)
  I-->>A: code
  A->>O: POST /auth/oidc {code, verifier}
  O->>I: token exchange
  O->>O: validate id_token
  O->>L: resolve(iss, sub)
  alt linked
    L-->>A: tokens
  else unknown + no session
    L-->>A: new user, require phone OTP
  end""", "Sign-in path."),
    nostate="A link either exists or doesn't. There are no intermediate states beyond the OTP step owned by otp-auth.",
    d_flow=("""flowchart LR
  T["id_token claims"] --> N["normalize iss,sub,email"] --> FL[("federated_links")]
  N -.->|never stored| RAW["raw id_token"]""", "Only the identifiers needed for linking are kept."),
    d_fail=("""flowchart TB
  IDP["IdP down"] --> F["fallback: phone OTP login"]
  J["IdP JWKS rotated"] --> R["refetch on unknown kid, rate limited"]""", "Federation never becomes the only way into an account."),
    sql="""CREATE TABLE identity.federated_links (
  issuer text NOT NULL, subject text NOT NULL, user_id uuid NOT NULL REFERENCES identity.users(id),
  linked_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (issuer, subject));""",
    data="Deleted on user erasure, and on unlink.", api="""POST /v1/auth/oidc {provider, code, code_verifier, nonce} -> 200 tokens | 202 {needs_phone_verification}
POST /v1/me/links {provider, code, ...} (Bearer) -> 201
DELETE /v1/me/links/{provider} -> 204""",
    mech=[("PKCE + nonce", "PKCE binds the code to the client that started the flow. The nonce binds the ID token to this login attempt, which prevents code interception and replay."), ("Linking with proof of both", "Linking is only allowed from an authenticated session, so the user proves both identities.")],
    code="""ExternalIdentity ext = oidc.exchangeAndValidate(provider, code, verifier, nonce);
return links.find(ext.issuer(), ext.subject())
    .map(userId -> tokens.mintSession(userId, device))
    .orElseGet(() -> onboarding.startFederatedSignup(ext));""", cx="O(1) plus one IdP round trip.",
    fail=[F("IdP outage", "Exchange errors", "Federated logins fail", "Phone OTP fallback", "None"), F("Malicious IdP claims email of victim", "Policy check", "ATO attempt", "Never auto-link by email", "None")],
    alts=[["Auto-link on verified email", "Rejected", "IdP trust varies", "Enterprise IdP with verified domain ownership"], ["SAML for enterprise", "Supported via broker", "Some enterprises require SAML", "When customers demand it"]],
    adrs=[A("Federation introduced at Phase IV", "IV", "Business-travel product launch and Apple sign-in requirement for App Store.", [("Phase I", "Rejected: no demand"), ("Phase IV", "Chosen")], "Add OIDC adapter when business program launches.", "Demand-driven.", "More IdP integrations to maintain.", "If consumer data shows signup drop-off on OTP.")],
    qa=[Q("Security", "Why must riders still verify a phone after Apple sign-in?", "Drivers call or message riders through masked numbers, and fraud controls rely on phone-number reputation. Apple's relay email gives neither. A verified phone stays a platform requirement, and federation only removes the login friction.", "Making phone optional for business riders who use only the business portal is acceptable.")],
    tests=[T("Security", "ID token with wrong aud", "Rejected"), T("Integration", "Okta tenant SSO", "Linked to business profile"), T("Unit", "Replay ID token with used nonce", "Rejected")],
    evo=["N: Not needed for a pilot city", "N: Still no demand", "N: Still no demand", "I: OIDC adapter for Apple/Google + enterprise IdPs", "E: SAML broker for enterprise customers", "E: Regional IdP configs; global federated_links in directory"],
    ideas={"now": ["n/a before Phase IV"], "next": ["SCIM provisioning for enterprise employees"], "adv": ["Federated driver identity via government eID"], "rej": ["Facebook login: declining usage, privacy concerns"]})

# ======================================================================= Authorization
comp(id="authz", domain="identity", name="Authorization & Access Control", tag="Security · Core", phase="I", kind="Library in Phase I → library + central policy service (Phase IV)",
     biz="Ensures riders see only their own trips, drivers only their assigned riders, support agents only what their role allows, and services only call what they need.",
     eng="Converts an authenticated principal plus a requested action on a resource into an allow/deny decision, consistently and auditable, across users, staff and services.",
     deploy="Spring Security method-level checks in the monolith; from Phase IV a sidecar/library evaluating centrally-distributed policies (OPA bundles) plus mTLS service identity.",
     data_own="roles, role_bindings, policy bundles, service identities (SPIFFE IDs).", up=["identity", "admin-policy"], down=["api-gateway", "trip", "support", "admin-policy", "payments"], ext=["SPIFFE/SPIRE or mesh CA"],
     interfaces="In-process `AccessDecision decide(Principal, Action, Resource)`; Phase IV: OPA sidecar `POST /v1/data/atlas/allow`, policy bundles from a bundle server.",
     problem="Authorization rules are scattered and inconsistent unless centralised. Data leaks (seeing another rider's trip) are the most common API vulnerability (BOLA/IDOR).",
     fr=["Role-based permissions for staff (agent, senior agent, ops, finance)", "Resource ownership checks for riders/drivers", "Relationship checks (driver ↔ rider on an active trip)", "Service-to-service allow-lists (Phase IV)", "Decision audit for staff access to PII"],
     nfr=["Decision latency < 1 ms in-process; < 3 ms via sidecar", "Fail closed", "Policy change propagation < 60 s"], workload="Every API call (≈50K decisions/s at Phase V).",
     success="Zero BOLA findings; every staff PII access is logged with justification.", failure="Cross-tenant data exposure; staff overreach; services calling anything.",
     derive="**Decisions need** the principal (from token), the action, and resource attributes (owner, trip participants, city). The resource attributes live in the owning service, so ownership checks must run *in* the owning service, not at the gateway. Coarse checks (role can call endpoint) can run at the gateway. Separating the policy *definition* (central) from *evaluation* (local) gives consistency without a network hop.",
     owns=["Role definitions and bindings", "Policy language and bundles", "Service identity issuance (Phase IV)", "Access audit for staff"], not_owns=["Authentication (Identity)", "Resource data (each owning service)", "Business restrictions like account suspension (owning domains)"],
     sync=["Every decision (in-process)"], **{"async": ["Policy bundle distribution", "Audit log shipping"]},
     boundary_why="Policies are owned centrally so security can review them. Evaluation is local because resource facts are local, and a central decision service on every request would be a single point of failure.",
     hld=("""flowchart LR
  GW["Gateway: coarse role/scope check"] --> SVC["Owning service"]
  SVC --> PEP["Policy enforcement point"] --> PDP["Local policy engine (library/OPA sidecar)"]
  PDP -->|bundle pull| BS["Policy bundle server"]
  PAP["Policy admin (Git + review)"] --> BS
  PEP -->|staff PII access| AUD[("Access audit log")]
  MESH["mTLS service identity"] -.-> SVC""", "Policy as code: authored and reviewed in Git (PAP), distributed as bundles, evaluated locally (PDP) at enforcement points in owning services."),
     seq=("""sequenceDiagram
  participant A as Rider app
  participant T as Trip service
  participant P as PolicyEngine
  A->>T: GET /trips/42
  T->>T: load trip 42 (rider_id, driver_id)
  T->>P: decide(principal, read, trip{rider,driver})
  P-->>T: allow (owner)
  T-->>A: 200 trip""", "Ownership check after loading the resource. The gateway cannot do this because it doesn't have the trip's participants."),
     subdeps=[("ownership-guard", "rbac-policy"), ("service-identity", "rbac-policy")],
     flow="Requests carry the principal from the JWT. The gateway checks token scopes and coarse roles. The owning service loads the resource and calls the policy engine with the resource attributes. Staff decisions that touch PII write an audit record that includes the ticket id justification.",
     data="`roles(id, name)`, `role_permissions(role, permission)`, `role_bindings(principal, role, scope{city}, expires_at)`. Policies are versioned in Git, and bundles are content-hashed.",
     rel=[["Failure mode", "Policy engine unavailable → deny (fail closed); bundles cached locally with last-known-good."], ["Timeouts", "Sidecar call 5 ms; local evaluation otherwise."], ["Propagation", "Bundle polling every 30 s with ETag."]],
     sec=[["Threat: BOLA", "Every resource endpoint calls `decide`; ArchUnit test fails builds that bypass it."], ["Threat: staff overreach", "Just-in-time elevated roles with expiry; dual approval for finance actions."], ["Audit", "Staff PII access logged with ticket reference, immutable store."]],
     adrs=[A("Local evaluation of centrally-authored policies", "IV", "Consistency without a hot-path dependency.", [("Central PDP service", "Rejected: hot-path dependency"), ("Hardcoded checks per service", "Rejected: inconsistent"), ("OPA bundles + local eval", "Chosen")],
             "Policy bundles distributed to sidecars/libraries.", "Sub-ms decisions, central review.", "Bundle propagation lag up to 60 s.", "If relationship graphs grow (fleet managers ↔ drivers ↔ vehicles) consider a Zanzibar-style relationship service.")],
     qa=[Q("Security", "How do you guarantee no endpoint forgets the ownership check?", "Make it structurally hard. Repository methods that load user-owned resources require a `Principal` and apply the check (`findTripForPrincipal`). An ArchUnit rule forbids controllers from calling raw repository finders. CI runs an automated BOLA test suite that calls every endpoint with a second user's token and expects 403/404.", "Code review alone misses checks under deadline pressure.")],
     impl_order=["rbac-policy (roles + Spring method security)", "ownership-guard", "service-identity (Phase IV)"],
     pkg="""com.atlas.authz
├── Principal, Action, ResourceRef
├── PolicyEngine (interface) → LocalRbacEngine (P1) / OpaEngine (P4)
├── ownership (OwnershipGuard, @OwnedBy)
└── audit (AccessAuditWriter)""",
     tests=[T("Security", "Automated BOLA sweep across all endpoints", "All cross-user calls 403/404"), T("Unit", "Expired role binding", "Denied"), T("Failure", "Bundle server down", "Last-known-good bundle used")],
     evo=[("I", "Spring Security roles + ownership guard in monolith", "roles tables in identity schema", "Fail closed", "Basic correctness"),
          ("E", "Staff RBAC with city scopes; audit log", "Audit table", "JIT elevation for agents", "Support team grows"),
          ("U", "No change: authorization stays local", "—", "—", "Events don't need authorization changes"),
          ("R", "OPA bundles + mTLS service identity", "Bundle server; SPIFFE IDs", "Service allow-lists", "Many services, zero-trust network"),
          ("E", "Relationship-based checks for fleets", "Relationship index", "Decision caching", "Fleet manager product"),
          ("E", "Regional bundle servers; global policy repo", "Region-scoped roles", "Residency-aware access", "Regional compliance")],
     ideas={"now": ["Deny-by-default ArchUnit rule"], "next": ["Zanzibar-style relationship service for fleets"], "adv": ["Attribute-based access with data classification tags"], "rej": ["Gateway-only authorization: cannot see resource ownership"]})

sub(id="rbac-policy", comp="authz", name="RBAC & Policy Engine", phase="I", cat="Security · Authorization",
    resp="Define roles and permissions for staff and coarse permissions for users and services, and evaluate them consistently.",
    inp="principal (roles, scopes), action, context (city)", out="allow/deny + reason", deps="Identity (roles in token), Admin & Policy (bindings UI)", cons="Every service's enforcement points", own="roles, role_permissions, role_bindings",
    problem="Different actors need different capabilities, and those capabilities must be managed without code changes and checked identically everywhere.",
    without="Ad-hoc `if (user.isAdmin)` checks that drift, leaving staff with excess access.",
    guar=["Deny by default", "Every allow traceable to a role binding or policy rule", "Bindings can expire"], nong=["Resource ownership (ownership-guard)", "Business eligibility"],
    usecase="A support agent in Bengaluru can view rider trips in their assigned cities but cannot issue refunds above ₹2,000 without the senior-agent role.",
    derive="- Permissions are verbs on resource types (`trip:read`, `refund:issue`).\n- Staff scope is geographic, so bindings carry a city scope.\n- Temporary elevation is common, so bindings need an expiry.\n- Limits (refund amount) are attributes, not roles, which means policy rules beyond pure RBAC.",
    conc="Bindings change rarely; standard optimistic locking. Evaluation is read-only.", consistency="Bindings are strongly consistent in DB. Token role claims are stale up to access-token TTL, and sensitive staff actions re-check bindings from DB.",
    idem="Granting an existing binding is a no-op.", order="Bundles carry a monotonically increasing revision. A sidecar ignores a bundle older than the one it holds, so a delayed download cannot roll policy back.", restart="Bundles and role tables reloaded on start; last-known-good cached on disk (Phase IV).", scale="Read-only evaluation, CPU-bound, horizontally trivial.",
    arch="Phase I: Spring Security `@PreAuthorize(\"hasPermission(#tripId,'trip','read')\")` backed by a `PermissionEvaluator` reading role_permissions (cached). Phase IV: Rego policies evaluated by OPA, distributed as signed bundles.",
    modules=[["RoleStore", "Roles, permissions, bindings"], ["Evaluator", "Combine role permissions + attribute rules"], ["BundleBuilder (P4)", "Compile Git policies into signed bundles"]],
    d_arch=("""flowchart LR
  CTRL["Controller @PreAuthorize"] --> EV["Evaluator"]
  EV --> RC["Role cache"] --> RS[("roles, bindings")]
  EV --> AR["Attribute rules (limits)"]
  ADM["Admin UI"] --> RS""", "Evaluation reads a cached role model. Admin writes invalidate the cache."),
    d_seq=("""sequenceDiagram
  participant Ag as Agent
  participant S as Support API
  participant E as Evaluator
  Ag->>S: POST /refunds amount=2500
  S->>E: decide(agent, refund:issue, {amount:2500, city:BLR})
  E-->>S: deny (limit 2000 for role agent)
  S-->>Ag: 403 REQUIRES_ROLE senior_agent""", "An attribute-limited permission."),
    nostate="Roles and bindings are configuration records. A binding's only lifecycle is active→expired, which is a timestamp comparison.",
    d_flow=("""flowchart LR
  GIT["policy repo"] --> CI["tests + review"] --> B["signed bundle"] --> SC["sidecars"]""", "Phase IV policy delivery pipeline."),
    d_fail=("""flowchart TB
  B["bundle fetch fails"] --> L["keep last-known-good"] --> A{"age > 24h?"} -->|yes| AL["alert; still serve"]
  P["policy bug denies all"] --> RB["rollback bundle version"]""", "Delivery failures keep the old policy. Bad policies are rolled back like code."),
    sql="""CREATE TABLE authz.role_permissions (role text NOT NULL, permission text NOT NULL, max_amount numeric, PRIMARY KEY(role, permission));
CREATE TABLE authz.role_bindings (principal_id uuid NOT NULL, role text NOT NULL, city_scope text[] NOT NULL DEFAULT '{}',
  granted_by uuid NOT NULL, expires_at timestamptz, PRIMARY KEY(principal_id, role));""",
    data="Bindings are audited (who granted, when). Expired bindings are kept for 1 year of audit.", api="""interface PolicyEngine { Decision decide(Principal p, String action, Map<String,Object> resource); }
OPA (P4): POST /v1/data/atlas/authz/allow {input:{principal, action, resource}} -> {result:{allow, reason}}""",
    mech=[("Deny by default", "The evaluator returns deny unless a rule explicitly allows. A missing permission becomes a safe failure."), ("Policy-as-code", "Rego files are versioned, unit-tested (`opa test`) and reviewed, so policy changes get the same rigour as code.")],
    code="""public Decision decide(Principal p, String action, Map<String,Object> res) {
    return p.roles().stream()
        .flatMap(r -> perms.of(r).stream())
        .filter(perm -> perm.action().equals(action))
        .filter(perm -> perm.allowsCity(res.get("city")) && perm.withinLimit(res.get("amount")))
        .findFirst().map(Decision::allow).orElse(Decision.deny("no matching permission"));
}""", cx="O(roles × permissions); tiny.",
    fail=[F("Stale role in token", "Role revoked but token valid", "≤10 min excess access", "Sensitive actions re-check DB", "Bounded"), F("Policy bug", "Deny spike metric", "Outage of a feature", "Bundle rollback", "None")],
    alts=[["ACL per resource", "Rejected", "Explodes in size", "Shared documents"], ["ReBAC (Zanzibar)", "Next phase", "Fleets/relations", "Complex sharing"]],
    adrs=[A("Attribute limits inside RBAC", "II", "Refund limits by role.", [("Separate roles per limit", "Rejected: role explosion"), ("Attributes on permission", "Chosen")], "Permissions carry optional limits.", "Few roles.", "Rules more complex.", "If many attributes → ABAC policies.")],
    qa=[Q("Operations", "How do you safely give an engineer production data access during an incident?", "Break-glass: a time-boxed binding (1–4 h) requested via the admin tool with an incident id, auto-approved for on-call, with access logged and reviewed. The binding expires automatically.", "Permanent access is convenient but creates standing privilege.")],
    tests=[T("Unit", "Agent refund 2001", "Denied"), T("Unit", "Binding expired 1s ago", "Denied"), T("Contract", "Rego policy tests", "100% rule coverage")],
    evo=["I: Spring method security + tables", "E: City scopes, limits, JIT elevation", "U: No change needed", "R: OPA + signed bundles", "E: Decision caching; ReBAC for fleets", "E: Regional bundle servers"],
    ideas={"now": ["Permission naming convention resource:verb"], "next": ["Access reviews quarterly"], "adv": ["ABAC with data classification"], "rej": ["Super-admin role used daily"]})

sub(id="ownership-guard", comp="authz", name="Resource Ownership Guard (anti-BOLA)", phase="I", cat="Security · Authorization",
    resp="Ensure a user can only act on resources they own or participate in (their trips, their payment methods, their messages).",
    inp="principal, resource with owner/participant attributes", out="allow / 404", deps="Owning repositories", cons="All user-facing endpoints", own="No data; enforces on others' data",
    problem="APIs that take an id (`/trips/{id}`) leak data if they don't check that the caller is a participant. This is the #1 API vulnerability class.",
    without="Enumerating ids exposes other riders' trips, addresses and driver details.",
    guar=["Every user-facing read/write of an owned resource checks participation", "Unauthorized access returns 404 (no existence leak)"], nong=["Staff access (RBAC)"],
    usecase="A driver tries `GET /trips/{id}` for a trip they weren't assigned: 404. During an active trip, the driver can read the rider's first name and pickup point only.",
    derive="- Ownership is a property of the resource, so the check happens after loading it, or as a predicate in the query.\n- Putting the predicate in the query (`WHERE id=? AND rider_id=?`) is both faster and safer.\n- Relationship access is time-bound: a driver can see rider details only during the trip plus 24 h.",
    conc="Read-only checks; for writes the ownership predicate is part of the UPDATE's WHERE clause, so a concurrent ownership change can't race.", consistency="Same transaction as the read/write.",
    idem="The guard has no side effects. Repeating a request re-evaluates the same predicate and yields the same answer.", order="Participation changes (driver reassigned) are committed in the trip row. The next request reads the new participants, so there is no message ordering to depend on.", restart="Stateless: nothing to recover. Correctness depends only on the owning table.", scale="Zero extra queries when predicates are in the query.",
    arch="A repository-layer pattern: `TripRepository.findForParticipant(tripId, principal)` that builds `WHERE id=? AND (rider_id=? OR (driver_id=? AND (ended_at IS NULL OR ended_at > now()-interval '24 hours')))`. Controllers cannot access unscoped finders (ArchUnit).",
    modules=[["ScopedRepositories", "Principal-aware finders"], ["ParticipationRules", "Time-bounded relationship rules"], ["ArchRules", "Build-time enforcement"]],
    d_arch=("""flowchart LR
  C["Controller"] -->|principal| SR["Scoped repository"] --> DB[("trips")]
  AR["ArchUnit rule"] -.->|forbids| UR["Unscoped finder"]""", "Unscoped finders exist only for internal jobs, and the build fails if a controller calls one."),
    d_seq=("""sequenceDiagram
  participant D as Driver
  participant T as TripController
  participant R as ScopedRepo
  D->>T: GET /trips/77
  T->>R: findForParticipant(77, driver)
  R-->>T: empty
  T-->>D: 404""", "The non-participant receives 404, not 403."),
    nostate="Stateless predicate logic.",
    d_flow=("""flowchart LR
  JWT["sub, roles"] --> P["Principal"] --> Q["SQL predicate"] --> ROW["row or nothing"]""", "The principal is translated into a SQL predicate."),
    d_fail=("""flowchart TB
  M["missing check in new endpoint"] --> CI["BOLA test suite in CI"] --> F["build fails"]""", "Detection happens before production."),
    sql="""-- predicate pattern
SELECT * FROM trip.trips t
WHERE t.id = :tripId
  AND (t.rider_id = :uid OR (t.driver_id = :uid AND (t.ended_at IS NULL OR t.ended_at > now() - interval '24 hours')));""",
    data="Uses owning tables' existing indexes (PK).", api="""Optional<Trip> findForParticipant(TripId id, Principal p);
Response: 404 NOT_FOUND for both nonexistent and not-owned""",
    mech=[("Predicate pushdown", "Folding authorization into the query eliminates time-of-check/time-of-use gaps and an extra round trip."), ("404 instead of 403", "Prevents attackers from learning which ids exist.")],
    code="""@Query("select t from Trip t where t.id = :id and (t.riderId = :uid or (t.driverId = :uid and (t.endedAt is null or t.endedAt > :cutoff)))")
Optional<Trip> findForParticipant(UUID id, UUID uid, Instant cutoff);""", cx="O(1) PK lookup.",
    fail=[F("Developer bypasses guard", "ArchUnit + BOLA suite", "Potential leak", "Build blocked", "N/A")],
    alts=[["Gateway checks", "Rejected", "No resource data at gateway", "Never"], ["Row-level security in PostgreSQL", "Viable alternative", "DB-enforced; needs session vars per request", "Multi-tenant B2B data"]],
    adrs=[A("Repository predicates over post-load checks", "I", "Safety + performance.", [("Load then check", "OK but error-prone"), ("Predicate in query", "Chosen")], "Scoped finders.", "Can't forget, no extra query.", "More repository methods.", "If RLS adopted.")],
    qa=[Q("Privacy", "After a trip ends, what can the driver still see?", "For 24 h: rider first name, pickup and drop-off area (rounded), and rating ability, for lost items and ratings. After that, nothing. Contact goes only through Support (masked communication expires at trip end + 30 min).", "")],
    tests=[T("Security", "Every GET/PUT with another user's id", "404"), T("Unit", "Driver at trip end + 25h", "404")],
    evo=["I: Scoped repositories + ArchUnit", "E: Automated BOLA suite in CI", "U: No change needed", "E: Same pattern per service; contract tests include authz cases", "U: No change needed", "E: Region-local checks; no cross-region ownership calls"],
    ideas={"now": ["404 for not-owned"], "next": ["PostgreSQL RLS for B2B data"], "adv": ["Static analysis for tainted ids"], "rej": ["Sequential ids exposed publicly: use UUIDs"]})

sub(id="service-identity", comp="authz", name="Service Identity & mTLS", phase="IV", cat="Security · Zero trust",
    resp="Give every service a cryptographic identity and authorize service-to-service calls by identity, not network location.",
    inp="workload attestation (Kubernetes service account)", out="short-lived X.509 SVIDs; allow/deny for calls", deps="Mesh CA / SPIRE, RBAC policy", cons="Every service", own="Service allow-list policy",
    problem="Once services are separate, a compromised pod could call the ledger or payment service directly. Network ACLs are coarse and IP-based.",
    without="Lateral movement after any single compromise.",
    guar=["All service traffic mutually authenticated and encrypted", "Calls allowed only per declared dependencies", "Certificates rotate ≤ 24 h"], nong=["End-user authorization (propagated user context is checked by the callee)"],
    usecase="The notification service attempts to call `ledger.PostEntries`. The mesh denies it: notification is not in ledger's allowed callers.",
    derive="- Identity must be bound to the workload, not the IP, which means attestation via the orchestrator.\n- Short-lived certs avoid revocation infrastructure.\n- Policies are declared per callee (who may call me), matching ownership.",
    conc="N/A (certificate issuance is per workload).", consistency="Policy changes propagate in ≤ 60 s.", idem="Cert issuance idempotent per workload.", order="Policies are applied by resource version in the control plane. A stale push is rejected, so the mesh converges to the latest Git state.",
    restart="Sidecar fetches a new SVID on start; the service stays unready until it has one.", scale="CA issuance load = pods × rotations/day (trivial).",
    arch="Service mesh (Istio/Linkerd) with SPIFFE IDs `spiffe://atlas/ns/payments/sa/payment-svc`. AuthorizationPolicy per service lists allowed callers and methods. User context is propagated as a signed internal token (`x-atlas-user`) issued by the gateway.",
    modules=[["Mesh CA / SPIRE", "Issue SVIDs"], ["AuthorizationPolicy", "Per-service caller allow-lists"], ["Context propagation", "Gateway-signed user context header"]],
    d_arch=("""flowchart LR
  A["Pod A + sidecar"] -->|mTLS SVID A| B["Pod B + sidecar"]
  CA["Mesh CA"] -->|SVID| A & B
  POL["AuthorizationPolicy B: allow A"] -.-> B""", "Sidecars terminate mTLS and enforce policy before traffic reaches the app."),
    d_seq=("""sequenceDiagram
  participant N as Notification
  participant L as Ledger sidecar
  N->>L: gRPC PostEntries (mTLS)
  L->>L: peer SVID = notification, not allowed
  L-->>N: PERMISSION_DENIED""", "Lateral movement is blocked."),
    nostate="Certificates rotate on a timer, and policies are static configuration.",
    d_flow=("""flowchart LR
  K8S["service account token"] --> CA["CA attests"] --> SVID["X.509 SVID (24h)"] --> SC["sidecar"]""", "Attestation chain."),
    d_fail=("""flowchart TB
  CA["CA down"] --> C["existing certs valid ≤24h"] --> AL["page if > 6h"]""", "The CA is not on the request path."),
    sql="-- No relational data; policies are Kubernetes resources in Git.", data="Policies live in Git (GitOps). Certificates are never stored.",
    api="""apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata: {name: ledger-callers, namespace: ledger}
spec:
  action: ALLOW
  rules:
  - from: [{source: {principals: ["cluster.local/ns/payments/sa/payment-svc", "cluster.local/ns/earnings/sa/earnings-svc"]}}]
    to: [{operation: {methods: ["POST"], paths: ["/atlas.ledger.v1.Ledger/PostEntries"]}}]""",
    mech=[("mTLS", "Both sides present certificates, so each proves its identity and the channel is encrypted."), ("Short-lived certificates", "A 24 h validity makes revocation lists unnecessary: a compromised cert dies quickly.")],
    code="""// App-level: verify propagated user context signed by gateway
UserContext ctx = internalTokenVerifier.verify(headers.get("x-atlas-user"));""", cx="Handshake cost amortized by connection reuse.",
    fail=[F("Policy too strict after deploy", "Deny metrics spike", "Feature outage", "GitOps rollback", "None"), F("CA outage", "Issuance errors", "New pods can't start after 24h", "CA HA; alert", "None")],
    alts=[["Network policies only", "Insufficient", "IP-based", "Supplement"], ["API keys per service", "Rejected", "Secret sprawl", "Third-party callers"]],
    adrs=[A("Mesh mTLS at Phase IV", "IV", "Services extracted.", [("App-level TLS libs", "Rejected: per-language effort"), ("Mesh", "Chosen")], "Adopt mesh.", "Uniform.", "Sidecar latency ~1 ms.", "Ambient/eBPF mesh in Phase V.")],
    qa=[Q("Security", "How is the end user's identity carried across 4 service hops?", "The gateway verifies the user JWT and mints a short-lived internal token (`x-atlas-user`) signed with an internal key, containing user id, roles and session id. Each hop forwards it unchanged. Callees verify the signature and apply their own ownership checks. Service identity (mTLS) says *which service* is calling. The context token says *on whose behalf*.", "Forwarding the raw external JWT leaks it internally and ties services to external token format.")],
    tests=[T("Security", "Call ledger from notification pod", "Denied"), T("Recovery", "Rotate CA root with overlap", "No dropped connections")],
    evo=["N: Single process; no service calls", "N: Still a monolith", "N: Few services; private network + TLS", "I: Mesh mTLS + allow-lists", "E: eBPF/ambient mesh to reduce sidecar cost", "E: Cross-region trust domains federated"],
    ideas={"now": ["n/a before Phase IV"], "next": ["Ambient mesh"], "adv": ["Workload identity federation to cloud IAM"], "rej": ["Shared service API keys"]})
