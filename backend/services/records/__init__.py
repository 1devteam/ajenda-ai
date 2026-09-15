"""Ajenda Records kernel contracts.

CRM identity, effect receipts, and reconciliation live here so the kernel
does not import the vertical pack.
"""

from backend.services.records.contracts import (
    EffectCertainty,
    EffectReceiptContract,
    IdentityDecisionStatus,
    IdentityMatchDecision,
)
from backend.services.records.crm_reconciliation import (
    CanonicalCRMDesiredState,
    CRMLifecycleState,
    CRMOperationKind,
    CRMProviderObservation,
    CRMReconciliationPlan,
    plan_crm_reconciliation,
)

__all__ = [
    "CanonicalCRMDesiredState",
    "CRMLifecycleState",
    "CRMOperationKind",
    "CRMProviderObservation",
    "CRMReconciliationPlan",
    "EffectCertainty",
    "EffectReceiptContract",
    "IdentityDecisionStatus",
    "IdentityMatchDecision",
    "plan_crm_reconciliation",
]
