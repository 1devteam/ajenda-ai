"""
Compliance reporting API endpoints.

Provides REST API for compliance reporting and analytics:
- GET /api/v1/compliance/reports/summary - Overall compliance summary
- GET /api/v1/compliance/reports/agent/{agent_id} - Agent-specific report
- GET /api/v1/compliance/reports/violations - List compliance violations
- GET /api/v1/compliance/reports/trends - Compliance trends over time
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict

from backend.agents.compliance.engine import ComplianceEngine
from backend.agents.compliance.approval import get_approval_store, ApprovalStatus

router = APIRouter(prefix="/api/v1/compliance/reports", tags=["compliance"])


# Response Models

class ComplianceSummary(BaseModel):
    """Overall compliance summary"""
    total_checks: int = Field(..., description="Total compliance checks performed")
    allowed: int = Field(..., description="Number of checks that allowed the action")
    blocked: int = Field(..., description="Number of checks that blocked the action")
    approval_rate: float = Field(..., description="Percentage of checks that allowed action")
    block_rate: float = Field(..., description="Percentage of checks that blocked action")
    top_blocking_rules: List[Dict[str, Any]] = Field(..., description="Most frequently blocking rules")
    top_agents: List[Dict[str, Any]] = Field(..., description="Agents with most compliance checks")
    top_tools: List[Dict[str, Any]] = Field(..., description="Tools with most compliance checks")


class AgentComplianceReport(BaseModel):
    """Agent-specific compliance report"""
    agent_id: str
    agent_type: str
    total_checks: int
    allowed: int
    blocked: int
    approval_rate: float
    violations: List[Dict[str, Any]]
    tool_usage: Dict[str, int]


class ComplianceViolation(BaseModel):
    """Compliance violation record"""
    timestamp: str
    agent_id: str
    agent_type: str
    tool_name: str
    rule: str
    reason: str
    parameters: Dict[str, Any]


class ComplianceTrends(BaseModel):
    """Compliance trends over time"""
    period: str = Field(..., description="Time period (hour, day, week)")
    data_points: List[Dict[str, Any]] = Field(..., description="Trend data points")


# In-memory compliance log (for demo purposes)
# In production, use database or time-series database
_compliance_log: List[Dict[str, Any]] = []


def log_compliance_check(
    agent_id: str,
    agent_type: str,
    tool_name: str,
    allowed: bool,
    blocking_rule: Optional[str] = None,
    reason: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None
) -> None:
    """
    Log compliance check for reporting.
    
    Args:
        agent_id: Agent ID
        agent_type: Agent type
        tool_name: Tool name
        allowed: Whether action was allowed
        blocking_rule: Rule that blocked action (if blocked)
        reason: Reason for blocking (if blocked)
        parameters: Tool parameters
    """
    _compliance_log.append({
        "timestamp": datetime.utcnow(),
        "agent_id": agent_id,
        "agent_type": agent_type,
        "tool_name": tool_name,
        "allowed": allowed,
        "blocking_rule": blocking_rule,
        "reason": reason,
        "parameters": parameters or {}
    })


# API Endpoints

@router.get("/summary", response_model=ComplianceSummary)
async def get_compliance_summary(
    hours: int = Query(24, ge=1, le=168, description="Time window in hours")
):
    """
    Get overall compliance summary.
    
    Args:
        hours: Time window in hours (default: 24)
    
    Returns:
        Compliance summary
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    recent_logs = [log for log in _compliance_log if log["timestamp"] >= cutoff]
    
    if not recent_logs:
        return ComplianceSummary(
            total_checks=0,
            allowed=0,
            blocked=0,
            approval_rate=0.0,
            block_rate=0.0,
            top_blocking_rules=[],
            top_agents=[],
            top_tools=[]
        )
    
    total_checks = len(recent_logs)
    allowed = sum(1 for log in recent_logs if log["allowed"])
    blocked = total_checks - allowed
    
    # Calculate rates
    approval_rate = (allowed / total_checks * 100) if total_checks > 0 else 0.0
    block_rate = (blocked / total_checks * 100) if total_checks > 0 else 0.0
    
    # Top blocking rules
    rule_counts = defaultdict(int)
    for log in recent_logs:
        if not log["allowed"] and log["blocking_rule"]:
            rule_counts[log["blocking_rule"]] += 1
    
    top_blocking_rules = [
        {"rule": rule, "count": count}
        for rule, count in sorted(rule_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]
    
    # Top agents
    agent_counts = defaultdict(int)
    for log in recent_logs:
        agent_counts[log["agent_id"]] += 1
    
    top_agents = [
        {"agent_id": agent_id, "checks": count}
        for agent_id, count in sorted(agent_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]
    
    # Top tools
    tool_counts = defaultdict(int)
    for log in recent_logs:
        tool_counts[log["tool_name"]] += 1
    
    top_tools = [
        {"tool": tool, "checks": count}
        for tool, count in sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]
    
    return ComplianceSummary(
        total_checks=total_checks,
        allowed=allowed,
        blocked=blocked,
        approval_rate=round(approval_rate, 2),
        block_rate=round(block_rate, 2),
        top_blocking_rules=top_blocking_rules,
        top_agents=top_agents,
        top_tools=top_tools
    )


@router.get("/agent/{agent_id}", response_model=AgentComplianceReport)
async def get_agent_compliance_report(
    agent_id: str,
    hours: int = Query(24, ge=1, le=168, description="Time window in hours")
):
    """
    Get agent-specific compliance report.
    
    Args:
        agent_id: Agent ID
        hours: Time window in hours
    
    Returns:
        Agent compliance report
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    agent_logs = [
        log for log in _compliance_log
        if log["agent_id"] == agent_id and log["timestamp"] >= cutoff
    ]
    
    if not agent_logs:
        raise HTTPException(status_code=404, detail="No compliance data found for agent")
    
    total_checks = len(agent_logs)
    allowed = sum(1 for log in agent_logs if log["allowed"])
    blocked = total_checks - allowed
    approval_rate = (allowed / total_checks * 100) if total_checks > 0 else 0.0
    
    # Get violations
    violations = [
        {
            "timestamp": log["timestamp"].isoformat(),
            "tool_name": log["tool_name"],
            "rule": log["blocking_rule"],
            "reason": log["reason"]
        }
        for log in agent_logs if not log["allowed"]
    ]
    
    # Tool usage
    tool_usage = defaultdict(int)
    for log in agent_logs:
        tool_usage[log["tool_name"]] += 1
    
    return AgentComplianceReport(
        agent_id=agent_id,
        agent_type=agent_logs[0]["agent_type"],
        total_checks=total_checks,
        allowed=allowed,
        blocked=blocked,
        approval_rate=round(approval_rate, 2),
        violations=violations,
        tool_usage=dict(tool_usage)
    )


@router.get("/violations", response_model=List[ComplianceViolation])
async def list_compliance_violations(
    hours: int = Query(24, ge=1, le=168, description="Time window in hours"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    rule: Optional[str] = Query(None, description="Filter by rule"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of violations")
):
    """
    List compliance violations.
    
    Args:
        hours: Time window in hours
        agent_id: Optional agent ID filter
        rule: Optional rule filter
        limit: Maximum number of violations
    
    Returns:
        List of compliance violations
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    violations = [
        log for log in _compliance_log
        if not log["allowed"] and log["timestamp"] >= cutoff
    ]
    
    # Apply filters
    if agent_id:
        violations = [v for v in violations if v["agent_id"] == agent_id]
    
    if rule:
        violations = [v for v in violations if v["blocking_rule"] == rule]
    
    # Sort by timestamp (newest first)
    violations.sort(key=lambda v: v["timestamp"], reverse=True)
    
    # Limit results
    violations = violations[:limit]
    
    return [
        ComplianceViolation(
            timestamp=v["timestamp"].isoformat(),
            agent_id=v["agent_id"],
            agent_type=v["agent_type"],
            tool_name=v["tool_name"],
            rule=v["blocking_rule"] or "unknown",
            reason=v["reason"] or "No reason provided",
            parameters=v["parameters"]
        )
        for v in violations
    ]


@router.get("/trends", response_model=ComplianceTrends)
async def get_compliance_trends(
    period: str = Query("hour", description="Time period (hour, day, week)"),
    hours: int = Query(24, ge=1, le=168, description="Time window in hours")
):
    """
    Get compliance trends over time.
    
    Args:
        period: Time period for grouping (hour, day, week)
        hours: Time window in hours
    
    Returns:
        Compliance trends
    """
    if period not in ["hour", "day", "week"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid period. Valid values: hour, day, week"
        )
    
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    recent_logs = [log for log in _compliance_log if log["timestamp"] >= cutoff]
    
    # Group by period
    period_data = defaultdict(lambda: {"allowed": 0, "blocked": 0})
    
    for log in recent_logs:
        # Determine period key
        if period == "hour":
            key = log["timestamp"].strftime("%Y-%m-%d %H:00")
        elif period == "day":
            key = log["timestamp"].strftime("%Y-%m-%d")
        else:  # week
            # Get week number
            week_start = log["timestamp"] - timedelta(days=log["timestamp"].weekday())
            key = week_start.strftime("%Y-W%U")
        
        if log["allowed"]:
            period_data[key]["allowed"] += 1
        else:
            period_data[key]["blocked"] += 1
    
    # Convert to list of data points
    data_points = [
        {
            "period": key,
            "allowed": data["allowed"],
            "blocked": data["blocked"],
            "total": data["allowed"] + data["blocked"]
        }
        for key, data in sorted(period_data.items())
    ]
    
    return ComplianceTrends(
        period=period,
        data_points=data_points
    )


@router.get("/approvals/stats")
async def get_approval_stats():
    """
    Get approval workflow statistics.
    
    Returns:
        Approval statistics
    """
    store = get_approval_store()
    
    all_requests = store.list(limit=10000)
    
    if not all_requests:
        return {
            "total_requests": 0,
            "pending": 0,
            "approved": 0,
            "rejected": 0,
            "expired": 0,
            "cancelled": 0,
            "approval_rate": 0.0,
            "avg_response_time_seconds": 0.0
        }
    
    # Count by status
    status_counts = defaultdict(int)
    for req in all_requests:
        status_counts[req.status.value] += 1
    
    # Calculate approval rate (approved / (approved + rejected))
    approved = status_counts["approved"]
    rejected = status_counts["rejected"]
    total_resolved = approved + rejected
    approval_rate = (approved / total_resolved * 100) if total_resolved > 0 else 0.0
    
    # Calculate average response time
    response_times = []
    for req in all_requests:
        if req.approved_at:
            response_time = (req.approved_at - req.requested_at).total_seconds()
            response_times.append(response_time)
    
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0.0
    
    return {
        "total_requests": len(all_requests),
        "pending": status_counts["pending"],
        "approved": status_counts["approved"],
        "rejected": status_counts["rejected"],
        "expired": status_counts["expired"],
        "cancelled": status_counts["cancelled"],
        "approval_rate": round(approval_rate, 2),
        "avg_response_time_seconds": round(avg_response_time, 2)
    }
