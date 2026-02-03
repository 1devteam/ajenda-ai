"""
Saga Orchestration Implementation for Omnipath v5.0
Manages distributed transactions across multiple services with compensation

Built with Pride for Obex Blackvault
"""

import uuid
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime

from backend.core.logging_config import get_logger, LoggerMixin
from backend.core.event_sourcing.event_store_impl import EventStore, Event


logger = get_logger(__name__)


# ============================================================================
# Saga Models
# ============================================================================

class SagaStatus(str, Enum):
    """Status of saga execution"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    FAILED = "failed"


class StepStatus(str, Enum):
    """Status of saga step execution"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


@dataclass
class SagaStep:
    """
    Single step in a saga
    """
    step_id: str
    name: str
    action: Callable
    compensation: Optional[Callable] = None
    status: StepStatus = StepStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class SagaDefinition:
    """
    Definition of a saga workflow
    """
    saga_id: str
    name: str
    steps: List[SagaStep] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    status: SagaStatus = SagaStatus.PENDING
    current_step: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ============================================================================
# Saga Orchestrator
# ============================================================================

class SagaOrchestrator(LoggerMixin):
    """
    Orchestrates saga execution with automatic compensation on failure
    """
    
    def __init__(self, event_store: EventStore):
        """
        Initialize saga orchestrator
        
        Args:
            event_store: Event store for saga events
        """
        self.event_store = event_store
        self._sagas: Dict[str, SagaDefinition] = {}
    
    def create_saga(self, name: str, context: Optional[Dict[str, Any]] = None) -> SagaDefinition:
        """
        Create new saga
        
        Args:
            name: Name of the saga
            context: Initial context data
        
        Returns:
            Created saga definition
        """
        saga = SagaDefinition(
            saga_id=str(uuid.uuid4()),
            name=name,
            context=context or {}
        )
        
        self._sagas[saga.saga_id] = saga
        
        self.log_info(
            f"Saga created: {name}",
            saga_id=saga.saga_id
        )
        
        return saga
    
    def add_step(
        self,
        saga: SagaDefinition,
        name: str,
        action: Callable,
        compensation: Optional[Callable] = None
    ) -> SagaStep:
        """
        Add step to saga
        
        Args:
            saga: Saga to add step to
            name: Name of the step
            action: Action to execute
            compensation: Optional compensation action
        
        Returns:
            Created step
        """
        step = SagaStep(
            step_id=str(uuid.uuid4()),
            name=name,
            action=action,
            compensation=compensation
        )
        
        saga.steps.append(step)
        
        self.log_debug(
            f"Step added to saga: {name}",
            saga_id=saga.saga_id,
            step_id=step.step_id
        )
        
        return step
    
    async def execute(self, saga: SagaDefinition) -> bool:
        """
        Execute saga with automatic compensation on failure
        
        Args:
            saga: Saga to execute
        
        Returns:
            True if successful, False if compensated
        """
        saga.status = SagaStatus.RUNNING
        saga.started_at = datetime.utcnow()
        
        self.log_info(
            f"Saga execution started: {saga.name}",
            saga_id=saga.saga_id,
            steps=len(saga.steps)
        )
        
        # Emit saga started event
        await self._emit_event(
            saga_id=saga.saga_id,
            event_type='saga.started',
            data={'name': saga.name, 'steps': len(saga.steps)}
        )
        
        try:
            # Execute steps sequentially
            for i, step in enumerate(saga.steps):
                saga.current_step = i
                
                success = await self._execute_step(saga, step)
                
                if not success:
                    # Step failed, start compensation
                    await self._compensate(saga, i)
                    saga.status = SagaStatus.COMPENSATED
                    saga.completed_at = datetime.utcnow()
                    
                    # Emit saga compensated event
                    await self._emit_event(
                        saga_id=saga.saga_id,
                        event_type='saga.compensated',
                        data={'failed_step': step.name}
                    )
                    
                    return False
            
            # All steps completed successfully
            saga.status = SagaStatus.COMPLETED
            saga.completed_at = datetime.utcnow()
            
            self.log_info(
                f"Saga completed successfully: {saga.name}",
                saga_id=saga.saga_id,
                duration_ms=(saga.completed_at - saga.started_at).total_seconds() * 1000
            )
            
            # Emit saga completed event
            await self._emit_event(
                saga_id=saga.saga_id,
                event_type='saga.completed',
                data={'steps_completed': len(saga.steps)}
            )
            
            return True
            
        except Exception as e:
            self.log_error(
                f"Saga execution failed: {saga.name}",
                exc_info=True,
                saga_id=saga.saga_id,
                error=str(e)
            )
            
            # Start compensation
            await self._compensate(saga, saga.current_step)
            saga.status = SagaStatus.FAILED
            saga.completed_at = datetime.utcnow()
            
            # Emit saga failed event
            await self._emit_event(
                saga_id=saga.saga_id,
                event_type='saga.failed',
                data={'error': str(e)}
            )
            
            return False
    
    async def _execute_step(self, saga: SagaDefinition, step: SagaStep) -> bool:
        """
        Execute single saga step
        
        Args:
            saga: Saga being executed
            step: Step to execute
        
        Returns:
            True if successful, False otherwise
        """
        step.status = StepStatus.RUNNING
        step.started_at = datetime.utcnow()
        
        self.log_info(
            f"Executing step: {step.name}",
            saga_id=saga.saga_id,
            step_id=step.step_id
        )
        
        # Emit step started event
        await self._emit_event(
            saga_id=saga.saga_id,
            event_type='saga.step.started',
            data={'step_name': step.name, 'step_id': step.step_id}
        )
        
        try:
            # Execute step action
            result = await step.action(saga.context)
            
            step.result = result
            step.status = StepStatus.COMPLETED
            step.completed_at = datetime.utcnow()
            
            # Update saga context with result
            saga.context[f"{step.name}_result"] = result
            
            self.log_info(
                f"Step completed: {step.name}",
                saga_id=saga.saga_id,
                step_id=step.step_id,
                duration_ms=(step.completed_at - step.started_at).total_seconds() * 1000
            )
            
            # Emit step completed event
            await self._emit_event(
                saga_id=saga.saga_id,
                event_type='saga.step.completed',
                data={'step_name': step.name, 'step_id': step.step_id}
            )
            
            return True
            
        except Exception as e:
            step.error = str(e)
            step.status = StepStatus.FAILED
            step.completed_at = datetime.utcnow()
            
            self.log_error(
                f"Step failed: {step.name}",
                exc_info=True,
                saga_id=saga.saga_id,
                step_id=step.step_id,
                error=str(e)
            )
            
            # Emit step failed event
            await self._emit_event(
                saga_id=saga.saga_id,
                event_type='saga.step.failed',
                data={'step_name': step.name, 'step_id': step.step_id, 'error': str(e)}
            )
            
            return False
    
    async def _compensate(self, saga: SagaDefinition, failed_step_index: int) -> None:
        """
        Compensate completed steps in reverse order
        
        Args:
            saga: Saga to compensate
            failed_step_index: Index of the step that failed
        """
        saga.status = SagaStatus.COMPENSATING
        
        self.log_info(
            f"Starting compensation: {saga.name}",
            saga_id=saga.saga_id,
            steps_to_compensate=failed_step_index
        )
        
        # Emit compensation started event
        await self._emit_event(
            saga_id=saga.saga_id,
            event_type='saga.compensation.started',
            data={'steps_to_compensate': failed_step_index}
        )
        
        # Compensate completed steps in reverse order
        for i in range(failed_step_index - 1, -1, -1):
            step = saga.steps[i]
            
            if step.status == StepStatus.COMPLETED and step.compensation:
                await self._compensate_step(saga, step)
        
        self.log_info(
            f"Compensation completed: {saga.name}",
            saga_id=saga.saga_id
        )
        
        # Emit compensation completed event
        await self._emit_event(
            saga_id=saga.saga_id,
            event_type='saga.compensation.completed',
            data={}
        )
    
    async def _compensate_step(self, saga: SagaDefinition, step: SagaStep) -> None:
        """
        Compensate single step
        
        Args:
            saga: Saga being compensated
            step: Step to compensate
        """
        step.status = StepStatus.COMPENSATING
        
        self.log_info(
            f"Compensating step: {step.name}",
            saga_id=saga.saga_id,
            step_id=step.step_id
        )
        
        # Emit step compensation started event
        await self._emit_event(
            saga_id=saga.saga_id,
            event_type='saga.step.compensation.started',
            data={'step_name': step.name, 'step_id': step.step_id}
        )
        
        try:
            # Execute compensation action
            await step.compensation(saga.context, step.result)
            
            step.status = StepStatus.COMPENSATED
            
            self.log_info(
                f"Step compensated: {step.name}",
                saga_id=saga.saga_id,
                step_id=step.step_id
            )
            
            # Emit step compensation completed event
            await self._emit_event(
                saga_id=saga.saga_id,
                event_type='saga.step.compensation.completed',
                data={'step_name': step.name, 'step_id': step.step_id}
            )
            
        except Exception as e:
            self.log_error(
                f"Step compensation failed: {step.name}",
                exc_info=True,
                saga_id=saga.saga_id,
                step_id=step.step_id,
                error=str(e)
            )
            
            # Emit step compensation failed event
            await self._emit_event(
                saga_id=saga.saga_id,
                event_type='saga.step.compensation.failed',
                data={'step_name': step.name, 'step_id': step.step_id, 'error': str(e)}
            )
    
    async def _emit_event(
        self,
        saga_id: str,
        event_type: str,
        data: Dict[str, Any]
    ) -> None:
        """
        Emit saga event
        
        Args:
            saga_id: ID of the saga
            event_type: Type of event
            data: Event data
        """
        await self.event_store.append(
            aggregate_id=saga_id,
            aggregate_type='saga',
            event_type=event_type,
            data=data
        )
    
    def get_saga(self, saga_id: str) -> Optional[SagaDefinition]:
        """
        Get saga by ID
        
        Args:
            saga_id: ID of the saga
        
        Returns:
            Saga definition or None
        """
        return self._sagas.get(saga_id)


# ============================================================================
# Pre-defined Sagas
# ============================================================================

class MissionExecutionSaga:
    """
    Saga for executing a mission with credit deduction and result recording
    """
    
    def __init__(self, orchestrator: SagaOrchestrator):
        """
        Initialize mission execution saga
        
        Args:
            orchestrator: Saga orchestrator
        """
        self.orchestrator = orchestrator
    
    async def execute(
        self,
        mission_id: str,
        agent_id: str,
        command: str,
        estimated_cost: float
    ) -> bool:
        """
        Execute mission saga
        
        Args:
            mission_id: ID of the mission
            agent_id: ID of the agent
            command: Command to execute
            estimated_cost: Estimated cost in credits
        
        Returns:
            True if successful, False if compensated
        """
        # Create saga
        saga = self.orchestrator.create_saga(
            name="mission_execution",
            context={
                'mission_id': mission_id,
                'agent_id': agent_id,
                'command': command,
                'estimated_cost': estimated_cost
            }
        )
        
        # Step 1: Reserve credits
        self.orchestrator.add_step(
            saga,
            name="reserve_credits",
            action=self._reserve_credits,
            compensation=self._release_credits
        )
        
        # Step 2: Execute mission
        self.orchestrator.add_step(
            saga,
            name="execute_mission",
            action=self._execute_mission,
            compensation=self._cancel_mission
        )
        
        # Step 3: Record result
        self.orchestrator.add_step(
            saga,
            name="record_result",
            action=self._record_result,
            compensation=self._delete_result
        )
        
        # Step 4: Deduct actual cost
        self.orchestrator.add_step(
            saga,
            name="deduct_cost",
            action=self._deduct_cost,
            compensation=self._refund_cost
        )
        
        # Execute saga
        return await self.orchestrator.execute(saga)
    
    async def _reserve_credits(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Reserve credits for mission"""
        # Implementation would call economy service
        return {'reserved': True, 'reservation_id': str(uuid.uuid4())}
    
    async def _release_credits(self, context: Dict[str, Any], result: Any) -> None:
        """Release reserved credits"""
        # Implementation would call economy service
        pass
    
    async def _execute_mission(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the mission"""
        # Implementation would call mission executor
        return {'result': 'Mission completed', 'actual_cost': context['estimated_cost'] * 0.9}
    
    async def _cancel_mission(self, context: Dict[str, Any], result: Any) -> None:
        """Cancel mission execution"""
        # Implementation would call mission executor
        pass
    
    async def _record_result(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Record mission result"""
        # Implementation would save to database
        return {'recorded': True}
    
    async def _delete_result(self, context: Dict[str, Any], result: Any) -> None:
        """Delete recorded result"""
        # Implementation would delete from database
        pass
    
    async def _deduct_cost(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Deduct actual cost from agent balance"""
        mission_result = context.get('execute_mission_result', {})
        actual_cost = mission_result.get('actual_cost', context['estimated_cost'])
        
        # Implementation would call economy service
        return {'deducted': actual_cost}
    
    async def _refund_cost(self, context: Dict[str, Any], result: Any) -> None:
        """Refund deducted cost"""
        # Implementation would call economy service
        pass
