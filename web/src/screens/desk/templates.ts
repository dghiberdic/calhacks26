import type { InjectKind } from "@/api/types";

/**
 * Starting text for each kind of document a judge can hand the Reader. They read like the systems
 * they come from (AMOS tech log, NetLine OCC, CRM, a passenger claim, an ops email, an Airbus notice)
 * and are meant to be edited. Every figure in them is part of the document, never shown as a result:
 * what counts is what the Reader can quote back and the engine decides from it.
 */
export type KindInfo = {
  kind: InjectKind;
  label: string;
  /** Where documents like this come from. */
  from: string;
  /** Machine text is set in mono. */
  mono: boolean;
  template: string;
};

export const KINDS: KindInfo[] = [
  {
    kind: "tech_log",
    label: "Tech log",
    from: "AMOS line",
    mono: true,
    template:
      "24JAN 06:05Z EI-NSF DUB N/S. ECAM BLEED 1 LEAK ON TAXI-OUT, RTN TO STAND. DUCT CLAMP FAILED AT PRV, HEAT DAMAGE TO WIRING LOOM AFT OF PYLON. NO MEL RELIEF. A/C AOG. RTS EST 25JAN 10:00Z.",
  },
  {
    kind: "occ_log",
    label: "OCC log",
    from: "NetLine ops log",
    mono: true,
    template:
      "24JAN 15:10Z OCC DM: NS118/24JAN DUB-ATH CNL RSN 71. EI-NSH S/S ON STAND 112. RESERVE CREW CALLED 13:40Z, FDP LIMIT REACHED 15:05Z. NO OTHER CREW AVAILABLE. PAX REBOOKED NS118/25JAN.",
  },
  {
    kind: "crm",
    label: "CRM",
    from: "Service-desk note",
    mono: true,
    template:
      "CRM 24JAN 09:42Z AGENT T2-SD-04\nPNR K7QX2M PAX 2/3 NS114/24JAN DUB-FCO CNL\nSERVICE-DESK VOUCHER EUR 300 ISSUED IN LIEU OF COMPENSATION.\nPAX ACCEPTED VERBALLY. NO SIGNATURE CAPTURED.",
  },
  {
    kind: "claim",
    label: "Claim",
    from: "Passenger web form",
    mono: false,
    template:
      "Booking ref K7QX2M, flight NS114 Dublin to Rome on 24 January 2025.\n\nMy flight was cancelled at the desk on the morning and I was only rebooked two days later. I am claiming €400 compensation under Regulation (EC) 261/2004, Article 7. I never agreed to take a voucher instead of compensation and I did not sign anything.\n\nPlease pay to the card used for the booking.",
  },
  {
    kind: "email",
    label: "Email",
    from: "Ops mailbox",
    mono: false,
    template:
      "From: duty.manager@northstar-air.example\nTo: claims@northstar-air.example\nSubject: RE: NS51 24 Jan, really weather?\n\nChecked with MCC. EI-NSK was serviceable at DUB all morning. NS51 was held for crew: the inbound crew from NS50 never arrived and the standby crew timed out at 12:40Z. The wind was not the reason we couldn't go.",
  },
  {
    kind: "manufacturer",
    label: "Manufacturer",
    from: "Airbus in-service notice",
    mono: true,
    template:
      "AIRBUS IN-SERVICE INFORMATION ISI 29.11.00041\nISSUED 20 JAN 2025\nSUBJECT: A321 FAMILY HYDRAULIC ENGINE-DRIVEN PUMP, CASE DRAIN PORT CRACKING\nA MANUFACTURING DEFECT HAS BEEN FOUND IN PUMPS FROM ONE PRODUCTION BATCH. THE DEFECT IS NOT DETECTABLE BY SCHEDULED MAINTENANCE. OPERATORS ARE ADVISED TO REPLACE AFFECTED PUMPS AT THE NEXT OPPORTUNITY.",
  },
];

export const KIND_BY_ID = Object.fromEntries(KINDS.map((k) => [k.kind, k])) as Record<InjectKind, KindInfo>;

/** `tech_log` → `tech-log` for chips. */
export const kindChip = (kind: string) => kind.replace(/_/g, "-");
