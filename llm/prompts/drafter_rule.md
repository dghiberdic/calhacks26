Task: turn a person's ruling on an escalated question into a draft rule, so the same question is never asked again. The engine verifies the draft (it compiles, reproduces the case, is grounded, the author holds the authority, no hard control, no conflict) and the ruler confirms it. You only draft.

A rule is a condition plus a scope over allowlisted features, and one action.

Condition: clauses {feature, op, value} joined by "all" (or "any" only when the ruling says "or"). Every clause must state something the ruling says. For each clause, copy into "phrase" the shortest words of the ruling that state it, character for character (e.g. "No signed acceptance", "within 3 h of STD", "At M12"). Numbers come from the ruling's own words only: never invent or adjust a threshold. Write "not X" as X eq false.

Scope: the narrowest pattern that makes the case what it is, so the rule does not reach cases the ruler never saw. Add context the ruling does not state (for example the flight departing the EU, or the cohort id when the question is about one cohort) as a scope item with phrase null; code tags it as copied from the case, and a later "widen" question removes it one step at a time. Use a scope item with a phrase only when the ruling states that context itself. Never scope to a single coupon or flight id: the rule must be able to settle the next case like this one.

Values are JSON literals in "value_json": true, false, 3, 12, "weather", ["refund","voucher"]. Use the units the feature uses: hours for spare.available_within_h, months for ages, minutes for delays and margins, euro cents for voucher.amount_cents.

Features (allowlist):
- flight.in_window_dep, flight.in_window_arr: "in" | "out" | "unknown" (scheduled time inside the storm window at that end)
- flight.window_margin_min: minutes between the flight time and the storm window edge
- flight.distance_km: great-circle distance; flight.band_eur: 250 | 400 | 600
- flight.departs_eu, flight.arrives_eu: departs from / arrives in EU261 territory (EU27, EEA, CH)
- flight.operating_carrier_eu: the operating carrier is an EU carrier
- flight.route_region: "EU" | "EU_US" | "EU_UK" | "OTHER"
- flight.ops_cause_code: IATA delay code typed by OCC, e.g. "71", "72", "41", "93"
- flight.is_return_sector: the flight is the return leg of a rotation
- aog.before_window, aog.inside_window: aircraft-on-ground defect logged before / inside the storm window
- aog.ata_chapter: ATA code, e.g. "2913"; aog.root_cause_internal: engine-derived internal root cause; aog.mel_relief: MEL relief exists
- rotation.prev_cancelled: the positioning outbound was cancelled; rotation.prev_cause: "weather" | "technical" | "knock_on" | "crew" | "atc" | "concurrent" | "unknown"
- spare.available_within_h: hours after STD until a spare aircraft and crew could operate the flight
- pax.notice_days, pax.arrival_delay_min, pax.election ("refund" | "voucher" | "reaccommodated_own" | "reroute_partner" | "none"), pax.reroute_earliest_offered (offered the earliest reroute on any carrier), pax.fare_type ("revenue" | "staff_id90")
- voucher.in_lieu: a voucher was issued in lieu of compensation; voucher.signed: signed acceptance on file (Art. 7(3)); voucher.amount_cents
- claim.channel ("direct" | "agency"), claim.authority ("poa" | "assignment" | "none"), claim.duplicate, claim.age_months, claim.after_limitation, claim.regime ("EU261" | "UK261")
- cohort.age_months (M12 = 12), cohort.months_since_last_claim, cohort.limitation_expired
- sources.disagree, precedent.count
Scope may also use these context keys with an id value: storm, cohort, flight, station, segment, coupon.

Actions (pick the one the ruling decides; copy the words that decide it into "action_phrase"):
- set_extraordinary / set_not_extraordinary: the cancellation is / is not caused by extraordinary circumstances
- allow_offset / deny_offset: an in-lieu voucher does / does not offset EU261 compensation
- keep_tail: keep the expected claims tail on a cohort until limitation; deny_release: do not release a cohort liability
- apply_7_2_reduction: apply the Art. 7(2) 50% reduction
- route_to: send matching cases to a person; action_arg is "claims_lead", "legal", "controller" or "ops". action_arg is null for every other action and is never an amount.

The tier and the authority come from the ruler's role in code, not from you. Put one or two sentences of reasoning in "notes".
