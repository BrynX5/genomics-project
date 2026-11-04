"""
RxGenome analysis: answer Q1 and Q2 from validated tables, then draw the three figures.

    python -m rxgenome.analysis

Q1  Which protein targets absorb the most gross Part D spend among the negotiated drugs?
    -> data/processed/target_spend.csv, figures/q1_spend_by_target.png, figures/q1_spend_by_class.png
Q2  Did negotiation cut list prices harder for some target classes than others?
    -> data/processed/price_cuts.csv, figures/q2_price_cut_by_class.png

Labels are part of correctness: spend is GROSS, prices are LIST vs NEGOTIATED, never net.
"""

from __future__ import annotations

import re

import pandas as pd

from rxgenome.contracts import CLASS_SUMMARY, FIRM_EXPOSURE, PRICE_CUTS, TARGET_SPEND
from rxgenome.validate import ROOT, load

FIG = ROOT / "figures"


def _need(name: str) -> pd.DataFrame:
    df = load(name)
    if df is None:
        raise SystemExit(f"{name} is missing; run the earlier stage first (see CLAUDE.md, Workflow)")
    return df


def human_targets(dt: pd.DataFrame) -> pd.DataFrame:
    h = dt[dt["organism"].fillna("").str.contains("Homo sapiens") & dt["uniprot"].notna()]
    return h.sort_values(["drug_id", "target_order"]).drop_duplicates(["drug_id", "uniprot"])


def q1_target_spend() -> pd.DataFrame:
    from rxgenome.pipeline import match_spend

    nd, py, dt = _need("negotiated_drugs"), _need("partd_drug_year"), _need("drug_target")
    classes = load("target_classes")
    year = int(py["year"].max())
    spend = (match_spend(nd, py[py["year"] == year])
             .groupby("drug_id", as_index=False)["gross_spend_usd"].sum())
    h = human_targets(dt)

    out = []
    for rule in ("equal", "first_target"):
        t = h if rule == "equal" else h.groupby("drug_id").head(1)
        t = t.assign(weight=1 / t.groupby("drug_id")["uniprot"].transform("nunique"))
        t = t.merge(spend, on="drug_id", how="inner")
        t["attributed"] = t["gross_spend_usd"].astype(float) * t["weight"]
        g = (t.groupby("uniprot", as_index=False)
             .agg(gross_spend_usd=("attributed", "sum"), n_drugs=("drug_id", "nunique"),
                  drugs=("drug_id", lambda s: ";".join(sorted(set(s)))), target_name=("target_name", "first")))
        g["share_of_total"] = g["gross_spend_usd"] / g["gross_spend_usd"].sum()
        g["split_rule"], g["spend_year"] = rule, year
        out.append(g)
    res = pd.concat(out)
    if classes is not None:
        res = res.merge(classes[["uniprot", "gene_symbol", "target_class"]], on="uniprot", how="left")
    else:
        res["gene_symbol"], res["target_class"] = pd.NA, pd.NA
    res = res.sort_values(["split_rule", "gross_spend_usd"], ascending=[True, False])
    return res[TARGET_SPEND.column_names]


def q2_price_cuts() -> pd.DataFrame:
    nd, dt = _need("negotiated_drugs"), _need("drug_target")
    classes = load("target_classes")
    p = nd[nd["list_price_30d_usd"].notna() & nd["negotiated_price_30d_usd"].notna()].copy()
    primary = human_targets(dt).groupby("drug_id").head(1)[["drug_id", "uniprot"]]
    if classes is not None:
        primary = primary.merge(classes[["uniprot", "target_class"]], on="uniprot", how="left")
    else:
        primary["target_class"] = pd.NA
    p = p.merge(primary[["drug_id", "target_class"]], on="drug_id", how="left")
    p["pct_cut"] = 1 - p["negotiated_price_30d_usd"].astype(float) / p["list_price_30d_usd"].astype(float)
    return p.sort_values("pct_cut", ascending=False)[PRICE_CUTS.column_names]


def class_summary(ts: pd.DataFrame, pc: pd.DataFrame) -> pd.DataFrame:
    """Q1 (equal split) and Q2 rolled up to target class. Drugs with no classed primary target are left out of Q2."""
    eq = ts[ts["split_rule"] == "equal"].dropna(subset=["target_class"])
    q1 = eq.groupby("target_class").agg(gross_spend_usd=("gross_spend_usd", "sum"), n_targets=("uniprot", "nunique"))
    q1["share_of_total"] = q1["gross_spend_usd"] / q1["gross_spend_usd"].sum()
    q2 = pc.dropna(subset=["target_class"]).groupby("target_class")["pct_cut"].agg(
        n_drugs_priced="count", median_pct_cut="median", min_pct_cut="min", max_pct_cut="max")
    out = q1.join(q2, how="outer").reset_index()
    out[["gross_spend_usd", "share_of_total"]] = out[["gross_spend_usd", "share_of_total"]].fillna(0.0)
    out[["n_targets", "n_drugs_priced"]] = out[["n_targets", "n_drugs_priced"]].fillna(0).astype(int)
    out["spend_year"] = int(ts["spend_year"].iloc[0])
    return out.sort_values("gross_spend_usd", ascending=False)[CLASS_SUMMARY.column_names]


def firm_exposure(nd: pd.DataFrame, mf: pd.DataFrame, fl: pd.DataFrame) -> pd.DataFrame:
    """Q3a: per parent firm, latest-year gross spend on all drugs and the share in negotiated drugs.

    Manufacturer rows are tagged with a negotiated drug_id by the same regexes as match_spend; a row's
    firm comes from firm_labelers. Labelers not in firm_labelers count for no firm.
    """
    year = int(mf["year"].max())
    y = mf[(mf["year"] == year) & mf["gross_spend_usd"].notna()].copy()
    y["drug_id"] = pd.NA
    for r in nd.itertuples():
        g, b = re.compile(r.cms_generic_regex, re.I), re.compile(r.cms_brand_regex, re.I)
        hit = y["generic_name"].map(lambda v: bool(g.search(str(v)))) & y["brand_name"].map(lambda v: bool(b.search(str(v))))
        y.loc[hit, "drug_id"] = r.drug_id
    y = y.merge(fl[["cms_mftr_name", "parent_firm"]], left_on="mftr_name", right_on="cms_mftr_name", how="inner")
    neg = y[y["drug_id"].notna()]
    out = y.groupby("parent_firm").agg(total_gross_usd=("gross_spend_usd", "sum"), n_labelers=("mftr_name", "nunique"))
    out = out.join(neg.groupby("parent_firm").agg(
        negotiated_gross_usd=("gross_spend_usd", "sum"), n_negotiated_drugs=("drug_id", "nunique"),
        negotiated_drugs=("drug_id", lambda s: ";".join(sorted(set(s)))))).reset_index()
    out[["negotiated_gross_usd"]] = out[["negotiated_gross_usd"]].fillna(0.0)
    out["n_negotiated_drugs"] = out["n_negotiated_drugs"].fillna(0).astype(int)
    out["share_negotiated"] = out["negotiated_gross_usd"] / out["total_gross_usd"]
    out["spend_year"] = year
    return out.sort_values("share_negotiated", ascending=False)[FIRM_EXPOSURE.column_names]


# ----------------------------------------------------------------------------- figures
def figures(ts: pd.DataFrame, pc: pd.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIG.mkdir(exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    eq = ts[ts["split_rule"] == "equal"]
    year = int(eq["spend_year"].iloc[0])
    total_b = eq["gross_spend_usd"].sum() / 1e9

    # Q1a: top targets
    top = eq.nlargest(15, "gross_spend_usd").iloc[::-1]
    label = top["gene_symbol"].fillna(top["target_name"]).fillna(top["uniprot"])
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.barh(label, top["gross_spend_usd"] / 1e9, color="#3b6ea8")
    ax.set_xlabel(f"Gross Part D spend, {year} ($ billions)")
    ax.set_title(f"Top targets of the negotiated drugs (${total_b:,.1f}B gross, {year})", loc="left")
    fig.text(0.01, 0.01, "Gross cost before rebates. Spend split equally across each drug's human targets. Source: CMS, ChEMBL.",
             fontsize=7.5, color="#555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG / "q1_spend_by_target.png", dpi=200)
    plt.close(fig)

    # Q1b: by class
    by = eq.assign(target_class=eq["target_class"].fillna("Unclassified")) \
        .groupby("target_class")["gross_spend_usd"].sum().sort_values()
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.barh(by.index, by / 1e9, color="#3b6ea8")
    ax.set_xlabel(f"Gross Part D spend, {year} ($ billions)")
    ax.set_title(f"Gross spend on the negotiated drugs by target class, {year}", loc="left")
    fig.text(0.01, 0.01, "Gross cost before rebates. Equal split across targets. Source: CMS, ChEMBL.",
             fontsize=7.5, color="#555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG / "q1_spend_by_class.png", dpi=200)
    plt.close(fig)

    # Q2: price cut by class, one dot per drug
    d = pc.assign(target_class=pc["target_class"].fillna("No human target"))
    order = d.groupby("target_class")["pct_cut"].median().sort_values().index.tolist()
    fig, ax = plt.subplots(figsize=(7, 0.6 * len(order) + 1.6))
    for i, cls in enumerate(order):
        sub = d[d["target_class"] == cls].sort_values("pct_cut")
        ax.scatter(sub["pct_cut"] * 100, [i] * len(sub), color="#3b6ea8", zorder=3)
        ax.scatter(sub["pct_cut"].median() * 100, i, marker="|", s=400, color="#c0392b", zorder=2)
        for j, r in enumerate(sub.itertuples()):  # cycle four label heights so close neighbours don't collide
            ax.annotate(r.brand.split(";")[0], (r.pct_cut * 100, i), xytext=(0, (7, -13, 15, -21)[j % 4]),
                        textcoords="offset points", ha="center", fontsize=7, color="#333")
    ax.set_yticks(range(len(order)), order)
    ax.set_ylim(-0.7, len(order) - 0.3)  # room for labels above the top row and below the bottom row
    ax.set_xlim(0, 100)
    ax.set_xlabel("Cut from list price to negotiated price, 30-day supply (%)")
    ax.set_title("Negotiated price cuts by primary target class", loc="left")
    fig.text(0.01, 0.01, "Red bar = class median. List price (WAC) vs negotiated price, both before rebates. List prices are CY2023\n"
             "for the 2026 cycle and CY2024 for the 2027 cycle. Source: CMS negotiated-price fact sheets.", fontsize=7.5, color="#555")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(FIG / "q2_price_cut_by_class.png", dpi=200)
    plt.close(fig)


def main() -> None:
    from rxgenome.pipeline import write_validated

    ts, pc = q1_target_spend(), q2_price_cuts()
    write_validated(ts, TARGET_SPEND)
    write_validated(pc, PRICE_CUTS)
    write_validated(class_summary(ts, pc), CLASS_SUMMARY)
    fl, mf = load("firm_labelers"), load("partd_mftr_year")
    if fl is not None and mf is not None:  # Q3a is an extension; skip it until its inputs exist
        write_validated(firm_exposure(_need("negotiated_drugs"), mf, fl), FIRM_EXPOSURE)
    figures(ts, pc)
    print(f"[ok] figures written to {FIG.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
