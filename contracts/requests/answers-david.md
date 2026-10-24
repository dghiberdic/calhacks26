# Answers from David (contracts + engine) to Justin's requests (`contracts/requests/justin.md`, PR #5)

## Open questions

| # | Answer |
|---|---|
| **Q-a** · who may challenge | **Any authenticated session**, including the Judge and external or persona principals. A challenge is a submission, not an approval. The server stores it as a tier-4 Source, and Drafter `classify_challenge` labels it `assertion`, `new_fact` or `new_legal_pattern`. It never flips a decision by itself: a `new_fact` routes to Ops and a `new_legal_pattern` to Legal. The reply always starts **"Decision stands."** unless a human with authority later decides otherwise. The access matrix gets an explicit `challenge: all sessions` row (server agent). |
| **Q-b** · is Q1 already 3 h old | **Decided: no scrub (pending server confirmation).** After `POST /api/reset` the server seeds Q1 as already 3 h old by advancing the demo clock to boot + 3 h (2025-01-25T09:00Z). The chip then reads "Waiting on Claims Lead 3h · reminder sent · N others settled". `expected/` pins neither the clock nor `asked_at`, so this is free to do. If the server can't, the presenter scrubs +3 h; the server agent will say which. |
| **Q-c** · weather at the fault | The tech-log entry is 23 Jan 21:40Z. Quote the routine report nearest it, 21:30Z, verbatim: **`EIDW 232130Z 15014KT 120V180 9999 FEW015 BKN040 05/01 Q0990 NOSIG`** ("14 kt, no gust"). The plan's "13 kt" is the 21:00Z report (`EIDW 232100Z 16013KT 9999 FEW015 BKN050 05/01 Q0992 NOSIG`). Say "14 kt, no gust at 21:30Z", or just "light wind, no gust, before any storm window". The fixtures' timeline mark already uses the 21:30Z line. |
| **Q-d** | Filip's. |
| **Q-e** · 171 or 172 | **Both numbers are right; they count different things.** 172 passengers are owed, €99,000 full Art. 7 entitlement. **171 payouts are drafted, pending Claims Lead approval**, and 14C's €600 waits on her ruling (Q1). After Q1 is answered it becomes 172. Suggested wording: *"172 passengers owed · 171 payouts drafted, pending Claims Lead approval · 14C waits on her ruling."* The API says it as `counters.drafted = 171` and the NS31 summary's `status_line` = "171 payouts drafted, pending Claims Lead approval · 1 waits on a ruling". The fixtures now match the real engine (171). Keep reading the count off the screen. |
| **Q-2 confidence** | On the real server Q-2 shows the **default calibration's 0.37**; the fitted calibration would give about 4.6%. It does not show the plan's 47%. The fixtures use a display-only calibration (`cal-plan-fixture`) that reproduces the plan's 91%/47%. **The UI and the script should read confidence off the screen.** The 47% in IMPLEMENTATION_PLAN §1.2/§3 is illustrative. NS31's cause-finding confidence is 91% on both. |

## Requests: status

| # | Status |
|---|---|
| 3 `StormRun.name` | **Done** (model + engine + fakes): "Storm Éowyn", "Storm Herminia", from `real_context.storm_name`. |
| 4 `Question.others_settled` | **Done** (model + engine + fakes): other cases of the same storm run settled automatically while the question waits. A coupon-level question (Q1) counts coupons; a flight-level or cohort question counts flights. Golden: Q-1 4,761 · Q-2 24 · Q-3 24. The question's own holds never count. |
| 5/10 summary keys | **Done.** `contracts.models.EntitlementsSummary` documents every key, and the field stays a dict at runtime with its typed schema in OpenAPI. The keys are: `full_entitlement_cents`, `drafted_liability_cents`, `claim_rate`, `coupons`, `elections`, `status_line`, `band_label`, `claim_rate_label`, `full_entitlement_label`, `statuses`, `compensation_breakdown`, `reduction_7_2`, and the D0a ones. They come from one builder, `contracts/summary.py`, used by the engine (`engine.eu261.summarize`), the fakes and the fixtures. |
| 6 `Rule.cases_settled_by_storm` | **Model done**; `engine.storm.cases_settled_by_rule(decisions, ents)` computes it per run, and the server fills its stored rules. Fixtures: R-REG-ART5-3 {Éowyn: 23}, R-MINED-REDUCE {Éowyn: 14}. |
| 9 typed timeline | **Done**: `TimelineItem {at, kind, label, text, source_id, trust_tier}` (extra keys allowed). `TimelineKind` = tech_log, mcc, occ, spares, metar, window_start, window_end, metar_window_start, metar_window_end, crm, operated, schedule, pss, claim, care, warning, email, injection, challenge, ruling, info. |
| 11 `Question.proposal_rule_id` | **Model done**; the server fills it when a question has a pending proposal. Q-3 has none: "Reject" answers Q-3 with its reject option, and that rejection becomes R-CTL-1. |
| 12 `Confidence.features` | **Documented: `features` holds the raw model inputs, already encoded** (flags 0/1, margin in hours, precedent count; see `calibration_schema.json` x-encoding). New `contributions` (coef × input, in log-odds) and `intercept` sit beside them: score = logistic(intercept + Σ contributions). Engine and fakes fill both. |
| 13 `Rule.origin_quote` | **Done**: the ruler's own words (what they typed, else the option they chose), set when the rule is proposed. The static Reg 2026/2202 card carries its text here. |
| 15 `Commit.recorded_at` | **Model done**; the server fills it (fixtures: = `at`). |
| 16 `Rollforward.locked` | **Model done**; the server fills it from the lock state (Books is frozen). |
| 18 `je_ids` on rollforward rows | **Model field only.** Books won't fill it, so the server leaves it empty. Keep matching by journal kind. |
| 19 `CfoMetrics.cohort` | **Model done**; the server fills it (fixture: `EIDW@2025-01-24`). |
| 1, 2, 7, 8, 14, 17, 20, 21 | Server-side (the server agent). #14 `widen_next.question` already exists in the engine ("All storm cohorts?"). |

## From `justin-expansion.md`
- **Ask 2, the red-warning email as a `warning` timeline mark:** done in the fixtures. Every Éowyn weather flight's timeline has the forwarded Met Éireann email (`SRC-EMAIL-METEIREANN-FWD-2025-01-23T1600Z`) as `kind: "warning"`. The real server's timeline is the server agent's to extend the same way.
- **Ask 3, the 2026/2202 card text:** done on the static card (`origin_quote`): "Amounts (€250/400/600) and the 3 h threshold unchanged. A carrier relying on extraordinary circumstances names the circumstance and explains the causal link and reasonable measures within 30 days. New claims within nine months. Applies from 23 October 2027: no effect on today's balances." I left out on-block arrival and the hotel cap; they aren't confirmed against EUR-Lex. R-CTL-1 is not rescoped.
- **Ask 4, injection 06 wording:** done. The expected outcome now reads "After the limitation period that may apply (Ireland: 6 years; the forum decides, C-139/11 Moré) · not asserted · routed to the Claims Lead / Legal".
