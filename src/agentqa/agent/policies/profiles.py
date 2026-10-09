from __future__ import annotations

from agentqa.contracts.policies import PolicyKind, PolicyProfile

LLM_POLICY_VERSION = "llm-policy/1-uncalibrated"
CASCADE_POLICY_VERSION = "jev-cascade/1-uncalibrated"

LLM_PROFILE = PolicyProfile(
    policy=PolicyKind.LLM,
    version=LLM_POLICY_VERSION,
    allow_degradation=False,
    confidence_min=0.6,
    max_steps=24,
    stuck_after=3,
)

CASCADE_PROFILE = PolicyProfile(
    policy=PolicyKind.JEV_CASCADE,
    version=CASCADE_POLICY_VERSION,
    allow_degradation=True,
    confidence_min=0.6,
    p_max_min=0.5,
    margin_min=0.2,
    progress_stop=0.9,
    max_steps=24,
    stuck_after=3,
)


def profile_for(policy: PolicyKind) -> PolicyProfile:
    if policy is PolicyKind.JEV_CASCADE:
        return CASCADE_PROFILE
    return LLM_PROFILE
