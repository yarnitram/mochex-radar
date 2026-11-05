"""Versioned operational research notices. Trading signals are not enabled here."""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResearchNotice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    asset_id: str = Field(min_length=1, max_length=160)
    kind: Literal["SYSTEM_TEST", "DATA_QUALITY"]
    rule_version: str = Field(min_length=1, max_length=80)
    known_at: datetime
    expires_at: datetime
    summary: str = Field(min_length=1, max_length=500)
    evidence: list[str] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def timestamps_and_payload(self):
        for value in (self.known_at, self.expires_at):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError("notice timestamps must be UTC")
        if not self.known_at < self.expires_at <= self.known_at + timedelta(hours=24):
            raise ValueError("notice lifetime must be positive and at most 24 hours")
        if any(not item or len(item) > 300 for item in self.evidence):
            raise ValueError("evidence items require 1..300 characters")
        if len(self.render().encode("utf-16-le")) // 2 > 4096:
            raise ValueError("message exceeds Telegram limit")
        return self

    def dedup_key(self) -> str:
        identity = [self.asset_id, self.kind, self.rule_version, int(self.known_at.timestamp()) // 1800]
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    def render(self) -> str:
        return "\n".join([
            "Mochex Radar | " + self.kind.replace("_", " "),
            "Asset: " + self.asset_id, "Rule: " + self.rule_version,
            "Category: operational | Confidence: not assessed",
            "Known at: " + self.known_at.isoformat(), "Expires: " + self.expires_at.isoformat(),
            "", self.summary, "Evidence:", *["- " + item for item in self.evidence],
            "", "BTC context: not evaluated | Security: UNKNOWN",
            "Research notice only. No approved Pump/Dump signal or trade instruction.",
        ])
