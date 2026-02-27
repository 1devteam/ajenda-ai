"""
Audit API - REST endpoints for audit, compliance, and alerts.

Provides 15 endpoints for audit events, compliance checks, and alert management.

Author: Dev Team Lead
Date: 2026-02-27
Built with Pride for Obex Blackvault
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

from backend.agents.compliance.audit_monitor import (
    get_audit_monitor,
    AuditEvent,
    AuditEventType,
    EventResult,
    Anomaly,
)
from backend.agents.compliance.compliance_checker import (
    get_compliance_checker,
    ComplianceCheck,
    ComplianceCheckType,
    CheckStatus,
)
from backend.agents.compliance.alert_manager import (
    get_alert_manager,
    Alert,
    AlertType,
    AlertSeverity,
    AlertStatus,
)


router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


# ============================================================================
# Request/Response Models
# ============================================================================

class AuditEventResponse(BaseModel):
    """Audit event response."""
    event_id: str
    event_type: str
    timestamp: str
    actor: str
    action: str
    result: str
    asset_id: Optional[str]
    policy_ids: List[str]
    metadata: Dict[str, Any]
    context: Dict[str, Any]


class AnomalyResponse(BaseModel):
    """Anomaly response."""
    anomaly_id: str
    anomaly_type: str
    detected_at: str
    description: str
    severity: str
    affected_events: List[str]
    affected_assets: List[str]
    affected_users: List[str]
    metadata: Dict[str, Any]


class ComplianceCheckResponse(BaseModel):
    """Compliance check response."""
    check_id: str
    check_type: str
    status: str
    timestamp: str
    findings: List[Dict[str, Any]]
    recommendations: List[str]
    score: float
    metadata: Dict[str, Any]


class AlertResponse(BaseModel):
    """Alert response."""
    alert_id: str
    alert_type: str
    severity: str
    timestamp: str
    title: str
    description: str
    affected_assets: List[str]
    recipients: List[str]
    status: str
    acknowledged_by: Optional[str]
    acknowledged_at: Optional[str]
    resolved_by: Optional[str]
    resolved_at: Optional[str]
    resolution: Optional[str]
    metadata: Dict[str, Any]


class RunCheckRequest(BaseModel):
    """Request to run compliance check."""
    check_type: str = Field(..., description="Type of check to run")


class AcknowledgeAlertRequest(BaseModel):
    """Request to acknowledge alert."""
    user: str = Field(..., description="User acknowledging")


class ResolveAlertRequest(BaseModel):
    """Request to resolve alert."""
    user: str = Field(..., description="User resolving")
    resolution: str = Field(..., description="Resolution description")


# ============================================================================
# Audit Events Endpoints (5)
# ============================================================================

@router.get("/events", response_model=List[AuditEventResponse])
async def list_audit_events(
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    actor: Optional[str] = Query(None, description="Filter by actor"),
    asset_id: Optional[str] = Query(None, description="Filter by asset"),
    result: Optional[str] = Query(None, description="Filter by result"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of events"),
):
    """
    List audit events with optional filters.
    
    Returns recent audit events sorted by timestamp (newest first).
    """
    monitor = get_audit_monitor()
    
    # Convert string enums
    event_type_enum = AuditEventType(event_type) if event_type else None
    result_enum = EventResult(result) if result else None
    
    events = monitor.get_events(
        event_type=event_type_enum,
        actor=actor,
        asset_id=asset_id,
        result=result_enum,
        limit=limit,
    )
    
    return [AuditEventResponse(**e.to_dict()) for e in events]


@router.get("/events/{event_id}", response_model=AuditEventResponse)
async def get_audit_event(event_id: str):
    """
    Get audit event by ID.
    
    Returns detailed information about a specific audit event.
    """
    monitor = get_audit_monitor()
    event = monitor.get_event(event_id)
    
    if not event:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    
    return AuditEventResponse(**event.to_dict())


@router.get("/trail/{asset_id}", response_model=List[AuditEventResponse])
async def get_audit_trail(asset_id: str):
    """
    Get complete audit trail for an asset.
    
    Returns all events related to an asset, sorted chronologically.
    """
    monitor = get_audit_monitor()
    events = monitor.get_audit_trail(asset_id)
    
    return [AuditEventResponse(**e.to_dict()) for e in events]


@router.get("/anomalies", response_model=List[AnomalyResponse])
async def get_anomalies():
    """
    Get detected anomalies.
    
    Returns all anomalies detected by the audit monitor.
    """
    monitor = get_audit_monitor()
    anomalies = monitor.detect_anomalies()
    
    return [AnomalyResponse(**a.to_dict()) for a in anomalies]


@router.post("/export")
async def export_audit_data(
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
):
    """
    Export audit data.
    
    Returns audit data in exportable format (JSON).
    In production, this would support CSV, PDF, etc.
    """
    monitor = get_audit_monitor()
    
    # Parse dates
    start_time = datetime.fromisoformat(start_date) if start_date else None
    end_time = datetime.fromisoformat(end_date) if end_date else None
    event_type_enum = AuditEventType(event_type) if event_type else None
    
    events = monitor.get_events(
        event_type=event_type_enum,
        start_time=start_time,
        end_time=end_time,
        limit=10000,
    )
    
    return {
        "export_date": datetime.utcnow().isoformat(),
        "start_date": start_date,
        "end_date": end_date,
        "event_count": len(events),
        "events": [e.to_dict() for e in events],
    }


# ============================================================================
# Compliance Checks Endpoints (5)
# ============================================================================

@router.post("/checks/run", response_model=ComplianceCheckResponse)
async def run_compliance_check(request: RunCheckRequest):
    """
    Run a compliance check.
    
    Executes an automated compliance check and returns results.
    """
    checker = get_compliance_checker()
    
    try:
        check_type = ComplianceCheckType(request.check_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid check type: {request.check_type}",
        )
    
    check = checker.run_check(check_type)
    return ComplianceCheckResponse(**check.to_dict())


@router.get("/checks", response_model=List[ComplianceCheckResponse])
async def list_compliance_checks(
    check_type: Optional[str] = Query(None, description="Filter by check type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of checks"),
):
    """
    List compliance check results.
    
    Returns recent compliance checks sorted by timestamp.
    """
    checker = get_compliance_checker()
    
    # Convert string enums
    check_type_enum = ComplianceCheckType(check_type) if check_type else None
    status_enum = CheckStatus(status) if status else None
    
    checks = checker.list_checks(
        check_type=check_type_enum,
        status=status_enum,
        limit=limit,
    )
    
    return [ComplianceCheckResponse(**c.to_dict()) for c in checks]


@router.get("/checks/{check_id}", response_model=ComplianceCheckResponse)
async def get_compliance_check(check_id: str):
    """
    Get compliance check by ID.
    
    Returns detailed results of a specific compliance check.
    """
    checker = get_compliance_checker()
    check = checker.get_check(check_id)
    
    if not check:
        raise HTTPException(status_code=404, detail=f"Check {check_id} not found")
    
    return ComplianceCheckResponse(**check.to_dict())


@router.get("/compliance-score")
async def get_compliance_score():
    """
    Get overall compliance score.
    
    Returns aggregate compliance score (0-100) based on recent checks.
    """
    checker = get_compliance_checker()
    score = checker.get_compliance_score()
    
    return {
        "score": score,
        "timestamp": datetime.utcnow().isoformat(),
        "status": "compliant" if score >= 80 else "non_compliant" if score < 60 else "warning",
    }


@router.get("/violations")
async def get_violations():
    """
    Get active compliance violations.
    
    Returns all findings with CRITICAL or HIGH severity.
    """
    checker = get_compliance_checker()
    violations = checker.get_violations()
    
    return {
        "violation_count": len(violations),
        "violations": [v.to_dict() for v in violations],
        "timestamp": datetime.utcnow().isoformat(),
    }


# ============================================================================
# Alerts Endpoints (5)
# ============================================================================

@router.get("/alerts", response_model=List[AlertResponse])
async def list_alerts(
    alert_type: Optional[str] = Query(None, description="Filter by alert type"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of alerts"),
):
    """
    List alerts with optional filters.
    
    Returns recent alerts sorted by timestamp.
    """
    manager = get_alert_manager()
    
    # Convert string enums
    alert_type_enum = AlertType(alert_type) if alert_type else None
    severity_enum = AlertSeverity(severity) if severity else None
    status_enum = AlertStatus(status) if status else None
    
    alerts = manager.list_alerts(
        alert_type=alert_type_enum,
        severity=severity_enum,
        status=status_enum,
        limit=limit,
    )
    
    return [AlertResponse(**a.to_dict()) for a in alerts]


@router.get("/alerts/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: str):
    """
    Get alert by ID.
    
    Returns detailed information about a specific alert.
    """
    manager = get_alert_manager()
    alert = manager.get_alert(alert_id)
    
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    
    return AlertResponse(**alert.to_dict())


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, request: AcknowledgeAlertRequest):
    """
    Acknowledge an alert.
    
    Marks an alert as acknowledged by a user.
    """
    manager = get_alert_manager()
    success = manager.acknowledge_alert(alert_id, request.user)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    
    return {"status": "acknowledged", "alert_id": alert_id, "user": request.user}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str, request: ResolveAlertRequest):
    """
    Resolve an alert.
    
    Marks an alert as resolved with resolution description.
    """
    manager = get_alert_manager()
    success = manager.resolve_alert(alert_id, request.user, request.resolution)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    
    return {
        "status": "resolved",
        "alert_id": alert_id,
        "user": request.user,
        "resolution": request.resolution,
    }


@router.get("/alerts/active")
async def get_active_alerts():
    """
    Get active (unresolved) alerts.
    
    Returns all alerts that haven't been resolved.
    """
    manager = get_alert_manager()
    alerts = manager.get_active_alerts()
    
    return {
        "active_count": len(alerts),
        "alerts": [AlertResponse(**a.to_dict()) for a in alerts],
        "timestamp": datetime.utcnow().isoformat(),
    }
