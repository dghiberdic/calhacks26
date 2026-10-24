"""D2 · Root cause of a tech-log defect: internal (the carrier's own aircraft) or external (outside its control).

Derived by the ENGINE from the ATA chapter plus keywords in the AMOS-style line, never by the LLM (plan §1.2).

- **External** (routed to Legal as ``needs_legal``): bird strike, lightning, hail, FOD, de-icing, volcanic ash.
  External keywords win over the chapter: a bird strike logged under ATA 72 (engine) is still external.
- **Internal**: a chapter in the internal set AND an internal failure keyword (leak, pump, actuator, sensor...).
- **Unmatched**: anything else. Treated as not internal, so it routes to Legal like an external cause.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# ATA Spec 100 / JASC chapters where a failure is the carrier's own (Wallentin-Hermann ¶24-25: inherent in operation)
INTERNAL_CHAPTERS: dict[str, str] = {
    "21": "air conditioning", "22": "auto flight", "23": "communications", "24": "electrical power",
    "25": "equipment/furnishings", "26": "fire protection", "27": "flight controls", "28": "fuel",
    "29": "hydraulic power", "30": "ice and rain protection", "31": "indicating/recording", "32": "landing gear",
    "33": "lights", "34": "navigation", "35": "oxygen", "36": "pneumatic", "38": "water/waste",
    "45": "central maintenance", "46": "information systems", "49": "APU", "52": "doors", "56": "windows",
    "61": "propellers", "71": "powerplant", "72": "engine", "73": "engine fuel and control", "74": "ignition",
    "75": "engine air", "76": "engine controls", "77": "engine indicating", "78": "exhaust", "79": "oil",
    "80": "starting",
}

# components first, then failure modes: the description reads "<component> <mode>" (e.g. "engine-driven pump leak")
COMPONENT_KEYWORDS: dict[str, str] = {
    r"\bEDP\b": "engine-driven pump", r"\bPUMP\b": "pump", r"\bACTUATOR\b": "actuator", r"\bSENSOR\b": "sensor",
    r"\bPROBE\b": "probe", r"\bVALVE\b": "valve", r"\bAVIONICS?\b": "avionics",
    r"\b(COMPUTER|FMGC|ELAC|SEC|FAC|ADIRU)\b": "computer", r"\bBRAKES?\b": "brake", r"\b(TYRE|TIRE)S?\b": "tyre",
    r"\bSTARTER\b": "starter", r"\b(GENERATOR|IDG)\b": "generator",
}
MODE_KEYWORDS: dict[str, str] = {
    r"\bLEAK(S|ING|AGE)?\b": "leak", r"\b(FAULT|FLT)\b": "fault", r"\bFAIL(ED|URE|S)?\b": "failure",
    r"\bINOP\b": "inoperative", r"\bLO PR\b": "low pressure", r"\bCRACK(ED|S)?\b": "crack",
    r"\bCORRO(SION|DED)\b": "corrosion", r"\b(WORN|WEAR)\b": "wear", r"\bVIBRATION\b": "vibration",
    r"\bOVERHEAT\b": "overheat", r"\bECAM\b": "ECAM caution",
}
INTERNAL_KEYWORDS: dict[str, str] = {**COMPONENT_KEYWORDS, **MODE_KEYWORDS}

EXTERNAL_KEYWORDS: dict[str, str] = {
    r"\bBIRD\s*STRIKE\b|\bBIRDSTRIKE\b|\bBIRD\b": "bird strike",
    r"\bLIGHTNING\b|\bLTNG\b": "lightning strike",
    r"\bHAIL\b": "hail damage",
    r"\bFOD\b|\bFOREIGN OBJECT\b": "foreign object damage",
    r"\bDE-?IC(E|ING)\b|\bANTI-?ICING FLUID\b": "de-icing",
    r"\bVOLCANIC\b|\bASH\b": "volcanic ash",
    r"\bSABOTAGE\b|\bTERROR": "security event",
}

Category = Literal["internal", "external", "unmatched"]


@dataclass(frozen=True)
class AtaClass:
    chapter: str
    chapter_name: str | None
    category: Category
    matched: tuple[str, ...]        # human-readable keyword labels that decided it

    @property
    def internal(self) -> bool:
        return self.category == "internal"

    @property
    def defect(self) -> str:
        """Short description, e.g. "engine-driven pump leak"."""
        comps = [m for m in self.matched if m in COMPONENT_KEYWORDS.values()]
        modes = [m for m in self.matched if m in MODE_KEYWORDS.values()]
        if comps and modes:
            return f"{comps[0]} {modes[0]}"
        return (comps or modes or [f"ATA {self.chapter} defect"])[0]

    @property
    def label(self) -> str:
        what = ", ".join(self.matched) or "no keyword match"
        return f"ATA {self.chapter} ({self.chapter_name or 'unlisted'}): {self.category}, {what}"


def chapter_of(ata: str | None) -> str:
    digits = re.sub(r"\D", "", ata or "")
    return digits[:2] if len(digits) >= 2 else ""


def _hits(table: dict[str, str], text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(label for pat, label in table.items() if re.search(pat, text)))


def classify(ata: str | None, text: str) -> AtaClass:
    up = (text or "").upper()
    ch = chapter_of(ata)
    name = INTERNAL_CHAPTERS.get(ch)
    ext = _hits(EXTERNAL_KEYWORDS, up)
    if ext:
        return AtaClass(ch, name, "external", ext)
    inter = _hits(INTERNAL_KEYWORDS, up)
    if name is not None and inter:
        return AtaClass(ch, name, "internal", inter)
    return AtaClass(ch, name, "unmatched", inter)
