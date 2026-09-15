"""Compatibility shim. Canonical CRM reconciliation lives in backend.services.records."""

from backend.services.records.crm_reconciliation import (
    ALLOWED_LIFECYCLE_TRANSITIONS,
    CanonicalCRMDesiredState,
    CRMLifecycleState,
    CRMOperationKind,
    CRMProviderObservation,
    CRMReconciliationOperation,
    CRMReconciliationPlan,
    plan_crm_reconciliation,
    validate_lifecycle_transition,
)

__all__ = [
    "ALLOWED_LIFECYCLE_TRANSITIONS",
    "CanonicalCRMDesiredState",
    "CRMLifecycleState",
    "CRMOperationKind",
    "CRMProviderObservation",
    "CRMReconciliationOperation",
    "CRMReconciliationPlan",
    "plan_crm_reconciliation",
    "validate_lifecycle_transition",
]
