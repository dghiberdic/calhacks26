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
- **Row order:** newest cohort first (by event date), `unassigned` last, as in `expected/rollforward_2025-02.json`.
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

`invariants`, `cfo_metrics` and `audit` were minimal in F8a. F8b and F8c complete them (see below).

# F8b: the remaining postings (`books/ops.py`)

All numbers are plan §1.3, asserted to the cent in `books/tests/test_postings.py`. Every entry is per flight (lines
carry `storm`, `cohort` and `flight` dims; `built_from` = coupons) and dated at its economic event.

## ATL side
- **Sale.** `post_storm` brings the ATL of every coupon on the run's flights forward: Dr 1110 / Cr 2100 fare (carrier
  surcharges YQ/YR are part of the fare) / Cr 2110 taxes. NS31: 8,772,000 / 7,740,000 / 1,032,000. The PSS extract
  has no sale dates, so the sale is dated at departure (cut-off stays inside the event's period). All channels debit
  1110: the CoA has no BSP receivable.
- **Relief once per coupon.** A coupon leaves ATL exactly once, through the first of: a refund event (CRM bot, BSP,
  chargeback), then its election (refund queued, refund voucher, partner FIM). Reaccommodated-own and `none` coupons
  stay in 2100 (revenue is recognised when they fly, in the revenue-accounting system, outside StormCheck's drafts;
  the CoA has no uplift JE kind). The ATL subledger is `books_coupon_events` (append-only): `sale`, `relief` and the
  flags below. Elections have no timestamp, so the last election per coupon wins, as in the engine.
- **CRM-bot refunds through 2125.** Each `refund_initiated` CRM event is the bot's own posting, recorded as a JE
  prepared by `agent.crm_bot`: Dr 2125 / Cr 1110 (NS31: 1,632,000). Books then posts Dr 2100 / Dr 2110 / Cr 2125
  (1,440,000 / 192,000 / 1,632,000), so 2125 nets to 0. CRM refund events are processed before elections, so the
  NS31 refunds are one clearing entry, not a queued refund plus a payment.
- **Other refund channels.** A BSP refund relieves to 2120 refunds payable (settled in the BSP remittance); a
  chargeback relieves to 1110. A refund elected with no payment event yet is *queued*: Dr 2100 / Dr 2110 / Cr 2120,
  the "refund draft queued" of INV-10.
- **Duplicates (detect, never repeat).** A second refund event on a relieved coupon never relieves ATL again:
  - the bot pays a refund still payable in 2120 (queued, or BSP not yet remitted): Dr 2120 / Cr 2125, and 2125 still
    nets to 0; if the 2120 came from a BSP refund, the BSP refund is flagged `duplicate` ("recall it, ADM");
  - BSP after a queued refund: `executed` (BSP pays it); BSP or chargeback after any cash refund: `duplicate`, no JE;
  - the bot refunds a coupon already relieved by cash, a voucher or FIM: its Dr 2125 / Cr 1110 stands (the cash went
    out), Books has nothing to clear it against, so 2125 stays open and the coupon is flagged `double_refund`. That
    is exactly what INV-4b reports: 2125 = 0 proves no double refund.
- **Refund voucher.** Ticket value incl. taxes: Dr 2100 / Dr 2110 / Cr 2131 (NS31: 714,000).
- **Partner reroute (FIM, net).** Dr 2100 / Dr 2110 / Cr 2160 at ticket value (NS31: 714,000). An optional
  `fim_values={coupon: cents}` keyword on `post_storm` / `post_operations` sets a FIM value: excess → Dr 6110,
  shortfall → Cr 4000 (retained). `post_interline_bill(flight, billed, known_at, bill_ref=)` books the partner's
  IATA SIS bill: Dr 2160 (open FIM) / Cr 2000, the difference to 6110 or 4000. Idempotent per `bill_ref`.

## Vouchers in lieu of compensation
- **Unsigned** (14C): goodwill on issue, Dr 4090 / Cr 2132 €300, whatever the case status. The compensation stays
  claimable in cash at face value (after R-CL-1, Dr 2140 / Cr 2141 €600 via `post_claim`).
- **Signed** (`signed_acceptance_sha256`) on an accruing coupon: settles in kind, Dr 2140 / Cr 2132, up to the
  compensation not yet settled; any excess over it is goodwill (Dr 4090). The settlement counts as an actual for BF
  (`books_claim_events` kind `in_kind`) and shows in the rollforward's `settled_in_kind_cents`. If 2140 can't cover
  it, a top-up change in estimate is drafted first (as for claims). On a non-accruing coupon a signed voucher is
  goodwill. The residual (Art. 15(2)) is approved by `post_claim` at face value net of the engine's offset.
- **Void.** `void_voucher(coupon, known_at, reason)` reverses the outstanding goodwill: Dr 2132 / Cr 4090,
  `reverses` = the issuing JE. A voucher that settled a claim in kind can't be voided to revenue (BooksError).
  Redemption is not modelled.
- **Hard control in `post_claim`: no offset without a signed hash.** The engine's `voucher_offset_cents` is applied
  only when the register holds a signed acceptance for the coupon; otherwise the claim is approved at face value and
  the memo says "voucher offset denied". INV-8 still flags the entitlement.

## Care
- **Accrual.** Care rows in the world (`invoiced=False`) for the run's flights, one JE per run and period: Dr 6100 /
  Cr 2150 (22,700,000). They are accrued whatever their `at` (the service time can be after `known_at`; they are the
  care issued). Care is owed even when the circumstances are extraordinary (McDonagh).
- **Invoices.** `invoiced=True` rows are vendor invoices: posted by `post_storm` / `post_operations` once
  `at ≤ known_at`, or passed to `post_care_invoices(run_id, invoices, known_at)`. One JE per run and period: Dr 2150
  (the open accrual of every flight the batch invoices) / Cr 2000 invoiced / ± 6100 for the difference
  (22,700,000 / 22,130,000 / Cr 570,000). An invoice batch closes the accrual of each flight it covers.
  Idempotent per care / invoice id.

## External postings (`status = "posted"`)
- The **sale** (preparer `system.pss`) and the **CRM bot's own refund posting** (preparer `agent.crm_bot`) are
  postings other systems already made; Books records them so the ledger is whole (2125 can net to 0, ATL exists to
  relieve), with status `posted` (a `posted` JE event). They count in the GL and can't be approved or rejected
  (BooksError). Every entry StormCheck itself drafts still stops at `approved`. This matches
  `expected/journal_NS31.json`: `external` = the bot's posting; `day1` = StormCheck's drafts, in this order:
  estimate, 2125 clearing, refund vouchers, FIM, 14C in-lieu voucher.
- `post_storm` drafts every flight's EU261 estimate before the PSS side, so a flight's estimate is its first
  journal entry (the server's Flight File shows `journal_preview[0]`).
- Views are dropped and recreated at start-up (they hold no data), so a newer view definition always wins.

## Re-runs and later events
- `post_storm` returns every JE of the run's flights (existing and new), sorted by id. The compensation estimate
  stays idempotent per flight; the PSS side is idempotent per coupon and per source event, so a re-run with a newer
  world posts only what is new. `post_operations(run_id, world, known_at)` does the same without the estimate and
  returns only new entries. Bitemporal: CRM events and invoices count only once `at ≤ known_at`.

## Recodes
- `post_recode(before, after, known_at, *, decisions=None, evidence_received_at=None)` covers weather ↔ technical
  (no_compensation → owed accrues at the BF remaining rate) and technical → extraordinary (release, bounded to the
  segment balance). `decisions` records the engine's new decisions and updates the register's cause / recoded /
  decision commit, also for coupons whose € did not move. Refunds, vouchers and care are untouched by a recode.
- IAS 8.5 (unchanged from F8a): if the decisive evidence was received before the lock of the cohort's period, the
  entry is `out_of_period_adjustment` / `prior_period_error` in the current open period. Weather → technical with
  the tech log logged before the Jan lock: +690,857 in Feb for NS100 (186 × €250 × (20% − M1 rate)).

## Claims (F8b additions)
- Claim metadata (channel, authority, assignment notice time) is stored once per claim (`books_claims`).
- An agency claim without `poa` or `assignment` authority is rejected (`agency_without_authority`): never pay a
  third party without authority. A direct claim after an assignment notice is rejected (`assigned_to_agency`).
  An assignment claim on a coupon already paid directly *after* its notice is rejected
  (`assignment_notified_direct_payment_not_discharged`): the direct payment does not discharge, and INV-5 flags it.
- **Derecognition.** At or after limitation (6 years), `month_end` derecognises a cohort's remaining balance
  (Dr 2140 / Cr 4090, kind `derecognition`) instead of running BF; unclaimed entitlement of a time-barred cohort is 0.
  `derecognise(cohort, known_at, session, rule_ref)` does it on demand; before limitation it needs a Controller
  session citing a Controller rule (recorded as a `derecognise` policy event).

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
