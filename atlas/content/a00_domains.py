from model import domain

K = "Logical component"
domain("identity", "Identity and Access", "A", "Who a caller is (authentication), what they may do (authorization), and the lifecycle of credentials, sessions, devices and service identities. Every other domain trusts the principal this domain produces.",
       [["Identity & Authentication", "Logical component in the Phase I monolith → deployable service in Phase IV"], ["Authorization & Access Control", "Library + policy service (Phase IV)"],
        ["Identity federation (enterprise SSO, Apple/Google)", "Subcomponent of Identity"], ["Token signing keys", "Platform capability (KMS)"], ["SMS/email OTP providers", "External integration"]])
domain("rider", "Rider Platform", "B", "The rider as a customer: profile, saved places, preferences, consent and account lifecycle. Owns rider-facing customer data, not identity credentials or payment instruments.",
       [["Rider Profile", "Logical component (stays inside the Rider service from Phase IV)"], ["Account lifecycle", "Subcomponent"], ["Consent records", "Subcomponent; legal record"]])
domain("driver", "Driver Platform", "C", "Supply side: onboarding drivers, verifying documents and backgrounds, controlling who may go online, and vehicles/fleets.",
       [["Driver Onboarding", "Logical component → deployable service (Phase IV)"], ["Driver Supply State", "Logical component → deployable service (Phase IV), hot path"], ["Fleet & Vehicle", "Logical component"], ["Background-check vendor", "External integration"]])
domain("location", "Location and Geospatial", "D", "High-rate GPS ingestion, cleaning, indexing drivers by space for proximity search, geofences, and retained breadcrumbs for fares and safety.",
       [["Location Ingestion", "Deployable service from Phase III (highest write rate in the system)"], ["Geospatial Index", "Deployable service from Phase IV"], ["Location History", "Storage component"], ["H3 library", "Infrastructure dependency (open-source library)"]])
domain("routing", "Maps and Routing", "E", "Turning addresses into coordinates, coordinates into routes, and routes into ETAs that pricing, dispatch and riders rely on.",
       [["Maps Gateway", "Anti-corruption layer over external map providers"], ["Routing & ETA", "Logical component → service with in-house road graph (Phase V)"], ["Map/traffic providers", "External integration"]])
domain("pricing", "Discovery and Pricing", "F", "What products a rider can choose, how much each costs right now, and which promotions apply. Prices must be explainable and auditable.",
       [["Product Catalog & Discovery", "Logical component"], ["Pricing Engine", "Logical component → service (Phase IV)"], ["Promotions", "Logical component"], ["Surge", "Subcomponent of Pricing (stream-computed from Phase V)"]])
domain("dispatch", "Ride Request and Dispatch", "G", "Accepting a ride request exactly once, finding and ranking drivers, offering the trip, and committing one driver to one request atomically.",
       [["Ride Request", "Logical component"], ["Matching & Dispatch", "Deployable service (Phase IV), city-sharded (Phase V)"], ["Cancellation & Reassignment", "Logical component"]])
domain("trip", "Trip Management", "H", "The trip from assignment to completion: the authoritative state machine, live tracking, and the final fare.",
       [["Trip Lifecycle", "Logical component → service (Phase IV); owns the trip state"], ["Real-time Tracking", "Deployable service (Phase III, connection-heavy)"], ["Fare Finalization", "Logical component"]])
domain("payments", "Payments and Financial Systems", "I", "Moving money correctly: authorizing and capturing rider payments, recording every movement in a double-entry ledger, wallets, refunds, driver earnings, payouts and receipts.",
       [["Payment Orchestration", "Deployable service (Phase IV), PCI scope minimized"], ["Ledger", "Deployable service (Phase IV), system of record for money"], ["Wallet & Credits", "Logical component"], ["Driver Earnings & Payouts", "Logical component"], ["Receipts & Invoicing", "Logical component"], ["PSPs (Stripe/Adyen)", "External integration"]])
domain("communication", "Communications", "J", "Reaching riders and drivers reliably through push, SMS, email and in-app channels, and letting them reach each other without exposing phone numbers.",
       [["Notification Platform", "Platform capability (shared)"], ["Rider–Driver Communication", "Logical component"], ["APNs/FCM/SMS/email providers", "External integrations"]])
domain("safety", "Trust, Safety and Risk", "K", "Preventing fraud and abuse and protecting people physically: risk scoring, rules, device signals, emergency response and incident handling.",
       [["Risk & Fraud", "Deployable service (Phase IV)"], ["Safety", "Logical component; emergency path has the strictest availability"]])
domain("support", "Customer and Internal Operations", "L", "Humans helping humans: support tickets, disputes, manual interventions and the admin/policy tooling operators use.",
       [["Support & Disputes", "Logical component"], ["Admin & Policy", "Internal application + configuration plane"]])
domain("analytics", "Data and Analytics", "M", "Getting every business event into analytics safely, running experiments, and governing data quality and lineage.",
       [["Event Pipeline", "Platform capability"], ["Experimentation", "Platform capability"], ["Data Governance", "Platform capability"]])
domain("ml", "AI and Machine Learning", "N", "Feature management, training, registry, serving and monitoring, plus the applied models: ETA, demand forecasting and match scoring.",
       [["Feature Store", "Platform capability (Phase IV)"], ["ML Platform", "Platform capability"], ["Applied Models", "Logical models consumed by Routing, Pricing and Dispatch"]])
domain("platform", "Platform and Infrastructure", "O", "The shared runtime: edge/API gateway, queues and event bus, workflows and timers, discovery, configuration, secrets and caching.",
       [["API Gateway & Edge", "Infrastructure"], ["Messaging Backbone", "Infrastructure dependency"], ["Workflow & Scheduling", "Platform capability"], ["Service Runtime", "Platform capability"]])
domain("reliability", "Security, Reliability and Operations", "P", "Observability, resilience patterns, delivery and capacity management, and disaster recovery.",
       [["Observability", "Platform capability"], ["Resilience Toolkit", "Library/platform capability"], ["Delivery & Capacity", "Platform capability"], ["Disaster Recovery", "Operational capability"]])
domain("global", "Global Infrastructure and Privacy", "Q", "Multi-region placement, regional data ownership, failover, residency and privacy infrastructure (erasure, PII protection).",
       [["Global Regions", "Infrastructure (Phase VI)"], ["Privacy Infrastructure", "Platform capability (Phase II onward)"]])
