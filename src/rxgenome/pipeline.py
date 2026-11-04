"""
RxGenome pipeline: ingest CMS spending, then map negotiated drugs to protein targets.

    python -m rxgenome.pipeline ingest   # CMS Part D -> data/raw + data/interim/partd_drug_year.csv
    python -m rxgenome.pipeline map      # negotiated_drugs -> data/interim/drug_target.csv + unmapped.csv

Every stage reads its inputs through the contracts and validates what it writes.
All API responses are cached in data/.http_cache, so reruns are fast and offline-friendly.
Spend figures are GROSS (CMS excludes manufacturer rebates). Never call them net.
"""

from __future__ import annotations

import re
import sys
import time

import pandas as pd
import requests

from rxgenome.contracts import (DRUG_TARGET, PARTD_DRUG_YEAR, PARTD_MFTR_YEAR, PAYMENTS_DRUG_YEAR, PAYMENTS_YEAR_TOTAL,
                                UNMAPPED)
from rxgenome.validate import ROOT, load, validate_table

try:
    import requests_cache

    requests_cache.install_cache(str(ROOT / "data/.http_cache"), expire_after=60 * 60 * 24 * 30)
except ImportError:  # caching is a convenience, not a requirement
    pass

CMS_PARTD_DATASET = "7e0b4365-fd63-4a29-8f5e-e0ac9f66a81b"  # Medicare Part D Spending by Drug
CMS_API = f"https://data.cms.gov/data-api/v1/dataset/{CMS_PARTD_DATASET}/data"
RXNAV = "https://rxnav.nlm.nih.gov/REST"
CHEMBL = "https://www.ebi.ac.uk/chembl/api/data"

RAW_CMS = ROOT / "data/raw/partd_spending_by_drug.csv"

SESSION = requests.Session()
SESSION.headers["Accept"] = "application/json"


def get_json(url: str, params: dict | None = None, retries: int = 3):
    for attempt in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=60)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt + 1} for {url} ({exc})", file=sys.stderr)
            time.sleep(2 ** attempt)


def write_validated(df: pd.DataFrame, table) -> None:
    out = ROOT / table.path
    out.parent.mkdir(parents=True, exist_ok=True)
    df[table.column_names].to_csv(out, index=False)
    errs = validate_table(table)
    if errs:
        raise SystemExit(f"{table.name} broke its contract:\n  " + "\n  ".join(errs))
    print(f"[ok] {table.path}: {len(df):,} rows, contract passed")


# ----------------------------------------------------------------------------- ingest
def pull_cms(page_size: int = 5000) -> pd.DataFrame:
    if RAW_CMS.exists():
        print(f"[cms] using cached {RAW_CMS.relative_to(ROOT)} (delete it to re-download)")
        return pd.read_csv(RAW_CMS, dtype=str)
    rows, offset = [], 0
    while True:
        page = get_json(CMS_API, {"size": page_size, "offset": offset})
        if not page:
            break
        rows.extend(page)
        offset += page_size
        print(f"[cms] fetched {len(rows):,} rows")
    df = pd.DataFrame(rows)
    RAW_CMS.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(RAW_CMS, index=False)
    return df.astype(str)


def reshape_cms(raw: pd.DataFrame) -> pd.DataFrame:
    """Wide CMS file (Tot_Spndng_2024, Tot_Clms_2024, ...) -> one row per drug per year."""
    df = raw[raw["Mftr_Name"].str.strip().str.lower() == "overall"].copy()
    metric = {"Tot_Spndng": "gross_spend_usd", "Tot_Clms": "claims", "Tot_Benes": "beneficiaries"}
    pat = re.compile(r"^(Tot_Spndng|Tot_Clms|Tot_Benes)_(\d{4})$")
    cols = [c for c in df.columns if pat.match(c)]
    if not cols:
        raise SystemExit(f"no Tot_Spndng_/Tot_Clms_/Tot_Benes_ columns in CMS file; columns are {list(df.columns)[:15]}")
    long = df.melt(id_vars=["Brnd_Name", "Gnrc_Name"], value_vars=cols, var_name="col", value_name="value")
    parts = long["col"].str.extract(pat)
    long["metric"], long["year"] = parts[0].map(metric), parts[1].astype(int)
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    wide = long.pivot_table(index=["Brnd_Name", "Gnrc_Name", "year"], columns="metric",
                            values="value", aggfunc="sum", min_count=1).reset_index()
    wide = wide.rename(columns={"Brnd_Name": "brand_name", "Gnrc_Name": "generic_name"})
    for c in metric.values():
        if c not in wide.columns:
            wide[c] = pd.NA
    wide["brand_name"] = wide["brand_name"].str.strip()
    wide["generic_name"] = wide["generic_name"].str.strip()
    return wide.sort_values(["generic_name", "brand_name", "year"])


def reshape_cms_mftr(raw: pd.DataFrame) -> pd.DataFrame:
    """Manufacturer rows (not 'Overall') -> one row per drug per manufacturer per year, gross spend only."""
    df = raw[raw["Mftr_Name"].str.strip().str.lower() != "overall"].copy()
    cols = [c for c in df.columns if re.match(r"^Tot_Spndng_\d{4}$", c)]
    long = df.melt(id_vars=["Brnd_Name", "Gnrc_Name", "Mftr_Name"], value_vars=cols, var_name="col",
                   value_name="gross_spend_usd")
    long["year"] = long["col"].str[-4:].astype(int)
    long["gross_spend_usd"] = pd.to_numeric(long["gross_spend_usd"], errors="coerce")
    long = long.rename(columns={"Brnd_Name": "brand_name", "Gnrc_Name": "generic_name", "Mftr_Name": "mftr_name"})
    for c in ("brand_name", "generic_name", "mftr_name"):
        long[c] = long[c].str.strip()
    out = (long.groupby(["brand_name", "generic_name", "mftr_name", "year"], as_index=False)
           .agg(gross_spend_usd=("gross_spend_usd", lambda s: s.sum(min_count=1))))
    return out.sort_values(["generic_name", "brand_name", "mftr_name", "year"])


def ingest() -> None:
    raw = pull_cms()
    write_validated(reshape_cms(raw), PARTD_DRUG_YEAR)
    write_validated(reshape_cms_mftr(raw), PARTD_MFTR_YEAR)


def match_spend(negotiated: pd.DataFrame, partd: pd.DataFrame) -> pd.DataFrame:
    """CMS rows belonging to each negotiated drug, by its cms_generic_regex AND cms_brand_regex."""
    out = []
    for r in negotiated.itertuples():
        g = re.compile(r.cms_generic_regex, re.I)
        b = re.compile(r.cms_brand_regex, re.I)
        hit = partd[partd["generic_name"].map(lambda v: bool(g.search(str(v))))
                    & partd["brand_name"].map(lambda v: bool(b.search(str(v))))]
        if not hit.empty:
            out.append(hit.assign(drug_id=r.drug_id))
    cols = ["drug_id", "brand_name", "generic_name", "year", "gross_spend_usd", "claims", "beneficiaries"]
    return pd.concat(out)[cols] if out else pd.DataFrame(columns=cols)


# ----------------------------------------------------------------------------- map
def rxcui_for(name: str) -> str | None:
    js = get_json(f"{RXNAV}/rxcui.json", {"name": name, "search": 2})
    ids = (js.get("idGroup") or {}).get("rxnormId") or []
    return ids[0] if ids else None


def chembl_parent_for(name: str) -> str | None:
    js = get_json(f"{CHEMBL}/molecule/search.json", {"q": name, "limit": 10})
    mols = js.get("molecules", [])
    mols.sort(key=lambda m: ((m.get("pref_name") or "").lower() != name.lower(), -float(m.get("max_phase") or 0)))
    if not mols:
        return None
    m = mols[0]
    return (m.get("molecule_hierarchy") or {}).get("parent_chembl_id") or m["molecule_chembl_id"]


def mechanisms_for(parent_id: str) -> list[dict]:
    return get_json(f"{CHEMBL}/mechanism.json", {"parent_molecule_chembl_id": parent_id, "limit": 50}).get("mechanisms", [])


def target_rows(target_id: str) -> list[dict]:
    t = get_json(f"{CHEMBL}/target/{target_id}.json")
    base = {"target_chembl_id": target_id, "target_name": t.get("pref_name"),
            "target_type": t.get("target_type"), "organism": t.get("organism")}
    accs = [c.get("accession") for c in (t.get("target_components") or []) if c.get("accession")]
    return [{**base, "uniprot": a} for a in accs] or [{**base, "uniprot": None}]


def map_targets() -> None:
    nd = load("negotiated_drugs")
    if nd is None:
        raise SystemExit("data/reference/negotiated_drugs.csv is missing; run the curate-reference skill first")
    manual = load("manual_mappings")
    manual_keys = set() if manual is None else set(zip(manual["drug_id"], manual["ingredient"]))

    rows, failures = [], []
    for d in nd.itertuples():
        for ingredient in [g.strip() for g in d.generic.split("/")]:
            if (d.drug_id, ingredient) in manual_keys:
                continue  # manual mapping wins; added below
            print(f"[map] {d.drug_id:<18} {ingredient}")
            parent = chembl_parent_for(ingredient)
            if not parent:
                failures.append((d.drug_id, ingredient, "no ChEMBL molecule match"))
                continue
            mechs = [m for m in mechanisms_for(parent) if m.get("target_chembl_id")]
            if not mechs:
                failures.append((d.drug_id, ingredient, f"no ChEMBL mechanism for {parent}"))
                continue
            rxcui = rxcui_for(ingredient)
            for m in mechs:
                for t in target_rows(m["target_chembl_id"]):
                    rows.append({"drug_id": d.drug_id, "ingredient": ingredient, "rxcui": rxcui,
                                 "chembl_parent": parent, "mechanism_of_action": m.get("mechanism_of_action"),
                                 "action_type": m.get("action_type"), **t, "mapping_source": "auto"})

    if manual is not None:
        for m in manual.itertuples():
            rows.append({"drug_id": m.drug_id, "ingredient": m.ingredient, "rxcui": None,
                         "chembl_parent": m.chembl_parent, "mechanism_of_action": None, "action_type": None,
                         "target_chembl_id": m.target_chembl_id, "target_name": m.target_name,
                         "target_type": None, "organism": "Homo sapiens", "uniprot": m.uniprot,
                         "mapping_source": "manual"})

    dt = pd.DataFrame(rows, columns=[c for c in DRUG_TARGET.column_names if c != "target_order"])
    dt = dt.drop_duplicates(["drug_id", "ingredient", "target_chembl_id", "uniprot"])
    # primary target first: ingredient order in the generic name, then ChEMBL's mechanism order
    ing_order = {(d.drug_id, g.strip()): i for d in nd.itertuples() for i, g in enumerate(d.generic.split("/"))}
    dt["_ing"] = [ing_order.get(k, 99) for k in zip(dt["drug_id"], dt["ingredient"])]
    dt["_seq"] = range(len(dt))
    dt = dt.sort_values(["drug_id", "_ing", "_seq"])
    dt["target_order"] = dt.groupby("drug_id").cumcount() + 1
    write_validated(dt.drop(columns=["_ing", "_seq"]), DRUG_TARGET)

    still = [f for f in failures if (f[0], f[1]) not in manual_keys]
    # mapped, but only to non-human targets (e.g. rifaximin -> bacterial RNA polymerase)
    human = dt["organism"].fillna("").str.contains("Homo sapiens") & dt["uniprot"].notna()
    for (drug_id, ingredient), g in dt.groupby(["drug_id", "ingredient"]):
        if not human[g.index].any():
            orgs = ", ".join(sorted(g["organism"].fillna("unknown").unique()))
            still.append((drug_id, ingredient, f"no human target; ChEMBL targets are {orgs}"))
    write_validated(pd.DataFrame(still, columns=UNMAPPED.column_names), UNMAPPED)
    n = dt.loc[human, "drug_id"].nunique()
    print(f"[map] {n}/{len(nd)} drugs have a human target; {len(still)} ingredients unmapped")


# ----------------------------------------------------------------------------- open payments (Q3c)
OPEN_PAYMENTS = "https://openpaymentsdata.cms.gov/api/1"
RAW_OP = ROOT / "data/raw/open_payments_by_product.csv"
RAW_OP_TOTAL = ROOT / "data/raw/open_payments_by_category.csv"
OP_NAME = "name_of_drug_or_biological_or_device_or_medical_supply_{}"
OP_KIND = "indicate_drug_or_biological_or_device_or_medical_supply_1"
OP_AMOUNT = "total_amount_of_payment_usdollars"


def product_name_variants(nd: pd.DataFrame) -> dict[str, str]:
    """Spellings to look up in Open Payments (matching there is case-sensitive) -> drug_id."""
    out = {}
    for d in nd.itertuples():
        for b in [x.strip() for x in d.brand.split(";")]:
            for v in (b, b.upper(), b.title(), b.lower()):
                out[v] = d.drug_id
    return out


def _op_query(dataset_id: str, query: dict, retries: int = 3) -> list[dict]:
    url = f"{OPEN_PAYMENTS}/datastore/query/{dataset_id}/0"
    for attempt in range(retries):
        try:
            r = requests.post(url, json={**query, "count": False, "results": True}, timeout=600)
            r.raise_for_status()
            return r.json().get("results", [])
        except requests.RequestException as e:
            print(f"  retry {attempt + 1} for {url} ({e})")
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"Open Payments API unreachable: {url}")


def _op_general_datasets() -> dict[int, str]:
    items = get_json(f"{OPEN_PAYMENTS}/metastore/schemas/dataset/items")
    out = {}
    for d in items:
        m = re.match(r"^(\d{4}) General Payment Data$", d.get("title", ""))
        if m:
            out[int(m.group(1))] = d["identifier"]
    return dict(sorted(out.items()))


def pull_open_payments(nd: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Server-side totals of general payments by product name (5 product slots) and by product kind, per year."""
    if RAW_OP.exists() and RAW_OP_TOTAL.exists():
        print(f"[op] using cached {RAW_OP.relative_to(ROOT)} (delete it to re-download)")
        return pd.read_csv(RAW_OP), pd.read_csv(RAW_OP_TOTAL)
    names = sorted(product_name_variants(nd))
    by_product, by_kind = [], []
    for year, ds in _op_general_datasets().items():
        for slot in range(1, 6):
            f = OP_NAME.format(slot)
            res = _op_query(ds, {"conditions": [{"property": f, "value": names, "operator": "in"}],
                                 "properties": [f, {"expression": {"operator": "sum", "operands": [OP_AMOUNT]}, "alias": "total_usd"},
                                                {"expression": {"operator": "count", "operands": [f]}, "alias": "n_records"}],
                                 "groupings": [f], "limit": 500})
            by_product += [{"program_year": year, "slot": slot, "product_name": r[f], "total_usd": r["total_usd"],
                            "n_records": r["n_records"]} for r in res]
            print(f"[op] {year} slot {slot}: {len(res)} names", flush=True)
        res = _op_query(ds, {"properties": [OP_KIND, {"expression": {"operator": "sum", "operands": [OP_AMOUNT]}, "alias": "total_usd"},
                                            {"expression": {"operator": "count", "operands": [OP_AMOUNT]}, "alias": "n_records"}],
                             "groupings": [OP_KIND], "limit": 50})
        by_kind += [{"program_year": year, "product_kind": r[OP_KIND], "total_usd": r["total_usd"], "n_records": r["n_records"]}
                    for r in res]
        print(f"[op] {year} totals by kind: {len(res)} kinds", flush=True)
    a, b = pd.DataFrame(by_product), pd.DataFrame(by_kind)
    RAW_OP.parent.mkdir(parents=True, exist_ok=True)
    a.to_csv(RAW_OP, index=False)
    b.to_csv(RAW_OP_TOTAL, index=False)
    return a, b


def reshape_payments(by_product: pd.DataFrame, by_kind: pd.DataFrame, nd: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    v = product_name_variants(nd)
    p = by_product.assign(drug_id=by_product["product_name"].map(v)).dropna(subset=["drug_id"])
    p[["total_usd", "n_records"]] = p[["total_usd", "n_records"]].apply(pd.to_numeric)
    drug = (p.groupby(["drug_id", "program_year"], as_index=False)
             .agg(general_payments_usd=("total_usd", "sum"), n_records=("n_records", "sum"),
                  product_names=("product_name", lambda s: ";".join(sorted(set(s))))))
    k = by_kind.assign(total_usd=pd.to_numeric(by_kind["total_usd"]), n_records=pd.to_numeric(by_kind["n_records"]))
    k = k[k["product_kind"].fillna("").str.strip().str.lower().isin(["drug", "biological"])]
    total = k.groupby("program_year", as_index=False).agg(drug_bio_payments_usd=("total_usd", "sum"), n_records=("n_records", "sum"))
    return drug, total


def payments() -> None:
    nd = load("negotiated_drugs")
    drug, total = reshape_payments(*pull_open_payments(nd), nd)
    write_validated(drug, PAYMENTS_DRUG_YEAR)
    write_validated(total, PAYMENTS_YEAR_TOTAL)


if __name__ == "__main__":
    stages = {"ingest": ingest, "map": map_targets, "payments": payments}
    if len(sys.argv) != 2 or sys.argv[1] not in stages:
        raise SystemExit(f"usage: python -m rxgenome.pipeline [{'|'.join(stages)}]")
    stages[sys.argv[1]]()
