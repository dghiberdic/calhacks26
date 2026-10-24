"""Chart of accounts, exactly CONTRACTS §5."""
from __future__ import annotations

ACCOUNTS: dict[str, str] = {
    # Assets
    "1000": "Bank",
    "1110": "Card acquirer",
    # Liabilities
    "2000": "Trade payables",
    "2100": "ATL",
    "2110": "Taxes payable",
    "2120": "Refunds payable",
    "2125": "Refund clearing",
    "2131": "Refund vouchers",
    "2132": "Compensation vouchers",
    "2140": "EU261 compensation liability (estimated)",
    "2141": "EU261 compensation payable",
    "2150": "Accrued care",
    "2160": "Interline payable",
    "2170": "Legal costs provision (IAS 37)",
    # P&L
    "4000": "Passenger revenue",
    "4010": "Breakage",
    "4090": "EU261 compensation (reduction of passenger revenue)",
    "6100": "Care",
    "6110": "Rerouting",
    "6120": "Claims legal",
}

GROUP: dict[str, str] = {code: ("asset" if code[0] == "1" else "liability" if code[0] == "2" else "pnl")
                         for code in ACCOUNTS}

# Natural balance side: assets, expenses and the 4090 contra-revenue are debit-normal.
DEBIT_NORMAL: frozenset[str] = frozenset({"1000", "1110", "4090", "6100", "6110", "6120"})


def account_name(code: str) -> str:
    return ACCOUNTS[code]
