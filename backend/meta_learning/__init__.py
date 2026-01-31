"""
Meta-Learning System for Omnipath v5.0

This module provides agent self-improvement through:
- Performance tracking and analytics
- Adaptive configuration tuning
- Learning insights and recommendations
- Configuration comparison and optimization

Think of it as giving agents a brain that learns from experience!
"""
from .performance_tracker import (
    PerformanceTracker,
    MissionOutcome,
    get_tracker
)
from .adaptive_engine import (
    AdaptiveEngine,
    get_engine
)

__all__ = [
    'PerformanceTracker',
    'MissionOutcome',
    'get_tracker',
    'AdaptiveEngine',
    'get_engine'
]
