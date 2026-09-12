"""Agent 2: verify the extraction against the source text.

A second pass exists because the failure mode that matters here is quiet: an
extraction agent that invents a salary band produces output that looks perfect
and scores wrong. This agent re-reads the source with one question per field —
"is this actually in there?" — and reports what it could not confirm.

The output is advisory, not destructive. Unverified fields are flagged for the
user rather than deleted, since a false negative here would throw away good
data.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.client import structured_call
from app.agents.extraction import ExtractedJob

SYSTEM = """\
You audit structured extractions against their source text. You are checking \
one thing: is every claim in the extraction actually supported by the source?

For each populated field in the extraction, decide:

- `grounded` — the source states this, explicitly or by unambiguous paraphrase.
- `unverified` — the source does not state this. Includes plausible-sounding \
  inferences: a salary inferred from the market, a company size inferred from \
  the brand, a seniority inferred from the requirements list.
- `contradicted` — the source states something different.

Report every field that is not `grounded` in `unverified_fields`, using the \
extraction's own field names (e.g. "salary_max", "requirements[2].min_years").

For requirements specifically, check that each `evidence` string genuinely \
appears in the source and genuinely supports the requirement. An evidence \
quote that is paraphrased rather than verbatim is `unverified`. An evidence \
quote that supports a different skill than the one named is `contradicted`.

Set `confidence` to your overall trust in the extraction, from 0.0 to 1.0:

- 0.9-1.0: everything grounded, evidence quotes exact.
- 0.7-0.9: everything material grounded; minor fields unverified.
- 0.4-0.7: a material field (title, company, a required skill, salary) is \
  unverified.
- 0.0-0.4: contradictions present, or the source text is too garbled to audit.

Be specific in `notes` about what you could not confirm and why. Do not \
speculate about what the true value might be — that is the user's call, and \
guessing here would reintroduce the exact problem this pass exists to catch.\
"""


class ValidationReport(BaseModel):
    confidence: float = Field(ge=0.0, le=1.0)
    unverified_fields: list[str] = Field(default_factory=list)
    contradicted_fields: list[str] = Field(default_factory=list)
    #: Indices into the extraction's requirement list whose evidence did not
    #: hold up. The ingestion pipeline drops these before persisting.
    rejected_requirement_indices: list[int] = Field(default_factory=list)
    notes: str = Field(description="What could not be confirmed, and why.")


def validate_extraction(raw_text: str, extracted: ExtractedJob) -> ValidationReport:
    """Audit `extracted` against `raw_text`.

    Runs at `xhigh`: this is the anti-hallucination gate, and a validator that
    misses a fabrication is worse than no validator at all — it converts an
    obvious problem into a confident wrong answer.
    """
    payload = extracted.model_dump_json(indent=2, exclude_none=True)
    user = (
        "Audit this extraction against its source.\n\n"
        f"<source>\n{raw_text}\n</source>\n\n"
        f"<extraction>\n{payload}\n</extraction>"
    )
    return structured_call(
        system=SYSTEM,
        user=user,
        output_model=ValidationReport,
        effort="xhigh",
    )
