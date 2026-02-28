"""
Policy API Routes - REST API for policy management.

Provides endpoints for policy CRUD, templates, evaluation, and analytics.

Author: Dev Team Lead
Date: 2026-02-27
Built with Pride for Obex Blackvault
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import uuid

from backend.agents.compliance.policy_engine import (
    Policy,
    PolicyCondition,
    PolicyAction,
    PolicyStatus,
    ConditionType,
    ConditionOperator,
    ActionType,
    get_policy_manager,
)
from backend.agents.compliance.policy_evaluator import (
    EvaluationContext,
    get_policy_evaluator,
)
from backend.agents.registry.asset_registry import get_registry


router = APIRouter(prefix="/api/v1/policies", tags=["policies"])


# ============================================================================
# Request/Response Models
# ============================================================================


class PolicyConditionRequest(BaseModel):
    """Request model for policy condition."""

    condition_type: str
    operator: str
    field: str
    value: Any
    and_conditions: List["PolicyConditionRequest"] = []
    or_conditions: List["PolicyConditionRequest"] = []
    not_condition: Optional["PolicyConditionRequest"] = None


class PolicyActionRequest(BaseModel):
    """Request model for policy action."""

    action_type: str
    parameters: Dict[str, Any] = {}


class CreatePolicyRequest(BaseModel):
    """Request to create a policy."""

    name: str
    description: str
    conditions: List[PolicyConditionRequest]
    actions: List[PolicyActionRequest]
    applies_to: List[str] = []
    priority: int = 0
    created_by: str


class UpdatePolicyRequest(BaseModel):
    """Request to update a policy."""

    name: Optional[str] = None
    description: Optional[str] = None
    conditions: Optional[List[PolicyConditionRequest]] = None
    actions: Optional[List[PolicyActionRequest]] = None
    applies_to: Optional[List[str]] = None
    priority: Optional[int] = None
    updated_by: str


class CreateFromTemplateRequest(BaseModel):
    """Request to create policy from template."""

    template_id: str
    name: str
    description: Optional[str] = None
    applies_to: List[str] = []
    priority: int = 0
    created_by: str


class EvaluationContextRequest(BaseModel):
    """Request model for policy evaluation."""

    asset_id: str
    operation: str
    user_id: str
    user_role: str
    user_authority_level: int
    location: Optional[str] = None
    data_accessed: List[str] = []
    api_endpoints: List[str] = []
    metadata: Dict[str, Any] = {}


# ============================================================================
# Helper Functions
# ============================================================================


def _convert_condition_request(req: PolicyConditionRequest) -> PolicyCondition:
    """Convert request model to PolicyCondition."""
    return PolicyCondition(
        condition_type=ConditionType(req.condition_type),
        operator=ConditionOperator(req.operator),
        field=req.field,
        value=req.value,
        and_conditions=[_convert_condition_request(c) for c in req.and_conditions],
        or_conditions=[_convert_condition_request(c) for c in req.or_conditions],
        not_condition=(
            _convert_condition_request(req.not_condition) if req.not_condition else None
        ),
    )


def _convert_action_request(req: PolicyActionRequest) -> PolicyAction:
    """Convert request model to PolicyAction."""
    return PolicyAction(
        action_type=ActionType(req.action_type),
        parameters=req.parameters,
    )


# ============================================================================
# Policy Management Endpoints
# ============================================================================


@router.post("")
async def create_policy(request: CreatePolicyRequest) -> Dict[str, Any]:
    """Create a new policy."""
    manager = get_policy_manager()

    now = datetime.utcnow()
    policy = Policy(
        policy_id=f"policy-{uuid.uuid4().hex[:12]}",
        name=request.name,
        description=request.description,
        version="1.0",
        status=PolicyStatus.DRAFT,
        conditions=[_convert_condition_request(c) for c in request.conditions],
        actions=[_convert_action_request(a) for a in request.actions],
        created_at=now,
        created_by=request.created_by,
        updated_at=now,
        updated_by=request.created_by,
        applies_to=request.applies_to,
        priority=request.priority,
    )

    created = manager.create_policy(policy)
    return created.to_dict()


@router.get("")
async def list_policies(
    status: Optional[str] = Query(None, description="Filter by status"),
    applies_to: Optional[str] = Query(None, description="Filter by asset type"),
) -> Dict[str, Any]:
    """List policies with optional filters."""
    manager = get_policy_manager()

    policy_status = PolicyStatus(status) if status else None
    policies = manager.list_policies(status=policy_status, applies_to=applies_to)

    return {
        "total": len(policies),
        "policies": [p.to_dict() for p in policies],
    }


@router.get("/{policy_id}")
async def get_policy(policy_id: str) -> Dict[str, Any]:
    """Get policy by ID."""
    manager = get_policy_manager()

    policy = manager.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")

    return policy.to_dict()


@router.put("/{policy_id}")
async def update_policy(
    policy_id: str,
    request: UpdatePolicyRequest,
) -> Dict[str, Any]:
    """Update an existing policy."""
    manager = get_policy_manager()

    updates = {}
    if request.name is not None:
        updates["name"] = request.name
    if request.description is not None:
        updates["description"] = request.description
    if request.conditions is not None:
        updates["conditions"] = [_convert_condition_request(c) for c in request.conditions]
    if request.actions is not None:
        updates["actions"] = [_convert_action_request(a) for a in request.actions]
    if request.applies_to is not None:
        updates["applies_to"] = request.applies_to
    if request.priority is not None:
        updates["priority"] = request.priority

    try:
        updated = manager.update_policy(policy_id, request.updated_by, **updates)
        return updated.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{policy_id}")
async def delete_policy(
    policy_id: str,
    deleted_by: str = Query(..., description="User deleting the policy"),
) -> Dict[str, str]:
    """Delete a policy."""
    manager = get_policy_manager()

    try:
        manager.delete_policy(policy_id, deleted_by)
        return {"message": f"Policy {policy_id} deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{policy_id}/activate")
async def activate_policy(
    policy_id: str,
    activated_by: str = Query(..., description="User activating the policy"),
) -> Dict[str, Any]:
    """Activate a policy."""
    manager = get_policy_manager()

    try:
        policy = manager.activate_policy(policy_id, activated_by)

        # Clear evaluation cache when policy is activated
        evaluator = get_policy_evaluator()
        evaluator.clear_cache()

        return policy.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{policy_id}/deactivate")
async def deactivate_policy(
    policy_id: str,
    deactivated_by: str = Query(..., description="User deactivating the policy"),
) -> Dict[str, Any]:
    """Deactivate a policy."""
    manager = get_policy_manager()

    try:
        policy = manager.deactivate_policy(policy_id, deactivated_by)

        # Clear evaluation cache when policy is deactivated
        evaluator = get_policy_evaluator()
        evaluator.clear_cache()

        return policy.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{policy_id}/history")
async def get_policy_history(policy_id: str) -> Dict[str, Any]:
    """Get change history for a policy."""
    manager = get_policy_manager()

    # Check if policy exists
    policy = manager.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")

    history = manager.get_policy_history(policy_id)

    return {
        "policy_id": policy_id,
        "history": history,
    }


# ============================================================================
# Template Endpoints
# ============================================================================


@router.get("/templates")
async def list_templates(
    category: Optional[str] = Query(None, description="Filter by category"),
) -> Dict[str, Any]:
    """List policy templates."""
    manager = get_policy_manager()

    templates = manager.list_templates(category=category)

    return {
        "total": len(templates),
        "templates": [t.to_dict() for t in templates],
    }


@router.get("/templates/{template_id}")
async def get_template(template_id: str) -> Dict[str, Any]:
    """Get template by ID."""
    manager = get_policy_manager()

    template = manager.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    return template.to_dict()


@router.post("/from-template")
async def create_from_template(request: CreateFromTemplateRequest) -> Dict[str, Any]:
    """Create a policy from a template."""
    manager = get_policy_manager()

    try:
        policy = manager.create_from_template(
            request.template_id,
            request.name,
            request.created_by,
            description=request.description,
            applies_to=request.applies_to,
            priority=request.priority,
        )
        return policy.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================================================
# Evaluation Endpoints
# ============================================================================


@router.post("/evaluate")
async def evaluate_policies(request: EvaluationContextRequest) -> Dict[str, Any]:
    """Evaluate policies for a given context."""
    registry = get_registry()
    evaluator = get_policy_evaluator()

    # Get asset
    asset = registry.get(request.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {request.asset_id} not found")

    # Create evaluation context
    context = EvaluationContext(
        asset=asset,
        operation=request.operation,
        user_id=request.user_id,
        user_role=request.user_role,
        user_authority_level=request.user_authority_level,
        timestamp=datetime.utcnow(),
        location=request.location,
        data_accessed=request.data_accessed,
        api_endpoints=request.api_endpoints,
        metadata=request.metadata,
    )

    # Evaluate policies
    result = evaluator.evaluate(context)

    return result.to_dict()


@router.get("/applicable")
async def get_applicable_policies(
    asset_type: Optional[str] = Query(None, description="Asset type"),
) -> Dict[str, Any]:
    """Get all applicable policies for an asset type."""
    evaluator = get_policy_evaluator()

    policies = evaluator.get_applicable_policies(asset_type=asset_type)

    return {
        "total": len(policies),
        "policies": [p.to_dict() for p in policies],
    }


@router.post("/test")
async def test_policy(
    policy_id: str = Query(..., description="Policy ID to test"),
    context: EvaluationContextRequest = None,
) -> Dict[str, Any]:
    """Test a policy before activation."""
    manager = get_policy_manager()
    registry = get_registry()
    evaluator = get_policy_evaluator()

    # Get policy
    policy = manager.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")

    # Get asset
    asset = registry.get(context.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {context.asset_id} not found")

    # Create evaluation context
    eval_context = EvaluationContext(
        asset=asset,
        operation=context.operation,
        user_id=context.user_id,
        user_role=context.user_role,
        user_authority_level=context.user_authority_level,
        timestamp=datetime.utcnow(),
        location=context.location,
        data_accessed=context.data_accessed,
        api_endpoints=context.api_endpoints,
        metadata=context.metadata,
    )

    # Test policy
    result = evaluator.test_policy(policy, eval_context)

    return result.to_dict()


# ============================================================================
# Analytics Endpoints
# ============================================================================


@router.get("/stats")
async def get_policy_stats() -> Dict[str, Any]:
    """Get policy statistics."""
    manager = get_policy_manager()

    all_policies = manager.list_policies()

    stats = {
        "total_policies": len(all_policies),
        "by_status": {},
        "by_priority": {},
        "total_enforcements": 0,
        "most_enforced": [],
    }

    # Count by status
    for status in PolicyStatus:
        count = len([p for p in all_policies if p.status == status])
        stats["by_status"][status.value] = count

    # Count by priority
    priorities = {}
    for policy in all_policies:
        priorities[policy.priority] = priorities.get(policy.priority, 0) + 1
    stats["by_priority"] = priorities

    # Total enforcements
    stats["total_enforcements"] = sum(p.enforcement_count for p in all_policies)

    # Most enforced policies
    sorted_policies = sorted(all_policies, key=lambda p: p.enforcement_count, reverse=True)
    stats["most_enforced"] = [
        {
            "policy_id": p.policy_id,
            "name": p.name,
            "enforcement_count": p.enforcement_count,
        }
        for p in sorted_policies[:5]
    ]

    return stats


@router.get("/{policy_id}/enforcement")
async def get_enforcement_history(policy_id: str) -> Dict[str, Any]:
    """Get enforcement history for a policy."""
    manager = get_policy_manager()

    policy = manager.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")

    return {
        "policy_id": policy_id,
        "name": policy.name,
        "enforcement_count": policy.enforcement_count,
        "last_enforced_at": (
            policy.last_enforced_at.isoformat() if policy.last_enforced_at else None
        ),
    }


@router.get("/conflicts")
async def detect_policy_conflicts() -> Dict[str, Any]:
    """Detect potential policy conflicts."""
    manager = get_policy_manager()

    active_policies = manager.list_policies(status=PolicyStatus.ACTIVE)

    conflicts = []

    # Check for conflicting policies (same applies_to, different actions)
    for i, policy1 in enumerate(active_policies):
        for policy2 in active_policies[i + 1 :]:
            # Check if they apply to same asset types
            if policy1.applies_to == policy2.applies_to:
                # Check if they have conflicting actions
                has_deny_1 = any(a.action_type == ActionType.DENY for a in policy1.actions)
                has_allow_1 = any(a.action_type == ActionType.ALLOW for a in policy1.actions)
                has_deny_2 = any(a.action_type == ActionType.DENY for a in policy2.actions)
                has_allow_2 = any(a.action_type == ActionType.ALLOW for a in policy2.actions)

                if (has_deny_1 and has_allow_2) or (has_allow_1 and has_deny_2):
                    conflicts.append(
                        {
                            "policy_1": {
                                "id": policy1.policy_id,
                                "name": policy1.name,
                                "priority": policy1.priority,
                            },
                            "policy_2": {
                                "id": policy2.policy_id,
                                "name": policy2.name,
                                "priority": policy2.priority,
                            },
                            "conflict_type": "deny_allow_conflict",
                            "resolution": f"Policy with higher priority wins (currently: {policy1.name if policy1.priority > policy2.priority else policy2.name})",  # noqa: E501
                        }
                    )

    return {
        "total_conflicts": len(conflicts),
        "conflicts": conflicts,
    }
