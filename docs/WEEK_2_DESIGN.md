# Week 2: Contextual Tagging & Regulatory Mapping - Design Document

**Date:** February 26, 2026  
**Status:** Design Phase  
**Owner:** Dev Team Lead (reporting to Obex Blackvault)

---

## Executive Summary

Week 2 builds on the asset inventory foundation from Week 1 to add **contextual intelligence** - automatically tagging assets based on their usage patterns and mapping them to regulatory risk categories. This enables risk-based governance and prepares for EU AI Act compliance.

**Key Innovation:** Assets are tagged **dynamically based on context** (what data they access, who uses them, where they're deployed) rather than static manual tagging.

---

## Architecture Overview

### System Flow

```
Agent Execution Request
  ↓
ComplianceEngine.evaluate()
  ↓
ContextualTaggingRule.check()
  ├─ Analyze context (data, user, location)
  ├─ Auto-tag asset (PII, healthcare, finance, etc.)
  └─ Update asset registry with contextual tags
  ↓
RegulatoryMappingRule.check()
  ├─ Map tags to EU AI Act risk categories
  ├─ Determine risk level (minimal, limited, high, unacceptable)
  └─ Store risk assessment
  ↓
AutonomousAuthorityRule.check()
  ├─ Check user authority level
  ├─ Compare with required authority for risk level
  └─ Allow/Block based on authority
```

---

## Component Design

### 1. ContextualTaggingRule

**Purpose:** Automatically tag assets based on usage context

**Contextual Signals:**
- **Data accessed:** PII, PHI, financial data, biometric data
- **User role:** Admin, operator, analyst, end-user
- **Deployment location:** Production, staging, development
- **Usage patterns:** Frequency, data volume, user count
- **Integration points:** External APIs, databases, file systems

**Tag Categories:**
- **Data sensitivity:** `pii`, `phi`, `financial`, `biometric`, `public`
- **Domain:** `healthcare`, `finance`, `legal`, `hr`, `general`
- **Risk indicators:** `high-volume`, `external-api`, `user-facing`, `automated-decision`
- **Compliance:** `gdpr`, `hipaa`, `sox`, `eu-ai-act`

**Example:**
```python
context = {
    "agent_id": "medical-diagnosis-agent",
    "data_accessed": ["patient_records", "medical_images"],
    "user_role": "physician",
    "location": "production",
}

rule = ContextualTaggingRule()
result = rule.check(context)

# Result: Asset tagged with ["phi", "healthcare", "high-risk", "hipaa", "eu-ai-act"]
```

**Implementation:**
- Analyze context dictionary for data access patterns
- Match patterns against tag rules (configurable)
- Update asset registry with new tags
- Track tag history for audit trail

---

### 2. RegulatoryMappingRule

**Purpose:** Map asset tags to EU AI Act risk categories

**EU AI Act Risk Levels:**

| Risk Level | Description | Examples | Requirements |
|-----------|-------------|----------|--------------|
| **Unacceptable** | Prohibited AI systems | Social scoring, subliminal manipulation | Banned |
| **High** | Significant risk to safety/rights | Medical diagnosis, credit scoring, hiring | Strict requirements |
| **Limited** | Transparency obligations | Chatbots, emotion recognition | Transparency rules |
| **Minimal** | Low/no risk | Spam filters, video games | No special requirements |

**Mapping Rules:**

```python
RISK_MAPPINGS = {
    "unacceptable": {
        "tags": ["social-scoring", "subliminal-manipulation", "real-time-biometric-public"],
        "action": "block",
    },
    "high": {
        "tags": ["medical-diagnosis", "credit-scoring", "hiring", "law-enforcement", "critical-infrastructure"],
        "requirements": ["human-oversight", "risk-assessment", "documentation", "accuracy-testing"],
    },
    "limited": {
        "tags": ["chatbot", "emotion-recognition", "deepfake"],
        "requirements": ["transparency-disclosure"],
    },
    "minimal": {
        "tags": ["spam-filter", "content-recommendation", "general"],
        "requirements": [],
    },
}
```

**Example:**
```python
context = {
    "asset_id": "medical-diagnosis-agent",
    "tags": ["phi", "healthcare", "automated-decision", "medical-diagnosis"],
}

rule = RegulatoryMappingRule()
result = rule.check(context)

# Result:
# - risk_level: "high"
# - requirements: ["human-oversight", "risk-assessment", "documentation", "accuracy-testing"]
# - regulation: "EU AI Act Article 6"
```

**Implementation:**
- Load risk mappings from configuration
- Match asset tags against risk categories
- Determine highest applicable risk level
- Store risk assessment in asset metadata
- Generate compliance checklist

---

### 3. AutonomousAuthorityRule

**Purpose:** Enforce authority levels based on risk

**Authority Levels:**

| Level | Name | Allowed Risk Levels | Examples |
|-------|------|-------------------|----------|
| 0 | Guest | Minimal only | Read-only access |
| 1 | User | Minimal, Limited | Standard operations |
| 2 | Operator | Minimal, Limited, High (with oversight) | Supervised high-risk operations |
| 3 | Admin | All (except Unacceptable) | Full system access |
| 4 | Compliance Officer | All | Override for compliance |

**Enforcement Logic:**

```python
def check_authority(user_level: int, asset_risk: str, has_oversight: bool = False) -> bool:
    if asset_risk == "unacceptable":
        return user_level >= 4  # Only compliance officer
    
    if asset_risk == "high":
        if has_oversight:
            return user_level >= 2  # Operator with oversight
        else:
            return user_level >= 3  # Admin without oversight
    
    if asset_risk == "limited":
        return user_level >= 1  # User or above
    
    return True  # Minimal risk - all users
```

**Example:**
```python
context = {
    "user_id": "physician-001",
    "user_authority_level": 2,  # Operator
    "asset_id": "medical-diagnosis-agent",
    "asset_risk_level": "high",
    "human_oversight": True,
}

rule = AutonomousAuthorityRule()
result = rule.check(context)

# Result: allowed=True (Operator with oversight can use high-risk asset)
```

**Implementation:**
- Load user authority from user profile
- Load asset risk level from regulatory mapping
- Check if oversight is available
- Apply authority rules
- Log authorization decision

---

### 4. Contextual Tags API

**Purpose:** CRUD operations for contextual tags

**Endpoints:**

#### Tag Management
- `POST /api/v1/tags` - Create tag definition
- `GET /api/v1/tags` - List all tag definitions
- `GET /api/v1/tags/{name}` - Get tag details
- `PUT /api/v1/tags/{name}` - Update tag definition
- `DELETE /api/v1/tags/{name}` - Delete tag

#### Asset Tagging
- `POST /api/v1/assets/{id}/tags` - Add tags to asset
- `DELETE /api/v1/assets/{id}/tags/{name}` - Remove tag from asset
- `GET /api/v1/assets/{id}/tags` - Get asset tags with history

#### Tag Analysis
- `GET /api/v1/tags/{name}/assets` - Get assets with tag
- `GET /api/v1/tags/stats` - Tag usage statistics
- `GET /api/v1/tags/compliance` - Compliance tag report

**Tag Definition Model:**

```python
@dataclass
class TagDefinition:
    name: str
    category: str  # data_sensitivity, domain, risk_indicator, compliance
    description: str
    risk_weight: float  # 0.0 (minimal) to 1.0 (unacceptable)
    auto_tag_rules: List[Dict[str, Any]]  # Pattern matching rules
    compliance_mapping: Dict[str, str]  # Map to regulations
    created_at: datetime
    updated_at: datetime
```

**Example Tag Definition:**

```json
{
  "name": "phi",
  "category": "data_sensitivity",
  "description": "Protected Health Information under HIPAA",
  "risk_weight": 0.8,
  "auto_tag_rules": [
    {
      "condition": "data_accessed",
      "pattern": ["patient_records", "medical_images", "diagnoses"]
    }
  ],
  "compliance_mapping": {
    "hipaa": "164.502",
    "eu_ai_act": "high_risk"
  }
}
```

---

## Data Models

### Updated AIAsset Model

```python
@dataclass
class AIAsset:
    # Existing fields from Week 1
    asset_id: str
    asset_type: AssetType
    name: str
    description: str
    owner: str
    status: AssetStatus
    metadata: Dict[str, Any]
    tags: List[str]
    dependencies: List[str]
    lineage: Optional[ModelLineage]
    created_at: datetime
    updated_at: datetime
    
    # New fields for Week 2
    contextual_tags: Dict[str, ContextualTag]  # Tag name -> ContextualTag
    risk_assessment: Optional[RiskAssessment]
    compliance_status: Dict[str, ComplianceStatus]  # Regulation -> Status
```

### New Models

```python
@dataclass
class ContextualTag:
    name: str
    category: str
    applied_at: datetime
    applied_by: str  # "auto" or user_id
    context: Dict[str, Any]  # Context that triggered the tag
    confidence: float  # 0.0 to 1.0
    expires_at: Optional[datetime]  # For temporary tags

@dataclass
class RiskAssessment:
    risk_level: str  # minimal, limited, high, unacceptable
    regulation: str  # EU AI Act, HIPAA, etc.
    requirements: List[str]
    assessed_at: datetime
    assessed_by: str
    valid_until: Optional[datetime]
    notes: str

@dataclass
class ComplianceStatus:
    regulation: str
    status: str  # compliant, non_compliant, pending, not_applicable
    requirements_met: List[str]
    requirements_missing: List[str]
    last_checked: datetime
    next_check: datetime
```

---

## Integration Points

### With Week 1 Components

1. **Asset Registry:**
   - Extend AIAsset model with contextual tags
   - Add tag history tracking
   - Update search to filter by contextual tags

2. **Lineage Tracker:**
   - Track tag application events
   - Track risk assessment changes
   - Link tags to lineage chain

3. **Inventory Rules:**
   - AgentInventoryRule checks contextual tags
   - ToolInventoryRule checks contextual tags
   - Both rules consider risk level

### With ComplianceEngine

```python
# ComplianceEngine evaluates rules in order:
1. AgentInventoryRule (is agent registered?)
2. ToolInventoryRule (is tool registered?)
3. ContextualTaggingRule (auto-tag based on context)
4. RegulatoryMappingRule (map to risk categories)
5. AutonomousAuthorityRule (check user authority)
6. [Future Week 3] ContextualRiskRule (calculate risk score)
7. [Future Week 3] TieredApprovalRule (route to approval)
```

---

## Configuration

### Tag Rules Configuration

```yaml
# config/tag_rules.yaml
contextual_tags:
  pii:
    category: data_sensitivity
    risk_weight: 0.7
    auto_tag_rules:
      - condition: data_accessed
        patterns: [email, phone, ssn, address, name]
      - condition: api_endpoint
        patterns: [/users/, /customers/, /contacts/]
  
  phi:
    category: data_sensitivity
    risk_weight: 0.8
    auto_tag_rules:
      - condition: data_accessed
        patterns: [patient_records, medical_images, diagnoses]
      - condition: domain
        value: healthcare
  
  financial:
    category: data_sensitivity
    risk_weight: 0.75
    auto_tag_rules:
      - condition: data_accessed
        patterns: [credit_card, bank_account, transactions]
      - condition: domain
        value: finance
```

### Risk Mappings Configuration

```yaml
# config/risk_mappings.yaml
eu_ai_act:
  unacceptable:
    tags: [social-scoring, subliminal-manipulation, real-time-biometric-public]
    action: block
  
  high:
    tags: [medical-diagnosis, credit-scoring, hiring, law-enforcement]
    requirements:
      - human-oversight
      - risk-assessment
      - documentation
      - accuracy-testing
      - data-governance
  
  limited:
    tags: [chatbot, emotion-recognition, deepfake]
    requirements:
      - transparency-disclosure
  
  minimal:
    tags: [spam-filter, content-recommendation, general]
    requirements: []
```

---

## Testing Strategy

### Unit Tests

1. **test_contextual_tagging.py:**
   - Test auto-tagging based on data access patterns
   - Test tag confidence scoring
   - Test tag expiration
   - Test tag history tracking

2. **test_regulatory_mapping.py:**
   - Test risk level determination
   - Test requirement generation
   - Test multiple regulation mapping
   - Test edge cases (conflicting tags)

3. **test_autonomous_authority.py:**
   - Test authority level enforcement
   - Test oversight requirements
   - Test compliance officer override
   - Test unauthorized access blocking

4. **test_tags_api.py:**
   - Test tag CRUD operations
   - Test asset tagging
   - Test tag analysis endpoints
   - Test compliance reporting

### Integration Tests

1. **test_week2_integration.py:**
   - Test full flow: context → tags → risk → authority
   - Test with Week 1 components (registry, lineage)
   - Test with ComplianceEngine
   - Test API endpoints end-to-end

---

## Success Criteria

1. ✅ ContextualTaggingRule auto-tags assets based on context
2. ✅ RegulatoryMappingRule maps to EU AI Act risk categories
3. ✅ AutonomousAuthorityRule enforces authority levels
4. ✅ Tags API provides CRUD and analysis endpoints
5. ✅ All tests passing (target: 95%+)
6. ✅ Integration with Week 1 components
7. ✅ Documentation complete
8. ✅ Committed and pushed to main

---

## Timeline

- **Day 1 (Feb 27):** Implement ContextualTaggingRule
- **Day 2 (Feb 28):** Implement RegulatoryMappingRule
- **Day 3 (Mar 1):** Implement AutonomousAuthorityRule
- **Day 4 (Mar 2):** Implement Tags API
- **Day 5 (Mar 3):** Write comprehensive tests
- **Day 6 (Mar 4):** Integration testing and fixes
- **Day 7 (Mar 5):** Documentation and commit

---

## Next Steps: Week 3 Preview

**Week 3: Risk Tiering (Mar 6-12)**
- ContextualRiskRule: Calculate risk scores based on context
- TieredApprovalRule: Route high-risk actions to approval workflows
- ImpactAssessmentRule: Assess potential impact before execution
- Risk dashboard API

---

**Built with Pride for Obex Blackvault.**  
**Target: EU AI Act readiness by August 2, 2026.**
