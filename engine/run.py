"""Entry point used by the CLI and tests: scenario object -> Section 4 output document."""
from . import ENGINE_VERSION
from .validate import validate


def invalid_output(errors, scenario_id, assumptions=()):
    return {
        "scenario_id": scenario_id,
        "engine_version": ENGINE_VERSION,
        "status": "invalid_input",
        "summary": f"Input rejected: {len(errors)} field problem(s) must be fixed before a stack can be recommended.",
        "architecture_style": "other",
        "stack": None,
        "estimated_monthly_cost_usd": {"min": None, "max": None,
                                       "assumptions": ["Not estimated: the input is invalid, so no stack was chosen."]},
        "warnings": [],
        "assumptions": list(assumptions),
        "validation_errors": errors,
    }


def evaluate(raw, counterfactuals=True):
    sid = raw.get("scenario_id") if isinstance(raw, dict) and isinstance(raw.get("scenario_id"), str) else None
    req, errors, assumptions = validate(raw)
    if errors:
        return invalid_output(errors, sid, assumptions)
    from .recommend import recommend
    return recommend(req, assumptions, sid, probe=not counterfactuals)
