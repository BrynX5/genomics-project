"""
Offline tests: contracts catch bad data, the reshape and analysis work end to end on synthetic
inputs, the gates behave, and the hook blocks a broken table. No network needed.

    make test
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rxgenome import analysis, contracts, pipeline, validate  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A throwaway project root with the real reference data copied in."""
    for d in ("data/reference", "data/interim", "data/processed", "data/raw", "figures"):
        (tmp_path / d).mkdir(parents=True)
    shutil.copy(REPO / contracts.NEGOTIATED_DRUGS.path, tmp_path / contracts.NEGOTIATED_DRUGS.path)
    for mod in (validate, pipeline, analysis):
        monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(analysis, "FIG", tmp_path / "figures")
    return tmp_path


def _fake_acc(i: int) -> str:
    return f"P1{i:03d}9"  # valid UniProt format, not a real protein


def _write_synthetic_inputs(root: Path, skip=()) -> pd.DataFrame:
    nd = validate.load("negotiated_drugs")
    partd, dt, classes = [], [], []
    names = {  # names that satisfy each drug's cms regexes
        "novolog": ("Novolog", "Insulin Aspart"), "trelegy-ellipta": ("Trelegy Ellipta", "Fluticasone/Umeclidin/Vilanter"),
        "breo-ellipta": ("Breo Ellipta", "Fluticasone/Vilanterol"), "janumet": ("Janumet", "Sitagliptin/Metformin HCl"),
        "entresto": ("Entresto", "Sacubitril/Valsartan"), "semaglutide": ("Ozempic", "Semaglutide"),
        "austedo": ("Austedo", "Deutetrabenazine"),
    }
    cls = sorted(contracts.TARGET_CLASSES)
    for i, d in enumerate(nd.itertuples()):
        brand, generic = names.get(d.drug_id, (d.brand.split(";")[0], d.generic))
        for year in (2023, 2024):
            partd.append({"brand_name": brand, "generic_name": generic, "year": year,
                          "gross_spend_usd": 1e9 * (i + 1), "claims": 1e5, "beneficiaries": 1e4})
        if d.drug_id in skip:
            continue
        for k in range(2 if "/" in d.generic else 1):  # combos get two targets
            acc = _fake_acc(i * 10 + k)
            dt.append({"drug_id": d.drug_id, "ingredient": d.generic.split("/")[k].strip(), "rxcui": "123",
                       "chembl_parent": "CHEMBL1", "mechanism_of_action": "x", "action_type": "INHIBITOR",
                       "target_chembl_id": f"CHEMBL{i * 10 + k + 2}", "target_name": f"T{i}", "target_type": "SINGLE PROTEIN",
                       "organism": "Homo sapiens", "uniprot": acc, "target_order": k + 1, "mapping_source": "auto"})
            classes.append({"uniprot": acc, "gene_symbol": f"G{i}{k}", "target_class": cls[i % len(cls)],
                            "source_url": "https://www.uniprot.org/"})
    pipeline.write_validated(pd.DataFrame(partd), contracts.PARTD_DRUG_YEAR)
    pipeline.write_validated(pd.DataFrame(dt), contracts.DRUG_TARGET)
    pd.DataFrame(classes)[contracts.TARGET_CLASSES_REF.column_names].to_csv(root / contracts.TARGET_CLASSES_REF.path, index=False)
    return nd


# ----------------------------------------------------------------------------- contracts
def test_repo_reference_data_passes():
    assert validate.validate_table(contracts.NEGOTIATED_DRUGS) == []
    nd = validate.load("negotiated_drugs")
    assert len(nd) == 25 and nd["drug_id"].is_unique
    assert nd["negotiated_price_30d_usd"].notna().all() and nd["verified"].all()


def test_contract_catches_bad_rows(project):
    p = project / contracts.NEGOTIATED_DRUGS.path
    df = pd.read_csv(p, dtype=str)
    df.loc[0, "drug_id"] = "Bad Slug"
    df.loc[10, "negotiated_price_30d_usd"] = "99999"  # above list price
    df.loc[11, "price_source_url"] = ""  # price without a source
    df.loc[12, "cycle"] = "2031"
    df.to_csv(p, index=False)
    errs = "\n".join(validate.validate_table(contracts.NEGOTIATED_DRUGS))
    assert "drug_id: bad format" in errs and "cycle" in errs
    df.loc[0, "drug_id"], df.loc[12, "cycle"] = "eliquis", "2026"  # fix format errors to reach table checks
    df.to_csv(p, index=False)
    errs = "\n".join(validate.validate_table(contracts.NEGOTIATED_DRUGS))
    assert "negotiated price is below list price" in errs
    assert "a price needs a price_source_url" in errs


def test_unexpected_column_is_rejected(project):
    p = project / contracts.NEGOTIATED_DRUGS.path
    pd.read_csv(p, dtype=str).assign(extra="x").to_csv(p, index=False)
    assert any("unexpected columns" in e for e in validate.validate_table(contracts.NEGOTIATED_DRUGS))


# ----------------------------------------------------------------------------- pipeline + analysis
def test_reshape_cms_keeps_overall_rows_only():
    raw = pd.DataFrame({
        "Brnd_Name": ["Eliquis", "Eliquis"], "Gnrc_Name": ["Apixaban", "Apixaban"],
        "Tot_Mftr": ["1", "1"], "Mftr_Name": ["Overall", "Bristol-Myers"],
        "Tot_Spndng_2023": ["100", "100"], "Tot_Spndng_2024": ["200", "200"],
        "Tot_Clms_2024": ["10", "10"], "Tot_Benes_2024": ["", ""], "Avg_Spnd_Per_Clm_2024": ["20", "20"],
    })
    long = pipeline.reshape_cms(raw)
    assert len(long) == 2
    assert long.set_index("year").loc[2024, "gross_spend_usd"] == 200


def test_end_to_end_synthetic(project):
    _write_synthetic_inputs(project)
    assert validate.gate(1) == []
    analysis.main()
    ts, pc = validate.load("target_spend"), validate.load("price_cuts")
    for rule in ("equal", "first_target"):
        assert abs(ts.loc[ts.split_rule == rule, "share_of_total"].sum() - 1) < 1e-9
    # equal split preserves the total spend of mapped drugs (latest year)
    total = validate.load("partd_drug_year").query("year == 2024")["gross_spend_usd"].sum()
    assert abs(ts.loc[ts.split_rule == "equal", "gross_spend_usd"].sum() - total) < 1
    assert len(pc) == 25 and pc["target_class"].notna().all()
    assert all((project / "figures" / f).exists() for f in
               ("q1_spend_by_target.png", "q1_spend_by_class.png", "q2_price_cut_by_class.png"))
    pc_path = project / contracts.PRICE_CUTS.path
    pd.read_csv(pc_path, dtype=str).assign(verified=lambda d: d["verified"].where(d.index > 0, "false")).to_csv(pc_path, index=False)
    errs = "\n".join(validate.gate(2))  # one price unverified, README missing -> must fail
    assert "unverified prices" in errs and "Findings" in errs


def test_class_summary_rolls_up_by_class():
    ts = pd.DataFrame({
        "split_rule": ["equal", "equal", "equal", "first_target"], "spend_year": 2024,
        "uniprot": [_fake_acc(1), _fake_acc(2), _fake_acc(3), _fake_acc(1)],
        "target_class": ["Kinase", "Kinase", "GPCR", "Kinase"],
        "gross_spend_usd": [30.0, 10.0, 60.0, 999.0],  # first_target row must be ignored
    })
    pc = pd.DataFrame({"target_class": ["Kinase", "Kinase", "Protease", None], "pct_cut": [0.4, 0.6, 0.8, 0.5]})
    cs = analysis.class_summary(ts, pc).set_index("target_class")
    assert list(cs.index) == ["GPCR", "Kinase", "Protease"]  # sorted by spend; unclassed drug dropped
    assert cs.loc["Kinase", "gross_spend_usd"] == 40 and cs.loc["Kinase", "share_of_total"] == 0.4
    assert cs.loc["Kinase", "n_targets"] == 2 and cs.loc["Kinase", "median_pct_cut"] == 0.5
    assert cs.loc["GPCR", "n_drugs_priced"] == 0 and pd.isna(cs.loc["GPCR", "median_pct_cut"])
    assert cs.loc["Protease", "gross_spend_usd"] == 0 and cs.loc["Protease", "max_pct_cut"] == 0.8


def test_reshape_cms_mftr_drops_overall_rows():
    raw = pd.DataFrame({
        "Brnd_Name": ["Eliquis", "Eliquis "], "Gnrc_Name": ["Apixaban", "Apixaban"],
        "Mftr_Name": ["Overall", " BMS Primarycare "], "Tot_Spndng_2023": ["100", "90"], "Tot_Spndng_2024": ["200", ""],
    })
    long = pipeline.reshape_cms_mftr(raw)
    assert set(long["mftr_name"]) == {"BMS Primarycare"} and set(long["brand_name"]) == {"Eliquis"}
    assert long.set_index("year").loc[2023, "gross_spend_usd"] == 90
    assert pd.isna(long.set_index("year").loc[2024, "gross_spend_usd"])


def test_firm_exposure_by_parent():
    nd = pd.DataFrame({"drug_id": ["eliquis"], "cms_generic_regex": ["^apixaban$"], "cms_brand_regex": ["^eliquis$"]})
    mf = pd.DataFrame({
        "brand_name": ["Eliquis", "Orencia", "Opdivo", "Eliquis", "Other"],
        "generic_name": ["Apixaban", "Abatacept", "Nivolumab", "Apixaban", "X"],
        "mftr_name": ["BMS Primarycare", "BMS Primarycare", "Celgene/BMS", "BMS Primarycare", "Unmapped Co"],
        "year": [2024, 2024, 2024, 2023, 2024],
        "gross_spend_usd": [60.0, 30.0, 10.0, 999.0, 500.0],  # 2023 row and unmapped labeler must be ignored
    })
    fl = pd.DataFrame({"cms_mftr_name": ["BMS Primarycare", "Celgene/BMS"], "parent_firm": ["BMS", "BMS"]})
    fe = analysis.firm_exposure(nd, mf, fl).set_index("parent_firm")
    assert list(fe.index) == ["BMS"]
    assert fe.loc["BMS", "total_gross_usd"] == 100 and fe.loc["BMS", "negotiated_gross_usd"] == 60
    assert fe.loc["BMS", "share_negotiated"] == 0.6 and fe.loc["BMS", "n_labelers"] == 2
    assert fe.loc["BMS", "negotiated_drugs"] == "eliquis" and fe.loc["BMS", "spend_year"] == 2024


def test_monopoly_tier_boundaries():
    # 42 U.S.C. 1320f-3(c): extended = at least 12 but fewer than 16 years; long = at least 16
    assert [analysis.monopoly_tier(y) for y in (11.99, 12.0, 15.99, 16.0)] == ["short", "extended", "extended", "long"]


def test_cut_drivers_and_stats():
    pc = pd.DataFrame({"drug_id": ["a", "b", "c"], "brand": ["A", "B", "C"], "cycle": [2026, 2026, 2027],
                       "pct_cut": [0.4, 0.6, 0.8], "list_price_30d_usd": [900.0, 500.0, 100.0],
                       "target_class": ["Kinase", None, "GPCR"]})
    fa = pd.DataFrame({"drug_id": ["a", "b", "c"], "approval_date": ["2015-08-29", "2010-08-29", "2005-01-17"]})
    cd = pd.DataFrame({"cycle": [2026, 2027], "selected_drug_publication_date": ["2023-08-29", "2025-01-17"]})
    fe = pd.DataFrame({"parent_firm": ["F", "G"], "share_negotiated": [0.2, 0.9], "negotiated_drugs": ["a;b", "c"]})
    cdr = analysis.cut_drivers(pc, fa, cd, fe).set_index("drug_id")
    assert round(cdr.loc["a", "years_since_approval"], 1) == 8.0 and cdr.loc["a", "monopoly_tier"] == "short"
    assert cdr.loc["b", "monopoly_tier"] == "extended" and cdr.loc["c", "monopoly_tier"] == "long"
    assert cdr.loc["c", "ceiling_pct_of_nonfamp"] == 0.40 and cdr.loc["b", "parent_firm"] == "F"
    st = analysis.cut_driver_stats(cdr.reset_index()).set_index(["statistic", "variable"])
    assert st.loc[("spearman_rho", "list_price_30d_usd"), "value"] == pytest.approx(-1.0)  # perfectly inverse ranks
    assert st.loc[("spearman_rho", "years_since_approval"), "value"] == pytest.approx(1.0)
    assert st.loc[("median_cut", "long"), "value"] == 0.8 and st.loc[("median_cut", "long"), "n"] == 1


def test_selection_years_rule():
    cd = pd.DataFrame({"cycle": [2026, 2027], "selected_drug_publication_date": ["2023-08-29", "2025-01-17"]})
    sy = analysis.selection_years(cd).set_index("cycle")
    assert tuple(sy.loc[2026]) == (2022, 2024) and tuple(sy.loc[2027]) == (2024, 2025)


def test_payments_change_against_market():
    nd = pd.DataFrame({"drug_id": ["a", "b", "c"], "cycle": [2026, 2026, 2026]})
    cd = pd.DataFrame({"cycle": [2026], "selected_drug_publication_date": ["2023-08-29"]})
    pdy = pd.DataFrame({"drug_id": ["a", "a", "b", "c"], "program_year": [2022, 2024, 2022, 2024],
                        "general_payments_usd": [100.0, 50.0, 10.0, 7.0], "n_records": [1, 1, 1, 1], "product_names": ["A"] * 4})
    pyt = pd.DataFrame({"program_year": [2022, 2023, 2024], "drug_bio_payments_usd": [1000.0, 1000.0, 2000.0], "n_records": [1, 1, 1]})
    chg, summ = analysis.payments_change(nd, pdy, pyt, cd)
    c = chg.set_index("drug_id")
    assert c.loc["a", "drug_ratio"] == 0.5 and c.loc["a", "market_ratio"] == 2.0 and c.loc["a", "relative_change"] == -0.75
    assert c.loc["b", "post_usd"] == 0.0 and c.loc["b", "drug_ratio"] == 0.0  # absent in a published year = no payments
    assert pd.isna(c.loc["c", "drug_ratio"])  # no pre-year payments: ratio undefined
    s = summ.iloc[0]
    assert s["n_drugs"] == 2 and s["n_fell_vs_market"] == 2 and s["median_drug_ratio"] == 0.25
    assert s["n_promoted"] == 0 and pd.isna(s["median_relative_change_promoted"])  # all pre_usd below $1M
    assert s["aggregate_drug_ratio"] == pytest.approx(57 / 110) and s["aggregate_relative_change"] == pytest.approx(57 / 110 / 2 - 1)


def test_reshape_payments_maps_spellings():
    nd = pd.DataFrame({"drug_id": ["eliquis"], "brand": ["Eliquis"]})
    bp = pd.DataFrame({"program_year": [2024, 2024, 2024], "slot": [1, 2, 1], "product_name": ["ELIQUIS", "Eliquis", "Other"],
                       "total_usd": ["10.5", "2", "99"], "n_records": ["3", "1", "9"]})
    bk = pd.DataFrame({"program_year": [2024, 2024, 2024], "product_kind": ["Drug", "Biological", "Device"],
                       "total_usd": ["100", "50", "999"], "n_records": ["5", "5", "5"]})
    drug, total = pipeline.reshape_payments(bp, bk, nd)
    assert drug.iloc[0]["general_payments_usd"] == 12.5 and drug.iloc[0]["product_names"] == "ELIQUIS;Eliquis"
    assert total.iloc[0]["drug_bio_payments_usd"] == 150


def test_gate1_reports_unmapped_drugs(project):
    _write_synthetic_inputs(project, skip={"eliquis", "xarelto", "ofev"})
    errs = "\n".join(validate.gate(1))
    assert "22/25" in errs and "eliquis" in errs


# ----------------------------------------------------------------------------- hook
def test_hook_blocks_broken_table(project):
    _write_synthetic_inputs(project)
    hook = REPO / ".claude/hooks/validate_on_write.py"
    target = project / contracts.TARGET_CLASSES_REF.path

    def run():
        ev = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(target)}})
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
        # the hook imports rxgenome from <project>/src
        shutil.copytree(REPO / "src", project / "src", dirs_exist_ok=True)
        return subprocess.run([sys.executable, str(hook)], input=ev, capture_output=True, text=True, env=env)

    assert run().returncode == 0
    df = pd.read_csv(target, dtype=str)
    df.loc[0, "target_class"] = "Enzyme-ish"
    df.to_csv(target, index=False)
    r = run()
    assert r.returncode == 2 and "target_class" in r.stderr
