"use client";

import { useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useApp } from "@/lib/store";
import { payouts, pseudonym } from "@/data/app";
import { FLIGHTS, NS31 } from "@/data/scenario";

/** Opens the receipt an auditor's link points at: ?why=provision&flight=NS31 or ?why=<payout id>. */
export function ReceiptFromUrl() {
  const params = useSearchParams();
  const why = params.get("why");
  const flight = params.get("flight");

  useEffect(() => {
    if (!why) return;
    const { openWhy, role } = useApp.getState();
    if (why === "provision") {
      if (FLIGHTS.some((f) => f.id === flight && f.verdict === "technical")) openWhy({ kind: "provision", flight: flight!, amount: NS31.provision });
      return;
    }
    const p = payouts().find((x) => x.id === why);
    if (p && p.amount > 0) openWhy({ kind: "payout", id: p.id, flight: p.flight, passenger: role === "ops" ? pseudonym(p) : p.name, amount: p.amount });
  }, [why, flight]);

  return null;
}
