"""
Redis Cache Manager
Caching strategy for governance system

Built with Pride for Obex Blackvault
"""
import json
import redis
from typing import Optional, Any, Dict, List
from datetime import timedelta
import hashlib

from backend.config.settings import settings


class CacheManager:
    """
    Redis cache manager for governance system
    
    Implements caching strategies:
    - Risk scores (30-day TTL)
    - Policy evaluations (5-min TTL)
    - Asset metadata (1-hour TTL)
    - Compliance status (1-hour TTL)
    - Approval queues (real-time, no TTL)
    """
    
    # Cache key prefixes
    PREFIX_RISK = "governance:risk:"
    PREFIX_POLICY_EVAL = "governance:policy_eval:"
    PREFIX_ASSET = "governance:asset:"
    PREFIX_COMPLIANCE = "governance:compliance:"
    PREFIX_APPROVAL_QUEUE = "governance:approval_queue:"
    
    # TTL values (seconds)
    TTL_RISK = 30 * 24 * 60 * 60  # 30 days
    TTL_POLICY_EVAL = 5 * 60  # 5 minutes
    TTL_ASSET = 60 * 60  # 1 hour
    TTL_COMPLIANCE = 60 * 60  # 1 hour
    
    def __init__(self):
        """Initialize Redis connection"""
        self.redis_client = redis.from_url(
            settings.REDIS_URL,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=True
        )
    
    def _serialize(self, value: Any) -> str:
        """
        Serialize value to JSON string
        
        Args:
            value: Value to serialize
            
        Returns:
            JSON string
        """
        return json.dumps(value)
    
    def _deserialize(self, value: Optional[str]) -> Any:
        """
        Deserialize JSON string to value
        
        Args:
            value: JSON string
            
        Returns:
            Deserialized value or None
        """
        if value is None:
            return None
        return json.loads(value)
    
    def _make_key(self, prefix: str, *parts: str) -> str:
        """
        Make cache key from prefix and parts
        
        Args:
            prefix: Key prefix
            *parts: Key parts
            
        Returns:
            Cache key
        """
        return prefix + ":".join(parts)
    
    # Risk Score Caching
    
    def get_risk_score(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """
        Get cached risk score
        
        Args:
            asset_id: Asset ID
            
        Returns:
            Risk score dict or None
        """
        key = self._make_key(self.PREFIX_RISK, asset_id)
        value = self.redis_client.get(key)
        return self._deserialize(value)
    
    def set_risk_score(
        self,
        asset_id: str,
        risk_score: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> None:
        """
        Cache risk score
        
        Args:
            asset_id: Asset ID
            risk_score: Risk score data
            ttl: Optional custom TTL (default: 30 days)
        """
        key = self._make_key(self.PREFIX_RISK, asset_id)
        value = self._serialize(risk_score)
        self.redis_client.setex(key, ttl or self.TTL_RISK, value)
    
    def invalidate_risk_score(self, asset_id: str) -> None:
        """
        Invalidate risk score cache
        
        Args:
            asset_id: Asset ID
        """
        key = self._make_key(self.PREFIX_RISK, asset_id)
        self.redis_client.delete(key)
    
    # Policy Evaluation Caching
    
    def get_policy_evaluation(
        self,
        asset_id: str,
        policy_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached policy evaluation
        
        Args:
            asset_id: Asset ID
            policy_id: Policy ID
            
        Returns:
            Policy evaluation dict or None
        """
        key = self._make_key(self.PREFIX_POLICY_EVAL, asset_id, policy_id)
        value = self.redis_client.get(key)
        return self._deserialize(value)
    
    def set_policy_evaluation(
        self,
        asset_id: str,
        policy_id: str,
        evaluation: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> None:
        """
        Cache policy evaluation
        
        Args:
            asset_id: Asset ID
            policy_id: Policy ID
            evaluation: Evaluation data
            ttl: Optional custom TTL (default: 5 minutes)
        """
        key = self._make_key(self.PREFIX_POLICY_EVAL, asset_id, policy_id)
        value = self._serialize(evaluation)
        self.redis_client.setex(key, ttl or self.TTL_POLICY_EVAL, value)
    
    def invalidate_policy_evaluations(
        self,
        asset_id: Optional[str] = None,
        policy_id: Optional[str] = None
    ) -> int:
        """
        Invalidate policy evaluation caches
        
        Args:
            asset_id: Optional asset ID (invalidate all evals for asset)
            policy_id: Optional policy ID (invalidate all evals for policy)
            
        Returns:
            Number of keys deleted
        """
        if asset_id:
            pattern = self._make_key(self.PREFIX_POLICY_EVAL, asset_id, "*")
        elif policy_id:
            pattern = self._make_key(self.PREFIX_POLICY_EVAL, "*", policy_id)
        else:
            pattern = self.PREFIX_POLICY_EVAL + "*"
        
        keys = self.redis_client.keys(pattern)
        if keys:
            return self.redis_client.delete(*keys)
        return 0
    
    # Asset Metadata Caching
    
    def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """
        Get cached asset metadata
        
        Args:
            asset_id: Asset ID
            
        Returns:
            Asset dict or None
        """
        key = self._make_key(self.PREFIX_ASSET, asset_id)
        value = self.redis_client.get(key)
        return self._deserialize(value)
    
    def set_asset(
        self,
        asset_id: str,
        asset: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> None:
        """
        Cache asset metadata
        
        Args:
            asset_id: Asset ID
            asset: Asset data
            ttl: Optional custom TTL (default: 1 hour)
        """
        key = self._make_key(self.PREFIX_ASSET, asset_id)
        value = self._serialize(asset)
        self.redis_client.setex(key, ttl or self.TTL_ASSET, value)
    
    def invalidate_asset(self, asset_id: str) -> None:
        """
        Invalidate asset cache and all related caches.
        Gracefully handles Redis being unavailable.
        
        Args:
            asset_id: Asset ID
        """
        try:
            key = self._make_key(self.PREFIX_ASSET, asset_id)
            self.redis_client.delete(key)
            
            # Also invalidate related caches
            self.invalidate_risk_score(asset_id)
            self.invalidate_compliance_status(asset_id)
            self.invalidate_policy_evaluations(asset_id=asset_id)
        except Exception as e:
            # Redis unavailable is non-fatal — log and continue
            import logging
            logging.getLogger(__name__).warning(
                f"Cache invalidation skipped for asset {asset_id}: {e}"
            )
    
    # Compliance Status Caching
    
    def get_compliance_status(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """
        Get cached compliance status
        
        Args:
            asset_id: Asset ID
            
        Returns:
            Compliance status dict or None
        """
        key = self._make_key(self.PREFIX_COMPLIANCE, asset_id)
        value = self.redis_client.get(key)
        return self._deserialize(value)
    
    def set_compliance_status(
        self,
        asset_id: str,
        compliance: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> None:
        """
        Cache compliance status
        
        Args:
            asset_id: Asset ID
            compliance: Compliance data
            ttl: Optional custom TTL (default: 1 hour)
        """
        key = self._make_key(self.PREFIX_COMPLIANCE, asset_id)
        value = self._serialize(compliance)
        self.redis_client.setex(key, ttl or self.TTL_COMPLIANCE, value)
    
    def invalidate_compliance_status(self, asset_id: str) -> None:
        """
        Invalidate compliance status cache
        
        Args:
            asset_id: Asset ID
        """
        key = self._make_key(self.PREFIX_COMPLIANCE, asset_id)
        self.redis_client.delete(key)
    
    # Approval Queue Caching
    
    def get_approval_queue(self, tier: str) -> List[str]:
        """
        Get approval queue for risk tier
        
        Args:
            tier: Risk tier
            
        Returns:
            List of approval IDs
        """
        key = self._make_key(self.PREFIX_APPROVAL_QUEUE, tier)
        values = self.redis_client.lrange(key, 0, -1)
        return values
    
    def add_to_approval_queue(self, tier: str, approval_id: str) -> None:
        """
        Add approval to queue
        
        Args:
            tier: Risk tier
            approval_id: Approval ID
        """
        key = self._make_key(self.PREFIX_APPROVAL_QUEUE, tier)
        self.redis_client.rpush(key, approval_id)
    
    def remove_from_approval_queue(self, tier: str, approval_id: str) -> None:
        """
        Remove approval from queue
        
        Args:
            tier: Risk tier
            approval_id: Approval ID
        """
        key = self._make_key(self.PREFIX_APPROVAL_QUEUE, tier)
        self.redis_client.lrem(key, 0, approval_id)
    
    def get_approval_queue_depth(self, tier: str) -> int:
        """
        Get approval queue depth
        
        Args:
            tier: Risk tier
            
        Returns:
            Queue depth
        """
        key = self._make_key(self.PREFIX_APPROVAL_QUEUE, tier)
        return self.redis_client.llen(key)
    
    # General Cache Operations
    
    def clear_all(self) -> int:
        """
        Clear all governance caches
        
        Returns:
            Number of keys deleted
        """
        patterns = [
            self.PREFIX_RISK + "*",
            self.PREFIX_POLICY_EVAL + "*",
            self.PREFIX_ASSET + "*",
            self.PREFIX_COMPLIANCE + "*",
            self.PREFIX_APPROVAL_QUEUE + "*"
        ]
        
        total_deleted = 0
        for pattern in patterns:
            keys = self.redis_client.keys(pattern)
            if keys:
                total_deleted += self.redis_client.delete(*keys)
        
        return total_deleted
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics
        
        Returns:
            Dictionary with cache stats
        """
        stats = {}
        
        prefixes = {
            "risk_scores": self.PREFIX_RISK,
            "policy_evaluations": self.PREFIX_POLICY_EVAL,
            "assets": self.PREFIX_ASSET,
            "compliance_status": self.PREFIX_COMPLIANCE,
            "approval_queues": self.PREFIX_APPROVAL_QUEUE
        }
        
        for name, prefix in prefixes.items():
            keys = self.redis_client.keys(prefix + "*")
            stats[name] = len(keys)
        
        # Redis info
        info = self.redis_client.info()
        stats["redis_memory_used_mb"] = info.get("used_memory", 0) / (1024 * 1024)
        stats["redis_connected_clients"] = info.get("connected_clients", 0)
        
        return stats
    
    def ping(self) -> bool:
        """
        Check Redis connection
        
        Returns:
            True if connected
        """
        try:
            return self.redis_client.ping()
        except Exception:
            return False


# Global cache manager instance
cache_manager = CacheManager()
