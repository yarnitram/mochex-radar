import hashlib
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from mochex_radar.research_report import ResearchDataset, build_report, main

RAW=(Path(__file__).parent/"fixtures/research-dataset.json").read_bytes()


def test_reproducible_report_retains_decimal_precision_and_never_approves():
    dataset=ResearchDataset.model_validate_json(RAW)
    report=build_report(dataset,hashlib.sha256(RAW).hexdigest())
    encoded=TypeAdapter(dict).dump_json(report)
    assert TypeAdapter(dict).dump_json(build_report(dataset,report["dataset_hash"]))==encoded
    data=json.loads(encoded)
    assert data["swap_metrics"]["net_usd"]=="125"
    assert data["pump"]["score"]=="80.0"
    assert data["dump"]["score"]=="100"
    assert data["pump"]["research_threshold_met"] is True
    assert data["security_status"]=="UNKNOWN"
    assert data["approved_pump_watch"] is False and data["alerts_enabled"] is False


@pytest.mark.parametrize("case",["number_amount","boolean_path","nan","future_label","naive_time"])
def test_input_validation_and_future_label_handling(case):
    data=json.loads(RAW)
    if case=="number_amount":data["swaps"][0]["token_amount"]=1.5
    elif case=="boolean_path":data["swaps"][0]["instruction_path"]=[True]
    elif case=="nan":data["pump_features"][0]["value"]="NaN"
    elif case=="naive_time":data["as_of"]="2026-01-01T12:00:00"
    else:data["funding"][1]["label_known_at"]="2026-01-02T12:00:00Z"
    if case=="future_label":
        report=build_report(ResearchDataset.model_validate_json(json.dumps(data)),"fixture")
        assert report["funding_evidence"]["groups"]==[]
    else:
        with pytest.raises(ValidationError):
            ResearchDataset.model_validate_json(json.dumps(data))


def test_cli_writes_new_report_but_preserves_existing_output(tmp_path,monkeypatch):
    source=tmp_path/"dataset.json"
    source.write_bytes(RAW)
    output=tmp_path/"report.json"
    monkeypatch.setattr("sys.argv",["research_report","--input",str(source),"--output",str(output)])
    main()
    original=output.read_bytes()
    with pytest.raises(SystemExit):main()
    assert output.read_bytes()==original
