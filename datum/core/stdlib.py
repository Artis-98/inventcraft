"""The standard parts library: the CSV files in ``datum/stdlib``.

One file per family, its sizes as rows, and a few ``# key: value`` lines
on top saying what it is, where it sits in the library, where its numbers
came from and under which licence.  The folder is built from open sources
by ``tools/stdlib/build.py`` and can be given away on its own; see its
README for the sources and their licences.

``profiles()`` are the Frame Generator's steel shapes, ``fasteners()``
the bolts, screws, nuts, washers, pins and rings, ``bearings()`` the
bearings.  Each is read once.
"""
from __future__ import annotations

import csv
import glob
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


def folder() -> str:
    """Where the library is: next to the code, or in a built copy's
    bundle."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        bundled = os.path.join(base, "datum", "stdlib")
        if os.path.isdir(bundled):
            return bundled
    return os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "stdlib")


@dataclass
class Table:
    """One family's file, as read."""

    id: str
    name: str
    standard: str
    category: str
    kind: str
    drive: str = ""
    source: str = ""
    licence: str = ""
    columns: List[str] = field(default_factory=list)
    rows: List[List] = field(default_factory=list)
    lengths: List[float] = field(default_factory=list)
    ranges: Dict[str, Tuple[float, float]] = field(default_factory=dict)


def read(path: str) -> Table:
    meta: Dict[str, str] = {}
    body: List[str] = []
    with open(path, encoding="utf-8") as fp:
        for line in fp:
            # the notes are on top: a size such as #10 is a row, not one
            if not body and line.startswith("#"):
                key, _, value = line[1:].partition(":")
                if value:
                    meta[key.strip()] = value.strip()
            elif line.strip():
                body.append(line)
    reader = csv.reader(body)
    header = next(reader)
    ranged = header[-2:] == ["lmin", "lmax"]
    columns = header[1:-2] if ranged else header[1:]
    rows, ranges = [], {}
    for line in reader:
        size = line[0]
        rows.append([size] + [float(v) for v in line[1:1 + len(columns)]])
        if ranged and line[-2] and line[-1]:
            ranges[size] = (float(line[-2]), float(line[-1]))
    lengths = [float(v) for v in meta.get("lengths", "").split()]
    return Table(meta.get("id", os.path.splitext(os.path.basename(path))[0]),
                 meta.get("name", ""), meta.get("standard", ""),
                 meta.get("category", ""), meta.get("kind", ""),
                 meta.get("drive", ""), meta.get("source", ""),
                 meta.get("licence", ""), columns, rows, lengths, ranges)


_read: Dict[str, List[Table]] = {}


def _shelf(name: str) -> List[Table]:
    if name not in _read:
        paths = sorted(glob.glob(os.path.join(folder(), name, "*.csv")))
        _read[name] = [read(p) for p in paths]
    return _read[name]


def profiles() -> List[Table]:
    return _shelf("profiles")


def fasteners() -> List[Table]:
    return _shelf("fasteners")


def bearings() -> List[Table]:
    return _shelf("bearings")


def fittings() -> List[Table]:
    """Pipe fittings: the sockets' sizes, which Insert Pipe's automatic
    elbows, tees, couplings and reducers are made to."""
    return _shelf("fittings")


def body(standard: str) -> str:
    """The organisation a standard is from, as the library's Standards
    filter lists it: ISO 4762 is ISO, DIN EN 10056-1 and EN 1662 are EN,
    ASME B18.3 is ASME."""
    words = (standard or "").replace("-", " ").split()
    if not words:
        return "Other"
    if "EN" in words[:2]:
        return "EN"
    first = words[0].upper()
    if first in ("ISO", "DIN", "ASME", "ASTM", "BS", "IS", "GOST", "SAE",
                 "JIS", "GB", "AISC", "ANSI"):
        return first
    return "Other"
