// Northstar's flights for the two real storm days. Éowyn follows IMPLEMENTATION_PLAN.md §1.2 exactly
// (STD/STA UTC, pax from the manifest, tails); STAs the plan leaves out use realistic block times.
// Herminia is a mini-day built around the plan's Q1 payoff (31 unsigned in-lieu vouchers on an EU
// departure, 1 on BOS→DUB). `aircraft` is the registration, as in the contract tests ("EI-NSB").
import type { Flight } from "@/api/types";
import { bandFor } from "./airports";
import { utc } from "./util";

export type Group =
  | "outbound_weather" // STD inside the DUB window (OCC 71)
  | "return_weather" // STA inside the DUB window (OCC 71)
  | "overnight_inbound" // STA inside the DUB window (OCC 72, destination weather)
  | "knock_on" // return of a storm-cancelled outbound, calm at both ends → Legal
  | "technical" // AOG before the window, out of window at both ends → owed
  | "operated";

export type FlightSpec = { flight: Flight; group: Group; type: string };

export const EOWYN_ID = "EIDW@2025-01-24";
export const HERMINIA_ID = "EIDW@2025-01-26";
export const ISHA_COHORT = "EIDW@2024-01-21";

const TYPE_BY_TAIL: Record<string, string> = {
  "EI-NSB": "A321XLR", "EI-NSN": "A321XLR",
  "EI-NSR": "A330-300", "EI-NSS": "A330-300", "EI-NST": "A330-300", "EI-NSU": "A330-300", "EI-NSV": "A330-300", "EI-NSW": "A330-300",
  "EI-NSF": "A321neo", "EI-NSG": "A321neo", "EI-NSH": "A321neo", "EI-NTL": "A321neo", "EI-NTK": "A321neo",
};
export const aircraftType = (tail: string) => TYPE_BY_TAIL[tail] ?? "A320neo";

type Opts = Partial<Pick<Flight, "ops_cause_code" | "inbound_flight_id" | "outbound_pair_id" | "notified_at" | "actual_dep" | "actual_arr" | "date">>;

function spec(group: Group, number: string, date: string, origin: string, dest: string, dep: string, arr: string, pax: number, tail: string, opts: Opts = {}): FlightSpec {
  const sched_dep = dep.includes("T") ? dep : utc(date, dep);
  // An arrival time earlier than the departure time lands the next day.
  let sched_arr = arr.includes("T") ? arr : utc(sched_dep.slice(0, 10), arr);
  if (Date.parse(sched_arr) <= Date.parse(sched_dep)) sched_arr = new Date(Date.parse(sched_arr) + 86_400_000).toISOString().replace(/\.\d{3}Z$/, "Z");
  const localDate = opts.date ?? date;
  const cancelled = group !== "operated";
  const flight: Flight = {
    id: `${number}@${localDate}`,
    number,
    date: localDate,
    origin,
    dest,
    sched_dep,
    sched_arr,
    aircraft: tail,
    status: cancelled ? "cancelled" : "operated",
    actual_dep: opts.actual_dep ?? null,
    actual_arr: opts.actual_arr ?? null,
    pax,
    ops_cause_code: opts.ops_cause_code ?? null,
    inbound_flight_id: opts.inbound_flight_id ?? null,
    outbound_pair_id: opts.outbound_pair_id ?? null,
    notified_at: opts.notified_at ?? null,
    operating_carrier_eu: true,
  };
  return { flight, group, type: aircraftType(tail) };
}

const D = "2025-01-24";
const SMS = "2025-01-24T05:20:00Z"; // OCC: "IROPS SMS 05:20Z"
const INBD_NOTICE = "2025-01-23T20:10:00Z";
const out = (n: string, dest: string, dep: string, arr: string, pax: number, tail: string) => spec("outbound_weather", n, D, "DUB", dest, dep, arr, pax, tail, { ops_cause_code: "71", notified_at: SMS });
const ret = (n: string, origin: string, dep: string, arr: string, pax: number, tail: string, outbound: string, group: Group = "return_weather") =>
  spec(group, n, D, origin, "DUB", dep, arr, pax, tail, { ops_cause_code: "71", notified_at: SMS, outbound_pair_id: `${outbound}@${D}`, inbound_flight_id: `${outbound}@${D}` });
const flew = (n: string, dest: string, dep: string, arr: string, pax: number, tail: string, actDep: string, actArr: string) =>
  spec("operated", n, D, "DUB", dest, dep, arr, pax, tail, { actual_dep: utc(D, actDep), actual_arr: utc(D, actArr) });

/** Storm Éowyn: 27 cancelled (13 + 6 + 4 + 3 + NS31) and 11 operated between 15:30 and 17:30Z. */
export const EOWYN_FLIGHTS: FlightSpec[] = [
  // Outbound weather (13): STD inside the DUB window
  out("NS100", "LHR", "06:10", "07:25", 186, "EI-NSC"),
  out("NS102", "CDG", "06:40", "08:20", 180, "EI-NSD"),
  out("NS104", "AMS", "07:05", "08:40", 174, "EI-NSE"),
  out("NS106", "FRA", "07:30", "09:20", 188, "EI-NSF"),
  out("NS108", "BCN", "08:15", "10:40", 192, "EI-NSG"),
  out("NS110", "MAD", "09:00", "11:25", 190, "EI-NSH"),
  out("NS112", "LIS", "09:40", "12:20", 178, "EI-NSJ"),
  out("NS114", "FCO", "10:20", "13:15", 184, "EI-NSK"),
  out("NS116", "MUC", "11:00", "13:10", 170, "EI-NSL"),
  out("NS21", "JFK", "11:05", "18:35", 268, "EI-NSR"),
  out("NS41", "ORD", "12:10", "20:35", 254, "EI-NSS"),
  out("NS51", "YYZ", "13:00", "20:45", 241, "EI-NST"),
  out("NS118", "ATH", "12:40", "16:30", 183, "EI-NSM"),
  // Return sectors, weather (6): STA inside the DUB window
  ret("NS101", "LHR", "08:00", "09:15", 182, "EI-NSC", "NS100"),
  ret("NS103", "CDG", "08:50", "10:30", 176, "EI-NSD", "NS102"),
  ret("NS105", "AMS", "09:15", "10:40", 170, "EI-NSE", "NS104"),
  ret("NS107", "FRA", "09:50", "11:20", 185, "EI-NSF", "NS106"),
  ret("NS109", "BCN", "11:15", "13:40", 188, "EI-NSG", "NS108"),
  ret("NS111", "MAD", "11:55", "14:20", 186, "EI-NSH", "NS110"),
  // Overnight inbounds (4), destination weather 72. `date` is the local departure date (23 Jan in North America).
  spec("overnight_inbound", "NS20", D, "JFK", "DUB", "2025-01-23T23:30:00Z", "2025-01-24T05:50:00Z", 262, "EI-NSU", { ops_cause_code: "72", notified_at: INBD_NOTICE, date: "2025-01-23" }),
  spec("overnight_inbound", "NS30", D, "BOS", "DUB", "2025-01-24T00:10:00Z", "2025-01-24T05:30:00Z", 168, "EI-NSN", { ops_cause_code: "72", notified_at: INBD_NOTICE, date: "2025-01-23" }),
  spec("overnight_inbound", "NS40", D, "ORD", "DUB", "2025-01-23T23:00:00Z", "2025-01-24T05:40:00Z", 249, "EI-NSV", { ops_cause_code: "72", notified_at: INBD_NOTICE, date: "2025-01-23" }),
  spec("overnight_inbound", "NS50", D, "YYZ", "DUB", "2025-01-23T23:45:00Z", "2025-01-24T05:35:00Z", 236, "EI-NSW", { ops_cause_code: "72", notified_at: INBD_NOTICE, date: "2025-01-23" }),
  // Knock-on returns (3) → Legal: the outbound was cancelled by the storm; calm at both ends
  ret("NS113", "LIS", "13:20", "15:55", 178, "EI-NSJ", "NS112", "knock_on"),
  ret("NS115", "FCO", "14:10", "17:00", 184, "EI-NSK", "NS114", "knock_on"),
  ret("NS117", "MUC", "14:05", "16:20", 168, "EI-NSL", "NS116", "knock_on"),
  // NS31: technical (41), recoded from 71
  spec("technical", "NS31", D, "DUB", "BOS", "16:30", "23:45", 172, "EI-NSB", { ops_cause_code: "71", notified_at: SMS }),
  // Operated (11): "everyone else flew"
  flew("NS120", "LHR", "15:30", "16:45", 174, "EI-NTA", "15:42", "16:55"),
  flew("NS122", "AMS", "15:40", "17:10", 168, "EI-NTB", "15:51", "17:16"),
  flew("NS124", "CDG", "15:50", "17:30", 179, "EI-NTC", "16:04", "17:41"),
  flew("NS126", "FRA", "16:00", "17:50", 182, "EI-NTD", "16:12", "17:58"),
  flew("NS128", "BRU", "16:10", "17:35", 160, "EI-NTE", "16:19", "17:40"),
  flew("NS130", "MAN", "16:20", "17:15", 151, "EI-NTF", "16:27", "17:18"),
  flew("NS132", "EDI", "16:35", "17:40", 158, "EI-NTG", "16:41", "17:43"),
  flew("NS134", "ZRH", "16:45", "18:40", 171, "EI-NTH", "16:56", "18:44"),
  flew("NS136", "CPH", "16:55", "19:00", 165, "EI-NTJ", "17:03", "19:02"),
  flew("NS138", "FAO", "17:10", "20:00", 184, "EI-NTK", "17:16", "20:01"),
  flew("NS140", "AGP", "17:25", "20:10", 186, "EI-NTL", "17:29", "20:12"),
];

const H = "2025-01-26";
const H_SMS = "2025-01-26T10:02:00Z"; // OCC: "IROPS SMS 10:02Z"

/** Storm Herminia: 3 weather cancellations in the 11:30–13:00Z window, NS112 miscoded 71 (AOG), NS30 BOS→DUB technical. */
export const HERMINIA_FLIGHTS: FlightSpec[] = [
  spec("outbound_weather", "NS106", H, "DUB", "FRA", "11:50", "13:40", 176, "EI-NSF", { ops_cause_code: "71", notified_at: H_SMS }),
  spec("outbound_weather", "NS108", H, "DUB", "BCN", "12:20", "14:45", 189, "EI-NSG", { ops_cause_code: "71", notified_at: H_SMS }),
  spec("return_weather", "NS103", H, "CDG", "DUB", "10:50", "12:30", 171, "EI-NSD", { ops_cause_code: "71", notified_at: H_SMS }),
  spec("technical", "NS112", H, "DUB", "LIS", "16:55", "19:35", 178, "EI-NSJ", { ops_cause_code: "71", notified_at: H_SMS }),
  spec("technical", "NS30", H, "BOS", "DUB", "2025-01-26T00:10:00Z", "2025-01-26T05:30:00Z", 168, "EI-NSN", { ops_cause_code: "41", notified_at: "2025-01-25T22:35:00Z", date: "2025-01-25" }),
  spec("operated", "NS101", H, "LHR", "DUB", "14:20", "15:35", 180, "EI-NSC", { actual_dep: utc(H, "14:31"), actual_arr: utc(H, "15:44") }),
  spec("operated", "NS120", H, "DUB", "LHR", "15:30", "16:45", 174, "EI-NTA", { actual_dep: utc(H, "15:38"), actual_arr: utc(H, "16:50") }),
  spec("operated", "NS122", H, "DUB", "AMS", "15:45", "17:15", 168, "EI-NTB", { actual_dep: utc(H, "15:52"), actual_arr: utc(H, "17:19") }),
  spec("operated", "NS31", H, "DUB", "BOS", "16:30", "23:45", 176, "EI-NSB", { actual_dep: utc(H, "16:41"), actual_arr: "2025-01-26T23:50:00Z" }),
];

/** Fares by Art. 7 segment (carrier surcharges YQ/YR are part of the fare; taxes separate). NS31: €450 + €60. */
export function fareFor(origin: string, dest: string): { fare_cents: number; taxes_cents: number } {
  const { segment } = bandFor(origin, dest);
  if (segment === "long_haul_gt3500") return { fare_cents: 45_000, taxes_cents: 6_000 };
  if (segment === "medium_1500_3500") return { fare_cents: 16_000, taxes_cents: 3_200 };
  return { fare_cents: 11_000, taxes_cents: 2_800 };
}

export type Elections = { refund: number; voucher: number; reaccommodated_own: number; reroute_partner: number };

/** NS31's elections are the plan's (32 / 14 / 112 / 14); other flights use the generator's mix (≈19 / 8 / 64 / 9 %). */
export function electionsFor(f: Flight): Elections {
  if (f.number === "NS31" && f.date === "2025-01-24") return { refund: 32, voucher: 14, reaccommodated_own: 112, reroute_partner: 14 };
  const refund = Math.round(f.pax * 0.19);
  const voucher = Math.round(f.pax * 0.08);
  const reroute_partner = Math.round(f.pax * 0.09);
  return { refund, voucher, reroute_partner, reaccommodated_own: f.pax - refund - voucher - reroute_partner };
}

/** Seat refs for a flight's coupons: business 1–4 (A C D F) then economy rows of six. NS31 → 172 seats incl. 14C. */
export function seatRefs(pax: number): string[] {
  const seats: string[] = [];
  for (let row = 1; row <= 4 && seats.length < pax; row++) for (const s of "ACDF") if (seats.length < pax) seats.push(`${row}${s}`);
  for (let row = 5; seats.length < pax; row++) for (const s of "ABCDEF") if (seats.length < pax) seats.push(`${row}${s}`);
  return seats;
}
