"""
Data contracts for every table in RxGenome.

This file is the single source of truth for what each table must look like.
Code, Claude Code skills, the validation hook and the tests all read from here.

Rules
-----
* A table that breaks its contract is a bug in whatever wrote it, not in the contract.
* Change a contract only on purpose: edit this file AND add an entry to docs/decisions.md.
* Every column has a description; Claude reads them, so write them for a stranger.

Pure pandas, no extra dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

# ----------------------------------------------------------------------------- vocabularies
CYCLES = {2026, 2027, 2028}  # initial price applicability year of each negotiation cycle
PARTS = {"D", "B", "B/D"}
TARGET_CLASSES = {
    "Kinase",
    "Protease",
    "Other enzyme",
    "GPCR",
    "Ion channel",
    "Transporter",
    "Nuclear receptor",
    "Cytokine or receptor",
    "Other",
}
SPLIT_RULES = {"equal", "first_target"}
MAPPING_SOURCES = {"auto", "manual"}

RE_SLUG = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
RE_CHEMBL = r"^CHEMBL\d+$"
RE_UNIPROT = r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})$"
RE_URL = r"^https://\S+$"
RE_DIGITS = r"^\d+$"


# ----------------------------------------------------------------------------- spec types
@dataclass(frozen=True)
class Col:
    name: str
    dtype: str  # "str" | "int" | "float" | "bool"
    description: str
    required: bool = True  # no nulls allowed
    allowed: frozenset | None = None
    pattern: str | None = None
    min: float | None = None
    max: float | None = None


@dataclass(frozen=True)
class Check:
    """A table-level rule. `fn(df)` returns a boolean Series (True = row passes) or a bool."""

    description: str
    fn: Callable[[pd.DataFrame], "pd.Series | bool"]


@dataclass(frozen=True)
class Table:
    name: str
    path: str  # relative to the project root
    layer: str  # reference | interim | processed
    owner: str  # the skill that writes it
    description: str
    columns: tuple[Col, ...]
    key: tuple[str, ...] = ()
    checks: tuple[Check, ...] = field(default_factory=tuple)

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


def _regex_compiles(s: pd.Series) -> pd.Series:
    def ok(v: str) -> bool:
        try:
            re.compile(v)
            return True
        except re.error:
            return False

    return s.map(ok)


# ----------------------------------------------------------------------------- reference (hand-curated)
NEGOTIATED_DRUGS = Table(
    name="negotiated_drugs",
    path="data/reference/negotiated_drugs.csv",
    layer="reference",
    owner="curate-reference",
    description="One row per drug selected for Medicare price negotiation, with prices and how to find it in CMS data.",
    key=("drug_id",),
    columns=(
        Col("drug_id", "str", "Stable slug for the selected drug, e.g. 'eliquis'.", pattern=RE_SLUG),
        Col("brand", "str", "Brand name(s) as CMS lists the selected drug, ';'-separated."),
        Col("generic", "str", "Active ingredient(s), lowercase, ' / '-separated for combinations."),
        Col("cycle", "int", "Initial price applicability year: 2026, 2027 or 2028.", allowed=frozenset(CYCLES)),
        Col("part", "str", "Medicare part that pays for it.", allowed=frozenset(PARTS)),
        Col("cms_generic_regex", "str", "Case-insensitive regex matched against CMS Gnrc_Name."),
        Col("cms_brand_regex", "str", "Case-insensitive regex matched against CMS Brnd_Name."),
        Col("list_price_30d_usd", "float", "List price (WAC) for a 30-day supply, USD, from the CMS fact sheet: CY2023 for cycle 2026, CY2024 for cycle 2027.", required=False, min=0),
        Col("negotiated_price_30d_usd", "float", "Negotiated (maximum fair) price for a 30-day supply, USD.", required=False, min=0),
        Col("price_source_url", "str", "Page the prices were copied from. Required when any price is filled.", required=False, pattern=RE_URL),
        Col("verified", "bool", "True only after the prices were checked against the official CMS fact sheet."),
        Col("notes", "str", "Free text: caveats, which formulations are included.", required=False),
    ),
    checks=(
        Check("regexes compile", lambda d: _regex_compiles(d["cms_generic_regex"]) & _regex_compiles(d["cms_brand_regex"])),
        Check(
            "a price needs a price_source_url",
            lambda d: d["price_source_url"].notna() | (d["list_price_30d_usd"].isna() & d["negotiated_price_30d_usd"].isna()),
        ),
        Check(
            "negotiated price is below list price",
            lambda d: d["list_price_30d_usd"].isna() | d["negotiated_price_30d_usd"].isna()
            | (d["negotiated_price_30d_usd"] < d["list_price_30d_usd"]),
        ),
        Check("verified rows have both prices", lambda d: ~d["verified"].fillna(False).astype(bool)
              | (d["list_price_30d_usd"].notna() & d["negotiated_price_30d_usd"].notna())),
    ),
)

MANUAL_MAPPINGS = Table(
    name="manual_mappings",
    path="data/reference/manual_mappings.csv",
    layer="reference",
    owner="map-drug-targets",
    description="Hand fixes for ingredients the automatic crosswalk could not map. Each row is one ingredient-target link.",
    key=("drug_id", "ingredient", "target_chembl_id", "uniprot"),
    columns=(
        Col("drug_id", "str", "Must exist in negotiated_drugs.", pattern=RE_SLUG),
        Col("ingredient", "str", "One ingredient, lowercase."),
        Col("chembl_parent", "str", "ChEMBL parent molecule ID.", pattern=RE_CHEMBL),
        Col("target_chembl_id", "str", "ChEMBL target ID.", pattern=RE_CHEMBL),
        Col("target_name", "str", "Target preferred name."),
        Col("uniprot", "str", "Human UniProt accession.", pattern=RE_UNIPROT),
        Col("reason", "str", "Why the automatic mapping failed or was overridden."),
        Col("source_url", "str", "ChEMBL or UniProt page that supports the link.", pattern=RE_URL),
    ),
)

TARGET_CLASSES_REF = Table(
    name="target_classes",
    path="data/reference/target_classes.csv",
    layer="reference",
    owner="map-drug-targets",
    description="Controlled target class for each UniProt accession used in the analysis.",
    key=("uniprot",),
    columns=(
        Col("uniprot", "str", "Human UniProt accession.", pattern=RE_UNIPROT),
        Col("gene_symbol", "str", "HGNC gene symbol, e.g. F10."),
        Col("target_class", "str", "One of the fixed classes in contracts.TARGET_CLASSES.", allowed=frozenset(TARGET_CLASSES)),
        Col("source_url", "str", "UniProt or ChEMBL page the class was read from.", pattern=RE_URL),
    ),
)

# ----------------------------------------------------------------------------- interim (generated)
PARTD_DRUG_YEAR = Table(
    name="partd_drug_year",
    path="data/interim/partd_drug_year.csv",
    layer="interim",
    owner="ingest-cms",
    description="CMS Part D Spending by Drug, 'Overall' manufacturer rows only, reshaped to one row per drug per year. Gross cost.",
    key=("brand_name", "generic_name", "year"),
    columns=(
        Col("brand_name", "str", "CMS Brnd_Name."),
        Col("generic_name", "str", "CMS Gnrc_Name (may be truncated by CMS)."),
        Col("year", "int", "Calendar year of the claims.", min=2012, max=2030),
        Col("gross_spend_usd", "float", "Tot_Spndng: gross drug cost, before rebates.", required=False, min=0),
        Col("claims", "float", "Tot_Clms.", required=False, min=0),
        Col("beneficiaries", "float", "Tot_Benes (CMS suppresses small counts, so nulls are expected).", required=False, min=0),
    ),
)

DRUG_TARGET = Table(
    name="drug_target",
    path="data/interim/drug_target.csv",
    layer="interim",
    owner="map-drug-targets",
    description="Crosswalk: each negotiated drug's ingredients linked to their protein targets.",
    key=("drug_id", "ingredient", "target_chembl_id", "uniprot"),
    columns=(
        Col("drug_id", "str", "From negotiated_drugs.", pattern=RE_SLUG),
        Col("ingredient", "str", "One ingredient, lowercase."),
        Col("rxcui", "str", "RxNorm concept ID for the ingredient.", required=False, pattern=RE_DIGITS),
        Col("chembl_parent", "str", "ChEMBL parent molecule ID.", pattern=RE_CHEMBL),
        Col("mechanism_of_action", "str", "ChEMBL mechanism text.", required=False),
        Col("action_type", "str", "ChEMBL action type, e.g. INHIBITOR.", required=False),
        Col("target_chembl_id", "str", "ChEMBL target ID.", pattern=RE_CHEMBL),
        Col("target_name", "str", "Target preferred name.", required=False),
        Col("target_type", "str", "ChEMBL target type, e.g. SINGLE PROTEIN.", required=False),
        Col("organism", "str", "Target organism.", required=False),
        Col("uniprot", "str", "UniProt accession; null when ChEMBL lists none.", required=False, pattern=RE_UNIPROT),
        Col("target_order", "int", "Order of this target within the drug, 1 = primary.", min=1),
        Col("mapping_source", "str", "auto (pipeline) or manual (manual_mappings.csv).", allowed=frozenset(MAPPING_SOURCES)),
    ),
)

UNMAPPED = Table(
    name="unmapped",
    path="data/interim/unmapped.csv",
    layer="interim",
    owner="map-drug-targets",
    description="Ingredients still without a target after manual mappings were applied.",
    columns=(
        Col("drug_id", "str", "From negotiated_drugs.", pattern=RE_SLUG),
        Col("ingredient", "str", "One ingredient, lowercase."),
        Col("reason", "str", "Why mapping failed."),
    ),
)

# ----------------------------------------------------------------------------- processed (analysis outputs)
TARGET_SPEND = Table(
    name="target_spend",
    path="data/processed/target_spend.csv",
    layer="processed",
    owner="analyze-question",
    description="Q1: gross Part D spend on negotiated drugs, attributed to human protein targets.",
    key=("split_rule", "uniprot"),
    columns=(
        Col("split_rule", "str", "equal = spend split evenly across a drug's targets; first_target = all to target 1.", allowed=frozenset(SPLIT_RULES)),
        Col("spend_year", "int", "Year of the spending data.", min=2012, max=2030),
        Col("uniprot", "str", "Human UniProt accession.", pattern=RE_UNIPROT),
        Col("gene_symbol", "str", "HGNC symbol.", required=False),
        Col("target_name", "str", "Target preferred name.", required=False),
        Col("target_class", "str", "From target_classes.", required=False, allowed=frozenset(TARGET_CLASSES)),
        Col("gross_spend_usd", "float", "Attributed gross spend, USD.", min=0),
        Col("share_of_total", "float", "Share of total attributed spend under this split_rule.", min=0, max=1),
        Col("n_drugs", "int", "Number of negotiated drugs hitting this target.", min=1),
        Col("drugs", "str", "drug_ids, ';'-separated."),
    ),
    checks=(
        Check("shares sum to 1 within each split_rule",
              lambda d: bool((d.groupby("split_rule")["share_of_total"].sum() - 1).abs().lt(1e-6).all())),
    ),
)

PRICE_CUTS = Table(
    name="price_cuts",
    path="data/processed/price_cuts.csv",
    layer="processed",
    owner="analyze-question",
    description="Q2: list-to-negotiated price cut per drug, labelled with its primary target class. List prices, not net.",
    key=("drug_id",),
    columns=(
        Col("drug_id", "str", "From negotiated_drugs.", pattern=RE_SLUG),
        Col("brand", "str", "Brand name(s)."),
        Col("cycle", "int", "Negotiation cycle.", allowed=frozenset(CYCLES)),
        Col("target_class", "str", "Class of the drug's primary target.", required=False, allowed=frozenset(TARGET_CLASSES)),
        Col("list_price_30d_usd", "float", "List price (WAC), 30-day supply: CY2023 for cycle 2026, CY2024 for cycle 2027.", min=0),
        Col("negotiated_price_30d_usd", "float", "Negotiated price, 30-day supply.", min=0),
        Col("pct_cut", "float", "1 - negotiated / list.", min=0, max=1),
        Col("verified", "bool", "Prices checked against the CMS fact sheet."),
    ),
    checks=(
        Check("pct_cut matches the prices",
              lambda d: (d["pct_cut"] - (1 - d["negotiated_price_30d_usd"] / d["list_price_30d_usd"])).abs() < 1e-6),
    ),
)

CLASS_SUMMARY = Table(
    name="class_summary",
    path="data/processed/class_summary.csv",
    layer="processed",
    owner="analyze-question",
    description="Q1 and Q2 rolled up to target class, so the README can quote class-level numbers. Gross spend, list prices.",
    key=("target_class",),
    columns=(
        Col("target_class", "str", "From target_classes.", allowed=frozenset(TARGET_CLASSES)),
        Col("spend_year", "int", "Year of the spending data.", min=2012, max=2030),
        Col("gross_spend_usd", "float", "Gross spend attributed to the class's targets, equal split, USD.", min=0),
        Col("share_of_total", "float", "Share of total attributed gross spend (equal split).", min=0, max=1),
        Col("n_targets", "int", "Human targets in this class that carry spend.", min=0),
        Col("n_drugs_priced", "int", "Drugs in price_cuts whose primary target is in this class.", min=0),
        Col("median_pct_cut", "float", "Median list-to-negotiated cut among those drugs.", required=False, min=0, max=1),
        Col("min_pct_cut", "float", "Smallest cut among those drugs.", required=False, min=0, max=1),
        Col("max_pct_cut", "float", "Largest cut among those drugs.", required=False, min=0, max=1),
    ),
    checks=(
        Check("shares sum to 1", lambda d: abs(d["share_of_total"].sum() - 1) < 1e-6),
        Check("cut stats present exactly when drugs are priced",
              lambda d: (d["n_drugs_priced"] > 0) == d["median_pct_cut"].notna()),
    ),
)

TABLES: dict[str, Table] = {
    t.name: t
    for t in (
        NEGOTIATED_DRUGS, MANUAL_MAPPINGS, TARGET_CLASSES_REF,
        PARTD_DRUG_YEAR, DRUG_TARGET, UNMAPPED,
        TARGET_SPEND, PRICE_CUTS, CLASS_SUMMARY,
    )
}

# Cross-table rules: (description, function(load) -> list[str] of problems)
CrossCheck = Callable[[Callable[[str], "pd.DataFrame | None"]], list[str]]


def _fk(child: str, col: str, parent: str, parent_col: str) -> CrossCheck:
    def run(load):
        c, p = load(child), load(parent)
        if c is None or p is None or c.empty:
            return []
        missing = sorted(set(c[col].dropna()) - set(p[parent_col].dropna()))
        return [f"{child}.{col} values not in {parent}.{parent_col}: {missing[:10]}"] if missing else []
    return run


CROSS_CHECKS: list[tuple[str, CrossCheck]] = [
    ("manual_mappings.drug_id exists", _fk("manual_mappings", "drug_id", "negotiated_drugs", "drug_id")),
    ("drug_target.drug_id exists", _fk("drug_target", "drug_id", "negotiated_drugs", "drug_id")),
    ("unmapped.drug_id exists", _fk("unmapped", "drug_id", "negotiated_drugs", "drug_id")),
    ("price_cuts.drug_id exists", _fk("price_cuts", "drug_id", "negotiated_drugs", "drug_id")),
    ("every target in target_spend has a class", _fk("target_spend", "uniprot", "target_classes", "uniprot")),
]
