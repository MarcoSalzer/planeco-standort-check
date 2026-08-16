"""merge_fields: Feld-Merge-Regel bei F3 (Konzept §4).

Pro Feld einzeln: neuer Wert gefüllt -> neuer Wert gewinnt (Korrektur
schlägt Alt). Neuer Wert leer, alter gefüllt -> alter Wert wird
übernommen (Lücke wird gefüllt). Beide leer -> leer.

"Leer" heißt None oder ein nur aus Whitespace bestehender String -
False (z.B. is_owner=False) ist ein echter, gefüllter Wert und wird
nicht mit "keine Angabe" verwechselt.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MergeResult:
    values: dict[str, Any]
    changed_fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    merged_fields: dict[str, Any] = field(default_factory=dict)


def merge_fields(*, old: dict[str, Any], new: dict[str, Any]) -> MergeResult:
    values: dict[str, Any] = {}
    changed_fields: dict[str, dict[str, Any]] = {}
    merged_fields: dict[str, Any] = {}

    for key, new_value in new.items():
        old_value = old.get(key)
        if _is_filled(new_value):
            values[key] = new_value
            if _is_filled(old_value) and old_value != new_value:
                changed_fields[key] = {"alt": old_value, "neu": new_value}
        elif _is_filled(old_value):
            values[key] = old_value
            merged_fields[key] = old_value
        else:
            values[key] = new_value

    return MergeResult(values=values, changed_fields=changed_fields, merged_fields=merged_fields)


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True
