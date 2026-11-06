"""Validated batch provenance; caller declarations do not verify coverage."""

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime

from cluster_radar.intelligence.research import require_utc


@dataclass(frozen=True)
class HistoryProvenance:
    source: str
    parser_version: str
    wallet: str
    window_start: datetime
    window_end: datetime
    retrieved_at: datetime
    raw_sha256: str
    pagination_exhausted: bool
    coverage_verified: bool = False

    def __post_init__(self):
        require_utc(self.window_start, self.window_end, self.retrieved_at)
        if not self.window_start < self.window_end <= self.retrieved_at:
            raise ValueError("invalid history coverage window")
        if any(not isinstance(v, str) or not v.strip() or len(v) > 200
               for v in (self.source, self.parser_version, self.wallet)):
            raise ValueError("bounded source/parser/wallet required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.raw_sha256):
            raise ValueError("raw evidence SHA256 required")
        if type(self.pagination_exhausted) is not bool or self.coverage_verified is not False:
            raise ValueError("coverage verification is unsupported")

    def envelope(self):
        payload = asdict(self)
        for key in ("window_start", "window_end", "retrieved_at"):
            payload[key] = payload[key].isoformat()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return {"batch_id": hashlib.sha256(encoded).hexdigest(), "provenance": payload,
                "completeness": "unverified", "signals_enabled": False}
