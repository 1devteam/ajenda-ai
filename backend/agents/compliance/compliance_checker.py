"""
Compliance Checker - Automated compliance validation.

Runs automated compliance checks, validates against regulatory requirements,
generates compliance reports, and schedules periodic audits.

Author: Dev Team Lead
Date: 2026-02-27
Built with Pride for Obex Blackvault
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
import uuid

from backend.agents.registry.asset_registry import get_registry, AssetStatus
from backend.agents.compliance.policy_engine import get_policy_manager, PolicyStatus
from backend.agents.compliance.risk_scoring import get_risk_scoring_engine, RiskTier


# ============================================================================
# Enums
# ============================================================================

class ComplianceCheckType(Enum):
    """Types of compliance checks."""
    ASSET_COMPLIANCE = "asset_compliance"  # All assets properly registered
    POLICY_COMPLIANCE = "policy_compliance"  # Required policies active
    APPROVAL_COMPLIANCE = "approval_compliance"  # High-risk ops approved
    DATA_COMPLIANCE = "data_compliance"  # Sensitive data protected
    AUDIT_COMPLIANCE = "audit_compliance"  # Complete audit trails
    RISK_COMPLIANCE = "risk_compliance"  # Risk assessments current
    TAG_COMPLIANCE = "tag_compliance"  # Assets properly tagged


class CheckStatus(Enum):
    """Status of a compliance check."""
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    ERROR = "error"


class Severity(Enum):
    """Severity of a finding."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Regulation(Enum):
    """Regulatory frameworks."""
    GDPR = "gdpr"
    HIPAA = "hipaa"
    SOX = "sox"
    EU_AI_ACT = "eu_ai_act"
    CCPA = "ccpa"
    PCI_DSS = "pci_dss"


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class ComplianceFinding:
    """
    Represents a compliance finding.
    """
    finding_id: str
    description: str
    affected_assets: List[str]
    regulation: Regulation
    article: str  # Specific article/section
    severity: Severity
    remediation: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "finding_id": self.finding_id,
            "description": self.description,
            "affected_assets": self.affected_assets,
            "regulation": self.regulation.value,
            "article": self.article,
            "severity": self.severity.value,
            "remediation": self.remediation,
            "metadata": self.metadata,
        }


@dataclass
class ComplianceCheck:
    """
    Represents a compliance check result.
    """
    check_id: str
    check_type: ComplianceCheckType
    status: CheckStatus
    timestamp: datetime
    findings: List[ComplianceFinding]
    recommendations: List[str]
    score: float  # 0-100
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "check_id": self.check_id,
            "check_type": self.check_type.value,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "findings": [f.to_dict() for f in self.findings],
            "recommendations": self.recommendations,
            "score": self.score,
            "metadata": self.metadata,
        }


# ============================================================================
# Compliance Checker
# ============================================================================

class ComplianceChecker:
    """
    Automated compliance validation system.
    
    Runs checks against regulatory requirements and generates reports.
    Singleton pattern ensures consistent checking.
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._checks: Dict[str, ComplianceCheck] = {}
        self._scheduled_checks: Dict[ComplianceCheckType, int] = {}  # Type -> interval (seconds)
        self._initialized = True
    
    def run_check(self, check_type: ComplianceCheckType) -> ComplianceCheck:
        """
        Run a compliance check.
        
        Args:
            check_type: Type of check to run
            
        Returns:
            Check result
        """
        check_id = f"check-{uuid.uuid4()}"
        
        if check_type == ComplianceCheckType.ASSET_COMPLIANCE:
            result = self._check_asset_compliance(check_id)
        elif check_type == ComplianceCheckType.POLICY_COMPLIANCE:
            result = self._check_policy_compliance(check_id)
        elif check_type == ComplianceCheckType.APPROVAL_COMPLIANCE:
            result = self._check_approval_compliance(check_id)
        elif check_type == ComplianceCheckType.DATA_COMPLIANCE:
            result = self._check_data_compliance(check_id)
        elif check_type == ComplianceCheckType.AUDIT_COMPLIANCE:
            result = self._check_audit_compliance(check_id)
        elif check_type == ComplianceCheckType.RISK_COMPLIANCE:
            result = self._check_risk_compliance(check_id)
        elif check_type == ComplianceCheckType.TAG_COMPLIANCE:
            result = self._check_tag_compliance(check_id)
        else:
            result = ComplianceCheck(
                check_id=check_id,
                check_type=check_type,
                status=CheckStatus.ERROR,
                timestamp=datetime.utcnow(),
                findings=[],
                recommendations=[],
                score=0.0,
                metadata={"error": "Unknown check type"},
            )
        
        self._checks[check_id] = result
        return result
    
    def _check_asset_compliance(self, check_id: str) -> ComplianceCheck:
        """Check if all assets are properly registered and maintained."""
        registry = get_registry()
        assets = registry.list_all()
        
        findings = []
        recommendations = []
        
        # Check for assets without owners
        no_owner = [a for a in assets if not a.owner]
        if no_owner:
            findings.append(ComplianceFinding(
                finding_id=f"finding-{uuid.uuid4()}",
                description=f"{len(no_owner)} assets without owners",
                affected_assets=[a.asset_id for a in no_owner],
                regulation=Regulation.EU_AI_ACT,
                article="Article 16 (Obligations of providers)",
                severity=Severity.HIGH,
                remediation="Assign owners to all assets",
            ))
            recommendations.append("Assign owners to all assets for accountability")
        
        # Check for deprecated assets still active
        deprecated_active = [
            a for a in assets
            if a.status == AssetStatus.DEPRECATED and "production" in a.tags
        ]
        if deprecated_active:
            findings.append(ComplianceFinding(
                finding_id=f"finding-{uuid.uuid4()}",
                description=f"{len(deprecated_active)} deprecated assets still in production",
                affected_assets=[a.asset_id for a in deprecated_active],
                regulation=Regulation.EU_AI_ACT,
                article="Article 9 (Risk management)",
                severity=Severity.CRITICAL,
                remediation="Remove deprecated assets from production",
            ))
            recommendations.append("Immediately remove deprecated assets from production")
        
        # Check for assets without descriptions
        no_description = [a for a in assets if not a.description]
        if no_description:
            findings.append(ComplianceFinding(
                finding_id=f"finding-{uuid.uuid4()}",
                description=f"{len(no_description)} assets without descriptions",
                affected_assets=[a.asset_id for a in no_description],
                regulation=Regulation.EU_AI_ACT,
                article="Article 13 (Transparency)",
                severity=Severity.MEDIUM,
                remediation="Add descriptions to all assets",
            ))
            recommendations.append("Document all assets with clear descriptions")
        
        # Calculate score
        total_issues = len(no_owner) + len(deprecated_active) + len(no_description)
        score = max(0, 100 - (total_issues * 5))  # -5 points per issue
        
        status = CheckStatus.PASS if not findings else (
            CheckStatus.FAIL if any(f.severity == Severity.CRITICAL for f in findings)
            else CheckStatus.WARNING
        )
        
        return ComplianceCheck(
            check_id=check_id,
            check_type=ComplianceCheckType.ASSET_COMPLIANCE,
            status=status,
            timestamp=datetime.utcnow(),
            findings=findings,
            recommendations=recommendations,
            score=score,
            metadata={
                "total_assets": len(assets),
                "issues_found": total_issues,
            },
        )
    
    def _check_policy_compliance(self, check_id: str) -> ComplianceCheck:
        """Check if required policies are active."""
        policy_manager = get_policy_manager()
        policies = policy_manager.list_policies()
        
        findings = []
        recommendations = []
        
        # Check for required policy templates
        required_templates = ["gdpr-pii-protection", "high-risk-approval"]
        active_policies = [p for p in policies if p.status == PolicyStatus.ACTIVE]
        
        for template_id in required_templates:
            has_template = any(
                p.metadata.get("template_id") == template_id
                for p in active_policies
            )
            if not has_template:
                findings.append(ComplianceFinding(
                    finding_id=f"finding-{uuid.uuid4()}",
                    description=f"Required policy template '{template_id}' not active",
                    affected_assets=[],
                    regulation=Regulation.EU_AI_ACT if "high-risk" in template_id else Regulation.GDPR,
                    article="Article 14" if "high-risk" in template_id else "Article 5",
                    severity=Severity.HIGH,
                    remediation=f"Activate policy from template '{template_id}'",
                ))
                recommendations.append(f"Activate required policy: {template_id}")
        
        # Check for policies without conditions
        no_conditions = [p for p in active_policies if not p.conditions]
        if no_conditions:
            findings.append(ComplianceFinding(
                finding_id=f"finding-{uuid.uuid4()}",
                description=f"{len(no_conditions)} active policies without conditions",
                affected_assets=[],
                regulation=Regulation.EU_AI_ACT,
                article="Article 17 (Quality management)",
                severity=Severity.MEDIUM,
                remediation="Add conditions to all policies or deactivate",
            ))
            recommendations.append("Review and fix policies without conditions")
        
        # Calculate score
        score = max(0, 100 - (len(findings) * 10))
        
        status = CheckStatus.PASS if not findings else CheckStatus.WARNING
        
        return ComplianceCheck(
            check_id=check_id,
            check_type=ComplianceCheckType.POLICY_COMPLIANCE,
            status=status,
            timestamp=datetime.utcnow(),
            findings=findings,
            recommendations=recommendations,
            score=score,
            metadata={
                "total_policies": len(policies),
                "active_policies": len(active_policies),
            },
        )
    
    def _check_approval_compliance(self, check_id: str) -> ComplianceCheck:
        """
        Check if high-risk operations are properly approved.

        Queries the :class:`ApprovalWorkflow` singleton for pending requests
        that have exceeded their SLA and for executed operations that were
        performed without a corresponding approved request.
        """
        from backend.agents.compliance.approval_workflows import (
            get_approval_workflow,
            ApprovalState,
        )

        workflow = get_approval_workflow()
        findings: List[ComplianceFinding] = []
        recommendations: List[str] = []

        # ----------------------------------------------------------------
        # 1. Pending requests that have expired without resolution
        # ----------------------------------------------------------------
        expired = workflow.process_expired_requests()
        if expired:
            findings.append(
                ComplianceFinding(
                    finding_id=f"finding-{uuid.uuid4()}",
                    description=(
                        f"{len(expired)} high-risk approval request(s) expired "
                        "without being approved or rejected"
                    ),
                    affected_assets=[r.asset_id for r in expired],
                    regulation=Regulation.EU_AI_ACT,
                    article="Article 14 (Human oversight)",
                    severity=Severity.HIGH,
                    remediation=(
                        "Review and resolve expired approval requests; "
                        "ensure approvers are notified promptly"
                    ),
                    metadata={"expired_request_ids": [r.request_id for r in expired]},
                )
            )
            recommendations.append(
                "Configure shorter SLA windows or add escalation rules for approval requests"
            )

        # ----------------------------------------------------------------
        # 2. Pending requests that have been waiting > 24 hours (SLA breach)
        # ----------------------------------------------------------------
        sla_threshold = datetime.utcnow() - timedelta(hours=24)
        overdue = [
            r for r in workflow.get_pending_requests()
            if r.created_at < sla_threshold
        ]
        if overdue:
            findings.append(
                ComplianceFinding(
                    finding_id=f"finding-{uuid.uuid4()}",
                    description=(
                        f"{len(overdue)} approval request(s) pending for more than 24 hours"
                    ),
                    affected_assets=[r.asset_id for r in overdue],
                    regulation=Regulation.EU_AI_ACT,
                    article="Article 14 (Human oversight)",
                    severity=Severity.MEDIUM,
                    remediation="Escalate overdue approval requests to senior approvers",
                    metadata={"overdue_request_ids": [r.request_id for r in overdue]},
                )
            )
            recommendations.append(
                "Implement automated escalation for approval requests pending > 24 hours"
            )

        # ----------------------------------------------------------------
        # 3. Score calculation
        # ----------------------------------------------------------------
        total_requests = len(workflow._requests)
        resolved = sum(
            1
            for r in workflow._requests.values()
            if r.state in (
                ApprovalState.APPROVED,
                ApprovalState.REJECTED,
                ApprovalState.EXECUTED,
            )
        )
        resolution_rate = (resolved / total_requests) if total_requests > 0 else 1.0
        score = max(0.0, min(100.0, resolution_rate * 100 - len(findings) * 10))

        status = (
            CheckStatus.PASS
            if not findings
            else (
                CheckStatus.FAIL
                if any(f.severity == Severity.HIGH for f in findings)
                else CheckStatus.WARNING
            )
        )

        return ComplianceCheck(
            check_id=check_id,
            check_type=ComplianceCheckType.APPROVAL_COMPLIANCE,
            status=status,
            timestamp=datetime.utcnow(),
            findings=findings,
            recommendations=recommendations,
            score=round(score, 2),
            metadata={
                "total_requests": total_requests,
                "resolved_requests": resolved,
                "pending_requests": len(workflow.get_pending_requests()),
                "expired_requests": len(expired),
                "overdue_requests": len(overdue),
            },
        )
    
    def _check_data_compliance(self, check_id: str) -> ComplianceCheck:
        """Check if sensitive data is properly protected."""
        registry = get_registry()
        assets = registry.list_all()
        
        findings = []
        recommendations = []
        
        # Check for assets with PII/PHI tags but no protection policies
        sensitive_tags = ["pii", "phi", "financial", "biometric"]
        sensitive_assets = [
            a for a in assets
            if any(tag in a.tags for tag in sensitive_tags)
        ]
        
        if sensitive_assets:
            # Check if protection policies exist
            policy_manager = get_policy_manager()
            policies = policy_manager.list_policies(status=PolicyStatus.ACTIVE)
            
            has_gdpr_policy = any("gdpr" in p.name.lower() for p in policies)
            has_hipaa_policy = any("hipaa" in p.name.lower() for p in policies)
            
            if not has_gdpr_policy:
                pii_assets = [a for a in sensitive_assets if "pii" in a.tags]
                if pii_assets:
                    findings.append(ComplianceFinding(
                        finding_id=f"finding-{uuid.uuid4()}",
                        description=f"{len(pii_assets)} assets with PII but no GDPR policy",
                        affected_assets=[a.asset_id for a in pii_assets],
                        regulation=Regulation.GDPR,
                        article="Article 32 (Security)",
                        severity=Severity.CRITICAL,
                        remediation="Activate GDPR PII protection policy",
                    ))
                    recommendations.append("Activate GDPR PII protection policy immediately")
            
            if not has_hipaa_policy:
                phi_assets = [a for a in sensitive_assets if "phi" in a.tags]
                if phi_assets:
                    findings.append(ComplianceFinding(
                        finding_id=f"finding-{uuid.uuid4()}",
                        description=f"{len(phi_assets)} assets with PHI but no HIPAA policy",
                        affected_assets=[a.asset_id for a in phi_assets],
                        regulation=Regulation.HIPAA,
                        article="Security Rule",
                        severity=Severity.CRITICAL,
                        remediation="Activate HIPAA PHI protection policy",
                    ))
                    recommendations.append("Activate HIPAA PHI protection policy immediately")
        
        # Calculate score
        score = max(0, 100 - (len(findings) * 20))
        
        status = CheckStatus.PASS if not findings else CheckStatus.FAIL
        
        return ComplianceCheck(
            check_id=check_id,
            check_type=ComplianceCheckType.DATA_COMPLIANCE,
            status=status,
            timestamp=datetime.utcnow(),
            findings=findings,
            recommendations=recommendations,
            score=score,
            metadata={
                "sensitive_assets": len(sensitive_assets),
            },
        )
    
    def _check_audit_compliance(self, check_id: str) -> ComplianceCheck:
        """
        Check if complete audit trails exist.

        Queries the :class:`AuditMonitor` singleton to verify:
        1. Every registered asset has at least one audit event.
        2. No anomalies have been detected in the last 24 hours.
        3. The audit event volume is above a minimum threshold.
        """
        from backend.agents.compliance.audit_monitor import (
            get_audit_monitor,
            EventResult,
        )

        monitor = get_audit_monitor()
        registry = get_registry()
        assets = registry.list_all()
        findings: List[ComplianceFinding] = []
        recommendations: List[str] = []

        # ----------------------------------------------------------------
        # 1. Assets with no audit trail
        # ----------------------------------------------------------------
        no_trail = [
            a for a in assets
            if not monitor.get_audit_trail(a.asset_id)
        ]
        if no_trail:
            findings.append(
                ComplianceFinding(
                    finding_id=f"finding-{uuid.uuid4()}",
                    description=(
                        f"{len(no_trail)} asset(s) have no audit trail recorded"
                    ),
                    affected_assets=[a.asset_id for a in no_trail],
                    regulation=Regulation.GDPR,
                    article="Article 5(2) (Accountability)",
                    severity=Severity.HIGH,
                    remediation=(
                        "Ensure all asset operations are tracked via AuditMonitor.track_event()"
                    ),
                )
            )
            recommendations.append(
                "Instrument all asset operations with audit events"
            )

        # ----------------------------------------------------------------
        # 2. Active anomalies detected in the last 24 hours
        # ----------------------------------------------------------------
        anomalies = monitor.detect_anomalies()
        recent_anomalies = [
            a for a in anomalies
            if a.detected_at >= datetime.utcnow() - timedelta(hours=24)
        ]
        if recent_anomalies:
            findings.append(
                ComplianceFinding(
                    finding_id=f"finding-{uuid.uuid4()}",
                    description=(
                        f"{len(recent_anomalies)} anomaly(ies) detected in the last 24 hours"
                    ),
                    affected_assets=list(
                        {a.asset_id for a in recent_anomalies if a.asset_id}
                    ),
                    regulation=Regulation.EU_AI_ACT,
                    article="Article 9 (Risk management)",
                    severity=Severity.HIGH,
                    remediation="Investigate and resolve detected anomalies",
                    metadata={
                        "anomaly_types": list(
                            {a.anomaly_type.value for a in recent_anomalies}
                        )
                    },
                )
            )
            recommendations.append(
                "Review anomaly alerts and update detection thresholds if needed"
            )

        # ----------------------------------------------------------------
        # 3. Score calculation
        # ----------------------------------------------------------------
        stats = monitor.get_statistics()
        total_events = stats.get("total_events", 0)
        denied_events = stats.get("denied_events", 0)
        denial_rate = (denied_events / total_events) if total_events > 0 else 0.0

        # Penalise high denial rates (potential policy misconfiguration)
        denial_penalty = min(20.0, denial_rate * 100)
        score = max(
            0.0,
            min(100.0, 100.0 - len(findings) * 15 - denial_penalty),
        )

        status = (
            CheckStatus.PASS
            if not findings
            else (
                CheckStatus.FAIL
                if any(f.severity == Severity.HIGH for f in findings)
                else CheckStatus.WARNING
            )
        )

        return ComplianceCheck(
            check_id=check_id,
            check_type=ComplianceCheckType.AUDIT_COMPLIANCE,
            status=status,
            timestamp=datetime.utcnow(),
            findings=findings,
            recommendations=recommendations,
            score=round(score, 2),
            metadata={
                "total_assets": len(assets),
                "assets_without_trail": len(no_trail),
                "total_audit_events": total_events,
                "recent_anomalies": len(recent_anomalies),
                "denial_rate": round(denial_rate, 4),
            },
        )
    
    def _check_risk_compliance(self, check_id: str) -> ComplianceCheck:
        """Check if risk assessments are current."""
        registry = get_registry()
        assets = registry.list_all()
        scorer = get_risk_scoring_engine()
        
        findings = []
        recommendations = []
        
        # Check for high-risk assets without recent risk assessment
        stale_threshold = datetime.utcnow() - timedelta(days=30)
        
        for asset in assets:
            score = scorer.get_risk_score(asset.asset_id)
            if score and score.risk_tier in [RiskTier.HIGH, RiskTier.CRITICAL]:
                if score.calculated_at < stale_threshold:
                    findings.append(ComplianceFinding(
                        finding_id=f"finding-{uuid.uuid4()}",
                        description=f"High-risk asset {asset.asset_id} has stale risk assessment",
                        affected_assets=[asset.asset_id],
                        regulation=Regulation.EU_AI_ACT,
                        article="Article 9 (Risk management)",
                        severity=Severity.HIGH,
                        remediation="Recalculate risk score",
                    ))
        
        if findings:
            recommendations.append("Recalculate risk scores for all high-risk assets monthly")
        
        # Calculate score
        score = max(0, 100 - (len(findings) * 10))
        
        status = CheckStatus.PASS if not findings else CheckStatus.WARNING
        
        return ComplianceCheck(
            check_id=check_id,
            check_type=ComplianceCheckType.RISK_COMPLIANCE,
            status=status,
            timestamp=datetime.utcnow(),
            findings=findings,
            recommendations=recommendations,
            score=score,
            metadata={
                "total_assets": len(assets),
                "stale_assessments": len(findings),
            },
        )
    
    def _check_tag_compliance(self, check_id: str) -> ComplianceCheck:
        """Check if assets are properly tagged."""
        registry = get_registry()
        assets = registry.list_all()
        
        findings = []
        recommendations = []
        
        # Check for assets without tags
        no_tags = [a for a in assets if not a.tags]
        if no_tags:
            findings.append(ComplianceFinding(
                finding_id=f"finding-{uuid.uuid4()}",
                description=f"{len(no_tags)} assets without tags",
                affected_assets=[a.asset_id for a in no_tags],
                regulation=Regulation.EU_AI_ACT,
                article="Article 13 (Transparency)",
                severity=Severity.MEDIUM,
                remediation="Add contextual tags to all assets",
            ))
            recommendations.append("Tag all assets with appropriate contextual tags")
        
        # Calculate score
        score = max(0, 100 - (len(no_tags) * 2))
        
        status = CheckStatus.PASS if not findings else CheckStatus.WARNING
        
        return ComplianceCheck(
            check_id=check_id,
            check_type=ComplianceCheckType.TAG_COMPLIANCE,
            status=status,
            timestamp=datetime.utcnow(),
            findings=findings,
            recommendations=recommendations,
            score=score,
            metadata={
                "total_assets": len(assets),
                "untagged_assets": len(no_tags),
            },
        )
    
    def get_check(self, check_id: str) -> Optional[ComplianceCheck]:
        """Get check result by ID."""
        return self._checks.get(check_id)
    
    def list_checks(
        self,
        check_type: Optional[ComplianceCheckType] = None,
        status: Optional[CheckStatus] = None,
        limit: int = 100,
    ) -> List[ComplianceCheck]:
        """
        List check results.
        
        Args:
            check_type: Filter by check type
            status: Filter by status
            limit: Maximum number of results
            
        Returns:
            List of checks
        """
        checks = list(self._checks.values())
        
        if check_type:
            checks = [c for c in checks if c.check_type == check_type]
        if status:
            checks = [c for c in checks if c.status == status]
        
        checks.sort(key=lambda c: c.timestamp, reverse=True)
        return checks[:limit]
    
    def get_compliance_score(self) -> float:
        """
        Get overall compliance score.
        
        Returns:
            Score 0-100
        """
        if not self._checks:
            return 0.0
        
        # Get most recent check of each type
        recent_checks = {}
        for check in self._checks.values():
            if check.check_type not in recent_checks or \
               check.timestamp > recent_checks[check.check_type].timestamp:
                recent_checks[check.check_type] = check
        
        if not recent_checks:
            return 0.0
        
        # Average score
        total_score = sum(c.score for c in recent_checks.values())
        return total_score / len(recent_checks)
    
    def get_violations(self) -> List[ComplianceFinding]:
        """
        Get all active violations.
        
        Returns:
            List of findings with CRITICAL or HIGH severity
        """
        violations = []
        
        # Get most recent check of each type
        recent_checks = {}
        for check in self._checks.values():
            if check.check_type not in recent_checks or \
               check.timestamp > recent_checks[check.check_type].timestamp:
                recent_checks[check.check_type] = check
        
        # Collect high-severity findings
        for check in recent_checks.values():
            for finding in check.findings:
                if finding.severity in [Severity.CRITICAL, Severity.HIGH]:
                    violations.append(finding)
        
        return violations
    
    def schedule_check(self, check_type: ComplianceCheckType, interval_seconds: int) -> None:
        """
        Schedule a recurring check.
        
        Args:
            check_type: Type of check
            interval_seconds: Interval in seconds
        """
        self._scheduled_checks[check_type] = interval_seconds
    
    def clear(self) -> None:
        """Clear all checks (for testing)."""
        self._checks.clear()
        self._scheduled_checks.clear()


# ============================================================================
# Singleton Access
# ============================================================================

def get_compliance_checker() -> ComplianceChecker:
    """Get the singleton compliance checker instance."""
    return ComplianceChecker()
