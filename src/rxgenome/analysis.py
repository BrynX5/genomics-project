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

from rxgenome.contracts import (CLASS_SUMMARY, CUT_DRIVER_STATS, CUT_DRIVERS, FIRM_EXPOSURE, PAYMENTS_CHANGE,
                                PAYMENTS_SUMMARY, PRICE_CUTS, TARGET_SPEND)
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


# 42 U.S.C. 1320f-3(c)(3)-(5): price ceiling as a share of non-FAMP, by years since approval
CEILING = {"short": 0.75, "extended": 0.65, "long": 0.40}


def monopoly_tier(years: float) -> str:
    return "long" if years >= 16 else "extended" if years >= 12 else "short"


def cut_drivers(pc: pd.DataFrame, fa: pd.DataFrame, cd: pd.DataFrame, fe: pd.DataFrame | None) -> pd.DataFrame:
    """Q3b: each drug's cut next to its years on market (and statutory tier), list price and firm exposure."""
    d = pc.merge(fa[["drug_id", "approval_date"]], on="drug_id", how="left") \
          .merge(cd[["cycle", "selected_drug_publication_date"]], on="cycle", how="left")
    days = pd.to_datetime(d["selected_drug_publication_date"]) - pd.to_datetime(d["approval_date"])
    d["years_since_approval"] = days.dt.days / 365.25
    d["monopoly_tier"] = d["years_since_approval"].map(monopoly_tier)
    d["ceiling_pct_of_nonfamp"] = d["monopoly_tier"].map(CEILING)
    if fe is not None:
        firm = fe.dropna(subset=["negotiated_drugs"]).assign(drug_id=lambda f: f["negotiated_drugs"].str.split(";")) \
                 .explode("drug_id")[["drug_id", "parent_firm", "share_negotiated"]]
        d = d.merge(firm.rename(columns={"share_negotiated": "firm_share_negotiated"}), on="drug_id", how="left")
    else:
        d["parent_firm"], d["firm_share_negotiated"] = pd.NA, pd.NA
    return d.sort_values("years_since_approval", ascending=False)[CUT_DRIVERS.column_names]


def _spearman_perm(x: pd.Series, y: pd.Series, n_perm: int = 10_000, seed: int = 0) -> tuple[float, float, int]:
    import numpy as np

    ok = x.notna() & y.notna()
    rx, ry = x[ok].rank().to_numpy(), y[ok].rank().to_numpy()
    rho = float(np.corrcoef(rx, ry)[0, 1])
    rng = np.random.default_rng(seed)
    null = np.array([np.corrcoef(rx, rng.permutation(ry))[0, 1] for _ in range(n_perm)])
    p = float((np.sum(np.abs(null) >= abs(rho) - 1e-12) + 1) / (n_perm + 1))
    return rho, p, int(ok.sum())


def cut_driver_stats(cdr: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for var in ("years_since_approval", "list_price_30d_usd", "firm_share_negotiated", "cycle"):
        rho, p, n = _spearman_perm(cdr[var].astype(float), cdr["pct_cut"].astype(float))
        rows.append({"statistic": "spearman_rho", "variable": var, "value": rho, "n": n, "p_value": p})
    for tier, g in cdr.groupby("monopoly_tier"):
        rows.append({"statistic": "median_cut", "variable": tier, "value": g["pct_cut"].median(), "n": len(g), "p_value": None})
    return pd.DataFrame(rows)[CUT_DRIVER_STATS.column_names]


PROMOTED_MIN_USD = 1_000_000  # a drug counts as actively promoted with at least this much in general payments in pre_year


def selection_years(cd: pd.DataFrame) -> pd.DataFrame:
    """pre = last full program year before publication; post = first year mostly after it (before 1 July -> same year)."""
    pub = pd.to_datetime(cd["selected_drug_publication_date"])
    return cd.assign(pre_year=pub.dt.year - 1, post_year=pub.dt.year + (pub.dt.month >= 7).astype(int))[["cycle", "pre_year", "post_year"]]


def payments_change(nd: pd.DataFrame, pdy: pd.DataFrame, pyt: pd.DataFrame, cd: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Q3c: general payments naming each drug, year before vs year after selection, against all drug payments."""
    d = nd[["drug_id", "cycle"]].merge(selection_years(cd), on="cycle", how="left")
    amt = pdy.set_index(["drug_id", "program_year"])["general_payments_usd"]
    tot = pyt.set_index("program_year")["drug_bio_payments_usd"]
    d["pre_usd"] = [amt.get((r.drug_id, r.pre_year)) for r in d.itertuples()]
    d["post_usd"] = [amt.get((r.drug_id, r.post_year)) for r in d.itertuples()]
    has_post = d["post_year"].isin(pdy["program_year"].unique())  # a drug absent in a published year had no payments
    d.loc[d["pre_usd"].isna() & d["pre_year"].isin(pdy["program_year"].unique()), "pre_usd"] = 0.0
    d.loc[d["post_usd"].isna() & has_post, "post_usd"] = 0.0
    d["drug_ratio"] = d["post_usd"] / d["pre_usd"].where(d["pre_usd"] > 0)
    d["market_ratio"] = d["post_year"].map(tot) / d["pre_year"].map(tot)
    d["relative_change"] = d["drug_ratio"] / d["market_ratio"] - 1
    change = d.sort_values(["cycle", "relative_change"])[PAYMENTS_CHANGE.column_names]

    rows = []
    for (cycle, pre, post), g in change.groupby(["cycle", "pre_year", "post_year"]):
        ok = g.dropna(subset=["drug_ratio"])
        promoted = ok[ok["pre_usd"] >= PROMOTED_MIN_USD]
        mkt = g["market_ratio"].iloc[0]
        agg = g["post_usd"].sum() / g["pre_usd"].sum() if g["pre_usd"].sum() > 0 and g["post_usd"].notna().any() else None
        rows.append({"cycle": cycle, "pre_year": pre, "post_year": post, "n_drugs": len(ok),
                     "median_drug_ratio": ok["drug_ratio"].median() if len(ok) else None,
                     "market_ratio": mkt,
                     "median_relative_change": ok["relative_change"].median() if len(ok) else None,
                     "n_fell_vs_market": int((ok["relative_change"] < 0).sum()),
                     "n_promoted": len(promoted),
                     "median_relative_change_promoted": promoted["relative_change"].median() if len(promoted) else None,
                     "aggregate_drug_ratio": agg,
                     "aggregate_relative_change": agg / mkt - 1 if agg is not None and pd.notna(mkt) else None})
    return change, pd.DataFrame(rows)[PAYMENTS_SUMMARY.column_names]


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


def cut_driver_figure(cdr: pd.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIG.mkdir(exist_ok=True)
    colors = {"short": "#3b6ea8", "extended": "#e08a2c", "long": "#c0392b"}
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6), sharey=True)
    for ax, col, xlabel in ((axes[0], "years_since_approval", "Years from FDA approval to selection"),
                            (axes[1], "list_price_30d_usd", "List price, 30-day supply (USD, log scale)")):
        for tier, g in cdr.groupby("monopoly_tier"):
            ax.scatter(g[col], g["pct_cut"] * 100, color=colors[tier], label=f"{tier} ({len(g)})", zorder=3)
        for r in cdr.itertuples():
            ax.annotate(r.brand.split(";")[0], (getattr(r, col), r.pct_cut * 100), xytext=(4, 2),
                        textcoords="offset points", fontsize=6.5, color="#333")
        ax.set_xlabel(xlabel)
    axes[0].axvline(12, color="#999", ls=":", lw=1)
    axes[0].axvline(16, color="#999", ls=":", lw=1)
    axes[1].set_xscale("log")
    axes[0].set_ylabel("Cut from list price to negotiated price (%)")
    axes[0].set_ylim(0, 100)
    axes[0].legend(title="Statutory tier", fontsize=8, title_fontsize=8, loc="lower right")
    fig.suptitle("What tracks the negotiated price cut?", x=0.01, ha="left")
    fig.text(0.01, 0.01, "List price (WAC) vs negotiated price, both before rebates. Dotted lines: 12 and 16 years, where the statutory "
             "ceiling drops\nfrom 75% to 65% to 40% of non-FAMP (a different base from list price). Sources: CMS fact sheets, openFDA.",
             fontsize=7.5, color="#555")
    fig.tight_layout(rect=(0, 0.07, 1, 0.96))
    fig.savefig(FIG / "q3b_cut_drivers.png", dpi=200)
    plt.close(fig)


def payments_figure(nd: pd.DataFrame, pdy: pd.DataFrame, pyt: pd.DataFrame, cd: pd.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIG.mkdir(exist_ok=True)
    sy = selection_years(cd).set_index("cycle")
    tot = pyt.set_index("program_year")["drug_bio_payments_usd"]
    years = sorted(pdy["program_year"].unique())
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4), sharey=True)
    for ax, (cycle, s) in zip(axes, sy.iterrows()):
        base = int(s["pre_year"])
        idx = []
        for drug in nd.loc[nd["cycle"] == cycle, "drug_id"]:
            ser = pdy[pdy["drug_id"] == drug].set_index("program_year")["general_payments_usd"].reindex(years, fill_value=0.0)
            if ser.get(base, 0) >= PROMOTED_MIN_USD:
                idx.append(ser / ser[base] * 100)
                ax.plot(years, idx[-1], color="#b8c7dd", lw=0.9, zorder=1)
        if idx:
            ax.plot(years, pd.concat(idx, axis=1).median(axis=1), color="#3b6ea8", lw=2.4, label=f"Median of {len(idx)} promoted drugs", zorder=3)
        ax.plot(years, tot.reindex(years) / tot[base] * 100, color="#333", ls="--", lw=1.6, label="All drug/biologic payments", zorder=2)
        pub = cd.set_index("cycle").loc[cycle, "selected_drug_publication_date"]
        ax.axvline(pd.Timestamp(pub).year + pd.Timestamp(pub).dayofyear / 366 - 0.5, color="#c0392b", ls=":", lw=1.2)
        ax.set_title(f"{cycle} cycle (selected {pub})", loc="left", fontsize=10)
        ax.set_xlabel("Open Payments program year")
        ax.set_yscale("log")
        ax.legend(fontsize=7.5, loc="lower left")
    axes[0].set_ylabel("Index, year before selection = 100")
    fig.suptitle("Manufacturer payments to clinicians naming the negotiated drugs", x=0.01, ha="left")
    fig.text(0.01, 0.01, "General payments (meals, speaking, consulting, travel), not research. A payment naming several products counts in full "
             "for each.\nOnly drugs with at least $1M of payments in the year before selection. Red dotted line: selection date. Log scale. "
             "Source: CMS Open Payments.", fontsize=7.5, color="#555")
    fig.tight_layout(rect=(0, 0.07, 1, 0.95))
    fig.savefig(FIG / "q3c_payments.png", dpi=200)
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
    fa, cd = load("fda_approvals"), load("cycle_dates")
    if fa is not None and cd is not None:  # Q3b, likewise
        cdr = cut_drivers(pc, fa, cd, load("firm_exposure"))
        write_validated(cdr, CUT_DRIVERS)
        write_validated(cut_driver_stats(cdr), CUT_DRIVER_STATS)
        cut_driver_figure(cdr)
    pdy, pyt = load("payments_drug_year"), load("payments_year_total")
    if pdy is not None and pyt is not None and cd is not None:  # Q3c, likewise
        chg, summ = payments_change(_need("negotiated_drugs"), pdy, pyt, cd)
        write_validated(chg, PAYMENTS_CHANGE)
        write_validated(summ, PAYMENTS_SUMMARY)
        payments_figure(_need("negotiated_drugs"), pdy, pyt, cd)
    figures(ts, pc)
    print(f"[ok] figures written to {FIG.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
