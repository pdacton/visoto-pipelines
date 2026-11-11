"""Identifier value domains: one per validator, written by hand (format and checksum).

A strong validator recognises its values alone (format plus checksum or a distinctive prefix);
a weak one (any integer in a range) also needs a hint in the slot's name.
"""
import re
from dataclasses import dataclass, field
from typing import Callable

XSD = "http://www.w3.org/2001/XMLSchema#"


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def ahv_valid(s: str) -> bool:
    """AHV/AVS number (756.XXXX.XXXX.XX): EAN-13 check digit."""
    if not re.fullmatch(r"756\.?\d{4}\.?\d{4}\.?\d{2}", s.strip()):
        return False
    d = [int(c) for c in _digits(s)]
    total = sum(x * (3 if i % 2 else 1) for i, x in enumerate(d[:12]))
    return (10 - total % 10) % 10 == d[12]


def uid_valid(s: str) -> bool:
    """Swiss business identification number (CHE-123.456.789, optionally MWST/TVA/IVA/HR/RC/RI): mod 11."""
    m = re.fullmatch(r"CHE-?(\d{3})\.?(\d{3})\.?(\d{3})(\s*(MWST|TVA|IVA|HR|RC|RI))?", s.strip().upper())
    if not m:
        return False
    d = [int(c) for c in "".join(m.group(1, 2, 3))]
    check = 11 - sum(x * w for x, w in zip(d[:8], (5, 4, 3, 2, 7, 6, 5, 4))) % 11
    check = 0 if check == 11 else check
    return check != 10 and check == d[8]


def egrid_valid(s: str) -> bool:
    """E-GRID, the federal land parcel identifier: CH followed by 12 digits."""
    return bool(re.fullmatch(r"CH\d{12}", s.strip().upper()))


def int_range(lo: int, hi: int) -> Callable[[str], bool]:
    def valid(s: str) -> bool:
        t = s.strip()
        if re.fullmatch(r"\d+(\.0+)?", t):
            return lo <= int(float(t)) <= hi
        return False
    return valid


@dataclass
class Validator:
    name: str                       # identifier of the value domain (…/valuedomain/identifier/{name})
    title: dict
    description: dict
    datatype: str
    valid: Callable[[str], bool]
    pattern: str | None = None      # sh:pattern of the value domain
    name_hint: re.Pattern | None = None   # required for weak validators
    conforms_to: list = field(default_factory=list)

    def rate(self, sample: list[str]) -> float:
        return sum(1 for v in sample if self.valid(v)) / len(sample) if sample else 0.0

    def applies(self, slot_name: str, sample: list[str], min_rate: float, min_values: int = 3) -> float | None:
        """The pass rate when the slot's values are this identifier, else None."""
        if len(sample) < min_values:
            return None
        if self.name_hint and not self.name_hint.search(slot_name.lower()):
            return None
        r = self.rate(sample)
        return r if r >= min_rate else None


VALIDATORS = [
    Validator("ahv", {"en": "AHV number", "de": "AHV-Nummer", "fr": "Numéro AVS", "it": "Numero AVS"},
              {"en": "Swiss social security number, 13 digits starting with 756, with an EAN-13 check digit."},
              XSD + "string", ahv_valid, pattern=r"^756\.?\d{4}\.?\d{4}\.?\d{2}$"),
    Validator("uid", {"en": "Business identification number (UID)", "de": "Unternehmens-Identifikationsnummer (UID)",
                      "fr": "Numéro d'identification des entreprises (IDE)",
                      "it": "Numero d'identificazione delle imprese (IDI)"},
              {"en": "CHE followed by 9 digits, the last a mod-11 check digit."},
              XSD + "string", uid_valid, pattern=r"^CHE-?\d{3}\.?\d{3}\.?\d{3}"),
    Validator("egrid", {"en": "Land parcel identifier (E-GRID)", "de": "Grundstücks-Identifikator (E-GRID)",
                        "fr": "Identificateur d'immeuble (E-GRID)", "it": "Identificatore del fondo (E-GRID)"},
              {"en": "Federal land parcel identifier: CH followed by 12 digits."},
              XSD + "string", egrid_valid, pattern=r"^CH\d{12}$"),
    Validator("egid", {"en": "Federal building identifier (EGID)", "de": "Eidgenössischer Gebäudeidentifikator (EGID)",
                       "fr": "Identificateur fédéral de bâtiment (EGID)",
                       "it": "Identificatore federale degli edifici (EGID)"},
              {"en": "Building number of the Federal Register of Buildings and Dwellings, 1 to 999999999."},
              XSD + "integer", int_range(1, 999_999_999), name_hint=re.compile(r"(^|[^a-z])(gwr_)?egid([^a-z]|$)")),
    Validator("ewid", {"en": "Federal dwelling identifier (EWID)", "de": "Eidgenössischer Wohnungsidentifikator (EWID)",
                       "fr": "Identificateur fédéral de logement (EWID)",
                       "it": "Identificatore federale delle abitazioni (EWID)"},
              {"en": "Dwelling number within a building of the Federal Register of Buildings and Dwellings, 1 to 999."},
              XSD + "integer", int_range(1, 999), name_hint=re.compile(r"(^|[^a-z])ewid([^a-z]|$)")),
    Validator("edid", {"en": "Federal entrance identifier (EDID)", "de": "Eidgenössischer Eingangsidentifikator (EDID)",
                       "fr": "Identificateur fédéral d'entrée (EDID)", "it": "Identificatore federale dell'entrata (EDID)"},
              {"en": "Entrance number within a building of the Federal Register of Buildings and Dwellings, 0 to 99."},
              XSD + "integer", int_range(0, 99), name_hint=re.compile(r"(^|[^a-z])edid([^a-z]|$)")),
    Validator("postcode", {"en": "Swiss postcode", "de": "Postleitzahl", "fr": "Numéro postal d'acheminement",
                           "it": "Numero postale d'avviamento"},
              {"en": "Four-digit Swiss postal code, 1000 to 9699."},
              XSD + "integer", int_range(1000, 9699),
              name_hint=re.compile(r"(^|[^a-z])(plz|npa|cap|postleitzahl|postcode|postal_?code|zip)([^a-z]|$)")),
]
