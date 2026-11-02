"""Expanded synchronous/asynchronous boundaries, events and states for workflows.

Applied after w01_workflows so each workflow page states its boundaries precisely.
"""
from model import REG

D = {
    2: dict(sync="POST /me/contact and the verify call are synchronous request/response; the step-up check happens inline."),
    3: dict(sync="Applicant step saves and document uploads are synchronous; everything after submission is asynchronous."),
    6: dict(sync="Only the batch upload and its acknowledgement (after durable produce) are synchronous."),
    7: dict(states="Quote: (none) → Issued; it later becomes Used or Expired.", events="QuoteIssued{quote_id, rider_id, product, price, surge, rate_card_version} for analytics and pricing audit.",
            sync="POST /quotes, including routing, surge read and promotion eligibility within a 250 ms budget.", **{"async": "QuoteIssued export to the lake; audit verification jobs."}),
    8: dict(events="RideRequested{request_id, rider_id, city, product, pickup, dropoff, quote_id} via outbox."),
    9: dict(**{"async": "None in the search itself. Results are logged asynchronously for recall measurement (candidates vs eventual match)."}),
    10: dict(events="No business events. Ranking score components are logged to the lake as dispatch.ranking_logs.", **{"async": "Score logging and model feature logging for training."}),
    11: dict(events="OfferSent{offer_id, request_id, driver_id}, OfferResolved{offer_id, outcome}.", sync="POST /offers/{id}/accept|decline from the driver app; tryReserve call to Supply."),
    12: dict(sync="Supply.assign (the pivot), Trip.createIfAbsent and Request.markAssigned, called in order by the committer with retries."),
    13: dict(events="DriverArrived{trip_id, at, distance_to_pickup_m}.", sync="POST /trips/{id}/arrive with location guard."),
    14: dict(events="TripStarted{trip_id, at}; TripAnomalyDetected when checks fire.", sync="POST /trips/{id}/start (PIN verification inline)."),
    15: dict(states="No business state changes. Each subscriber's last-sent version advances.", events="Position updates on the location stream; no new business events.",
             sync="WebSocket subscribe (authorized) and snapshot delivery on subscribe.", **{"async": "Routing of updates by registry to gateways, and throttled pushes to clients."}),
    16: dict(states="Route plan version increments on reroute.", db="trip.route_plans (polyline, eta, version).", events="RouteDeviated{trip_id, distance_m, at}; EtaUpdated to tracking.",
             consistency="Eventually consistent ETAs. Stale results are dropped by position version, and rider and driver see the same server-side ETA."),
    17: dict(events="TripCompleted{trip_id, rider_id, driver_id, started_at, ended_at, quote_id, city} via outbox; DriverStatusChanged(AVAILABLE).",
             sync="POST /trips/{id}/complete and the Supply release in the same request (same transaction in Phase I–III)."),
    18: dict(states="Fare: none → Final; later adjustments are separate records.", db="fare.fares (unique trip_id), fare.outbox.", events="FareFinalized{trip_id, amount_minor, currency, basis, breakdown}.",
             sync="None: fare finalization is triggered by an event.", **{"async": "TripCompleted consumption, input collection (matched distance, tolls), and FareFinalized publication."}),
    19: dict(sync="The PSP capture call is synchronous inside the consumer, and its outcome may also arrive by webhook."),
    20: dict(events="ReceiptIssued{trip_id, number, amount}.", sync="None: receipts are generated from PaymentCaptured.", **{"async": "Numbering, rendering, storage and email delivery."}),
    21: dict(sync="None: earnings are computed from FareFinalized.", **{"async": "Earnings line insert, ledger posting and driver app refresh."}),
    22: dict(events="PayoutCreated, PayoutPaid, PayoutFailed{payout_id, driver_id, amount}."),
    23: dict(events="RideCancelled{request_id, trip_id, by, reason, fee_minor}; CancellationFeeCharged.", sync="POST /trips/{id}/cancel (or /ride-requests/{id}/cancel) with conditional transition and fee decision."),
    24: dict(events="RefundIssued{refund_id, trip_id, amount_minor, destination}.", sync="POST /internal/refunds (reserve against captured amount) by agent tools."),
    25: dict(sync="POST /sos to the isolated SOS service; persisted before acknowledgement.", **{"async": "Parallel alert fan-out (emergency API, pager, console), location streaming every 5 s, legal holds."}),
    26: dict(sync="Risk score call inline at the card-add checkpoint (50 ms budget, fail closed for cards)."),
    27: dict(events="TicketCreated, DisputeDecided{trip_id, outcome, amount}, FareAdjusted.", sync="Ticket creation and agent console actions are synchronous API calls."),
    28: dict(sync="RestrictRider command to Rider Profile (synchronous, idempotent by command id)."),
    29: dict(sync="DSR intake with identity verification is synchronous.", **{"async": "ErasureRequested fan-out to handlers, completion tracking, identity tombstone and the completion report."}),
}

for w in REG["workflows"]:
    w.update(D.get(w["n"], {}))
