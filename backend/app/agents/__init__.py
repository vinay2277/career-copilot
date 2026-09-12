"""LLM agents.

Each module here owns one prompt and one output schema. Agents never compute
scores — `services/analytics/` does that deterministically, and the agents read
the result. Keeping that boundary is what makes the numbers auditable.
"""

from app.agents.career_intelligence import CareerGuidance, recommend
from app.agents.client import AgentError, structured_call
from app.agents.extraction import ExtractedJob, ExtractedRequirement, extract_job
from app.agents.interview import (
    AnswerFeedback,
    QuestionSet,
    SessionSummary,
    generate_questions,
    grade_answer,
    summarize_session,
)
from app.agents.learning import LearningRoadmap, build_roadmap
from app.agents.resume import (
    ResumeAnalysis,
    TailoredResumeDraft,
    analyze_resume,
    tailor_resume,
)
from app.agents.validation import ValidationReport, validate_extraction

__all__ = [
    "AgentError",
    "AnswerFeedback",
    "CareerGuidance",
    "ExtractedJob",
    "ExtractedRequirement",
    "LearningRoadmap",
    "QuestionSet",
    "ResumeAnalysis",
    "SessionSummary",
    "TailoredResumeDraft",
    "ValidationReport",
    "analyze_resume",
    "build_roadmap",
    "extract_job",
    "generate_questions",
    "grade_answer",
    "recommend",
    "structured_call",
    "summarize_session",
    "tailor_resume",
    "validate_extraction",
]
