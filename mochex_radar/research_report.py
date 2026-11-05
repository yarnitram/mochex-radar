"""Bounded offline research reports; no provider requests or alert approval."""

import argparse
import hashlib
from dataclasses import fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from cluster_radar.intelligence.research import FundingEvidence, Swap, funding_groups, require_utc, swap_metrics
from cluster_radar.signals.research import FeatureEvidence, score_research


class ResearchDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: Literal[1]
    mint: str = Field(min_length=1,max_length=160)
    as_of: datetime
    window_end: datetime
    lookback_seconds: int = Field(default=900,ge=1,le=86400,strict=True)
    swaps: list[Swap] = Field(default_factory=list,max_length=10000)
    funding: list[FundingEvidence] = Field(default_factory=list,max_length=10000)
    pump_features: list[FeatureEvidence] = Field(default_factory=list,max_length=5)
    dump_features: list[FeatureEvidence] = Field(default_factory=list,max_length=5)

    @model_validator(mode="before")
    @classmethod
    def decimal_strings(cls,data):
        if isinstance(data,dict):
            if type(data.get("format_version")) is not int or data["format_version"]!=1:
                raise ValueError("format_version must be integer 1")
            if any(not isinstance(data.get(name),str) or "T" not in data[name] for name in ("as_of","window_end")):
                raise ValueError("decision timestamps require ISO strings")
            for section,names in (("swaps",("event_at","known_at")),("funding",("event_at","known_at","label_known_at")),
                                  ("pump_features",("window_start","window_end","known_at")),("dump_features",("window_start","window_end","known_at"))):
                rows=data.get(section,[])
                if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):
                    raise ValueError("research evidence requires arrays of records")
                model=Swap if section=="swaps" else FundingEvidence if section=="funding" else FeatureEvidence
                allowed={field.name for field in fields(model)}
                if any(set(row)-allowed for row in rows):
                    raise ValueError("unexpected research evidence field")
                if any(not isinstance(row.get(name),str) or "T" not in row[name] for row in rows for name in names):
                    raise ValueError("evidence timestamps require ISO strings")
            swaps=data.get("swaps",[])
            if not isinstance(swaps,list) or any(not isinstance(row,dict) for row in swaps):
                raise ValueError("swaps require an array of records")
            for row in swaps:
                if not isinstance(row.get("instruction_path"),list) or any(type(n) is not int for n in row["instruction_path"]) or type(row.get("swap_index")) is not int:
                    raise ValueError("swap identity requires integer path and index")
                if not isinstance(row.get("token_amount"),str) or (row.get("usd_amount") is not None and not isinstance(row["usd_amount"],str)):
                    raise ValueError("amounts require decimal strings")
            for section in ("pump_features","dump_features"):
                rows=data.get(section,[])
                if not isinstance(rows,list) or any(not isinstance(row,dict) or not isinstance(row.get("value"),str) for row in rows):
                    raise ValueError("features require decimal strings")
        return data

    @model_validator(mode="after")
    def decision_window(self):
        require_utc(self.as_of,self.window_end)
        if self.window_end>self.as_of:
            raise ValueError("decision window cannot be future")
        return self


def build_report(dataset: ResearchDataset, dataset_hash: str) -> dict:
    return {"format_version":1,"report_version":"wallet-research-report-v1",
        "engine_source_commit":"20a9d5edce573b332d2e9049f284ad16dc989f12",
        "dataset_hash":dataset_hash,"as_of":dataset.as_of,"mint":dataset.mint,
        "swap_metrics":swap_metrics(dataset.swaps,dataset.mint,dataset.as_of,timedelta(seconds=dataset.lookback_seconds)),
        "funding_evidence":funding_groups(dataset.funding,dataset.as_of),
        "pump":score_research("pump",dataset.pump_features,as_of=dataset.as_of,window_end=dataset.window_end),
        "dump":score_research("dump",dataset.dump_features,as_of=dataset.as_of,window_end=dataset.window_end),
        "security_status":"UNKNOWN","alerts_enabled":False,"approved_pump_watch":False,
        "limitations":["normalized input features require external validation",
                       "funding relations do not prove ownership or target-mint holdings","scores are provisional and not profitability estimates",
                       "live wallet ingestion and independent risk gates are incomplete"]}


def main():
    parser=argparse.ArgumentParser(description="Create a point-in-time report from normalized offline research evidence")
    parser.add_argument("--input",required=True,type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    try:
        with args.input.open("rb") as stream:
            raw=stream.read(5_000_001)
        if len(raw)>5_000_000:
            raise ValueError("dataset exceeds 5 MB")
        dataset=ResearchDataset.model_validate_json(raw)
        report=build_report(dataset,hashlib.sha256(raw).hexdigest())
        rendered=TypeAdapter(dict).dump_json(report,indent=2).decode()+"\n"
        if args.output:
            with args.output.open("x",encoding="utf-8") as stream:
                stream.write(rendered)
        else:
            print(rendered,end="")
    except Exception as exc:
        parser.exit(1,f"Research report failed: {type(exc).__name__}; check input schema, timestamps and output path.\n")


if __name__=="__main__":
    main()
