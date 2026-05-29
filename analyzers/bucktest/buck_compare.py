#!/usr/bin/env python3
"""
Compare two buck_characterize.py CSV files by matching test setpoints.

The comparison keys are:
  iq:         test + vin_set
  efficiency: test + vin_set + iload_set_a
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Key:
    test: str
    vin_set: float
    iload_set_a: Optional[float]


@dataclass
class Metric:
    label: str
    csv_field: str
    scale: float = 1.0
    unit: str = ""


IQ_METRICS = [
    Metric("Vin", "vin_meas", unit="V"),
    Metric("Iin", "iin_meas_a", scale=1000.0, unit="mA"),
    Metric("Pin", "pin_w", scale=1000.0, unit="mW"),
    Metric("Iq", "iq_ma", unit="mA"),
]

EFFICIENCY_METRICS = [
    Metric("Vin", "vin_meas", unit="V"),
    Metric("Iin", "iin_meas_a", scale=1000.0, unit="mA"),
    Metric("Pin", "pin_w", unit="W"),
    Metric("Vout", "vout_meas", unit="V"),
    Metric("Iout", "iout_meas_a", scale=1000.0, unit="mA"),
    Metric("Pout", "pout_w", unit="W"),
    Metric("Efficiency", "efficiency", scale=100.0, unit="pct"),
]


def parse_float(value: str) -> Optional[float]:
    if value == "":
        return None
    return float(value)


def load_csv(path: Path) -> dict[Key, dict[str, str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"{path} has no CSV header")

        rows = list(reader)
        if not rows:
            raise ValueError(f"{path} has no data rows")

    indexed = {}
    for row in rows:
        key = Key(
            test=row["test"],
            vin_set=float(row["vin_set"]),
            iload_set_a=parse_float(row["iload_set_a"]),
        )
        if key in indexed:
            raise ValueError(f"{path} has duplicate row for {format_key(key)}")
        indexed[key] = row
    return indexed


def numeric_value(row: dict[str, str], metric: Metric) -> Optional[float]:
    value = parse_float(row[metric.csv_field])
    if value is None:
        return None
    return value * metric.scale


def format_key(key: Key) -> str:
    if key.iload_set_a is None:
        return f"{key.test} Vin={key.vin_set:g}"
    return f"{key.test} Vin={key.vin_set:g} Iload={key.iload_set_a:g}"


def fmt(value: float, unit: str = "") -> str:
    text = f"{value:.6g}"
    if unit:
        return f"{text} {unit}"
    return text


def percent_difference(old: float, new: float) -> float:
    return (new - old) / max(abs(old), abs(new), 1e-30) * 100.0


def format_pct(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if abs(value) < 0.005:
        value = 0.0
    return f"{value:+.2f}%"


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def format_row(row: list[str]) -> str:
        return "  ".join(cell.rjust(widths[idx]) for idx, cell in enumerate(row))

    print(format_row(headers))
    print(format_row(["-" * width for width in widths]))
    for row in rows:
        print(format_row(row))


def pct_at(rows_a: dict[Key, dict[str, str]],
           rows_b: dict[Key, dict[str, str]],
           key: Key,
           metric: Metric) -> Optional[float]:
    if key not in rows_a or key not in rows_b:
        return None
    old = numeric_value(rows_a[key], metric)
    new = numeric_value(rows_b[key], metric)
    if old is None or new is None:
        return None
    return percent_difference(old, new)


def print_iq_matrix(rows_a: dict[Key, dict[str, str]],
                    rows_b: dict[Key, dict[str, str]]) -> None:
    vins = sorted({key.vin_set for key in rows_a if key.test == "iq"} |
                  {key.vin_set for key in rows_b if key.test == "iq"})
    if not vins:
        return

    print()
    print("Iq percent difference")
    headers = ["metric"] + [f"{vin:g}V" for vin in vins]
    rows = []
    for metric in IQ_METRICS:
        row = [metric.label]
        for vin in vins:
            key = Key("iq", vin, None)
            row.append(format_pct(pct_at(rows_a, rows_b, key, metric)))
        rows.append(row)
    print_table(headers, rows)


def print_efficiency_matrix(rows_a: dict[Key, dict[str, str]],
                            rows_b: dict[Key, dict[str, str]],
                            metric: Metric) -> None:
    keys = [key for key in set(rows_a) | set(rows_b) if key.test == "efficiency"]
    if not keys:
        return
    vins = sorted({key.vin_set for key in keys})
    loads = sorted({key.iload_set_a for key in keys if key.iload_set_a is not None})

    print()
    print(f"{metric.label} percent difference")
    headers = ["load"] + [f"{vin:g}V" for vin in vins]
    rows = []
    for load in loads:
        row = [f"{load * 1000:g}mA"]
        for vin in vins:
            key = Key("efficiency", vin, load)
            row.append(format_pct(pct_at(rows_a, rows_b, key, metric)))
        rows.append(row)
    print_table(headers, rows)


def print_key_status(rows_a: dict[Key, dict[str, str]],
                     rows_b: dict[Key, dict[str, str]]) -> list[Key]:
    keys_a = set(rows_a)
    keys_b = set(rows_b)
    common = sorted(keys_a & keys_b, key=lambda k: (k.test, k.vin_set, k.iload_set_a or -1))
    missing_b = sorted(keys_a - keys_b, key=lambda k: (k.test, k.vin_set, k.iload_set_a or -1))
    missing_a = sorted(keys_b - keys_a, key=lambda k: (k.test, k.vin_set, k.iload_set_a or -1))

    print("Setpoints:")
    print(f"  common: {len(common)}")
    print(f"  only in first file: {len(missing_b)}")
    print(f"  only in second file: {len(missing_a)}")
    for key in missing_b[:10]:
        print(f"    first only:  {format_key(key)}")
    for key in missing_a[:10]:
        print(f"    second only: {format_key(key)}")
    return common


def compare(args: argparse.Namespace) -> int:
    path_a = Path(args.first)
    path_b = Path(args.second)
    rows_a = load_csv(path_a)
    rows_b = load_csv(path_b)

    print(f"Comparing {path_a} to {path_b}")
    print(f"Cells are 100 * ({path_b.stem} - {path_a.stem}) / max(abs(values)).")
    print_key_status(rows_a, rows_b)
    print_iq_matrix(rows_a, rows_b)
    print_efficiency_matrix(rows_a, rows_b, Metric("Efficiency", "efficiency"))

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two buck_characterize.py CSV files.")
    parser.add_argument("first", help="First buck CSV")
    parser.add_argument("second", help="Second buck CSV")
    args = parser.parse_args()

    try:
        return compare(args)
    except (OSError, KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
