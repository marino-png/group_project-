"""High-level package API for solar cooking simulations.

Import from here when using the project as a library rather than CLI scripts.
"""

from .models import GenerationConfig, LPConfig, RuleConfig, RunArtifacts
from .pipeline import run_lp_case, run_rule_case

__all__ = [
    "GenerationConfig",
    "RuleConfig",
    "LPConfig",
    "RunArtifacts",
    "run_rule_case",
    "run_lp_case",
]
