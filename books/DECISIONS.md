# books/ decisions (F8a)

Judgment calls made while building the books core. Golden numbers (CONTRACTS §5) are asserted to the cent in
`books/tests/test_golden.py`.

## Ledger semantics
- **Parked-journal ledger.** StormCheck never posts past "approved", so the GL that the rollforward ties to counts
  **draft and approved** entries. Rejected entries never count. *Gated* entries count only once approved: payouts
  (`claim_paid`, Dr 2141 / Cr 1000) and release proposals. That way "cash basis €0" holds until the Claims Lead
  releases a payout, and a release proposal never moves 2140 unless the Controller accepts it.
- **Opening balances** (`World.opening_balances`, e.g. the Isha cohort) are migrated balances, not JEs. They count
  in GL 2140 and in the rollforward opening for every period from `period(as_of)` on. They are loaded idempotently
  by `post_storm` or by `post_opening_balances`.
- **Status** (draft / approved / rejected), approver and lock are views over `books_je_events` and
  `books_period_events`. Every `books_*` table aborts UPDATE and DELETE.
- **JE ids** are `JE-000001`, sequential. Lines carry the dims `cohort`, `segment`, `flight` (plus `coupon` and
  `claim` on claim entries).

## Measurement
- **Cohort = `run_id`** (the StormRun id, e.g. `EIDW@2025-01-24`). The cohort's event date is parsed from the id.
  If the id has no date, it is the earliest flight date (for opening balances, the date in the cohort id, else
  `as_of`).
- **Segment** comes from `band_eur`: 600 → long_haul_gt3500, 400 → medium_1500_3500, 250 → short_le1500. Art. 7(2)
  50% coupons stay in their band's segment.
- **Accruing statuses** are `owed`, `held` and `needs_ruling` (held and needs-Legal items accrue under IFRS 15.56).
  `no_compensation`, `exempt_notice`, `out_of_scope` and `staff_ticket` don't accrue and get no JE.
- **Accrual base** is the gross `compensation_cents`. A signed in-lieu voucher is a settlement in kind later
  (F8b, Dr 2140 / Cr 2132), not a cut to the estimate. A **claim is approved at face value**:
  `compensation_cents − voucher_offset_cents`, never the amount claimed (e.g. a UK261 £520 claim pays €250).
- **Rounding.** Rates are exact fractions (0.35 = 35/100). Each JE amount is rounded once, half away from zero,
  per (flight, segment).
- **Curves** load from `contracts/fixtures/golden/curves.json` when it parses. The parser is tolerant: it accepts
  a list of ClaimCurve-like objects, a dict keyed by segment or version, `{"curves": ...}`, and `[m, rate]` pairs
  or `{"M1": .09}` points. Otherwise built-in defaults (LH-v1 M1 .09, M3 .17, M6 .24, M12 .29, M18 .32, ultimate
  .35; MH .27; SH .20) are used. `Books.curves_source` says which one was used.
  - Medium and short curves without their own points reuse the LH shape scaled to their ultimate.
  - Rates between points are interpolated linearly from (0, 0). Past the last observed point the curve runs
    linearly to the ultimate at month 72 (the 6-year limitation).
  - Default `n_by_point` is zeros: we don't fabricate counts. F3's real curves fill them in.
- **Age.** M1 = the month-end of (event + 28 days), i.e. the first month-end at least 28 days after the event.
  Age is 0 before M1, 1 at M1 and 12 at M12. **There is no true-up before M1**: the day-1 estimate stands, and
  claims draw it down (which is why Jan closes at 3,105,000).

## Month end (BF)
- The true-up runs per cohort × segment. BF remaining = (ultimate − expected rate at age) × entitlement, bounded
  to [0, unclaimed entitlement]. Change in estimate = BF − book, drafted as a `change_in_estimate` JE (IAS 8.36)
  dated at period end, with `estimate_ref = BF:<cohort>:<segment>@<period>`. Re-running a month end posts only
  the increment, and `month_end` returns all of the period's BF and release entries.
- **BF is always the selected method.** THREAD_FILIP says "BF while <50% developed", but the F8a brief says BF
  is selected. On the golden cohorts BF already equals chain-ladder where development passes 50% (Isha at M12:
  both give 360,000). The `selected` field is there if this changes.
- **Estimate card formulas** (per segment, then summed):
  - expected-loss = ultimate × E − actual;
  - BF as above;
  - **chain-ladder = actual × ultimate / rate(age) − actual**, the standard CDF on actual to date. Before M1
    (rate 0) it falls back to expected-loss.
  - All three are bounded to [0, unclaimed].
  - A/E = actual / (rate(age) × E), € basis, 3 dp.
  - `credibility_z` = rate(age) / ultimate, i.e. BF's implicit credibility weight on the chain-ladder.
  - Sensitivity = 5 pp × E.
  - The card is computed at the close of `known_at`'s period.
- **Release proposal.** It is drafted when age ≥ M12, `months_since_last_claim` ≥ 3 and the balance is > 0. It is
  made once per cohort and never under a keep-tail policy. It is a gated `change_in_estimate` (Dr 2140 / Cr 4090,
  the full balance) with `estimate_ref = release:<cohort>`.
  - `months_since_last_claim` runs from the latest approved claim. For an opening balance with claims, `as_of`
    stands in for the last-claim date (see the gaps below).
- **Keep tail (R-CTL-1).** `keep_tail(rule_ref, cohorts|None, known_at)` floors BF at
  (ultimate − M12 rate) × E from M12 on and suppresses release proposals. `None` applies it to all cohorts ("All
  storm cohorts?"). `reject(je_id, session, reason)` records the Controller's rejection of the proposal.

## Claims
- `post_claim` returns [approval Dr 2140 / Cr 2141, payout Dr 2141 / Cr 1000]. Both are drafts and both need the
  Claims Lead; the payout is gated. The event date is `known_at`'s UTC date.
  - `held` / `needs_ruling` → no entry (reason `pending_ruling:<status>`).
  - Other non-owed statuses → rejected with the status as the reason code.
  - A second claim on the same coupon → `duplicate_payment_coupon`, no entry.
  - The same claim id twice → the same JEs (idempotent).
- **Claims beyond the estimate.** If an approval would take the cohort-segment 2140 balance below 0, a top-up
  `change_in_estimate` (Dr 4090 / Cr 2140) is drafted first, so 2140 never goes negative (property-tested).

## Recode and preview
- **The delta uses the BF remaining rate** for the cohort's current age: (ultimate − rate(age)) × Δentitlement.
  At age 0 that is the ultimate, which gives exactly −4,749,600 for the knock-ons.
  - After M1, a full release is booked partly by the recode and partly by the next month-end's BF re-base, which
    takes zero-entitlement segments to nil. This is tested in `test_curves_and_ias8.py`.
  - Releases are bounded to the cohort-segment balance.
- **`post_recode` diffs `after` against the obligation register** where the register knows the coupon (else
  against `before`), so a repeat call posts nothing. A coupon missing from `after` counts as unchanged.
  - It drafts one JE per flight, kind `recode`, `ias8_class = change_in_estimate`, in the current open period.
  - Optional keyword `evidence_received_at` applies the IAS 8.5 test. If it is ≤ the lock time of the flight's
    locked period, the JE becomes `out_of_period_adjustment` / `prior_period_error` ("prior-period error,
    corrected in current period (immaterial)").
- **`preview`** returns one flip per flight (`field = "eu261_liability_cents"`) with `rule_ref = "preview"` and
  `known_at = clock.now()`. It writes nothing.

## Controls
- **SoD.** The preparer check comes first. Roles: `claim_approved` / `claim_paid` need the claims_lead; every
  other kind needs the controller. Agents, judges and the CFO can never approve. Denied attempts are logged as
  `denied` JE events (`audit(je_id)["events"]`).
- **Locked periods.** A direct post (`post_entry`, `month_end`) into a locked period raises `PeriodLocked`.
  - Higher-level posts (`post_storm`, `post_claim`, `post_recode`) whose event date falls in a locked period are
    redirected. They go to the first open period ≥ max(next(locked), period(known_at)), dated `known_at` if that
    is in the open period, else on its first day.
  - Redirected JEs are flagged: line dims `adjusted_from_period` and `original_event_date`, plus a memo suffix.
    The rollforward shows them in `out_of_period_cents`.
  - Approving or rejecting a JE in a locked period raises, as in SAP, where a parked document can't be posted
    into a closed period.
  - `lock_period` needs the controller (`Forbidden` otherwise).
- **`post_storm` is idempotent per flight id**, across runs. A later change to a flight must go through
  `post_recode`.

## Rollforward
- **Sign convention:** `claims_approved_cents`, `settled_in_kind_cents` and `derecognised_cents` are positive
  magnitudes; `change_in_estimate_cents`, `recode_cents` and `out_of_period_cents` are signed. So:
  `closing = opening + new − claims − settled − derecognised + change_in_estimate + recode + out_of_period`.
- `gl_balance_cents` is an independent Σ(cr − dr) over the GL 2140 lines plus opening balances. A JE kind with no
  rollforward column doesn't foot, so `ties_to_gl = False` surfaces the mapping gap.
- `unclaimed_entitlement_cents` = accruing entitlement (register as of period end) + opening entitlement − claims
  approved through period end.

## Beyond BooksAPI (books-local extensions; the server may call them)
`post_entry`, `post_opening_balances`, `reject`, `keep_tail`, `register`, `gl_balance`, `segment_balances`,
`locked_periods`, `journal_entry` and `close`. Errors are in `books.errors`: `BooksError(code="validation")`,
`NotFound`, `Forbidden`, `SoDViolation(code="sod_violation")` and `PeriodLocked`.

`invariants`, `cfo_metrics` and `audit` are minimal in F8a: INV-1, 1b, 2, 6, 9a, 9b and 11; refunds, care and
vouchers read 0. F8b and F8c complete them.

## Contract gaps (not changed; `contracts/` is David's)
1. `SoDViolation` / `PeriodLocked` aren't in `contracts/`. The server must import them from `books.errors`, or
   David can add `contracts/errors.py`.
2. `OpeningBalance` has no event date, last-claim date or pax. The event date is parsed from the cohort id,
   `as_of` stands in for the last claim, and pax = 0 on the card.
3. `JournalEntry.status` has no `rejected`, so rejected entries are omitted from `journal()`. `JournalEntry` has
   no flags field, so out-of-period flags live in line dims.
4. `BooksAPI` has no way to: reject a JE; apply a keep-tail policy (R-CTL-1); load opening balances; or pass the
   IAS 8.5 evidence time to `post_recode`. These are covered by the local extensions above, with
   `evidence_received_at` as a keyword-only argument.
5. The `RollforwardRow` sign convention is unspecified (choice above). `expected/rollforward_2025-02.json` should
   use the same one.
6. The `curves.json` format isn't defined yet, hence the tolerant loader.
7. `ReplayDiff.flips` entity granularity is unspecified. Books reports per flight; the engine reports decisions.
