# Day 1-2: Mission Execution Foundation - Implementation Notes

**Date**: 2026-02-05  
**Phase**: Week 1, Day 1-2  
**Goal**: Wire up mission execution end-to-end  
**Built with Pride**: 100%

---

## Changes Overview

### 1. Initialize Core Services in main.py

**What**: Add global instances of LLMFactory, ResourceMarketplace, NATSEventBus, and MissionExecutor

**Why**: These services need to be initialized once at startup and shared across all requests

**How**:
- Create instances in lifespan startup
- Connect to NATS
- Pass to routers via dependency injection

### 2. Create LLM Service Layer

**What**: Wrapper around LLMFactory that handles configuration and caching

**Why**: MissionExecutor expects a service interface, not direct factory access

**How**:
- Create `backend/integrations/llm/llm_service.py`
- Implement `get_llm(agent_type, tenant_id)` method
- Handle provider selection based on settings
- Add error handling and fallbacks

### 3. Wire MissionExecutor to API

**What**: Call executor.execute_mission() from create_mission endpoint

**Why**: Currently missions are just stored, never executed

**How**:
- Add MissionExecutor as FastAPI dependency
- Use BackgroundTasks to execute asynchronously
- Update mission status in database as it progresses

### 4. Add Status Update Mechanism

**What**: Update mission status in database during execution

**Why**: Users need to see progress (pending → running → completed/failed)

**How**:
- Add callback mechanism to MissionExecutor
- Update database after each phase
- Publish events to NATS

### 5. Error Handling

**What**: Comprehensive error handling for all failure scenarios

**Why**: LLM APIs can fail, timeouts can occur, etc.

**How**:
- Try-except around all LLM calls
- Retry logic with exponential backoff
- Store error messages in mission.error field
- Update status to FAILED on error

---

## Files to Modify

1. `backend/main.py` - Initialize services
2. `backend/integrations/llm/llm_service.py` - NEW FILE
3. `backend/api/routes/missions.py` - Wire execution
4. `backend/orchestration/mission_executor.py` - Fix bugs, add callbacks

---

## Implementation Steps

### Step 1: Create LLM Service (30 min)

```python
# backend/integrations/llm/llm_service.py

from typing import Optional, Dict
from langchain_core.language_models import BaseChatModel
from backend.integrations.llm.llm_factory import LLMFactory
from backend.config.settings import Settings

class LLMService:
    """Service layer for LLM access with configuration management"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self._llm_cache: Dict[str, BaseChatModel] = {}
    
    def get_llm(self, agent_type: str, tenant_id: str) -> BaseChatModel:
        """
        Get LLM for specific agent type
        
        Args:
            agent_type: "commander", "guardian", "archivist", "fork", "custom"
            tenant_id: Tenant identifier (for future per-tenant config)
        
        Returns:
            Configured LLM instance
        """
        # Get provider and model from settings
        provider_key = f"{agent_type.upper()}_PROVIDER"
        model_key = f"{agent_type.upper()}_MODEL"
        temp_key = f"{agent_type.upper()}_TEMPERATURE"
        
        provider = getattr(self.settings, provider_key, "openai")
        model = getattr(self.settings, model_key, None)
        temperature = getattr(self.settings, temp_key, 0.7)
        
        # Get API key
        api_key = self._get_api_key(provider)
        
        # Cache key
        cache_key = f"{tenant_id}:{agent_type}:{provider}:{model}"
        
        if cache_key not in self._llm_cache:
            self._llm_cache[cache_key] = LLMFactory.create_llm(
                provider=provider,
                model=model,
                temperature=temperature,
                api_key=api_key
            )
        
        return self._llm_cache[cache_key]
    
    def get_llm_by_model(self, model_name: str, tenant_id: str) -> BaseChatModel:
        """Get LLM by specific model name"""
        # Determine provider from model name
        provider = self._infer_provider(model_name)
        api_key = self._get_api_key(provider)
        
        cache_key = f"{tenant_id}:custom:{provider}:{model_name}"
        
        if cache_key not in self._llm_cache:
            self._llm_cache[cache_key] = LLMFactory.create_llm(
                provider=provider,
                model=model_name,
                temperature=0.7,
                api_key=api_key
            )
        
        return self._llm_cache[cache_key]
    
    def _get_api_key(self, provider: str) -> Optional[str]:
        """Get API key for provider"""
        key_map = {
            "openai": self.settings.OPENAI_API_KEY,
            "anthropic": self.settings.ANTHROPIC_API_KEY,
            "google": self.settings.GOOGLE_API_KEY,
            "xai": self.settings.XAI_API_KEY,
            "ollama": None  # Ollama doesn't need API key
        }
        return key_map.get(provider)
    
    def _infer_provider(self, model_name: str) -> str:
        """Infer provider from model name"""
        if "gpt" in model_name.lower():
            return "openai"
        elif "claude" in model_name.lower():
            return "anthropic"
        elif "gemini" in model_name.lower():
            return "google"
        elif "grok" in model_name.lower():
            return "xai"
        else:
            return "openai"  # Default
```

### Step 2: Initialize Services in main.py (1 hour)

Add to imports:
```python
from backend.integrations.llm.llm_service import LLMService
from backend.economy.resource_marketplace import ResourceMarketplace
from backend.core.event_bus.nats_bus import NATSEventBus
from backend.orchestration.mission_executor import MissionExecutor
```

Add global instances after settings:
```python
# Initialize core services
llm_service: Optional[LLMService] = None
marketplace: Optional[ResourceMarketplace] = None
event_bus: Optional[NATSEventBus] = None
mission_executor: Optional[MissionExecutor] = None
```

Modify lifespan function:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global llm_service, marketplace, event_bus, mission_executor
    
    # Startup
    logger.info("=" * 60)
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    ...
    
    # Initialize LLM Service
    logger.info("Initializing LLM Service...")
    llm_service = LLMService(settings)
    
    # Initialize Resource Marketplace
    logger.info("Initializing Resource Marketplace...")
    marketplace = ResourceMarketplace()
    
    # Initialize Event Bus
    logger.info("Initializing NATS Event Bus...")
    event_bus = NATSEventBus(settings.NATS_URL)
    if settings.NATS_ENABLED:
        await event_bus.connect()
    
    # Initialize Mission Executor
    logger.info("Initializing Mission Executor...")
    mission_executor = MissionExecutor(
        marketplace=marketplace,
        event_bus=event_bus,
        llm_service=llm_service
    )
    
    logger.info("✅ All services initialized")
    logger.info("=" * 60)
    ...
    
    yield
    
    # Shutdown
    logger.info(f"Shutting down {settings.APP_NAME}")
    if event_bus:
        await event_bus.disconnect()
    telemetry.shutdown()
```

Add dependency function:
```python
def get_mission_executor() -> MissionExecutor:
    """Dependency to get mission executor"""
    if mission_executor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mission executor not initialized"
        )
    return mission_executor
```

### Step 3: Fix MissionExecutor Constructor (15 min)

Change constructor signature:
```python
def __init__(
    self,
    marketplace: ResourceMarketplace,
    event_bus: NATSEventBus,
    llm_service: LLMService  # Changed from llm_factory
):
    self.marketplace = marketplace
    self.event_bus = event_bus
    self.llm_service = llm_service  # Changed
    self.active_missions: Dict[str, Dict[str, Any]] = {}
```

Update all references:
```python
# Old:
llm = self.llm_factory.get_llm("guardian", tenant_id)

# New:
llm = self.llm_service.get_llm("guardian", tenant_id)
```

### Step 4: Add Database Update Callback (30 min)

Add to MissionExecutor:
```python
def set_status_callback(self, callback: Callable):
    """Set callback for status updates"""
    self.status_callback = callback

async def _update_status(self, mission_id: str, status: str, **kwargs):
    """Update mission status via callback"""
    if hasattr(self, 'status_callback'):
        await self.status_callback(mission_id, status, **kwargs)
```

Call in execute_mission:
```python
async def execute_mission(...):
    ...
    # Update status to RUNNING
    await self._update_status(mission_id, "RUNNING")
    
    # Phase 1: Guardian validates
    await self._update_status(mission_id, "RUNNING", step="validation")
    validation_result = await self._validate_mission(...)
    
    if not validation_result["is_safe"]:
        await self._update_status(mission_id, "REJECTED", error=validation_result["reason"])
        return {...}
    
    # Phase 2: Commander plans
    await self._update_status(mission_id, "RUNNING", step="planning")
    plan = await self._create_execution_plan(...)
    
    # Phase 3: Execute
    await self._update_status(mission_id, "RUNNING", step="executing")
    result = await self._execute_with_agents(...)
    
    # Phase 4: Complete
    if result["status"] == "SUCCESS":
        await self._update_status(mission_id, "COMPLETED", result=result)
    else:
        await self._update_status(mission_id, "FAILED", error=result.get("error"))
    
    return result
```

### Step 5: Wire to API (1 hour)

Modify missions.py:

Add imports:
```python
from fastapi import BackgroundTasks
from backend.main import get_mission_executor
```

Modify create_mission:
```python
@router.post("", response_model=MissionResponse, status_code=status.HTTP_201_CREATED)
async def create_mission(
    mission: MissionCreate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    executor: MissionExecutor = Depends(get_mission_executor)
):
    """Create and execute a new mission"""
    
    # ... existing validation code ...
    
    # Create mission in database
    mission_data = Mission(...)
    db.add(mission_data)
    db.commit()
    db.refresh(mission_data)
    
    # Execute mission in background
    async def execute_and_update():
        """Background task to execute mission and update database"""
        
        # Create status update callback
        async def update_status(mission_id: str, status: str, **kwargs):
            # Get new database session for background task
            from backend.database import SessionLocal
            bg_db = SessionLocal()
            try:
                mission = bg_db.query(Mission).filter(Mission.id == mission_id).first()
                if mission:
                    mission.status = status
                    if status == "RUNNING":
                        if not mission.started_at:
                            mission.started_at = datetime.utcnow()
                    elif status in ["COMPLETED", "FAILED", "REJECTED"]:
                        mission.completed_at = datetime.utcnow()
                        if "result" in kwargs:
                            mission.result = kwargs["result"]
                        if "error" in kwargs:
                            mission.error = kwargs["error"]
                        if "execution_time" in kwargs:
                            mission.execution_time = kwargs["execution_time"]
                    bg_db.commit()
            finally:
                bg_db.close()
        
        # Set callback
        executor.set_status_callback(update_status)
        
        # Execute mission
        try:
            result = await executor.execute_mission(
                mission_id=mission_data.id,
                goal=mission_data.objective,
                tenant_id=mission_data.tenant_id,
                user_id=current_user["user_id"],
                budget=None  # TODO: Add budget support
            )
            
            # Update agent stats
            _update_agent_stats(
                db,
                mission_data.agent_id,
                success=(result["status"] == "SUCCESS")
            )
            
        except Exception as e:
            logger.error(f"Mission execution failed: {e}", exc_info=True)
            # Update mission to failed
            await update_status(mission_data.id, "FAILED", error=str(e))
    
    # Add to background tasks
    background_tasks.add_task(execute_and_update)
    
    # Return immediately with PENDING status
    return MissionResponse(...)
```

### Step 6: Add Error Handling (30 min)

Wrap all LLM calls in try-except:

```python
async def _validate_mission(...):
    with tracer.start_as_current_span("guardian_validate"):
        try:
            llm = self.llm_service.get_llm("guardian", tenant_id)
            response = await llm.ainvoke(prompt)
            ...
        except Exception as e:
            logger.error(f"Guardian validation failed: {e}")
            # Return safe default
            return {
                "is_safe": False,
                "risk_score": 1.0,
                "reason": f"Validation error: {str(e)}",
                "estimated_cost": 0.0,
                "estimated_duration_seconds": 0
            }
```

### Step 7: Testing (2 hours)

Create test script:
```python
# tests/manual/test_mission_execution.py

import asyncio
import httpx

async def test_mission_execution():
    """Test end-to-end mission execution"""
    
    client = httpx.AsyncClient(timeout=60.0)
    base_url = "http://localhost:8000"
    
    # 1. Register user
    print("1. Registering user...")
    reg_response = await client.post(
        f"{base_url}/api/v1/auth/register",
        json={
            "email": "test@example.com",
            "password": "Test123!",
            "full_name": "Test User"
        }
    )
    print(f"   Status: {reg_response.status_code}")
    
    # 2. Login
    print("2. Logging in...")
    login_response = await client.post(
        f"{base_url}/api/v1/auth/login",
        json={
            "username": "test@example.com",
            "password": "Test123!"
        }
    )
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"   Token: {token[:20]}...")
    
    # 3. Create agent
    print("3. Creating agent...")
    agent_response = await client.post(
        f"{base_url}/api/v1/agents",
        json={
            "name": "Test Agent",
            "type": "commander",
            "model": "gpt-3.5-turbo",
            "capabilities": ["general"]
        },
        headers=headers
    )
    agent_id = agent_response.json()["id"]
    print(f"   Agent ID: {agent_id}")
    
    # 4. Create mission
    print("4. Creating mission...")
    mission_response = await client.post(
        f"{base_url}/api/v1/missions",
        json={
            "objective": "Write a haiku about artificial intelligence",
            "agent_id": agent_id,
            "priority": "normal",
            "max_steps": 5,
            "timeout_seconds": 60
        },
        headers=headers
    )
    mission_id = mission_response.json()["id"]
    print(f"   Mission ID: {mission_id}")
    print(f"   Initial Status: {mission_response.json()['status']}")
    
    # 5. Poll for completion
    print("5. Waiting for completion...")
    for i in range(30):  # Wait up to 30 seconds
        await asyncio.sleep(1)
        status_response = await client.get(
            f"{base_url}/api/v1/missions/{mission_id}",
            headers=headers
        )
        status = status_response.json()["status"]
        print(f"   [{i+1}s] Status: {status}")
        
        if status in ["COMPLETED", "FAILED", "REJECTED"]:
            break
    
    # 6. Get final result
    print("6. Final result:")
    final_response = await client.get(
        f"{base_url}/api/v1/missions/{mission_id}",
        headers=headers
    )
    result = final_response.json()
    print(f"   Status: {result['status']}")
    print(f"   Result: {result.get('result')}")
    print(f"   Error: {result.get('error')}")
    print(f"   Execution Time: {result.get('execution_time')}s")
    
    await client.aclose()

if __name__ == "__main__":
    asyncio.run(test_mission_execution())
```

Run test:
```bash
cd /tmp/omnipath_complete
python tests/manual/test_mission_execution.py
```

---

## Success Criteria

✅ Mission status changes: PENDING → RUNNING → COMPLETED  
✅ Mission result contains LLM output  
✅ Mission execution_time is recorded  
✅ Agent stats updated (total_missions, successful_missions)  
✅ Events published to NATS  
✅ Errors handled gracefully  
✅ No crashes or unhandled exceptions  

---

## Rollback Procedure

If something goes wrong:

1. Revert commits:
   ```bash
   git revert HEAD~3..HEAD
   git push origin v5.0-rewrite
   ```

2. Restart backend:
   ```bash
   docker compose -f docker-compose.v3.yml restart backend
   ```

3. Verify health:
   ```bash
   curl http://localhost:8000/health
   ```

---

## Next Steps (Day 3-4)

After Day 1-2 is complete and tested:
- Enhance Commander agent with emotional intelligence
- Add risk assessment logic
- Integrate with event sourcing
- Add comprehensive logging

---

**Built with Pride for Obex Blackvault**
