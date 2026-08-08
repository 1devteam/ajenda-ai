# Business Ontology — Slice 1

**Status:** Implemented (contracts only)  
**Cluster:** Business object / ontology expansion  
**Date:** 2026-08-08  
**Depends on:** Evidence Intelligence Slice 1 (`EvidenceFact` optional linkage)

## Target capability

Ajenda has a shared vocabulary for core business identities and commercial objects that already repeat across abilities, so evidence and decisions can optionally name *what* they are about without forcing every vertical into one storage model.

This slice does **not**:

- invent Goal / KPI / Campaign / Vendor / Offer as first-class types
- build an ability graph (`input_types` / `output_types`)
- rewrite light_crm storage
- wire composition → runtime
- introduce StrategyEngine

## Canonical object types

| Type | Meaning | Earned from |
|------|---------|-------------|
| `person` | Individual human | Contact name/email patterns |
| `organization` | Company or entity | Account / company aliases |
| `account` | Commercial view of an organization | `SUPPORTED_RECORD_TYPES`, light_crm |
| `contact` | Person in a business relationship context | light_crm + sales |
| `lead` | Potential future commercial relationship | sales/GTM lead bags, prospects |
| `opportunity` | Possible commercial outcome being pursued | light_crm pipeline stages |

## Relationships (declarative)

Defined in `RELATIONSHIP_SPECS`:

- Contact → Account (many_to_one)
- Contact → Person (many_to_one)
- Account → Organization (one_to_one commercial view)
- Opportunity → Account (many_to_one)
- Opportunity ↔ Contact (many_to_many; primary contact_id in light_crm)
- Lead → Account / Contact (optional associations)

## Storage honesty

`LightCrmRecordService.identity_upsert` currently projects:

- `lead` / `leads` → **contact**
- `company` / `companies` → **account**
- `deal` / `deals` → **opportunity**

Canonical ontology still distinguishes **lead** so reasoning language is not collapsed. Storage unification is a later slice if repetition demands it.

## Contracts

- `backend/services/ontology/types.py` — `BusinessObjectType`, `BusinessObjectRef`, aliases, relationships
- `EvidenceFact.about_object_refs` — optional list of `BusinessObjectRef` (non-breaking)

## Deferred

- Goal, KPI, Campaign, Project, Offer, Customer, Vendor
- Observation / Claim / Decision / Outcome as ontology objects
- Ability input/output type declarations
- Closed loop Goal → Decision → Action → Outcome → Evidence → KPI

## Files

- `backend/services/ontology/__init__.py`
- `backend/services/ontology/types.py`
- `backend/services/tools/schemas.py` — optional `about_object_refs`
- `tests/unit/ontology/test_business_object_types.py`
- `docs/product/business-ontology-slice-1.md` (this file)
