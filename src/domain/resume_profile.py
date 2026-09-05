"""Layout profiles used while fitting generated resumes to one page."""

from __future__ import annotations

from typing import TypedDict


class ResumeProfile(TypedDict):
    summary_sentences: int
    experience_cvitems_limit: int
    experience_cvsubitems_limit: int
    personalprojects_limit: int
    aboutme_limit: int
    item_word_limit: int
