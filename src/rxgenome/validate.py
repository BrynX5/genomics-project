"""
Validate tables against their contracts, and run the project's day gates.

    python -m rxgenome.validate                 # every table that exists + cross-table checks
    python -m rxgenome.validate negotiated_drugs
    python -m rxgenome.validate --path data/interim/drug_target.csv
    python -m rxgenome.validate --gate 1        # Day 1 gate
    python -m rxgenome.validate --gate 2        # Day 2 gate
    python -m rxgenome.validate --describe      # print every contract (Claude: read this first)

Exit code 0 = clean, 1 = problems found (printed one per line).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import pandas as pd

from rxgenome.contracts import CROSS_CHECKS, TABLES, Table

ROOT = Path(os.environ.get("RXGENOME_ROOT", Path(__file__).resolve().parents[2]))

TRUE = {"true", "1", "yes", "y", "t"}
FALSE = {"false", "0", "no", "n", "f"}


# ----------------------------------------------------------------------------- loading
def read_table(t: Table, path: Path | None = None) -> pd.DataFrame:
    """Read a contract table as strings, then coerce each column to its declared type."""
    p = path or ROOT / t.path
    return pd.read_csv(p, dtype=str, keep_default_na=False, na_values=[""])


def load(name: str) -> pd.DataFrame | None:
    t = TABLES[name]
    p = ROOT / t.path
    if not p.exists():
        return None
    df, _ = coerce(t, read_table(t, p))
    return df


def coerce(t: Table, raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    errors: list[str] = []
    df = raw.copy()
    for c in t.columns:
        if c.name not in df.columns:
            continue
        s = df[c.name]
        if c.dtype in ("int", "float"):
            num = pd.to_numeric(s, errors="coerce")
            bad = s.notna() & num.isna()
            if bad.any():
                errors.append(f"{c.name}: not a number in rows {_rows(bad)} (e.g. {s[bad].iloc[0]!r})")
            if c.dtype == "int":
                frac = num.notna() & (num % 1 != 0)
                if frac.any():
                    errors.append(f"{c.name}: not a whole number in rows {_rows(frac)}")
                df[c.name] = num.astype("Int64")
            else:
                df[c.name] = num.astype("Float64")
        elif c.dtype == "bool":
            low = s.str.strip().str.lower()
            bad = s.notna() & ~low.isin(TRUE | FALSE)
            if bad.any():
                errors.append(f"{c.name}: not true/false in rows {_rows(bad)}")
            df[c.name] = low.map(lambda v: True if v in TRUE else (False if v in FALSE else pd.NA)).astype("boolean")
        else:
            df[c.name] = s.astype("string").str.strip()
    return df, errors


def _rows(mask: pd.Series, limit: int = 8) -> str:
    # report 1-based data row numbers (row 1 = first line under the header)
    idx = [str(i + 1) for i in mask[mask].index[:limit]]
    more = mask.sum() - len(idx)
    return ", ".join(idx) + (f" (+{more} more)" if more > 0 else "")


# ----------------------------------------------------------------------------- validation
def validate_table(t: Table, path: Path | None = None) -> list[str]:
    p = path or ROOT / t.path
    if not p.exists():
        return [f"{t.name}: missing file {p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}"]
    try:
        raw = read_table(t, p)
    except Exception as exc:  # unreadable CSV
        return [f"{t.name}: cannot read CSV ({exc})"]

    errs: list[str] = []
    expected, actual = t.column_names, list(raw.columns)
    missing = [c for c in expected if c not in actual]
    extra = [c for c in actual if c not in expected]
    if missing:
        errs.append(f"missing columns {missing}")
    if extra:
        errs.append(f"unexpected columns {extra} (add them to the contract first, with a decision log entry)")
    if actual[: len(expected)] != expected and not missing and not extra:
        errs.append(f"column order should be {expected}")

    df, type_errs = coerce(t, raw)
    errs += type_errs

    for c in t.columns:
        if c.name not in df.columns:
            continue
        s = df[c.name]
        if c.required and s.isna().any():
            errs.append(f"{c.name}: empty in rows {_rows(s.isna())}")
        present = s.notna()
        if c.allowed is not None:
            bad = present & ~s.isin(list(c.allowed))
            if bad.any():
                errs.append(f"{c.name}: {sorted(set(s[bad].astype(str)))[:5]} not in {sorted(map(str, c.allowed))}")
        if c.pattern is not None:
            rx = re.compile(c.pattern)
            ok = s.astype(object).where(present, "").map(lambda v: bool(rx.match(str(v)))).astype(bool)
            bad = present & ~ok
            if bad.any():
                errs.append(f"{c.name}: bad format in rows {_rows(bad)} (e.g. {s[bad].iloc[0]!r}, want /{c.pattern}/)")
        if c.min is not None:
            bad = present & (s < c.min)
            if bad.any():
                errs.append(f"{c.name}: below {c.min} in rows {_rows(bad)}")
        if c.max is not None:
            bad = present & (s > c.max)
            if bad.any():
                errs.append(f"{c.name}: above {c.max} in rows {_rows(bad)}")

    if t.key and all(k in df.columns for k in t.key):
        dup = df.duplicated(list(t.key), keep=False)
        if dup.any():
            errs.append(f"duplicate key {list(t.key)} in rows {_rows(dup)}")

    if not errs:  # table checks assume a type-clean frame
        for chk in t.checks:
            try:
                res = chk.fn(df)
            except Exception as exc:
                errs.append(f"check '{chk.description}' crashed: {exc}")
                continue
            if isinstance(res, pd.Series):
                bad = ~res.fillna(False).astype(bool)
                if bad.any():
                    errs.append(f"check failed: {chk.description} (rows {_rows(bad)})")
            elif not res:
                errs.append(f"check failed: {chk.description}")

    return [f"{t.name}: {e}" for e in errs]


def validate_all(only_existing: bool = True) -> list[str]:
    errs: list[str] = []
    for t in TABLES.values():
        if only_existing and not (ROOT / t.path).exists():
            continue
        errs += validate_table(t)
    if not errs:
        for desc, fn in CROSS_CHECKS:
            errs += [f"cross-check '{desc}': {e}" for e in fn(load)]
    return errs


def table_for_path(path: str | Path) -> Table | None:
    p = Path(path).resolve()
    for t in TABLES.values():
        if (ROOT / t.path).resolve() == p:
            return t
    return None


# ----------------------------------------------------------------------------- gates
def gate(n: int) -> list[str]:
    errs = validate_all()
    if n == 1:
        for name in ("negotiated_drugs", "partd_drug_year", "drug_target", "target_classes"):
            if not (ROOT / TABLES[name].path).exists():
                errs.append(f"gate 1: {TABLES[name].path} does not exist yet")
        nd, dt, py = load("negotiated_drugs"), load("drug_target"), load("partd_drug_year")
        if nd is not None and dt is not None:
            pd_ids = set(nd.loc[nd["part"].isin(["D", "B/D"]) & nd["cycle"].isin([2026, 2027]), "drug_id"])
            human = dt[dt["organism"].fillna("").str.contains("Homo sapiens") & dt["uniprot"].notna()]
            mapped = pd_ids & set(human["drug_id"])
            if len(mapped) < 23:
                errs.append(f"gate 1: only {len(mapped)}/{len(pd_ids)} Part D negotiated drugs have a human target "
                            f"(need 23). Missing: {sorted(pd_ids - mapped)}")
            classes = load("target_classes")
            have = set(classes["uniprot"]) if classes is not None else set()
            need = set(human["uniprot"]) - have
            if need:
                errs.append(f"gate 1: {len(need)} UniProt targets have no row in target_classes: {sorted(need)[:10]}")
        if nd is not None and py is not None:
            from rxgenome.pipeline import match_spend  # local import: pipeline imports requests
            m = match_spend(nd, py)
            latest = int(py["year"].max())
            hit = set(m.loc[m["year"] == latest, "drug_id"])
            miss = sorted(set(nd.loc[nd["part"].isin(["D", "B/D"]), "drug_id"]) - hit)
            if miss:
                errs.append(f"gate 1: no {latest} CMS spend rows matched for {miss}; fix cms_*_regex in negotiated_drugs")
    elif n == 2:
        for name in ("target_spend", "price_cuts"):
            if not (ROOT / TABLES[name].path).exists():
                errs.append(f"gate 2: {TABLES[name].path} does not exist yet")
        for fig in ("q1_spend_by_target.png", "q1_spend_by_class.png", "q2_price_cut_by_class.png"):
            if not (ROOT / "figures" / fig).exists():
                errs.append(f"gate 2: figures/{fig} missing")
        pc = load("price_cuts")
        if pc is not None and not pc["verified"].fillna(False).all():
            errs.append(f"gate 2: unverified prices in price_cuts: {sorted(pc.loc[~pc['verified'].fillna(False), 'drug_id'])}")
        readme = ROOT / "README.md"
        text = readme.read_text() if readme.exists() else ""
        if "## Findings" not in text:
            errs.append("gate 2: README.md has no '## Findings' section")
        if re.search(r"\b(TODO|TBD|\$X|X%|N targets)\b", text):
            errs.append("gate 2: README.md still has placeholders (TODO, TBD, $X, X%, N targets)")
        for word in ("gross", "list price"):
            if word not in text.lower():
                errs.append(f"gate 2: README.md never says '{word}' - every spend/price figure must be labelled")
    else:
        errs.append(f"unknown gate {n}")
    return errs


# ----------------------------------------------------------------------------- describe
def describe() -> str:
    out = []
    for t in TABLES.values():
        out.append(f"## {t.name}  ({t.layer}, written by skill: {t.owner})\n{t.path}\n{t.description}")
        if t.key:
            out.append(f"key: {', '.join(t.key)}")
        for c in t.columns:
            rules = [c.dtype, "required" if c.required else "nullable"]
            if c.allowed:
                rules.append("one of " + "|".join(sorted(map(str, c.allowed))))
            if c.pattern:
                rules.append(f"/{c.pattern}/")
            if c.min is not None:
                rules.append(f">= {c.min}")
            if c.max is not None:
                rules.append(f"<= {c.max}")
            out.append(f"  - {c.name} [{'; '.join(rules)}]: {c.description}")
        for chk in t.checks:
            out.append(f"  * check: {chk.description}")
        out.append("")
    out.append("## cross-table checks")
    out += [f"  * {d}" for d, _ in CROSS_CHECKS]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tables", nargs="*", help="table names (default: all that exist)")
    ap.add_argument("--path", help="validate the file at this path against its contract")
    ap.add_argument("--gate", type=int, choices=[1, 2])
    ap.add_argument("--describe", action="store_true")
    a = ap.parse_args(argv)

    if a.describe:
        print(describe())
        return 0
    if a.gate:
        errs = gate(a.gate)
        label = f"gate {a.gate}"
    elif a.path:
        t = table_for_path(a.path)
        if t is None:
            print(f"no contract covers {a.path}")
            return 0
        errs, label = validate_table(t, Path(a.path).resolve()), t.name
    elif a.tables:
        unknown = [n for n in a.tables if n not in TABLES]
        if unknown:
            print(f"unknown tables {unknown}; known: {sorted(TABLES)}")
            return 1
        errs = [e for n in a.tables for e in validate_table(TABLES[n])]
        label = ", ".join(a.tables)
    else:
        errs, label = validate_all(), "all tables"

    if errs:
        print(f"FAIL {label}: {len(errs)} problem(s)")
        print("\n".join(f"  - {e}" for e in errs))
        return 1
    print(f"PASS {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
