# engine/ decisions: review fixes (domain review, integrity review, F9 held-out eval)

Judgment calls made while fixing the confirmed findings, one line of reasoning each. Regression tests live in `engine/tests/test_review_engine.py` (decision core) and `engine/tests/test_review_lifecycle.py` (rules and lifecycle). The golden `expected/` files, NS31 = 9,900,000 and the storm day-1 liability of 8,214,600 are unchanged.

## Which AOG grounds a flight (domain 4, eval E3)

- **No fixed lookback.** A tail AOG logged any time before the cancellation still grounds the flight unless it was back in service by STD. "Back in service" means any of:
  - its RTS estimate is at or before STD;
  - a later tech-log line says RTS / returned to service, or defers the same ATA chapter under MEL;
  - the tail operated a flight in between.

  The 36 h window hid a still-AOG aircraft. The generator always sets `rts_est`, so old AOGs close themselves.
- **The cut-off is the cancellation decision:** the earliest OCC entry naming the flight with an RSN code or "CNL", else STD. An AOG logged after the OCC had already put the flight in its weather batch cannot have caused it (NS145/NS147). Golden is unaffected: Éowyn's batch is at 05:12Z with the NS31 AOG the night before, and Herminia's is at 05:50Z with the NS110 AOG at 05:35Z.

## Concurrent causes need the flight in a window (eval E2)

- **Concurrent = a decisive AOG and the flight itself in a window at either end.** An AOG logged during an earlier window on an out-of-window flight gives:
  - an internal root → `technical / not_extraordinary` (owed);
  - an external/weather root (lightning, hail, bird...) → `external_event` (Legal).

  The old rule also fired on `aog.inside_window` alone, which produced "sits in the window at neither end" (NS166/NS169/NS135).
- **An AOG at another station is not this flight's AOG.** If the tail is AOG somewhere other than the flight's origin, and this is a return whose outbound was cancelled, the outbound's finding travels with the rotation as a knock-on. NS169 (DUS→DUB, tail AOG at DUB) is a knock-on of NS168, matching the generator's truth.
- **An injected AOG with no `aog.station` keeps station `""` (unknown)** instead of assuming DUB. An unknown station is never "elsewhere".
- **`test_cause.py::test_aog_inside_window_is_concurrent` asserted the E2/E3 defect itself** (AOG at 08:00Z, after the 05:12Z batch, on a 16:30Z flight → concurrent). It is replaced by `test_aog_inside_an_earlier_window_is_not_concurrent`. `test_tech_log_not_known_yet` keeps its bitemporal intent with pre-batch times (logged 04:00Z, known 03:50Z vs 04:10Z).

## Trust tiers on overlaid facts (domain 3 and 8, integrity 1)

- **Only a tier-1 tech-log/MCC fact becomes a tech-log line.** Any other `aog.*` fact is an AOG claim (`FlightCase.aog_claims`). It never grounds a flight: the decision becomes `aog_unverified`, routed to Ops (sources disagree), and the claim is cited at its real tier. Claims count only within 48 h before the cancellation and while not returned to service.
- **Spare hours from facts below tier 2 are evidence only.**
- **A source found nowhere is tier 4** (fail closed), in `find_source` as well. "Nowhere" means not in the world and not registered (see "Injected documents" below), so an injected document's facts never read as tier 1 unless the trace holds that document.
- **Earliest reroute: the carrier's own records decide.** That means tier ≤ 2 (PSS, schedule, spares) or a genuine OCC/IROPS-desk line (the coordinator's "PSS/OCC"; the OCC log is tier 3). Passenger, agency and CRM lines never count. Best tier wins, then the latest.
  - An overlaid verdict counts at its fact's tier; one from an OCC-log source counts like an OCC line.
  - The negation is an explicit "not/never offered", "no (earliest) reroute" or "reroute not offered". "no hotel needed; earliest reroute offered" reads as offered.
- **Injected documents (regression on rehearsed injection 01).** A fact's source is looked up in the world first, then among documents registered outside it:
  - those in the trace: `TraceStore._run` binds `trace.sources()` (`engine.case.registered_sources`) while any `decide_fn` runs, so the server's overlay resolves an injected tech-log line without naming it;
  - those passed explicitly: `Engine.decide(..., sources=[...])`, `overlay_facts(..., sources)`.

  A registered document may not claim a better tier than its kind allows (`case.KIND_TIER`: tech log / MCC / METAR 1; schedule, manifest, PSS, BSP, spares, manufacturer 2; OCC log, CRM 3; claim, e-mail, challenge 4; any other kind 4). So an injected e-mail that declares tier 1 is still tier 4: a claim for Ops, never a flip. The curated world keeps its own tiers (golden has tier-2/3 operational e-mails), and a world source id always wins over a registered one. A source found nowhere is still tier 4.
- **Injection 01's 08:05Z timing is legally wrong.** The OCC put NS110@2025-01-24 in the 05:12Z weather CNL batch, so an AOG logged at 08:05Z cannot have caused the cancellation (E3; `test_injected_sources::test_an_aog_logged_after_the_occ_cancellation_does_not_flip_ns110_even_at_tier_1`). The same line at 04:05Z sits inside the 02:30Z–15:00Z DUB window and before the cancellation decision, so the weather and the grounded aircraft are concurrent causes: Legal. The fixture moves to 04:05Z together with the Reader's recording of the new text (`llm/demo_inputs.py`, `data/cache/demo/`); the expected outcome does not change.
- **Provenance:** an overlaid world carries `meta["_overlay"]` with each synthetic line's fact ids per field, its source and its tier. AOG and spares evidence cite the injected fact id and source, so `blame` reaches the injection.

## Cause rules settle only what they ruled on (domain 1 and 10)

- **`scope.pattern`** is a new DSL context key: the question a ruling answers. The flight features carry `pattern`, so a pinned rule only matches its own pattern. The lifecycle adds it to cause rules; the drafter never sets it.
- **AOG patterns** (`concurrent_causes`, `external_event`, `technical_internal`) are settled or cited only by a rule whose condition references `aog.*`. The knock-on ruling R-LEG-1 says nothing about an AOG, so it can't settle a concurrent case. Rules without a pinned pattern (stub cards, older rules) still get this guard.
- **Spares are blanked for concurrent causes as well as technical ones:** the tail is grounded either way.
- **Legal patterns are never routed away from Legal.** For a Legal pattern, a `ROUTE_TO` rule with any target other than Legal is ignored.

## OCC codes (domain 2 and 6)

- **An in-window flight with an OCC technical, crew, ATC or airport code and no tech-log line** becomes `occ_code_in_window`: unknown / needs_legal, Ops, sources disagree. It was auto weather. Concurrent causes need tier-1 AOG evidence, so this is Ops' question, not Legal's.
- **`capped:sources-disagree` is a hard gate in `routing.route`:** never automatic (batch review at ≥ 0.60).
- **Recode when the cause departs from the code.** An in-window weather finding on a rotation (9x) or other non-weather code is recoded to 71 (`93 → 71`).
- **Code groups:** 85/86/87/89 (security, immigration/customs, airport facilities, departure-airport restrictions) are `airport_restriction`, no longer "ATC". 81–84 and 88 stay ATC.
  - Like its ATC sibling, it stays an OCC-claimed extraordinary event (`extraordinary`) that Ops confirms, with entitlements held meanwhile (eu261, `test_eu261_golden::test_p8_*`).
  - The cause is `unknown`, because the `Cause` enum has no security/airport member.

## Routing (domain 7)

- **Automatic only through `controls.materiality_ok`** (< €50k AND ≥ 0.90). A rule-settled case skips the question (never asked twice) but not the review: below 0.90 it is batch review.
- **Not changed:** for extraordinary decisions the gate still sees no stake (liability 0). Pricing the stake as if not extraordinary would send golden NS21/NS41/NS51 (about €51–56k each) to the Controller and change `expected/`.

## ≥ 14 days' notice (eval E4)

- **Notice ≥ 14 days makes the cause question moot.** In `to_decision`, `eu261.flight_notice_exemption` (or `notice_exemption(flight, None)` until the other agent's helper lands) routes the decision auto with no question:
  - legal basis gets `EU261 Art.5(1)(c)(i)`, and the reason adds "Notice ≥14 days ... Art. 5(1)(c)(i)";
  - the cause is kept as found;
  - an undecided `needs_legal` is recorded as `not_extraordinary`, because the carrier relies on notice, not Art. 5(3);
  - entitlements are `exempt_notice`, with refund and care still due.
- **The exemption applies per flight, not per rotation.** The knock-on chain still uses the outbound's real finding, so a return without notice of its own is not exempted through its outbound.

## Confidence (integrity 5A, calibration)

- **A non-finite coefficient, intercept or feature gives `score = None`** ("uncalibrated", never automatic) plus a `capped:uncalibrated` chip. This follows lane B's `test_nan_calibration` on main (None) rather than the brief's "NaN → 0": the contract already defines None as uncalibrated, and the two must agree.
- **Cause features add `concurrent_causes`** (1 for a concurrent finding). `engine/default_calibration.json` now equals `contracts/calibration_default.json` (−4.0 prior), so concurrent cases stay far below 0.60.
