"""Typed representation of the persisted job packet contract."""

from __future__ import annotations

from typing import Any, TypedDict


class JobDetails(TypedDict):
    title: str
    company: str
    location: str
    employment_type: str
    description: str
    must_have: list[str]
    nice_to_have: list[str]
    responsibilities: list[str]
    domain: str


class JobMetadata(TypedDict, total=False):
    source_url: str
    parsed_at: str
    confidence: float
    field_attribution: dict[str, Any]
    validation_errors: list[str]


class JobPacket(TypedDict, total=False):
    job: JobDetails
    metadata: JobMetadata
    compatibility_score: int
