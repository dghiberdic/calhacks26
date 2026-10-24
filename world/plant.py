"""F3c · Planted errors: at least 5 of every plan §5 error type in each split, all recorded in the answer key.

Flight-level cases are planted as *latent events* (`DayPlan`) and re-simulated, so their evidence is consistent
(an AOG planted the night before has its AMOS line, MCC line and the OCC batch code that contradicts it). The planner
dry-runs each split, counts the cases that occur naturally, and tops each type up deterministically (RNG keyed by
seed and split). Claim/CRM-level cases are planted on the passengers afterwards.
"""
from __future__ import annotations

import random
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from contracts.models import Claim, Coupon, CrmEvent, Election, Flight, Source, SourceKind
from world import causes as C
from world import network as N
from world import pax as P
from world import texts as T
from world.days import WorldDay

TARGET = 5
LH_TECHNICAL = 4          # long-haul technical cancellations per split, so the LH € curve has owed passengers
AMBIGUOUS_SHARE = 0.05
FLIGHT_TYPES = ("miscoded_technical", "concurrent", "knock_on_return", "notice_ge_14d", "manifest_ops_pax_mismatch")
CLAIM_TYPES = ("duplicate_lead_booker_member", "duplicate_direct_agency", "duplicate_two_agencies",
               "duplicate_claim_chargeback", "agency_authority_none", "assignment_then_direct_payment",
               "crm_bot_plus_bsp_refund", "injection_email", "claim_after_limitation", "uk261_520_dub_lhr")
NATURAL_TYPES = ("voucher_in_lieu_unsigned", "staff_id90")
ALL_TYPES = FLIGHT_TYPES + ("ambiguous",) + CLAIM_TYPES + NATURAL_TYPES
LEGACY = {"train": (date(2017, 3, 14), date(2023, 9, 4)), "test": (date(2018, 9, 20), date(2025, 1, 6))}


def rng_for(seed: int, *key: object) -> random.Random:
    return random.Random(":".join([str(seed), *map(str, key)]))


def midnight(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), UTC)


# ---------------------------------------------------------------- flight-level planning

def flight_counts(outs: Sequence[Any]) -> Counter:
    c: Counter = Counter()
    for o in outs:
        for t in o.truth.values():
            for tag in t.planted:
                c[tag] += 1
        c["_cancelled"] += sum(1 for t in o.truth.values() if t.status == "cancelled")
        c["lh_technical"] += sum(1 for fid, t in o.truth.items() if t.latent == "internal_aog"
                                 and fid in o.sectors and o.sectors[fid].pair.long_haul)
    return c


def ambiguous_target(counts: Counter) -> int:
    return max(3, round(AMBIGUOUS_SHARE * counts["_cancelled"]))


def _sev(o: Any, s: N.Sector) -> tuple[float, float]:
    return C.severity(o.idx.get(s.origin), s.std), C.severity(o.idx.get(s.dest), s.sta)


def _ret(o: Any, s: N.Sector) -> N.Sector | None:
    return next((x for x in o.sectors.values() if x.pair is s.pair and x.is_return), None)


class Planner:
    def __init__(self, seed: int, run_day) -> None:
        self.seed = seed
        self.run_day = run_day          # (WorldDay, DayPlan) -> DayOutput (no pax)
        self.used: dict[date, set[str]] = {}

    def _free(self, o: Any, *keys: str) -> bool:
        used = self.used.setdefault(o.w_day, set())
        return not any(k in used for k in keys)

    def _take(self, o: Any, *keys: str) -> None:
        self.used.setdefault(o.w_day, set()).update(keys)

    def candidates(self, kind: str, outs: list[Any], plans: dict[date, Any], r: random.Random) -> list[tuple]:
        """(day, apply-callable) candidates for one planted type, in a seeded order."""
        out: list[tuple] = []
        for o in outs:
            d = o.w_day
            storm = o.meta["kind"] == "storm"
            secs = sorted(o.sectors.values(), key=lambda s: (s.std, s.number))
            rot = N.tail_rotation(secs)
            first = {ss[0].id for ss in rot.values()}
            for s in secs:
                t = o.truth[s.id]
                if kind == "lh_technical" and s.pair.long_haul and s.origin == N.HUB:
                    tail_secs = rot[s.tail]
                    k = [x.id for x in tail_secs].index(s.id)
                    prev = tail_secs[k - 1] if k else None
                    sd, sa = _sev(o, s)
                    if (prev is not None and o.truth[prev.id].status != "cancelled" and t.status != "cancelled"
                            and sd == sa == 0):
                        logged = max(prev.sta + timedelta(minutes=45), s.std - timedelta(hours=5))
                        if logged < s.std - timedelta(minutes=60):
                            out.append((d, (s.id, f"tail:{s.tail}"), ("lh_technical", s, logged, storm)))
                    continue
                if s.pair.long_haul or s.origin != N.HUB:
                    continue
                ret = _ret(o, s)
                if ret is None:
                    continue
                sd, sa = _sev(o, s)
                rd, ra = _sev(o, ret)
                calm = sd == sa == rd == ra == 0
                both_flew = t.status != "cancelled" and o.truth[ret.id].status != "cancelled"
                keys = (s.id, ret.id, f"tail:{s.tail}")
                if kind == "miscoded_technical" and s.id in first and calm and both_flew:
                    out.append((d, keys, ("miscode", s, ret, storm, s.dest == "LHR")))
                elif kind == "concurrent" and storm and t.latent in ("weather_dep", "none") and sd > 0:
                    # the aircraft must be at DUB: first sector of its day, or its previous sector flew in
                    tail_secs = rot[s.tail]
                    k = [x.id for x in tail_secs].index(s.id)
                    prev = tail_secs[k - 1] if k else None
                    if prev is not None and o.truth[prev.id].status == "cancelled":
                        continue
                    logged = s.std - timedelta(minutes=50)
                    if prev is not None:
                        logged = max(logged, prev.sta + timedelta(minutes=15))
                    if logged < s.std - timedelta(minutes=15) and C.severity(o.idx.get(N.HUB), logged) > 0:
                        out.append((d, keys, ("concurrent", s, logged)))
                elif kind == "knock_on_return" and storm and both_flew and max(sd, sa) > 0 and rd == ra == 0:
                    out.append((d, keys, ("knock_on", s)))
                elif kind == "notice_ge_14d" and not storm and both_flew and s.id in first:
                    out.append((d, keys, ("notice", s, ret)))
                elif kind == "ambiguous" and storm and both_flew:
                    if max(sd, sa) >= 0.08:
                        out.append((d, keys, ("amb_crew", s)))
                    elif calm and s.id in first:
                        out.append((d, keys, ("amb_unrecorded", s, ret)))
            if kind == "manifest_ops_pax_mismatch":
                for fid, t in sorted(o.truth.items()):
                    if t.status == "cancelled":
                        out.append((d, (f"pax:{fid}",), ("pax", fid)))
        r.shuffle(out)
        if kind == "miscoded_technical":     # one DUB-LHR case per split first (the UK261 £520 plant needs owed LHR)
            out.sort(key=lambda c: not c[2][4])
        return out

    def apply(self, plan: Any, action: tuple, o: Any, r: random.Random) -> None:
        a = action[0]
        d = o.w_day
        if a == "miscode":
            _, s, ret, storm, _lhr = action
            plan.aog[s.tail] = (midnight(d) - timedelta(hours=r.randint(2, 5), minutes=r.choice([5, 20, 35, 50])),
                                True)
            plan.code[s.id] = "71"
            if storm:
                plan.batch.update({s.id})
        elif a == "lh_technical":
            _, s, logged, storm = action
            plan.aog[s.tail] = (logged.replace(second=0, microsecond=0), True)
            if storm:                    # the NS31 pattern: batch-coded 71 with the storm list
                plan.batch.add(s.id)
                plan.code[s.id] = "71"
        elif a == "concurrent":
            _, s, logged = action
            plan.aog[s.tail] = (logged, True)
            plan.wx.add(s.id)           # the storm at DUB would have cancelled it too
        elif a == "knock_on":
            plan.wx.add(action[1].id)
        elif a == "notice":
            _, s, ret = action
            days = r.randint(15, 30)
            plan.notice[s.id] = days
            plan.notice[ret.id] = days
        elif a == "amb_crew":
            plan.crew.add(action[1].id)
            plan.batch.add(action[1].id)
        elif a == "amb_unrecorded":
            _, s, ret = action
            plan.aog[s.tail] = (midnight(d) - timedelta(hours=r.randint(2, 5)), False)
            plan.batch.add(s.id)
            plan.code[s.id] = "71"
        elif a == "pax":
            fid = action[1]
            f = next(x for x in o.flights if x.id == fid)
            plan.pax_mismatch[fid] = max(1, f.pax + r.choice([-9, -7, -5, -4, -3, -2, 2, 3, 4, 6, 8]))

    def plan(self, wdays: Sequence[WorldDay], plans: dict[date, Any], outs: dict[date, Any]) -> None:
        from world.generator import DayPlan

        for rnd in range(5):
            changed: set[date] = set()
            for split in ("train", "test"):
                days = [w.day for w in wdays if w.split == split]
                split_outs = [outs[d] for d in days]
                counts = flight_counts(split_outs)
                need = {k: TARGET - counts[k] for k in FLIGHT_TYPES}
                need["ambiguous"] = ambiguous_target(counts) - counts["ambiguous"]
                need["lh_technical"] = LH_TECHNICAL - counts["lh_technical"]
                for kind in ("lh_technical",) + FLIGHT_TYPES + ("ambiguous",):
                    if need[kind] <= 0:
                        continue
                    r = rng_for(self.seed, "plant", split, kind, rnd)
                    for d, keys, action in self.candidates(kind, split_outs, plans, r):
                        if need[kind] <= 0:
                            break
                        o = outs[d]
                        if not self._free(o, *keys):
                            continue
                        plans.setdefault(d, DayPlan())
                        self.apply(plans[d], action, o, r)
                        self._take(o, *keys)
                        changed.add(d)
                        need[kind] -= 1
            if not changed:
                return
            for w in wdays:
                if w.day in changed:
                    outs[w.day] = self.run_day(w, plans[w.day])


# ---------------------------------------------------------------- claim / CRM level planting

class PaxPlanter:
    def __init__(self, seed: int, split: str, outs: list[Any]) -> None:
        self.seed, self.split, self.outs = seed, split, outs
        self.r = rng_for(seed, "plant-pax", split)
        self.counts: Counter = Counter()

    # -- helpers
    def _ids(self, po: Any) -> set[str]:
        return {c.id for c in po.claims} | {e.id for e in po.crm}

    def _claims_by_coupon(self, po: Any) -> dict[str, list[Claim]]:
        m: dict[str, list[Claim]] = {}
        for c in po.claims:
            m.setdefault(c.coupon_id, []).append(c)
        return m

    def _flight(self, o: Any, fid: str) -> Flight:
        return next(f for f in o.flights if f.id == fid)

    def _add_claim(self, o: Any, coupon: Coupon, at: datetime, *, tag: str, valid: bool, reason: str,
                   channel: str = "direct", agency: str | None = None, authority: str | None = None,
                   regime: str = "EU261", amount: int | None = None, text: str | None = None) -> Claim:
        po = o.pax
        t = po.coupon_truth[coupon.id]
        spec = P.ClaimSpec(coupon, self._flight(o, coupon.flight_id), at, channel=channel, agency=agency,
                           authority=authority, regime=regime, amount_cents=amount, text=text, valid=valid,
                           pay_cents=t.get("pay_cents", 0) if valid else 0, reason=reason, planted=[tag])
        return P.claim_record(po, spec, self._ids(po), self.r)

    def _tag_claim(self, po: Any, claim_id: str, tag: str) -> None:
        po.claim_truth[claim_id]["planted"].append(tag)

    def _tag_coupon(self, po: Any, coupon_id: str, tag: str, handling: str | None = None) -> None:
        t = po.coupon_truth[coupon_id]
        t.setdefault("planted", []).append(tag)
        if handling:
            t.setdefault("also", []).append(handling)

    def _add_crm(self, o: Any, coupon: Coupon, at: datetime, kind: str, amount: int, actor: str, text: str,
                 src_kind: SourceKind, tier: int, tags: list[str], prefix: str) -> CrmEvent:
        po = o.pax
        seat = coupon.id.rsplit(":", 1)[1]
        f = self._flight(o, coupon.flight_id)
        rid = P._uniq(self._ids(po), f"{prefix}-{f.number}-{seat}-{P.stamp(at)}")
        ev = CrmEvent(id=rid, coupon_id=coupon.id, at=at, kind=kind, amount_cents=amount, actor=actor,  # type: ignore[arg-type]
                      text=text)
        po.crm.append(ev)
        po.sources.append(Source(id=f"SRC-{rid}", kind=src_kind, title=f"{kind} · {coupon.id}", text=text + "\n",
                                 sha256=P.sha(text + "\n"), received_at=at + timedelta(minutes=1), trust_tier=tier,
                                 acl_tags=tags))
        return ev

    def _pool(self) -> list[tuple[Any, Coupon]]:
        pool = [(o, c) for o in self.outs if o.pax is not None for c in o.pax.coupons]
        self.r.shuffle(pool)
        return pool

    def _owed(self, o: Any, c: Coupon) -> bool:
        return o.pax.coupon_truth[c.id]["status"] == "owed" and o.pax.coupon_truth[c.id].get("pay_cents", 0) > 0

    def _valid_claims(self, o: Any, c: Coupon) -> list[Claim]:
        return [x for x in self._claims_by_coupon(o.pax).get(c.id, []) if o.pax.claim_truth[x.id]["valid"]]

    # -- the cases
    def run(self) -> Counter:
        used: set[str] = set()
        pool = self._pool()

        def take(pred, n=TARGET):
            got = []
            for o, c in pool:
                if len(got) >= n:
                    break
                if c.id in used or not pred(o, c):
                    continue
                used.add(c.id)
                got.append((o, c))
            return got

        later = lambda t, lo=2, hi=30: (t + timedelta(days=self.r.randint(lo, hi), minutes=self.r.randint(0, 900)))  # noqa: E731

        # duplicates: direct + agency on the same coupon
        for o, c in take(lambda o, c: self._owed(o, c) and any(x.channel == "direct" for x in self._valid_claims(o, c))):
            first = next(x for x in self._valid_claims(o, c) if x.channel == "direct")
            self._tag_claim(o.pax, first.id, "duplicate_direct_agency")
            self._add_claim(o, c, later(first.received_at), tag="duplicate_direct_agency", valid=False,
                            reason="duplicate_already_claimed_direct", channel="agency",
                            agency=self.r.choice(T.AGENCIES), authority="poa")
            self.counts["duplicate_direct_agency"] += 1
        # duplicates: two agencies
        for o, c in take(lambda o, c: self._owed(o, c) and any(x.channel == "agency" and x.authority == "poa"
                                                                for x in self._valid_claims(o, c))):
            first = next(x for x in self._valid_claims(o, c) if x.channel == "agency")
            self._tag_claim(o.pax, first.id, "duplicate_two_agencies")
            other = next(a for a in T.AGENCIES if a != first.agency)
            self._add_claim(o, c, later(first.received_at), tag="duplicate_two_agencies", valid=False,
                            reason="duplicate_second_agency", channel="agency", agency=other, authority="poa")
            self.counts["duplicate_two_agencies"] += 1
        # assignment notified, then the passenger claims (and is paid) directly: does not discharge
        for o, c in take(lambda o, c: self._owed(o, c) and any(x.channel == "agency" for x in self._valid_claims(o, c))):
            first = next(x for x in self._valid_claims(o, c) if x.channel == "agency")
            if first.authority != "assignment":
                upd = first.model_copy(update={"authority": "assignment"})
                o.pax.claims[o.pax.claims.index(first)] = upd
                self._retext(o, upd)
                first = upd
            self._tag_claim(o.pax, first.id, "assignment_then_direct_payment")
            self._add_claim(o, c, later(first.received_at), tag="assignment_then_direct_payment", valid=False,
                            reason="assigned_pay_the_assignee_only")
            self._tag_coupon(o.pax, c.id, "assignment_then_direct_payment",
                             "direct payment to the passenger does not discharge the assignee's claim")
            self.counts["assignment_then_direct_payment"] += 1
        # agency without authority
        for o, c in take(lambda o, c: self._owed(o, c) and not self._claims_by_coupon(o.pax).get(c.id)):
            f = self._flight(o, c.flight_id)
            self._add_claim(o, c, f.sched_dep + timedelta(days=self.r.randint(5, 60)), tag="agency_authority_none",
                            valid=False, reason="agency_without_authority", channel="agency",
                            agency=self.r.choice(T.AGENCIES), authority="none")
            self.counts["agency_authority_none"] += 1
        # lead booker claims for the whole PNR, and a member claims too
        self._lead_booker(used)
        # claim + chargeback on a bot-refunded coupon
        for o, c in take(lambda o, c: self._owed(o, c) and self._valid_claims(o, c)
                         and any(e.coupon_id == c.id and e.kind == "refund_initiated" for e in o.pax.crm)):
            ref = next(e for e in o.pax.crm if e.coupon_id == c.id and e.kind == "refund_initiated")
            f = self._flight(o, c.flight_id)
            at = later(ref.at, 3, 25).replace(second=0, microsecond=0)
            self._add_crm(o, c, at, "chargeback", ref.amount_cents, "card-acquirer",
                          f"CHARGEBACK RC 13.1 SERVICES NOT PROVIDED {f.number}/{f.date.strftime('%d%b').upper()} "
                          f"{c.id.rsplit(':', 1)[1]} {P.eur(ref.amount_cents)}", SourceKind.CRM, 2, ["finance"], "CB")
            self._tag_claim(o.pax, self._valid_claims(o, c)[0].id, "duplicate_claim_chargeback")
            self._tag_coupon(o.pax, c.id, "duplicate_claim_chargeback", "contest the chargeback: refund already paid")
            self.counts["duplicate_claim_chargeback"] += 1
        # CRM-bot refund + BSP refund on the same coupon
        for o, c in take(lambda o, c: any(e.coupon_id == c.id and e.kind == "refund_initiated" for e in o.pax.crm)):
            ref = next(e for e in o.pax.crm if e.coupon_id == c.id and e.kind == "refund_initiated")
            f = self._flight(o, c.flight_id)
            at = later(ref.at, 2, 8).replace(second=0, microsecond=0)
            self._add_crm(o, c, at, "bsp_refund", ref.amount_cents, "bsp:agent-91-3-1234-5",
                          f"BSP RFND TKT 220-{self.r.randint(10**7, 10**8 - 1)} {f.number}/"
                          f"{f.date.strftime('%d%b').upper()} {c.id.rsplit(':', 1)[1]} {P.eur(ref.amount_cents)} "
                          "AGT 91-3 1234 5", SourceKind.BSP, 2, ["finance"], "BSP")
            self._tag_coupon(o.pax, c.id, "crm_bot_plus_bsp_refund", "duplicate refund: recover the BSP refund")
            self.counts["crm_bot_plus_bsp_refund"] += 1
        # UK261 £520 on DUB-LHR (EU261 €250 applies; pay once)
        for o, c in take(lambda o, c: self._owed(o, c) and self._valid_claims(o, c)
                         and "LHR" in (self._flight(o, c.flight_id).origin, self._flight(o, c.flight_id).dest)):
            first = self._valid_claims(o, c)[0]
            upd = first.model_copy(update={"currency_regime": "UK261", "amount_claimed_cents": 52000})
            o.pax.claims[o.pax.claims.index(first)] = upd
            self._retext(o, upd)
            self._tag_claim(o.pax, upd.id, "uk261_520_dub_lhr")
            self.counts["uk261_520_dub_lhr"] += 1
        # injection emails (on no-compensation coupons: whatever the email says, nothing is owed)
        for o, c in take(lambda o, c: o.pax.coupon_truth[c.id]["status"] == "no_compensation"):
            f = self._flight(o, c.flight_id)
            at = (f.sched_dep + timedelta(hours=self.r.randint(10, 400))).replace(second=0, microsecond=0)
            who = o.pax.names.get(c.id, T.name(self.r))
            text = T.injection_text(self.r, who, f.number, f.date.strftime("%d %B %Y"),
                                    f"{c.pnr} seat {c.id.rsplit(':', 1)[1]}")
            cl = self._add_claim(o, c, at, tag="injection_email", valid=False, reason="extraordinary_circumstances",
                                 text=text)
            sid = f"SRC-EMAIL-INJECTION-{f.number}-{c.id.rsplit(':', 1)[1]}-{P.stamp(at)}"
            o.pax.sources.append(Source(id=sid, kind=SourceKind.EMAIL, title=f"Email · {f.number} {c.id.rsplit(':', 1)[1]}",
                                        text=text + "\n", sha256=P.sha(text + "\n"), received_at=at, trust_tier=4,
                                        acl_tags=["pii"]))
            o.pax.claim_truth[cl.id]["email_source"] = sid
            self.counts["injection_email"] += 1
        # natural cases: tag them
        for o in self.outs:
            if o.pax is None:
                continue
            for e in o.pax.crm:
                if e.kind == "voucher_in_lieu_of_compensation" and not e.signed_acceptance_sha256:
                    self._tag_coupon(o.pax, e.coupon_id, "voucher_in_lieu_unsigned")
                    self.counts["voucher_in_lieu_unsigned"] += 1
            for c in o.pax.coupons:
                if c.fare_type == "staff_id90":
                    self._tag_coupon(o.pax, c.id, "staff_id90")
                    self.counts["staff_id90"] += 1
        return self.counts

    def _retext(self, o: Any, claim: Claim) -> None:
        """Rewrite a claim's raw text and Source after a planted change (regime, authority, PNR scope)."""
        po = o.pax
        f = self._flight(o, claim.coupon_id.rsplit(":", 1)[0])
        c = next(x for x in po.coupons if x.id == claim.coupon_id)
        seat = c.id.rsplit(":", 1)[1]
        text = T.claim_text(self.r, who=po.names.get(c.id, T.name(self.r)), flight_number=f.number,
                            day=f.date.strftime("%d %B %Y"), coupon_ref=f"{c.pnr} seat {seat}",
                            amount_eur=claim.amount_claimed_cents // 100, channel=claim.channel, agency=claim.agency,
                            authority=claim.authority, regime=claim.currency_regime, pnr_scope=claim.pnr_scope)
        new = claim.model_copy(update={"text": text})
        po.claims[po.claims.index(claim)] = new
        sid = f"SRC-{claim.id}"
        for i, s in enumerate(po.sources):
            if s.id == sid:
                po.sources[i] = s.model_copy(update={"text": text + "\n", "sha256": P.sha(text + "\n")})

    def _lead_booker(self, used: set[str]) -> None:
        n = 0
        for o in self.outs:
            if o.pax is None or n >= TARGET:
                continue
            by_pnr: dict[tuple[str, str], list[Coupon]] = {}
            for c in o.pax.coupons:
                by_pnr.setdefault((c.flight_id, c.pnr), []).append(c)
            for (_fid, _pnr), cs in sorted(by_pnr.items()):
                if n >= TARGET or len(cs) < 2 or not cs[0].lead_booker or any(c.id in used for c in cs):
                    continue
                if not all(self._owed(o, c) and len(self._valid_claims(o, c)) == 1 for c in cs):
                    continue
                lead = self._valid_claims(o, cs[0])[0]
                members = [self._valid_claims(o, c)[0] for c in cs[1:]]
                if any(m.received_at <= lead.received_at for m in members):
                    continue
                upd = lead.model_copy(update={"pnr_scope": "pnr"})
                o.pax.claims[o.pax.claims.index(lead)] = upd
                self._retext(o, upd)
                lt = o.pax.claim_truth[lead.id]
                lt["covers"] = [c.id for c in cs]
                lt["pay_cents"] = sum(o.pax.coupon_truth[c.id]["pay_cents"] for c in cs)
                lt["planted"].append("duplicate_lead_booker_member")
                for m in members:
                    mt = o.pax.claim_truth[m.id]
                    mt.update(valid=False, pay_cents=0, covers=[], reason="duplicate_covered_by_lead_booker_pnr_claim")
                    mt["planted"].append("duplicate_lead_booker_member")
                used.update(c.id for c in cs)
                n += 1
        self.counts["duplicate_lead_booker_member"] += n


# ---------------------------------------------------------------- claims after the limitation period (legacy)

def legacy_output(seed: int, split: str) -> Any:
    """A legacy cancelled flight > 6 years before the split, restored from the PSS archive with only its claimants,
    and 6 claims received in the split: time-barred in Ireland (6 years, C-139/11 Moré)."""
    from world.generator import DayOutput, FlightTruth

    fdate, claim_from = LEGACY[split]
    r = rng_for(seed, "legacy", split)
    std = datetime.combine(fdate, datetime.min.time(), UTC) + timedelta(hours=16, minutes=30)
    fid = f"NS31@{fdate.isoformat()}"
    o = DayOutput(w_day=fdate)
    f = Flight(id=fid, number="NS31", date=fdate, origin="DUB", dest="BOS", sched_dep=std,
               sched_arr=std + timedelta(minutes=400), aircraft="EI-NSB", status="cancelled", pax=6,
               ops_cause_code="41", notified_at=std - timedelta(hours=5))
    o.flights.append(f)
    o.truth[fid] = FlightTruth(fid, fdate.isoformat(), "legacy", "cancelled", "internal_aog", "technical",
                               "not_extraordinary", ops_code="41",
                               note="legacy flight restored from the PSS archive for claims after the limitation period")
    po = P.PaxOutput()
    ids: set[str] = set()
    for i, seat in enumerate(P.seats(6)):
        cid = f"{fid}:{seat}"
        c = Coupon(id=cid, pnr="".join(r.choice(P.PNR_ALPHABET) for _ in range(6)),
                   pax_ref="PAX-" + P.sha(f"{seed}:{cid}")[:10].upper(), flight_id=fid, fare_cents=42000,
                   taxes_cents=5800)
        po.coupons.append(c)
        po.names[cid] = T.name(r)
        po.elections.append(Election(coupon_id=cid, kind="reaccommodated_own",
                                     new_arrival=f.sched_arr + timedelta(hours=26), arrival_delay_min=1560,
                                     recorded_by="occ"))
        t = P.coupon_truth(f, o.truth[fid].__dict__, c, po.elections[-1], None)
        t["planted"] = ["claim_after_limitation"]
        t["also"] = ["time-barred: Irish limitation is 6 years (C-139/11 Moré)"]
        po.coupon_truth[cid] = t
        at = datetime.combine(claim_from, datetime.min.time(), UTC) + timedelta(days=17 * i + r.randint(0, 9),
                                                                               hours=r.randint(6, 20))
        spec = P.ClaimSpec(c, f, at, valid=False, reason="after_limitation_6y_ireland",
                           planted=["claim_after_limitation"])
        P.claim_record(po, spec, ids, r)
    text = (f"PSS ARCHIVE EXTRACT {f.number}/{fdate.strftime('%d%b%y').upper()} DUB-BOS EI-NSB · 6 CLAIMANT "
            "COUPONS RESTORED · STATUS CNL RSN 41\n")
    po.sources.append(Source(id=f"SRC-MANIFEST-{fid}", kind=SourceKind.MANIFEST, title=f"Manifest {f.number}/{fdate}",
                             text=text, sha256=P.sha(text),
                             received_at=datetime.combine(claim_from, datetime.min.time(), UTC),
                             trust_tier=2, acl_tags=["ops"]))
    o.pax = po
    o.meta = {"date": fdate.isoformat(), "storm_id": None, "kind": "legacy", "split": split, "flights": [fid],
              "cancelled": [fid]}
    return o
