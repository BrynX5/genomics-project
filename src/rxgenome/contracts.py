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
RE_DATE = r"^\d{4}-\d{2}-\d{2}$"
MONOPOLY_TIERS = {"short", "extended", "long"}  # 42 U.S.C. 1320f-3(c): <12, 12-16, >=16 years since approval


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
FIRM_LABELERS = Table(
    name="firm_labelers",
    path="data/reference/firm_labelers.csv",
    layer="reference",
    owner="curate-reference",
    description="Maps CMS manufacturer (labeler) names to parent firms for the firms behind the negotiated drugs. Names not listed are not counted for any firm.",
    key=("cms_mftr_name",),
    columns=(
        Col("cms_mftr_name", "str", "CMS Mftr_Name exactly as in the raw file, stripped (CMS truncates at 15 characters)."),
        Col("parent_firm", "str", "Parent company that owned the labeler in the spend year."),
        Col("basis", "str", "cms_name = the CMS name itself names the parent; acquisition = an ownership source says so.",
            allowed=frozenset({"cms_name", "acquisition"})),
        Col("source_url", "str", "Page that supports the link (CMS dataset, CMS fact sheet, or the acquisition release).", pattern=RE_URL),
        Col("notes", "str", "Why this name belongs to the parent.", required=False),
    ),
)

PARTD_MFTR_YEAR = Table(
    name="partd_mftr_year",
    path="data/interim/partd_mftr_year.csv",
    layer="interim",
    owner="ingest-cms",
    description="CMS Part D Spending by Drug, manufacturer rows (not 'Overall'), one row per drug per manufacturer per year. Gross cost.",
    key=("brand_name", "generic_name", "mftr_name", "year"),
    columns=(
        Col("brand_name", "str", "CMS Brnd_Name."),
        Col("generic_name", "str", "CMS Gnrc_Name (may be truncated by CMS)."),
        Col("mftr_name", "str", "CMS Mftr_Name, stripped."),
        Col("year", "int", "Calendar year of the claims.", min=2012, max=2030),
        Col("gross_spend_usd", "float", "Tot_Spndng: gross drug cost, before rebates.", required=False, min=0),
    ),
)

FDA_APPROVALS = Table(
    name="fda_approvals",
    path="data/reference/fda_approvals.csv",
    layer="reference",
    owner="curate-reference",
    description="FDA original approval (or licensure) date per negotiated drug: the earliest among the brands CMS groups under it.",
    key=("drug_id",),
    columns=(
        Col("drug_id", "str", "From negotiated_drugs.", pattern=RE_SLUG),
        Col("application_number", "str", "NDA or BLA number of the earliest approved application.", pattern=r"^(NDA|BLA)\d{6}$"),
        Col("approval_date", "str", "Date of the original approval (ORIG, AP) submission, YYYY-MM-DD.", pattern=RE_DATE),
        Col("source_url", "str", "openFDA drugsfda query for that application.", pattern=RE_URL),
        Col("notes", "str", "Which later applications were passed over.", required=False),
    ),
)

CYCLE_DATES = Table(
    name="cycle_dates",
    path="data/reference/cycle_dates.csv",
    layer="reference",
    owner="curate-reference",
    description="Selected drug publication date for each negotiation cycle, from the CMS selected-drug fact sheets.",
    key=("cycle",),
    columns=(
        Col("cycle", "int", "Initial price applicability year.", allowed=frozenset(CYCLES)),
        Col("selected_drug_publication_date", "str", "Date CMS published the selected drug list, YYYY-MM-DD.", pattern=RE_DATE),
        Col("source_url", "str", "CMS fact sheet that states the date.", pattern=RE_URL),
    ),
)

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

PAYMENTS_DRUG_YEAR = Table(
    name="payments_drug_year",
    path="data/interim/payments_drug_year.csv",
    layer="interim",
    owner="ingest-cms",
    description="Q3c: Open Payments general payments (not research) naming a negotiated drug in any of the 5 product slots, per program year.",
    key=("drug_id", "program_year"),
    columns=(
        Col("drug_id", "str", "From negotiated_drugs.", pattern=RE_SLUG),
        Col("program_year", "int", "Open Payments program year.", min=2013, max=2030),
        Col("general_payments_usd", "float", "Sum of total_amount_of_payment_usdollars. A record naming several products counts in full for each.", min=0),
        Col("n_records", "int", "Payment records (one record may bundle several payments).", min=0),
        Col("product_names", "str", "Product name spellings matched, ';'-separated."),
    ),
)

PAYMENTS_YEAR_TOTAL = Table(
    name="payments_year_total",
    path="data/interim/payments_year_total.csv",
    layer="interim",
    owner="ingest-cms",
    description="Q3c baseline: all Open Payments general payments whose first product is a drug or biological, per program year.",
    key=("program_year",),
    columns=(
        Col("program_year", "int", "Open Payments program year.", min=2013, max=2030),
        Col("drug_bio_payments_usd", "float", "Sum of payments with product slot 1 = Drug or Biological.", min=0),
        Col("n_records", "int", "Payment records.", min=0),
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

FIRM_EXPOSURE = Table(
    name="firm_exposure",
    path="data/processed/firm_exposure.csv",
    layer="processed",
    owner="analyze-question",
    description="Q3a: each parent firm's gross Part D spend and the share of it in negotiated drugs. Gross, before rebates.",
    key=("parent_firm",),
    columns=(
        Col("parent_firm", "str", "From firm_labelers."),
        Col("spend_year", "int", "Year of the spending data.", min=2012, max=2030),
        Col("total_gross_usd", "float", "Gross Part D spend on all drugs from the firm's mapped labelers.", min=0),
        Col("negotiated_gross_usd", "float", "Of which, gross spend on the negotiated drugs.", min=0),
        Col("share_negotiated", "float", "negotiated_gross_usd / total_gross_usd.", min=0, max=1),
        Col("n_negotiated_drugs", "int", "Negotiated drugs with spend under this firm.", min=0),
        Col("negotiated_drugs", "str", "drug_ids, ';'-separated.", required=False),
        Col("n_labelers", "int", "Mapped labeler names with spend in the year.", min=0),
    ),
    checks=(
        Check("negotiated spend is within total", lambda d: d["negotiated_gross_usd"] <= d["total_gross_usd"] + 1e-6),
        Check("share matches the spend", lambda d: (d["share_negotiated"] - d["negotiated_gross_usd"] / d["total_gross_usd"]).abs() < 1e-9),
    ),
)

CUT_DRIVERS = Table(
    name="cut_drivers",
    path="data/processed/cut_drivers.csv",
    layer="processed",
    owner="analyze-question",
    description="Q3b: per drug, the list-to-negotiated cut next to candidate explanations. List prices, not net.",
    key=("drug_id",),
    columns=(
        Col("drug_id", "str", "From negotiated_drugs.", pattern=RE_SLUG),
        Col("brand", "str", "Brand name(s)."),
        Col("cycle", "int", "Negotiation cycle.", allowed=frozenset(CYCLES)),
        Col("pct_cut", "float", "1 - negotiated / list price (from price_cuts).", min=0, max=1),
        Col("list_price_30d_usd", "float", "List price (WAC), 30-day supply.", min=0),
        Col("years_since_approval", "float", "Years from FDA approval to the cycle's selected drug publication date.", min=0),
        Col("monopoly_tier", "str", "short (<12 y), extended (12-16 y) or long (>=16 y), the statute's ceiling tiers.", allowed=frozenset(MONOPOLY_TIERS)),
        Col("ceiling_pct_of_nonfamp", "float", "Statutory price ceiling for the tier, as a share of non-FAMP (not of list price): 0.75, 0.65 or 0.40.", min=0, max=1),
        Col("target_class", "str", "Class of the primary target (from price_cuts).", required=False, allowed=frozenset(TARGET_CLASSES)),
        Col("parent_firm", "str", "Parent firm of the drug's CMS labeler (from firm_exposure).", required=False),
        Col("firm_share_negotiated", "float", "That firm's share of 2024 gross Part D spend in negotiated drugs.", required=False, min=0, max=1),
    ),
)

CUT_DRIVER_STATS = Table(
    name="cut_driver_stats",
    path="data/processed/cut_driver_stats.csv",
    layer="processed",
    owner="analyze-question",
    description="Q3b summary: rank correlations of the cut with each driver, and the median cut by monopoly tier.",
    key=("statistic", "variable"),
    columns=(
        Col("statistic", "str", "spearman_rho (cut vs variable) or median_cut (cut within a tier).", allowed=frozenset({"spearman_rho", "median_cut"})),
        Col("variable", "str", "Driver name, or the tier for median_cut."),
        Col("value", "float", "The statistic.", min=-1, max=1),
        Col("n", "int", "Drugs used.", min=1),
        Col("p_value", "float", "Two-sided permutation p-value (10,000 shuffles, seed 0); empty for medians.", required=False, min=0, max=1),
    ),
)

PAYMENTS_CHANGE = Table(
    name="payments_change",
    path="data/processed/payments_change.csv",
    layer="processed",
    owner="analyze-question",
    description="Q3c: Open Payments general payments naming each negotiated drug, the year before vs the year after selection, against the market.",
    key=("drug_id",),
    columns=(
        Col("drug_id", "str", "From negotiated_drugs.", pattern=RE_SLUG),
        Col("cycle", "int", "Negotiation cycle.", allowed=frozenset(CYCLES)),
        Col("pre_year", "int", "Last full program year before the selected drug publication date.", min=2013, max=2030),
        Col("post_year", "int", "First program year mostly after it (publication before 1 July -> that year, else the next).", min=2013, max=2031),
        Col("pre_usd", "float", "General payments naming the drug in pre_year.", required=False, min=0),
        Col("post_usd", "float", "General payments naming the drug in post_year (empty if not yet published).", required=False, min=0),
        Col("drug_ratio", "float", "post_usd / pre_usd.", required=False, min=0),
        Col("market_ratio", "float", "Same ratio for all drug/biological general payments.", required=False, min=0),
        Col("relative_change", "float", "drug_ratio / market_ratio - 1: change beyond the market trend.", required=False, min=-1),
    ),
)

PAYMENTS_SUMMARY = Table(
    name="payments_summary",
    path="data/processed/payments_summary.csv",
    layer="processed",
    owner="analyze-question",
    description="Q3c by cycle: median change in payments naming the selected drugs, against the market change.",
    key=("cycle",),
    columns=(
        Col("cycle", "int", "Negotiation cycle.", allowed=frozenset(CYCLES)),
        Col("pre_year", "int", "Before year.", min=2013, max=2030),
        Col("post_year", "int", "After year.", min=2013, max=2031),
        Col("n_drugs", "int", "Drugs with payments in both years.", min=0),
        Col("median_drug_ratio", "float", "Median post/pre ratio across those drugs.", required=False, min=0),
        Col("market_ratio", "float", "post/pre ratio for all drug/biological general payments.", required=False, min=0),
        Col("median_relative_change", "float", "Median of drug_ratio / market_ratio - 1.", required=False, min=-1),
        Col("n_fell_vs_market", "int", "Drugs whose payments changed less than the market (relative_change < 0).", min=0),
        Col("n_promoted", "int", "Drugs with at least $1M of general payments in pre_year (actively promoted).", min=0),
        Col("median_relative_change_promoted", "float", "Median relative_change among the promoted drugs.", required=False, min=-1),
        Col("aggregate_drug_ratio", "float", "Sum of post_usd / sum of pre_usd over the cycle's drugs (dominated by big spenders).", required=False, min=0),
        Col("aggregate_relative_change", "float", "aggregate_drug_ratio / market_ratio - 1.", required=False, min=-1),
    ),
)

TABLES: dict[str, Table] = {
    t.name: t
    for t in (
        NEGOTIATED_DRUGS, MANUAL_MAPPINGS, TARGET_CLASSES_REF, FIRM_LABELERS, FDA_APPROVALS, CYCLE_DATES,
        PARTD_DRUG_YEAR, PARTD_MFTR_YEAR, PAYMENTS_DRUG_YEAR, PAYMENTS_YEAR_TOTAL, DRUG_TARGET, UNMAPPED,
        TARGET_SPEND, PRICE_CUTS, CLASS_SUMMARY, FIRM_EXPOSURE, CUT_DRIVERS, CUT_DRIVER_STATS, PAYMENTS_CHANGE,
        PAYMENTS_SUMMARY,
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
    ("payments_drug_year.drug_id exists", _fk("payments_drug_year", "drug_id", "negotiated_drugs", "drug_id")),
    ("fda_approvals.drug_id exists", _fk("fda_approvals", "drug_id", "negotiated_drugs", "drug_id")),
    ("every target in target_spend has a class", _fk("target_spend", "uniprot", "target_classes", "uniprot")),
]
