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
    assert nd["negotiated_price_30d_usd"].notna().sum() == 15


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
    assert len(pc) == 15 and pc["target_class"].notna().all()
    assert all((project / "figures" / f).exists() for f in
               ("q1_spend_by_target.png", "q1_spend_by_class.png", "q2_price_cut_by_class.png"))
    errs = "\n".join(validate.gate(2))  # prices unverified, README missing -> must fail
    assert "unverified prices" in errs and "Findings" in errs


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
