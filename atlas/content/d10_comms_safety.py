from model import comp, sub, A, Q, F, T

# ======================================================================= Notifications
comp(id="notifications", domain="communication", name="Notification Platform", tag="Platform · Messaging", phase="I", kind="Platform capability (shared service from Phase III)",
     biz="Tells riders and drivers what they need to know (driver arriving, receipt, OTP, safety check-in) on the right channel, once, in their language.",
     eng="A multi-channel delivery pipeline: event → template → preference/consent check → dedupe → channel routing with provider failover → delivery tracking.",
     deploy="Module with sync calls (I); queue + workers (II); shared Notification service (III); regional (VI).", data_own="templates, notification_log, delivery receipts, push tokens (from session registry).",
     up=["consent-preferences", "session-registry"], down=[], ext=["APNs", "FCM", "SMS providers", "Email (SES/SendGrid)", "WhatsApp"],
     interfaces="`send(NotificationRequest{template, recipient, params, priority, dedupe_key, channels})`; events from domains; provider webhooks.",
     problem="Dozens of domains need to message users. Providers are unreliable and costly, users hate duplicates, OTPs are time-critical, and marketing needs consent.",
     fr=["Templates per locale", "Channels: push, SMS, email, in-app, WhatsApp", "Priority classes (OTP/safety > trip > receipt > marketing)", "Dedupe", "Consent/quiet hours", "Delivery tracking + fallback channel"],
     nfr=["OTP/safety p95 delivery < 5 s", "Trip updates < 3 s", "Marketing throughput 1M/hour without affecting critical", "No duplicate within dedupe window"],
     workload="≈ 10 notifications per trip; Phase V ≈ 20K/s peak.", success="Right message, once, on time.", failure="Missed OTPs, duplicate spam, marketing without consent.",
     derive="Producers shouldn't know channels, so intent-based requests (template + recipient). Priorities differ, so separate queues per class (bulkhead) so marketing can't delay OTPs. Providers fail, so channel routing with breakers and fallback. Duplicates come from at-least-once producers, so a dedupe key with TTL.",
     owns=["Templates", "Routing to channels", "Delivery state"], not_owns=["Consent decisions (Consent & Preferences)", "Message content semantics (producers)"], sync=["OTP send (enqueue + ack)"], **{"async": ["All delivery", "Receipts/webhooks"]},
     boundary_why="Centralizing delivery gives one place for provider contracts, consent enforcement, dedupe and analytics.",
     hld=("""flowchart LR
  P["Producers (domains)"] -->|NotificationRequest| ND["Notification dispatcher"]
  ND --> TPL["Templates"] & CON["Consent check"] & DD["Dedupe"]
  ND --> Q1[["critical queue"]] & Q2[["transactional queue"]] & Q3[["bulk queue"]]
  Q1 & Q2 & Q3 --> CD["Channel delivery workers"]
  CD --> APNS["APNs/FCM"] & SMS["SMS A/B"] & EM["Email"]
  APNS & SMS & EM -->|receipts| CD""", "The dispatcher decides what and whether. Priority queues isolate classes. Delivery workers handle providers and fallbacks."),
     seq=("""sequenceDiagram
  participant T as Trip
  participant N as Dispatcher
  participant Q as Queue
  participant W as Worker
  participant P as FCM
  T->>N: DriverArrived → template DRIVER_ARRIVED
  N->>N: dedupe key trip:arrived, render (hi-IN)
  N->>Q: transactional queue
  W->>P: push
  P-->>W: accepted
  W->>W: no open receipt in 30s → fallback SMS""", "Transactional push with SMS fallback."),
     subdeps=[("notification-dispatcher", "channel-delivery")],
     flow="Requests are validated, deduped, consent-checked and rendered, then enqueued by priority. Workers deliver via providers with breakers. Receipts update status. Missing confirmation triggers fallback for critical classes.",
     data="`templates(id, version, locale, channel, body)`, `notification_log(id, dedupe_key UNIQUE, recipient, template, priority, status, channel, provider_ref, created_at)` partitioned by day (retention 90 days).",
     rel=[["Bulkheads", "Separate queues and worker pools per priority."], ["Failover", "Provider breakers; channel fallback for critical."], ["Dedupe", "dedupe_key unique within 24 h."]],
     sec=[["Content", "OTP bodies never logged."], ["Consent", "Marketing requires positive consent at send time."], ["Abuse", "Per-recipient rate limits (no spam loops)."]],
     adrs=[A("Priority-class queues", "II", "Marketing blasts delayed OTPs.", [("Single queue", "Head-of-line blocking"), ("Per-class queues + pools", "Chosen")], "Critical/transactional/bulk.", "Isolation.", "More queues to operate.", "N/A")],
     qa=[Q("Reliability", "A marketing campaign enqueues 5M messages. How do OTPs stay fast?", "OTPs use the critical queue with dedicated workers and provider capacity reserved (separate SMS sender ids/accounts). Bulk workers are rate-limited (token bucket) to a provider share. Bulk queue depth doesn't affect critical consumers. Alerts on critical-queue lag.", "")],
     impl_order=["notification-dispatcher", "channel-delivery"], pkg="""com.atlas.notify
├── dispatch (Dispatcher, TemplateRenderer, DedupeStore, ConsentGate)
└── delivery (ChannelRouter, ApnsSender, FcmSender, SmsSender, EmailSender, ReceiptHandler)""",
     tests=[T("Load", "5M bulk + OTP traffic", "OTP p95 < 5 s"), T("Idempotency", "Same dedupe key ×3", "One message")],
     evo=[("I", "Sync provider calls in module", "Log table", "Timeouts", "Pilot"), ("R", "Queues + workers + priorities", "RabbitMQ", "Breakers, fallback", "Reliability"), ("R", "Shared service consuming domain events", "Kafka in, RabbitMQ out", "Idempotent", "Many producers"),
          ("E", "Autoscaled workers", "—", "SLO per class", "Scale"), ("E", "Provider cost routing", "—", "—", "Cost"), ("E", "Regional delivery", "In-region logs", "Residency", "Global")],
     ideas={"now": ["Dedupe keys"], "next": ["Priority queues"], "adv": ["Send-time optimization ML"], "rej": ["Domains calling providers directly"]})

sub(id="notification-dispatcher", comp="notifications", name="Notification Dispatcher (Templates, Consent, Dedupe)", phase="I", cat="Messaging · Orchestration",
    resp="Turn notification intents into rendered, consent-checked, deduplicated, prioritized delivery jobs.",
    inp="NotificationRequest from domains", out="delivery jobs on priority queues; notification_log rows", deps="Templates, Consent, Session registry (push tokens), Rider/Driver profile (locale)", cons="Channel delivery", own="templates, notification_log",
    problem="Uniform handling of every message's language, consent, duplication and priority.", without="Inconsistent, duplicated, non-compliant messages.",
    guar=["Each dedupe_key produces at most one delivery job in 24 h", "Marketing only with consent", "Rendering uses the recipient's locale (fallback en)"], nong=["Delivery itself"],
    usecase="TripCompleted arrives twice (at-least-once). The dedupe key `receipt:{trip}` exists, so the second is dropped, and the rider gets one receipt email.",
    derive="- Dedupe by unique insert on key.\n- Consent checked synchronously for marketing.\n- Template versions pinned at send for audit.",
    conc="Unique insert on dedupe_key.", consistency="Log row is authoritative for 'sent once'.", idem="dedupe_key unique.", order="Messages are independent. Trip-state messages carry version so stale ones (arrived after started) are suppressed.",
    restart="Requests consumed from Kafka/queue with at-least-once; dedupe ensures no duplicates.", scale="Stateless + DB partitioned by day; dedupe key cache in Redis (Phase V) with DB as backstop.",
    arch="Consumer of `notification-requests` and domain events (via mapping rules) → validate → dedupe → consent → resolve locale/tokens → render → enqueue priority job.",
    modules=[["EventMapper", "Domain event → request"], ["DedupeStore", "Unique key"], ["ConsentGate", "Purpose check"], ["TemplateRenderer", "Mustache-like with i18n"], ["PriorityRouter", "Queue selection"]],
    d_arch=("""flowchart LR
  EV["events / requests"] --> EM["EventMapper"] --> DS["DedupeStore"] --> CG["ConsentGate"] --> TR["TemplateRenderer"] --> PRR["PriorityRouter"] --> Q[["queues"]]""", "Linear pipeline."),
    d_seq=("""sequenceDiagram
  participant E as Event
  participant D as Dispatcher
  participant C as Consent
  participant Q as Queue
  E->>D: PromoLaunched(rider)
  D->>D: dedupe ok
  D->>C: allowed(marketing)?
  C-->>D: false
  D->>D: log SUPPRESSED_NO_CONSENT""", "A suppressed marketing message."),
    d_state=("""stateDiagram-v2
  [*] --> Accepted
  Accepted --> Suppressed: dedupe/consent/quiet hours
  Accepted --> Queued
  Queued --> Sent
  Sent --> Delivered
  Sent --> Failed
  Failed --> FallbackQueued""", "Notification status."),
    d_flow=("""flowchart LR
  P["params"] --> T["template v7 (hi-IN)"] --> B["body"] --> J["job {channel, to, body}"]""", "Rendering."),
    d_fail=("""flowchart TB
  CS["consent service down"] --> M["marketing suppressed; transactional proceed"]""", "Fail closed for marketing."),
    sql="""CREATE TABLE notify.notification_log (id uuid, dedupe_key text NOT NULL, recipient uuid NOT NULL, template text NOT NULL, template_version int NOT NULL,
  priority text NOT NULL, status text NOT NULL, channel text, provider_ref text, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, created_at), UNIQUE (dedupe_key, created_at)) PARTITION BY RANGE (created_at);""",
    data="90-day retention; OTP bodies never stored.", api="""NotificationRequest{dedupe_key, recipient_id, template, params, priority: CRITICAL|TRANSACTIONAL|BULK, purpose: SERVICE|MARKETING, channels?: [PUSH,SMS,EMAIL]}""",
    api_notes="Unique on (dedupe_key, created_at) is per partition. The daily partition plus a Redis 24 h key gives the dedupe window.",
    mech=[("Dedupe window", "Redis `SET dedupe:{key} NX EX 86400` is the fast check, and the DB unique constraint is the backstop within the partition."), ("Quiet hours", "Bulk messages scheduled outside quiet hours in the recipient's time zone.")],
    code="""if (!redis.setIfAbsent("dedupe:" + r.dedupeKey(), "1", Duration.ofHours(24))) return Status.SUPPRESSED_DUPLICATE;
if (r.purpose() == MARKETING && !consent.isAllowed(r.recipient(), MARKETING)) return Status.SUPPRESSED_NO_CONSENT;
queues.of(r.priority()).publish(Job.of(r, renderer.render(r, locales.of(r.recipient()))));""", cx="O(1).",
    fail=[F("Redis loss", "Errors", "Dedupe weaker", "DB unique backstop", "Possible dup across partitions"), F("Template missing locale", "Render fallback", "English sent", "Alert", "None")],
    alts=[["Third-party CPaaS orchestration", "Viable", "Faster", "Small team"]],
    adrs=[A("Event-mapped notifications", "III", "Producers shouldn't know templates.", [("Producers call send()", "Coupling"), ("Mapping rules on events", "Chosen")], "Mapping config.", "Decoupled.", "Mapping maintenance.", "N/A")],
    qa=[Q("Correctness", "A 'driver arriving' push is delivered after the trip already started. Can you prevent that?", "Include the trip state version in the request and set a TTL (APNs `apns-expiration`, FCM `ttl`) of ~60 s for trip updates. Before sending, the worker checks that the trip state version is still current (cheap cache lookup) and drops stale messages.", "")],
    tests=[T("Idempotency", "Duplicate events", "One send"), T("Compliance", "No consent", "Suppressed")],
    evo=["I: In-process with dedupe table", "E: Queue priorities", "R: Event-mapped service", "E: Redis dedupe", "E: Send-time optimization", "E: Regional"],
    ideas={"now": ["Dedupe"], "next": ["Event mapping"], "adv": ["Channel choice ML"], "rej": ["Logging OTP bodies"]})

sub(id="channel-delivery", comp="notifications", name="Channel Delivery & Provider Failover", phase="II", cat="Reliability · External integration",
    resp="Deliver jobs through push, SMS and email providers with rate limits, breakers, retries, fallback channels and delivery tracking.",
    inp="delivery jobs", out="provider submissions, statuses, fallbacks", deps="APNs/FCM, SMS, email providers", cons="Dispatcher (status), Analytics", own="delivery attempts",
    problem="Providers fail, throttle and report outcomes asynchronously. Critical messages need a fallback.", without="Lost OTPs and safety messages.",
    guar=["Critical jobs retried and fallen back until delivered or TTL", "Provider rate limits respected", "Status tracked per attempt"], nong=["End-user receipt for push (best-effort)"],
    usecase="SMS provider A returns 5xx for OTPs. The breaker opens, provider B sends the OTP within 2 s, and receipts confirm delivery.",
    derive="- Worker pools per priority + provider.\n- Retry with backoff for transient errors.\n- Invalid tokens (APNs 410) → remove token.",
    conc="Competing consumers; job acked after provider acceptance.", consistency="At-least-once delivery attempts; dedupe upstream.", idem="Provider message ids recorded. Retries of the same attempt reuse the job id (some providers dedupe).", order="Not guaranteed across messages, and trip messages are TTL-bounded.",
    restart="Unacked jobs redelivered.", scale="Workers scale per queue; provider throughput caps.", arch="RabbitMQ consumers per (priority, channel) → ChannelRouter (provider order, breakers) → sender adapters → receipt webhooks update status → fallback scheduler for critical.",
    modules=[["ChannelRouter", "Provider selection"], ["Senders", "APNs HTTP/2, FCM, SMS, SMTP/API"], ["ReceiptHandler", "Webhooks/feedback"], ["FallbackScheduler", "Critical-class fallback"]],
    d_arch=("""flowchart LR
  Q[["priority queues"]] --> W["workers"] --> CR["ChannelRouter"] --> P1["Provider A"] & P2["Provider B"]
  P1 & P2 -->|DLR/webhook| RH["ReceiptHandler"]
  RH --> FS["FallbackScheduler"] --> Q""", "Delivery with receipts and fallback."),
    d_seq=("""sequenceDiagram
  participant W as Worker
  participant A as SMS-A
  participant B as SMS-B
  W->>A: send OTP
  A-->>W: 503
  W->>W: breaker A failure
  W->>B: send OTP
  B-->>W: accepted id=b77
  B-->>W: DLR delivered""", "Failover."),
    d_state=("""stateDiagram-v2
  [*] --> Submitted
  Submitted --> Accepted
  Accepted --> Delivered
  Accepted --> Undelivered
  Submitted --> Retrying
  Retrying --> Submitted""", "Attempt state."),
    d_flow=("""flowchart LR
  J["job"] --> S["submit"] --> R["receipt"] --> ST["status"]""", "Tracking."),
    d_fail=("""flowchart TB
  BAD["invalid push token"] --> RM["remove token; fallback SMS for critical"]
  STORM["provider throttling"] --> RL["token bucket backoff"]""", "Feedback handling."),
    sql="CREATE TABLE notify.delivery_attempts (id uuid PRIMARY KEY, notification_id uuid NOT NULL, channel text, provider text, provider_ref text, status text, error text, at timestamptz NOT NULL DEFAULT now());",
    data="90 days.", api="""POST /webhooks/sms/{provider} (DLR)
APNs: POST /3/device/{token} (HTTP/2, JWT auth) headers apns-priority, apns-expiration""",
    mech=[("Token bucket per provider", "Smooths sending to provider limits and avoids 429 storms."), ("HTTP/2 multiplexing for APNs", "One connection carries thousands of concurrent pushes.")],
    code="""try { var ref = router.pick(job.channel()).send(job); attempts.record(job, ref, "ACCEPTED"); ack(job); }
catch (TransientProviderError e) { retry(job, backoff(job.attempt())); }
catch (InvalidRecipient e) { tokens.remove(job.to()); fallback.maybe(job); ack(job); }""", cx="O(1).",
    fail=[F("Provider outage", "Breaker", "Slower", "Failover", "None"), F("Duplicate DLR", "provider_ref", "None", "Idempotent update", "None")],
    alts=[["Single provider", "Phase I", "Simple", "Pilot"]],
    adrs=[A("Fallback only for critical class", "II", "Cost.", [("Fallback all", "Costly"), ("Critical only", "Chosen")], "OTP/safety fallback.", "Cost control.", "Some trip pushes missed.", "N/A")],
    qa=[Q("Cost", "SMS costs are rising. Options?", "Prefer push, then in-app, then WhatsApp (cheaper in many markets), with SMS as fallback. Shorten SMS templates to one segment (≤ 160 GSM-7 chars). Route by price per country across providers, and suppress SMS for recipients with recent push delivery.", "")],
    tests=[T("Failure", "Provider A down", "B used"), T("Unit", "APNs 410", "Token removed")],
    evo=["N: Phase I uses synchronous calls inside the dispatcher", "I: Queue workers + failover", "E: Receipts tracking", "E: Autoscaling", "E: Cost-based routing", "E: Regional providers"],
    ideas={"now": ["Breakers"], "next": ["Cost routing"], "adv": ["RCS messaging"], "rej": ["SMS-first"]})

# ======================================================================= Rider-Driver Comms
comp(id="rider-driver-comms", domain="communication", name="Rider–Driver Communication", tag="Communication · Privacy", phase="II", kind="Logical component",
     biz="Lets riders and drivers call or message each other about the pickup without revealing personal phone numbers.",
     eng="Number masking via a telephony provider (proxy sessions) and an in-app chat bound to the trip, with lifetimes and safety logging.",
     deploy="Module (II); communication service (IV).", data_own="proxy_sessions, chat_messages.",
     up=["trip", "notifications"], down=["support", "safety"], ext=["Telephony (Twilio Proxy-like)"],
     interfaces="`POST /v1/trips/{id}/call` → masked number; WebSocket chat channel per trip.",
     problem="Pickups need coordination, but sharing phone numbers creates harassment risk after the trip.",
     fr=["Masked calls", "In-app chat", "Expire after trip + 30 min", "Translate messages (Phase V)", "Keep metadata for safety"], nfr=["Call setup < 3 s", "Chat delivery < 1 s"],
     workload="≈ 30% of trips use contact.", success="Easy coordination, zero number exposure.", failure="Numbers leaked; harassment.",
     derive="A masked number pool is limited, so sessions map (rider, driver) pairs to pool numbers. Chat is part of the trip, so messages stored per trip with retention.",
     owns=["Proxy sessions", "Chat"], not_owns=["Phone numbers (Identity)"], sync=["Get masked number", "Send chat"], **{"async": ["Session expiry", "Safety scanning"]},
     boundary_why="Telephony integration and privacy rules are specific, and both trip and support depend on them.",
     hld=("""flowchart LR
  R["Rider"] -->|call masked #| TEL["Telephony proxy"] --> D["Driver"]
  MC["Masked calling"] --> TEL
  CH["In-app chat"] --> WS["Tracking WS gateway"]
  CH --> DB[("chat_messages")]""", "Calls via telephony, chat over the same WebSocket infrastructure as tracking."),
     seq=("""sequenceDiagram
  participant R as Rider
  participant M as MaskedCalling
  participant T as Telephony
  R->>M: call driver (trip 77)
  M->>T: create/get session(rider phone, driver phone)
  T-->>M: proxy +91 80 xxxx
  R->>T: dial proxy
  T->>T: bridge to driver""", "Masked call."),
     subdeps=[("masked-calling", "in-app-chat")],
     flow="Sessions created on demand and expired after trip end. Chat is delivered through tracking gateways.",
     data="`proxy_sessions(trip_id, provider_session_id, proxy_number, expires_at)`, `chat_messages(trip_id, seq, sender, body, at)`.",
     rel=[["Provider failure", "Fallback to in-app chat and VoIP."]], sec=[["Privacy", "Numbers never shown; sessions expire."], ["Safety", "Chat retained 90 days for incidents."]],
     adrs=[A("Masked numbers via provider", "II", "Privacy.", [("Show numbers", "Rejected"), ("Masking", "Chosen")], "Provider proxy.", "Privacy.", "Per-minute cost.", "In-app VoIP to cut cost (V).")],
     qa=[Q("Privacy", "How do you stop the driver calling the rider a week later?", "The proxy session expires at trip end + 30 min. After that the proxy number routes to a recorded message and the call is logged. For lost items, support initiates a fresh session.", "")],
     impl_order=["masked-calling", "in-app-chat"], pkg="""com.atlas.contact
├── calling (ProxySessionService)
└── chat    (ChatService)""",
     tests=[T("Privacy", "Call after expiry", "Not bridged"), T("Integration", "Chat over WS", "Delivered < 1 s")],
     evo=[("N", "Phase I shows driver first name only; support relays calls", "—", "—", "Pilot"), ("I", "Masked calling", "Sessions table", "Expiry", "Privacy"), ("E", "In-app chat", "Chat table", "—", "UX"), ("E", "Service", "—", "—", "Scale"), ("E", "VoIP + translation", "—", "—", "Cost"), ("E", "Regional telephony", "—", "—", "Global")],
     ideas={"now": ["Expiry"], "next": ["In-app VoIP"], "adv": ["Auto-translate chat"], "rej": ["Revealing numbers"]})

sub(id="masked-calling", comp="rider-driver-comms", name="Masked Calling", phase="II", cat="Privacy · Telephony",
    resp="Create time-bound proxy sessions so riders and drivers can call each other through masked numbers.",
    inp="call request for a trip", out="proxy number, call logs", deps="Telephony provider, Identity (numbers)", cons="Rider/driver apps, Safety", own="proxy_sessions",
    problem="Voice coordination without exposing numbers, with a limited number pool.", without="Number exposure.",
    guar=["Only trip participants are bridged", "Sessions expire at trip end + 30 min", "Call metadata logged"], nong=["Call quality"],
    usecase="Rider calls the driver at the airport. Proxy number +91-80-XXXX bridges them, and the call is logged with duration.",
    derive="- Proxy number reuse: a pool number can serve many sessions if the (caller) pair is unique per number.\n- Expire to recycle.",
    conc="Session per trip unique.", consistency="Provider holds the session. Our table mirrors it and is updated idempotently.", idem="Session creation idempotent by trip id.", order="Close after trip end, and late close is a no-op.",
    restart="Provider-side sessions persist.", scale="Pool size ≈ concurrent sessions / participants-per-number.", arch="Provider Proxy API with sessions keyed by trip, and a webhook for call events.",
    modules=[["SessionService", "Create/close"], ["CallLog", "Webhook metadata"]],
    d_arch=("""flowchart LR
  APP["App"] --> SS["SessionService"] --> PRV["Telephony"]
  PRV -->|call events| CL["CallLog"]""", "Provider-backed."),
    d_seq=("""sequenceDiagram
  participant A as App
  participant S as Sessions
  participant P as Provider
  A->>S: number for trip 77
  S->>P: create session(trip 77) idempotent
  P-->>S: proxy number
  S-->>A: +91-80-xxxx""", "Session creation."),
    d_state=("""stateDiagram-v2
  [*] --> Open
  Open --> Closed: trip end + 30m""", "Session lifecycle."),
    d_flow=("""flowchart LR
  PHONES["real numbers (Identity)"] --> P["provider only"]
  P --> PROXY["proxy shown"]""", "Real numbers stay server-side and at the provider."),
    d_fail=("""flowchart TB
  P["provider down"] --> V["in-app chat / VoIP fallback"]""", "Fallback."),
    sql="CREATE TABLE contact.proxy_sessions (trip_id uuid PRIMARY KEY, provider text, provider_session_id text, proxy_number text, expires_at timestamptz NOT NULL);",
    data="Call logs 90 days.", api="""POST /v1/trips/{id}/call -> {proxy_number}""",
    mech=[("Proxy pool reuse", "Provider maps (caller number, proxy number) → session, so one proxy number can serve many sessions as long as each caller has at most one active session on it.")],
    code="""public String numberFor(UUID trip, UUID caller) { return sessions.find(trip).orElseGet(() -> sessions.create(trip, provider.createSession(trip, participants(trip)))).proxyNumberFor(caller); }""", cx="O(1).",
    fail=[F("Provider outage", "Errors", "No calls", "Chat fallback", "None")],
    alts=[["In-app VoIP only", "Next", "Cheaper", "Data connectivity good"]],
    adrs=[A("Provider proxy", "II", "Speed to market.", [("Own telephony", "Complex"), ("Provider", "Chosen")], "Provider.", "Fast.", "Cost.", "VoIP at V.")],
    qa=[Q("Safety", "Should calls be recorded?", "Only where law allows and with notice. Default is metadata only (time, duration). Recording is enabled per market for safety programs with clear disclosure and short retention.", "")],
    tests=[T("Privacy", "Non-participant dials proxy", "Not bridged")],
    evo=["N: Phase I relies on support to relay calls", "I: Proxy sessions", "U: No change needed", "E: Service", "E: VoIP", "E: Regional"],
    ideas={"now": ["Expiry"], "next": ["VoIP"], "adv": ["Smart pickup instructions"], "rej": ["Number display"]})

sub(id="in-app-chat", comp="rider-driver-comms", name="In-App Chat", phase="III", cat="Real-time · Messaging",
    resp="Trip-scoped chat between rider and driver with quick replies, delivered over the live connection and stored for safety review.",
    inp="messages", out="delivered messages, read receipts", deps="Tracking WS gateways", cons="Rider/driver apps, Support, Safety", own="chat_messages",
    problem="Low-cost, low-friction coordination including for drivers who can't take calls while driving.", without="Calls while driving; missed pickups.",
    guar=["Messages ordered per trip", "Only participants can read/write", "Retention 90 days"], nong=["End-to-end encryption (needed for safety review)"],
    usecase="Driver taps quick reply 'I'm here, white Swift at gate 2'. The rider sees it in 300 ms.",
    derive="- Per-trip sequence numbers give ordering.\n- Delivery reuses tracking WebSockets.",
    conc="Sequence via `UPDATE chat_counters SET seq=seq+1 RETURNING seq` per trip.", consistency="Strong ordering per trip.", idem="client_msg_id unique per trip.", order="Server-assigned seq.",
    restart="Messages persisted before delivery.", scale="Small payloads; partition by day.", arch="POST message → persist with seq → route via tracking registry to recipient's gateway → ack/read receipts.",
    modules=[["ChatService", "Persist + seq"], ["Router", "Reuse tracking routing"], ["QuickReplies", "Templates per locale"]],
    d_arch=("""flowchart LR
  A["sender"] --> CS["ChatService"] --> DB[("chat_messages")]
  CS --> RT["Tracking router"] --> GW["WS gateway"] --> B["recipient"]""", "Reuses tracking infrastructure."),
    d_seq=("""sequenceDiagram
  participant D as Driver
  participant C as Chat
  participant G as Gateway
  participant R as Rider
  D->>C: send (client_msg_id)
  C->>C: persist seq 4
  C->>G: route
  G->>R: message seq 4""", "Delivery."),
    nostate="Messages are append-only.",
    d_flow=("""flowchart LR
  M["message"] --> S["seq"] --> D["deliver"] --> RR["read receipt"]""", "Flow."),
    d_fail=("""flowchart TB
  O["recipient offline"] --> P["push notification with preview"]""", "Offline fallback."),
    sql="CREATE TABLE contact.chat_messages (trip_id uuid, seq int, sender uuid NOT NULL, client_msg_id uuid NOT NULL, body text NOT NULL, at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(trip_id, seq), UNIQUE(trip_id, client_msg_id));",
    data="90 days.", api="""POST /v1/trips/{id}/messages {client_msg_id, body} -> {seq}
WS ← {"op":"chat","trip_id":…,"seq":4,"from":"driver","body":"…"}""",
    mech=[("Server-assigned sequence", "Gives a total order per trip regardless of client clocks.")],
    code="""@Transactional
public int send(UUID trip, UUID sender, UUID clientId, String body) { return msgs.findSeq(trip, clientId).orElseGet(() -> msgs.insert(trip, counters.next(trip), sender, clientId, body)); }""", cx="O(1).",
    fail=[F("Duplicate send", "client_msg_id", "None", "Return seq", "Single message")],
    alts=[["Third-party chat SDK", "Viable", "Faster", "No real-time infra yet"]],
    adrs=[A("Reuse tracking WS", "III", "Avoid second connection.", [("Separate chat infra", "Duplication"), ("Reuse", "Chosen")], "Reuse.", "Less infra.", "Coupled scaling.", "N/A")],
    qa=[Q("Safety", "How is abusive chat handled?", "Messages are scanned asynchronously for abuse keywords and ML toxicity, and flagged chats go to the safety queue. Either party can report from the chat, which attaches the transcript to an incident.", "")],
    tests=[T("Ordering", "Concurrent sends", "Strict seq")],
    evo=["N: No chat in pilot", "N: Masked calls only", "I: Chat over WS", "E: Service", "E: Translation", "E: Regional"],
    ideas={"now": ["Quick replies"], "next": ["Translation"], "adv": ["Voice notes"], "rej": ["E2E encryption without safety review path"]})

# ======================================================================= Risk & Fraud
comp(id="risk-fraud", domain="safety", name="Risk & Fraud Platform", tag="Trust · Decisioning", phase="II", kind="Logical component → deployable service (Phase IV)",
     biz="Stops fake accounts, stolen cards, promo abuse, GPS spoofing and collusion before they cost money, while keeping friction low for good users.",
     eng="Real-time decisioning combining rules, ML scores and device signals at key checkpoints (signup, add card, request, payout), with feedback loops from chargebacks and investigations.",
     deploy="Rules in monolith (II); Risk service (IV); streaming features + ML (V).", data_own="risk_decisions, rules, device fingerprints, entity graphs, labels.",
     up=["identity", "payment-vault", "location-ingest", "feature-store", "applied-models"], down=["otp-auth", "ride-request", "payments", "promotions", "payout-processing", "support"], ext=["Device intelligence SDKs", "Card network fraud signals"],
     interfaces="`score(checkpoint, entity, context) → {decision: ALLOW|CHALLENGE|BLOCK|REVIEW, score, reasons}`; signals ingestion; label feedback.",
     problem="Adversaries adapt quickly. Decisions must be fast (in the request path), explainable, and tunable without deploys, with low false positives.",
     fr=["Checkpoint decisions", "Rules editable by analysts", "ML scores", "Device fingerprinting", "Case review queue", "Feedback labels (chargebacks)"], nfr=["Decision p99 < 50 ms", "Fail-open/closed policy per checkpoint", "Rules deploy < 5 min"],
     workload="Every signup, card add, request, payout; Phase V ≈ 2K decisions/s.", success="Low fraud loss at low friction.", failure="Losses or blocking good users.",
     derive="Decisions are needed synchronously, so precomputed features (online store) and fast rules. Patterns emerge over time and across accounts, so streaming aggregates and graph links (shared devices/cards). Ground truth arrives late (chargebacks after 30–90 days), so a label pipeline.",
     owns=["Decisions", "Rules", "Fraud features", "Investigations"], not_owns=["Enforcement actions (owning domains apply restrictions)"], sync=["Score at checkpoints"], **{"async": ["Signals", "Feature aggregation", "Labels", "Case management"]},
     boundary_why="Risk advises and owning domains enforce. This keeps business state ownership clean and lets risk degrade without breaking flows.",
     hld=("""flowchart LR
  CP["Checkpoints: signup, card, request, payout"] --> RS["Risk scoring service"]
  RS --> RE["Rules engine"] & ML["Fraud models"] & DF["Device fingerprints"]
  RS --> FS[("online features")]
  SIG[["signals stream"]] --> AGG["Feature aggregation"] --> FS
  RS --> DEC[("decisions")]
  CB["Chargebacks / investigations"] --> LAB["Labels"] --> ML""", "Checkpoints call scoring. Scoring combines rules, models and device data over precomputed features. Labels close the loop."),
     seq=("""sequenceDiagram
  participant R as Ride request
  participant S as Risk
  participant F as Features
  R->>S: score(REQUEST, rider, ctx)
  S->>F: get(rider, device, card)
  S->>S: rules + model → 0.83
  S-->>R: CHALLENGE (3DS)""", "Checkpoint decision."),
     subdeps=[("risk-scoring", "rules-engine"), ("risk-scoring", "device-fingerprinting")],
     flow="Checkpoints call synchronously with context. The decision is logged with features and reasons. Domains apply challenges and blocks. Analysts tune rules, and labels retrain models.",
     data="`risk_decisions(id, checkpoint, entity, score, decision, reasons, features_hash, at)`, `rules(id, version, expr, action, status)`, `device_links(device_hash, account_id, first_seen)`.",
     rel=[["Timeout policy", "Per checkpoint: request ALLOW on timeout for low-value, payout BLOCK on timeout."], ["Shadow mode", "New rules run in shadow before enforcing."]], sec=[["Access", "Analyst RBAC; rule changes reviewed."], ["Privacy", "Device data purpose-limited to fraud."]],
     adrs=[A("Risk advises, domains enforce", "II", "Ownership.", [("Risk writes restrictions directly", "Coupling"), ("Decisions returned", "Chosen")], "Decisions only.", "Clean ownership.", "Domains must implement challenges.", "N/A")],
     qa=[Q("Architectural judgment", "Should the risk check at ride request fail open or closed when risk is down?", "Depends on value at risk. Ride requests for established riders (≥ 10 trips, good history cached locally) fail open, and new accounts and high-value products fail closed or require pre-auth. Payouts always fail closed. The policy is explicit per checkpoint and tested in game days.", "")],
     impl_order=["rules-engine", "device-fingerprinting", "risk-scoring"], pkg="""com.atlas.risk
├── scoring (RiskService, DecisionLog)
├── rules   (RuleEngine, RuleStore, ShadowEvaluator)
├── device  (FingerprintService, LinkGraph)
└── labels  (LabelIngest)""",
     tests=[T("Load", "2K decisions/s", "p99 < 50 ms"), T("Shadow", "New rule in shadow 7 days", "Precision/recall measured before enforce")],
     evo=[("N", "Phase I relies on payment pre-auth + manual review", "—", "—", "Pilot"), ("I", "Rules in monolith", "Decisions table", "Timeouts per checkpoint", "First abuse"), ("E", "Signals via events", "Streaming counters", "—", "Events"),
          ("R", "Risk service + device graph", "Online features", "Fail policies", "Scale"), ("R", "ML models + streaming features", "Feature store", "Shadow/champion-challenger", "Adaptive fraud"), ("E", "Regional models", "Residency", "—", "Global")],
     ideas={"now": ["Shadow mode"], "next": ["Device graph"], "adv": ["Graph neural networks for rings"], "rej": ["Hardcoded rules in domains"]})

sub(id="risk-scoring", comp="risk-fraud", name="Risk Scoring Service", phase="II", cat="Decisioning · Real-time",
    resp="Return a decision (allow/challenge/block/review) with reasons at each checkpoint within a strict latency budget.",
    inp="checkpoint, entity ids, context", out="decision + score + reasons", deps="Rules engine, Models, Feature store, Device fingerprints", cons="Identity, Request, Payments, Promotions, Payouts", own="risk_decisions",
    problem="Fast, explainable, auditable decisions under adversarial pressure.", without="Fraud loss or random friction.",
    guar=["Decision within deadline or policy default", "Every decision logged with inputs hash and reasons", "Deterministic for same inputs and versions"], nong=["Correctness of every decision"],
    usecase="New account, card used on 6 accounts in 24 h, device emulator flag → BLOCK at card add with reason CARD_VELOCITY+EMULATOR.",
    derive="- Fetch features (parallel), evaluate rules (deterministic), model score, then combine with policy.\n- Log for audit and training.",
    conc="Stateless request handling: concurrent decisions share only read-only rules and models, swapped by atomic reference.", consistency="Features eventually consistent (seconds).", idem="Same request id returns the logged decision.", order="Each decision is independent; features reflect events up to seconds ago.",
    restart="Stateless; loads rules/models at boot.", scale="Horizontal; feature store is the dependency.", arch="Fetch → rules → model → policy combiner → log (async) → respond.",
    modules=[["FeatureFetcher", "Parallel"], ["RuleEval", "Rules engine"], ["ModelEval", "Scores"], ["PolicyCombiner", "Final decision"], ["DecisionLog", "Async write"]],
    d_arch=("""flowchart LR
  REQ["checkpoint"] --> FF["FeatureFetcher"] --> FS[("features")]
  FF --> RE["Rules"] & MD["Model"] --> PC["PolicyCombiner"] --> RESP["decision"]
  PC --> DL["DecisionLog"]""", "Pipeline."),
    d_seq=("""sequenceDiagram
  participant C as Checkpoint
  participant R as Risk
  C->>R: score(CARD_ADD, user, card fp, device)
  R->>R: features (card on 6 accts/24h)
  R->>R: rule CARD_VELOCITY → BLOCK
  R-->>C: BLOCK [CARD_VELOCITY]""", "Decision."),
    nostate="Stateless per decision. Logged decisions are immutable.",
    d_flow=("""flowchart LR
  F["features"] --> R["rule hits"] --> M["model 0.91"] --> P["policy"] --> D["BLOCK"]""", "Combination."),
    d_fail=("""flowchart TB
  T["deadline exceeded"] --> DEF["checkpoint default policy"]""", "Defaults per checkpoint."),
    sql="""CREATE TABLE risk.risk_decisions (id uuid, request_id text NOT NULL, checkpoint text, entity_id uuid, score real, decision text, reasons text[], rules_version int, model_version text,
  features_hash bytea, at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(id, at), UNIQUE(request_id, at)) PARTITION BY RANGE (at);""",
    data="1–2 years for training/audit.", api="""rpc Score(ScoreRequest{request_id, checkpoint, entity_id, context}) returns (Decision{decision, score, reasons[]})""",
    mech=[("Policy combiner", "Rules can force decisions (hard block), and models provide graded scores mapped to actions by thresholds per checkpoint. This separates explainable hard rules from probabilistic signals.")],
    code="""Decision decide(List<RuleHit> hits, double score, CheckpointPolicy p) {
    return hits.stream().filter(RuleHit::isHard).findFirst().map(h -> Decision.of(h.action(), score, h.reason()))
        .orElseGet(() -> score >= p.block() ? Decision.block(score) : score >= p.challenge() ? Decision.challenge(score) : Decision.allow(score));
}""", cx="O(rules).",
    fail=[F("Feature store down", "Timeout", "Rules only", "Degraded", "None"), F("Model regression", "Decision-rate shift alert", "Friction spike", "Rollback model", "None")],
    alts=[["Vendor fraud platform", "Viable", "Faster start", "Phase II"]],
    adrs=[A("Per-checkpoint thresholds", "IV", "Different costs of error.", [("Global threshold", "Mismatched"), ("Per checkpoint", "Chosen")], "Config.", "Calibrated.", "More tuning.", "N/A")],
    qa=[Q("ML", "How do you evaluate a fraud model when labels arrive 60 days late?", "Use proxy early labels (account blocked by investigators, 3DS failures) for fast monitoring and true labels (chargebacks) for periodic evaluation. Keep a small randomized holdout (allow some risky-scored transactions under a loss cap) to measure true positive rate without selection bias.", "")],
    tests=[T("Load", "p99", "< 50 ms"), T("Unit", "Hard rule precedence", "Rule wins")],
    evo=["N: Phase I uses PSP fraud tools only", "I: Rules-based in monolith", "E: Streaming features", "R: Service + device graph", "E: ML models", "E: Regional"],
    ideas={"now": ["Decision logging"], "next": ["Models"], "adv": ["Graph ML"], "rej": ["Unlogged decisions"]})

sub(id="rules-engine", comp="risk-fraud", name="Fraud Rules Engine", phase="II", cat="Decisioning · Configuration",
    resp="Let analysts define, test, shadow and deploy fraud rules over features without code deploys.",
    inp="rule definitions, features", out="rule hits", deps="Feature catalog", cons="Risk scoring", own="rules",
    problem="Fraud patterns change weekly, and engineers can't be the bottleneck.", without="Slow response to attacks.",
    guar=["Rules validated against feature catalog", "Shadow before enforce", "Versioned and auditable"], nong=["Rule quality"],
    usecase="Analyst writes `card.accounts_24h >= 3 AND account.age_hours < 2 → BLOCK`. Shadow 48 h shows 92% precision, so it is enforced.",
    derive="- A safe expression language (CEL) instead of arbitrary code.\n- Shadow mode logs hits without effect.",
    conc="Atomic ruleset swap.", consistency="Rulesets propagate ≤ 60 s.", idem="Evaluation is pure: same features and ruleset version give the same hits.", order="Ruleset versions monotonic.",
    restart="Load active ruleset.", scale="Compiled expressions, μs per rule.", arch="Rules in CEL, compiled at publish. Evaluation over a feature map.",
    modules=[["RuleStore", "Versions"], ["Compiler", "CEL compile + type-check"], ["Evaluator", "Runtime"], ["ShadowRunner", "Log-only"]],
    d_arch=("""flowchart LR
  AN["Analyst UI"] --> RS["RuleStore"] --> CMP["Compiler"] --> RT["Runtime ruleset"]
  RT --> EV["Evaluator"] --> HITS["hits"]
  RT --> SH["Shadow"] --> LOG["shadow log"]""", "Authoring to runtime."),
    d_seq=("""sequenceDiagram
  participant A as Analyst
  participant S as RuleStore
  participant N as Nodes
  A->>S: publish rule v12 (shadow)
  S->>N: ruleset v12
  N->>N: evaluate, log shadow hits""", "Publish."),
    d_state=("""stateDiagram-v2
  [*] --> Draft
  Draft --> Shadow
  Shadow --> Enforced
  Enforced --> Retired""", "Rule lifecycle."),
    d_flow=("""flowchart LR
  E["CEL expr"] --> C["compiled"] --> V["eval(features)"]""", "Compile once, evaluate many."),
    d_fail=("""flowchart TB
  B["bad rule blocks 30% of users"] --> K["kill switch per rule + auto-disable on decision spike"]""", "Guardrails."),
    sql="CREATE TABLE risk.rules (id uuid, version int, checkpoint text, expr text NOT NULL, action text NOT NULL, mode text NOT NULL, author uuid, approved_by uuid, PRIMARY KEY(id, version));",
    data="All versions kept.", api="""POST /internal/risk/rules {checkpoint, expr, action, mode:SHADOW}""",
    mech=[("CEL", "A non-Turing-complete expression language with type-checking: safe to run analyst-authored logic in the hot path."), ("Auto-disable", "If a rule's hit rate exceeds N× its shadow baseline, it is disabled automatically and paged.")],
    code="""CelProgram p = cel.compile(rule.expr(), featureTypes); boolean hit = (Boolean) p.eval(features);""", cx="O(rules).",
    fail=[F("Over-blocking rule", "Spike", "Good users blocked", "Auto-disable", "Restrictions reversible")],
    alts=[["Drools", "Viable", "Heavier", "Complex inference"]],
    adrs=[A("CEL", "II", "Safety + speed.", [("Groovy scripts", "Unsafe"), ("CEL", "Chosen")], "CEL.", "Safe.", "Less expressive.", "N/A")],
    qa=[Q("Operations", "Who approves a new blocking rule?", "Four-eyes: the author plus a second analyst, after shadow metrics (precision on recent labels, projected block volume) are attached to the change. Emergency rules can be enforced immediately with post-hoc review within 24 h.", "")],
    tests=[T("Unit", "Type error rule", "Rejected at publish"), T("Integration", "Shadow", "No effect on decisions")],
    evo=["N: No rules engine in pilot", "I: Rules with shadow", "E: Streaming features in rules", "E: Distributed ruleset", "E: Auto-disable", "E: Regional rulesets"],
    ideas={"now": ["Shadow"], "next": ["Auto-disable"], "adv": ["Rule suggestions from ML"], "rej": ["Code deploys per rule"]})

sub(id="device-fingerprinting", comp="risk-fraud", name="Device Fingerprinting & Link Graph", phase="IV", cat="Signals · Graph",
    resp="Identify devices across accounts (attestation, hardware signals) and link accounts sharing devices, cards and payout accounts to expose fraud rings.",
    inp="device signals from SDK, account events", out="device hash, link counts, ring scores", deps="Attestation APIs, Identity, Payments", cons="Risk scoring", own="device_links, entity graph",
    problem="Fraudsters create many accounts; individual account signals look clean, but links reveal rings.", without="Fake-account farms abusing promotions.",
    guar=["Stable device hash within privacy policy", "Link counts updated within minutes"], nong=["Unique device identification (spoofable)"],
    usecase="40 accounts share 3 devices and 2 payout bank accounts, which marks them as a ring. Promo redemptions are blocked and accounts are routed to review.",
    derive="- Hash stable signals (attestation key id, install id) with a keyed hash (privacy).\n- Graph edges account–device, account–card, account–bank. Connected components give ring sizes.",
    conc="Edge inserts idempotent.", consistency="Eventual (minutes).", idem="Edges have a composite primary key, so re-processing a signal inserts nothing new and union operations are no-ops.", order="Edges are set-based and commutative, so order doesn't matter.",
    restart="Graph rebuildable from events.", scale="Phase V: graph DB or incremental union-find in streaming.", arch="Signals → edges table → incremental union-find (component ids) → features (component size, risky neighbours).",
    modules=[["SignalCollector", "SDK + attestation"], ["EdgeStore", "Typed edges"], ["ComponentTracker", "Union-find"], ["GraphFeatures", "Component size, labels"]],
    d_arch=("""flowchart LR
  SDK["device signals"] --> SC["SignalCollector"] --> ES[("edges")]
  ACC["account events"] --> ES
  ES --> CT["ComponentTracker"] --> GF["GraphFeatures"] --> FS[("online features")]""", "Edges to features."),
    d_seq=("""sequenceDiagram
  participant A as App
  participant S as Collector
  participant G as Graph
  A->>S: signals(attestation, install_id)
  S->>G: edge(account, device_hash)
  G->>G: union(account comp, device comp)
  G-->>S: component size 40""", "Linking."),
    nostate="Graph data with no lifecycle.",
    d_flow=("""flowchart LR
  ACC1["acct A"] --- DEV1["device x"] --- ACC2["acct B"] --- CARD1["card y"] --- ACC3["acct C"]""", "A ring via shared entities."),
    d_fail=("""flowchart TB
  S["shared family phone"] --> F["false link"] --> W["weight edges; require multiple link types"]""", "False positives handled by weighting."),
    sql="CREATE TABLE risk.edges (src_type text, src_id text, dst_type text, dst_id text, first_seen timestamptz, PRIMARY KEY(src_type, src_id, dst_type, dst_id));",
    data="Retention 1 year; keyed hashes.", api="""GraphFeatures features(UUID account)  // component_size, blocked_neighbors, shared_payout_accounts""",
    mech=[("Incremental union-find", "Each new edge unions two components in near-constant amortized time (path compression + union by rank), giving component ids without global graph scans.")],
    code="""int find(int x) { return parent[x] == x ? x : (parent[x] = find(parent[x])); }
void union(int a, int b) { a = find(a); b = find(b); if (a == b) return; if (rank[a] < rank[b]) { int t = a; a = b; b = t; } parent[b] = a; size[a] += size[b]; if (rank[a] == rank[b]) rank[a]++; }""", cx="α(n) amortized.",
    fail=[F("Hub nodes (public Wi-Fi)", "Huge components", "Noise", "Exclude low-specificity signals", "None")],
    alts=[["Graph DB (Neo4j)", "Viable", "Rich queries", "Investigations"], ["Vendor device intel", "Complement", "Better signals", "Always"]],
    adrs=[A("Union-find features + graph DB for investigation", "IV", "Online + offline needs.", [("Graph DB online", "Latency"), ("Union-find online", "Chosen")], "Both.", "Fast features.", "Two stores.", "N/A")],
    qa=[Q("Privacy", "Is device fingerprinting lawful?", "Under GDPR it may rely on legitimate interest for fraud prevention, with disclosure, minimization (keyed hashes, no raw identifiers beyond need), purpose limitation (fraud only) and retention limits. A DPIA documents it.", "")],
    tests=[T("Unit", "Union-find", "Correct components"), T("Integration", "Ring simulation", "Detected")],
    evo=["N: Not needed in pilot", "N: Basic device id only", "N: Basic device id only", "I: Link graph", "E: Streaming union-find", "E: Regional graphs"],
    ideas={"now": ["n/a"], "next": ["Streaming"], "adv": ["GNN"], "rej": ["Raw identifiers stored"]})

# ======================================================================= Safety
comp(id="safety", domain="safety", name="Rider & Driver Safety", tag="Trust · Critical", phase="I", kind="Logical component; emergency path independently deployed (Phase IV)",
     biz="Helps people in danger immediately (emergency button, live location to responders), detects risky trips, and investigates incidents to prevent recurrence.",
     eng="A highest-availability emergency path, anomaly detection on live trips, and an incident case-management system with evidence from trips, chats and locations.",
     deploy="Module (I); SOS path isolated with its own deployment and minimal dependencies (IV).", data_own="emergency_events, incidents, evidence references, safety checks.",
     up=["trip", "location-ingest", "trip-tracking", "notifications", "rider-driver-comms"], down=["support", "risk-fraud", "admin-policy"], ext=["Emergency services APIs (RapidSOS, 112)", "Telephony"],
     interfaces="`POST /v1/sos` (minimal deps), `POST /v1/safety/reports`; events `EmergencyTriggered`, `TripAnomalyDetected`.",
     problem="In an emergency every second matters and every dependency is a risk. Many safety issues surface only as patterns (unexpected stops, route deviation).",
     fr=["SOS with live location to emergency services and safety team", "Trusted contacts sharing", "Anomaly checks (long stop, deviation)", "Incident reports and investigation", "Driver/rider deactivation recommendations"],
     nfr=["SOS path availability 99.99%+ with degraded fallbacks", "SOS to agent alert < 5 s", "Evidence preserved (legal hold)"],
     workload="Rare but critical; anomaly checks on all active trips.", success="Fast response; fewer incidents.", failure="SOS lost; evidence missing.",
     derive="SOS must work even if most services are down, so a minimal-dependency path: direct to a dedicated SOS service with its own DB, pre-cached trip context on device, and multi-channel alerting. Investigations need immutable evidence, so legal holds on locations and chats.",
     owns=["SOS handling", "Anomaly detection", "Incidents"], not_owns=["Account restrictions (owning domains, via commands)", "Location storage"], sync=["SOS", "Report"], **{"async": ["Anomaly detection", "Investigations"]},
     boundary_why="Safety has unique availability and legal requirements. Isolation prevents a payment outage from impacting emergency handling.",
     hld=("""flowchart LR
  APP["App SOS button"] -->|direct, minimal deps| SOS["Emergency SOS service"]
  SOS --> ES["Emergency services API"] & AG["Safety agents console"] & TC["Trusted contacts"]
  SOS --> SDB[("sos store")]
  TRK["live positions"] --> AD["Trip anomaly detection"] --> CHK["check-in push"] --> IM["Incident management"]
  REP["reports"] --> IM --> HOLD["Legal hold on evidence"]""", "A minimal emergency path, plus anomaly detection and incident management."),
     seq=("""sequenceDiagram
  participant R as Rider app
  participant S as SOS
  participant E as Emergency API
  participant A as Agent
  R->>S: POST /sos (trip, location, cached driver/vehicle)
  S->>S: persist
  par
    S->>E: share location + details
    S->>A: page safety agent
  end
  S-->>R: 200 + call 112 prompt
  loop every 5s
    R->>S: location
  end""", "SOS."),
     subdeps=[("incident-management", "emergency-sos")],
     flow="SOS goes direct with app-cached context. Anomaly detection consumes positions and trip state. Incidents gather evidence and decisions.",
     data="`emergency_events(id, trip_id, user_id, role, lat, lng, status, at)`, `incidents(id, type, severity, state, trip_id, reporter, assignee, decision)`, `evidence(incident_id, kind, ref, hold_until)`.",
     rel=[["SOS isolation", "Separate deployment, DB and on-call; app retries + SMS fallback."], ["Evidence", "Legal hold overrides retention jobs."]], sec=[["Access", "Safety team only; strict audit."], ["Privacy", "Evidence access logged; minimal sharing with authorities per legal process."]],
     adrs=[A("Isolated SOS path", "IV", "Availability.", [("SOS through normal stack", "Shared failure"), ("Isolated", "Chosen")], "Isolated service.", "Survives other outages.", "Duplicate infra.", "N/A")],
     qa=[Q("Reliability", "The entire main API is down. Does SOS still work?", "Yes, by design. The SOS endpoint is on a separate domain and edge path, with its own service and DB. The app caches trip context (driver, plate, route) locally, so SOS needs no other service. If the network is down, the app falls back to dialling the local emergency number and sending an SMS with location to the SOS short code.", "")],
     impl_order=["emergency-sos", "incident-management"], pkg="""com.atlas.safety
├── sos       (SosController, EmergencyDispatcher)
├── anomaly   (TripAnomalyDetector)
└── incidents (IncidentService, EvidenceHolds)""",
     tests=[T("Game day", "Main stack down", "SOS succeeds end-to-end"), T("Latency", "SOS to agent", "< 5 s")],
     evo=[("I", "SOS in monolith calls emergency number + alerts ops", "PG", "—", "Pilot"), ("E", "Anomaly checks", "—", "Retries + SMS fallback", "Reliability"), ("E", "Event-driven anomalies", "Kafka", "—", "Events"),
          ("R", "Isolated SOS service", "Own DB", "Separate edge path", "Isolation"), ("E", "ML anomaly models", "Streaming", "—", "Scale"), ("E", "Regional emergency integrations", "In-country", "—", "Global")],
     ideas={"now": ["App-cached context"], "next": ["Isolated path"], "adv": ["Audio recording opt-in"], "rej": ["SOS via generic API stack"]})

sub(id="emergency-sos", comp="safety", name="Emergency SOS", phase="I", cat="Safety · High availability",
    resp="Accept emergency triggers, notify emergency services and safety agents immediately, stream live location, and keep working when the rest of the platform is degraded.",
    inp="SOS trigger with app-cached context, location stream", out="emergency notifications, agent alerts, case", deps="Emergency API, Paging, Telephony (minimal)", cons="Safety agents, Incident management", own="emergency_events",
    problem="Deliver help fast under any platform condition.", without="Lives at risk.",
    guar=["Persist SOS before acknowledging", "Agent paged within 5 s", "Location streamed every 5 s until resolved"], nong=["Emergency service response time"],
    usecase="Rider presses SOS. Within 3 s the safety agent sees the rider, driver, plate, live location and route, and emergency services receive location and vehicle details.",
    derive="- Minimal dependencies: the app sends everything needed.\n- Multi-path alerting (pager, console, SMS to on-call).\n- Idempotent per (trip, trigger) to tolerate retries.",
    conc="One open SOS per trip (unique partial index).", consistency="Strong in SOS DB.", idem="client_sos_id unique.", order="Location updates appended with ts.",
    restart="Open SOS events re-alerted on restart.", scale="Low volume; capacity for spikes (disasters).", arch="Separate service: persist → fan-out alerts (parallel, each with retries) → location stream ingestion → agent console.",
    modules=[["SosEndpoint", "Validate, persist"], ["AlertFanout", "Emergency API, pager, console"], ["LocationStream", "5 s updates"], ["Escalation", "Unacked alerts escalate"]],
    d_arch=("""flowchart LR
  APP["App"] --> EP["SosEndpoint"] --> DB[("sos DB")]
  EP --> AF["AlertFanout"] --> EMS["Emergency API"] & PG["Pager"] & CON["Agent console"]
  APP --> LS["LocationStream"] --> DB
  ESC["Escalation timer"] --> PG""", "A self-contained service."),
    d_seq=("""sequenceDiagram
  participant A as App
  participant S as SOS
  participant P as Pager
  A->>S: SOS (id s1)
  S->>S: insert (unique s1)
  S->>P: page on-call safety
  S-->>A: ack
  P--xS: not acked 60s
  S->>P: escalate to lead""", "Escalation."),
    d_state=("""stateDiagram-v2
  [*] --> Triggered
  Triggered --> Acknowledged: agent
  Acknowledged --> Resolved
  Triggered --> Escalated: 60 s no ack
  Escalated --> Acknowledged""", "SOS lifecycle."),
    d_flow=("""flowchart LR
  CTX["cached: driver, plate, route"] --> SOS["SOS record"] --> AG["agent view"]""", "The context travels with the trigger."),
    d_fail=("""flowchart TB
  N["no data network"] --> SMS["SMS to short code + dial emergency number"]
  E["emergency API down"] --> AGT["agent calls emergency services manually"]""", "Every path has a manual fallback."),
    sql="""CREATE TABLE safety.emergency_events (id uuid PRIMARY KEY, client_sos_id uuid NOT NULL UNIQUE, trip_id uuid, user_id uuid NOT NULL, role text, context jsonb NOT NULL,
  status text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), acked_by uuid, acked_at timestamptz);
CREATE UNIQUE INDEX one_open_sos_per_trip ON safety.emergency_events(trip_id) WHERE status IN ('Triggered','Escalated','Acknowledged');""",
    data="Legal hold by default; retention per law.", api="""POST https://sos.atlas.example/v1/sos {client_sos_id, trip_id, lat, lng, context:{driver, plate, route}} -> 200""",
    mech=[("Dependency minimization", "The client sends context and the server needs only its own DB and alerting. Every removed dependency removes a failure mode."), ("Escalation timers", "Unacknowledged alerts escalate up a chain automatically.")],
    code="""public Ack trigger(SosRequest r) {
    var e = repo.insertIfAbsent(r);                  // unique client_sos_id
    alerts.fanOutAsync(e);                           // each channel retried independently
    return Ack.of(e.id(), localEmergencyNumber(r.lat(), r.lng()));
}""", cx="O(1).",
    fail=[F("Main stack outage", "N/A", "None for SOS", "Isolated path", "None"), F("Duplicate trigger", "Unique id", "None", "Same event", "One case")],
    alts=[["Third-party safety SDK", "Complement", "Emergency integrations", "Markets with providers"]],
    adrs=[A("Separate domain + edge path", "IV", "Isolation.", [("Shared gateway", "Shared failure"), ("Separate", "Chosen")], "Separate.", "Isolation.", "More infra.", "N/A")],
    qa=[Q("Reliability", "How do you test SOS without bothering emergency services?", "Use a test mode flag routed to a sandbox emergency API and a test agent queue, with synthetic SOS every 5 minutes in production (canary) measuring end-to-end latency. Real emergency API integration is tested with provider-supported test numbers.", "")],
    tests=[T("Game day", "Kill all non-SOS services", "SOS works"), T("Canary", "Synthetic SOS", "Agent alert < 5 s")],
    evo=["I: In monolith with direct paging", "E: SMS fallback + escalation", "E: Events to incidents", "R: Isolated service", "E: Emergency API integrations", "E: Regional"],
    ideas={"now": ["Cached context"], "next": ["Isolation"], "adv": ["Crash detection from sensors"], "rej": ["SOS behind feature flags"]})

sub(id="incident-management", comp="safety", name="Incident Management & Trip Anomaly Detection", phase="II", cat="Safety · Case management",
    resp="Detect anomalous trips (long unexpected stops, route deviations), run check-ins, and manage reported incidents from intake through investigation and decision with preserved evidence.",
    inp="positions, trip events, reports, SOS events", out="check-ins, incidents, decisions (deactivation recommendations)", deps="Tracking/ETA refresh (deviation), Notifications, Location history, Chat, Support", cons="Safety team, Owning domains (enforcement)", own="incidents, evidence holds",
    problem="Most safety issues surface as signals or reports. They need fast triage, consistent investigation and preserved evidence.", without="Missed signals, lost evidence, inconsistent decisions.",
    guar=["Anomaly → check-in within 60 s", "Incident evidence placed on legal hold at creation", "Decisions recorded with reasons and reviewer"], nong=["Determining guilt automatically"],
    usecase="Trip stops for 12 minutes on a highway shoulder at 2 a.m. Anomaly detected, check-in push 'Is everything OK?' sent to both, no response in 60 s, so a safety agent calls and an incident is opened with evidence held.",
    derive="- Anomaly = rules over trip state (STARTED) + position + time (stop > N min in non-POI area).\n- Incidents are cases with a state machine and SLAs by severity.\n- Evidence = references to location, chat and call logs plus a hold flag.",
    conc="Incident updates optimistic-locked.", consistency="Strong for incidents; evidence holds applied synchronously before ack.", idem="Anomaly per (trip, type) deduped.", order="Detection uses event time.",
    restart="Detector state rebuildable from active trips.", scale="Active trips × rules; streaming in Phase V.", arch="Detector (per active trip timers) → check-in → escalation. Incident service with severity-based queues and an evidence-hold API calling Location history and Chat retention.",
    modules=[["TripAnomalyDetector", "Stop/deviation rules"], ["CheckIn", "Push + response"], ["IncidentService", "Cases"], ["EvidenceHolds", "Legal hold calls"]],
    d_arch=("""flowchart LR
  POS["positions"] --> TAD["TripAnomalyDetector"] --> CI["CheckIn"] --> IS["IncidentService"]
  REP["reports"] --> IS
  SOS["SOS"] --> IS
  IS --> EH["EvidenceHolds"] --> LH["Location history"] & CH["Chat"]""", "Detection, check-in and cases."),
    d_seq=("""sequenceDiagram
  participant D as Detector
  participant C as CheckIn
  participant I as Incidents
  D->>C: long stop trip 77
  C->>C: push both parties
  C--xC: no response 60 s
  C->>I: open incident (high)
  I->>I: holds on evidence""", "Escalation."),
    d_state=("""stateDiagram-v2
  [*] --> Open
  Open --> Investigating
  Investigating --> Decided
  Decided --> Appealed
  Appealed --> Decided
  Decided --> Closed""", "Incident lifecycle."),
    d_flow=("""flowchart LR
  E["evidence refs"] --> H["hold_until"] --> R["retention jobs skip"]""", "Holds."),
    d_fail=("""flowchart TB
  F["false positive (traffic jam)"] --> S["suppress if speed context shows congestion"]""", "False-positive control."),
    sql="""CREATE TABLE safety.incidents (id uuid PRIMARY KEY, type text, severity text, state text, trip_id uuid, reporter uuid, subject uuid, assignee uuid, decision text, reasons text, version int, created_at timestamptz);
CREATE TABLE safety.evidence (incident_id uuid, kind text, ref text, hold_until date, PRIMARY KEY(incident_id, kind, ref));""",
    data="Incidents retained per law (years).", api="""POST /v1/safety/reports {trip_id, category, description}
POST /internal/incidents/{id}/decision {decision, reasons}
event TripAnomalyDetected{trip_id, type, at}""",
    mech=[("Rule-based anomaly detection with context", "Stops are anomalous only outside POIs and congestion. Combining signals reduces false alarms that erode trust in check-ins.")],
    code="""if (trip.state() == STARTED && stop.duration().toMinutes() >= 8 && !pois.near(stop.pos()) && !traffic.congested(stop.pos())) checkIn.start(trip, "LONG_STOP");""", cx="O(1) per position.",
    fail=[F("Check-in push fails", "No delivery", "Missed check", "SMS fallback", "None")],
    alts=[["Third-party case tools", "Viable", "Faster", "Early phases"]],
    adrs=[A("Holds at creation", "II", "Evidence loss.", [("Manual holds", "Forgotten"), ("Automatic", "Chosen")], "Auto.", "Preserved.", "Storage.", "N/A")],
    qa=[Q("Fairness", "How do you avoid deactivating drivers based on false reports?", "Decisions require evidence review (trip data, chat, history), not only reports. There is a structured severity matrix and second-reviewer approval for permanent deactivation, plus an appeal process. Report-weaponization patterns (same rider reports many drivers) are flagged.", "")],
    tests=[T("Unit", "Stop at a petrol station POI", "No anomaly"), T("Integration", "No check-in response", "Incident opened")],
    evo=["N: Phase I handles reports via support tickets", "I: Incidents + simple anomaly checks", "E: Event-driven detection", "E: Severity queues and SLAs", "R: Streaming ML anomaly models", "E: Regional teams"],
    ideas={"now": ["Holds"], "next": ["Check-ins"], "adv": ["Audio-based detection"], "rej": ["Automatic deactivation on single report"]})
