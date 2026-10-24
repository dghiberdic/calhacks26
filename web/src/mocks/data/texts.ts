// Verbatim source texts for the mock world. The NS31 tech log, MCC, spares and OCC lines are copied
// exactly from IMPLEMENTATION_PLAN.md §1.2; everything else is written in the same register.
// Every Evidence.quote / Fact.span in the mocks is a substring of one of these texts (tests check it).
import type { Source, SourceKind } from "@/api/types";
import { sha256 } from "./util";

// ---------- Storm Éowyn, 23–24 Jan 2025 ----------
export const TECHLOG_NS31 =
  "23JAN 21:40Z EI-NSB DUB N/S. HYD FLUID ENG 2 LWR COWL. GND RUN: ECAM HYD Y ENG 2 PUMP LO PR. EXT LEAK EDP CASE DRAIN PORT, EXCEEDS AMM LIMIT. EDP RPLCMT REQD. NO MEL RELIEF. A/C AOG.";
export const MCC_NS31 = "22:15Z: NO EDP IN DUB STORES; POOL UNIT EX-TLS VIA CDG 25JAN ETA 14:00Z, RTS EST 20:00Z.";
export const SPARES_EOWYN = "No long-range tail at DUB. XLR EI-NSN at BOS (NS30 CNL 72); A330s at JFK/ORD/YYZ (NS20/40/50 CNL); A320/A321neo lack range.";
export const OCC_EOWYN =
  "05:12Z OCC DM: STORM ÉOWYN CNL LIST → NETLINE, RSN 71. NS100/101 NS102/103 NS104/105 NS106/107 NS108/109 NS110/111 NS112/113 NS114/115 NS116/117 NS118 NS21 NS41 NS51 NS31. INBD NS20 NS30 NS40 NS50 RSN 72. ASM SENT. IROPS SMS 05:20Z.";
/** The verbatim span of the OCC batch that carries the departure-weather code. */
export const OCC_EOWYN_71 = "STORM ÉOWYN CNL LIST → NETLINE, RSN 71";
export const OCC_EOWYN_72 = "INBD NS20 NS30 NS40 NS50 RSN 72";

/** Spares lines for the three knock-on returns (NS117's is the plan's). */
export const SPARES_KNOCK_ON: Record<string, string> = {
  NS113: "No tail at LIS. Earliest ferry ex-DUB 15:30Z → LIS dep 19:05Z = STD+5h45.",
  NS115: "No tail at FCO. Earliest ferry ex-DUB 15:40Z → FCO dep 19:30Z = STD+5h20.",
  NS117: "No tail at MUC. Earliest ferry ex-DUB 15:30Z → MUC dep 18:25Z = STD+4h20.",
};
/** PSS reaccommodation lines: the earliest reroute was offered on any carrier. */
export const PSS_KNOCK_ON: Record<string, string> = {
  NS113: "NS113 24JAN LIS-DUB CNL · 178 PAX · REROUTE OFFERED: EARLIEST AVAILABLE, TP DIRECT",
  NS115: "NS115 24JAN FCO-DUB CNL · 184 PAX · REROUTE OFFERED: EARLIEST AVAILABLE, AZ VIA LHR",
  NS117: "NS117 24JAN MUC-DUB CNL · 168 PAX · REROUTE OFFERED: EARLIEST AVAILABLE, LH VIA FRA",
};

/** 14C: the service-desk voucher in lieu (CRM, tier 3) and her claim (tier 4, PII). */
export const CRM_14C =
  "24JAN 14:52Z T2 SVC DESK · VOUCHER EUR 300.00 ISSUED IN LIEU OF COMPENSATION · NS31/24JAN SEAT 14C · STATUS ACCEPTED · SIGNATURE: NONE CAPTURED · AGT TD41";
export const PAX_14C_NAME = "Orla Keane";
export const PAX_14C_EMAIL = "o.keane@example.com";
export const CLAIM_14C = `From: ${PAX_14C_NAME} <${PAX_14C_EMAIL}>
Sent: 25 Jan 2025 01:17Z
Subject: NS31 24 Jan Dublin–Boston, seat 14C: EU261 claim

The service desk in Terminal 2 gave me a €300 voucher and said that was all I'd get. I never agreed to take it instead of compensation and I didn't sign anything. I'm claiming the €600 I'm owed under EU261. Booking ref K4TZ9P.`;
export const CLAIM_14C_SPAN = "I never agreed to take it instead of compensation and I didn't sign anything.";

/** CRM bot (06:02–09:40Z): 32 refunds initiated on direct-sold NS31 coupons, each with a "weather" email. */
export const CRM_BOT_FIRST = "24JAN 06:02Z CRM-BOT · NS31/24JAN · REFUND INITIATED EUR 510.00 · DIRECT · EMAIL SENT: WEATHER, NO COMPENSATION";
export const CRM_BOT_LAST = "24JAN 09:40Z CRM-BOT · NS31/24JAN · REFUND INITIATED EUR 510.00 · DIRECT · 32 OF 32 · EMAIL SENT: WEATHER, NO COMPENSATION";

// ---------- Storm Herminia, 26 Jan 2025 ----------
export const TECHLOG_NS112_HERMINIA = "26JAN 08:40Z EI-NSJ DUB. ENG 1 BLEED DUCT CLAMP FAILED, HOT AIR LEAK PYLON AREA. DUCT CLAMP RPLCMT REQD. NO MEL RELIEF. A/C AOG.";
export const TECHLOG_NS30_HERMINIA = "25JAN 22:05Z EI-NSN BOS N/S. BRK 3 WEAR PIN FLUSH. BRAKE CHANGE REQD. NO SPARE AT BOS. NO MEL RELIEF. A/C AOG.";
export const OCC_HERMINIA = "09:55Z OCC DM: STORM HERMINIA CNL LIST → NETLINE, RSN 71. NS106 NS108 NS103 NS112. ASM SENT. IROPS SMS 10:02Z.";
export const OCC_HERMINIA_71 = "STORM HERMINIA CNL LIST → NETLINE, RSN 71";
export const OCC_NS30_HERMINIA = "25JAN 22:30Z OCC: NS30 BOS-DUB CNL RSN 41 (EI-NSN AOG BOS).";
export const CRM_HERMINIA_DESK = "26JAN 14:10Z T2 SVC DESK · 31 VOUCHERS EUR 300.00 ISSUED IN LIEU OF COMPENSATION · NS112/26JAN · STATUS ACCEPTED · SIGNATURE: NONE CAPTURED";
export const CRM_HERMINIA_BOS = "26JAN 00:40Z BOS SVC DESK · VOUCHER EUR 300.00 ISSUED IN LIEU OF COMPENSATION · NS30/25JAN · STATUS ACCEPTED · SIGNATURE: NONE CAPTURED";

// ---------- PII registry (masked for every role except the Claims Lead) ----------
export const PII_STRINGS = [PAX_14C_NAME, PAX_14C_EMAIL];

// ---------- sources ----------
const TIER: Record<SourceKind, number> = {
  metar: 1, tech_log: 1, mcc_log: 1, schedule: 2, manifest: 2, pss: 2, bsp: 2, spares: 2, manufacturer: 2,
  occ_log: 3, crm: 3, claim: 4, email: 4, challenge: 4, regulation: 1, ruling: 1,
  finance: 2, // GL extracts, care accrual sheets, vendor invoices (D0b): system records, like BSP
};
const ACL: Partial<Record<SourceKind, string[]>> = {
  tech_log: ["maintenance", "ops"], mcc_log: ["maintenance", "ops"], spares: ["ops"], occ_log: ["ops"], schedule: ["ops"], manifest: ["ops", "pii"],
  pss: ["ops", "pii"], crm: ["pii"], claim: ["pii", "legal"], email: ["pii"], bsp: ["finance"], finance: ["finance"], metar: [], regulation: ["legal"], ruling: ["legal"],
};

export function makeSource(id: string, kind: SourceKind, title: string, text: string, received_at: string, uri: string | null = null): Source {
  return { id, kind, title, text, sha256: sha256(text), received_at, trust_tier: TIER[kind], acl_tags: ACL[kind] ?? [], uri };
}

export const trustTier = (kind: SourceKind) => TIER[kind];
