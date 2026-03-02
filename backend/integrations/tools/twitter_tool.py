"""
Twitter/X Posting Tool for Omnipath v2 — Phase 3 (v6.2)

Provides Twitter/X API v2 posting capability to agents via the MCP ToolRegistry.
Supports posting tweets, threading, and fetching engagement metrics.

Requires vault keys:
    twitter/api_key
    twitter/api_secret
    twitter/access_token
    twitter/access_token_secret

Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from backend.agents.tools.tool_registry import BaseTool, ToolCategory
from backend.core.logging_config import get_logger

logger = get_logger(__name__)


class TwitterTool(BaseTool):
    """
    Twitter/X API v2 tool for posting content and reading engagement.

    Supported actions:
        post_tweet    — Post a single tweet (max 280 chars).
        post_thread   — Post a thread of connected tweets.
        get_metrics   — Get engagement metrics for a tweet by ID.
        search_tweets — Search recent tweets by keyword.

    Credentials are resolved in this order:
        1. Explicit kwargs passed to __init__
        2. Environment variables (TWITTER_API_KEY, etc.)
        3. VaultService lookup (if vault_service is provided)

    Args:
        api_key:             Twitter API key (consumer key).
        api_secret:          Twitter API secret (consumer secret).
        access_token:        OAuth 1.0a access token.
        access_token_secret: OAuth 1.0a access token secret.
        bearer_token:        Bearer token for v2 read-only endpoints.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        access_token_secret: Optional[str] = None,
        bearer_token: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or os.getenv("TWITTER_API_KEY", "")
        self._api_secret = api_secret or os.getenv("TWITTER_API_SECRET", "")
        self._access_token = access_token or os.getenv("TWITTER_ACCESS_TOKEN", "")
        self._access_token_secret = (
            access_token_secret or os.getenv("TWITTER_ACCESS_TOKEN_SECRET", "")
        )
        self._bearer_token = bearer_token or os.getenv("TWITTER_BEARER_TOKEN", "")

    # ------------------------------------------------------------------
    # BaseTool interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "twitter"

    @property
    def description(self) -> str:
        return (
            "Post content to Twitter/X and read engagement metrics. "
            "Actions: post_tweet (text), post_thread (texts list), "
            "get_metrics (tweet_id), search_tweets (query). "
            "Requires Twitter API credentials in vault or environment."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.COMMUNICATION

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        action: str,
        text: Optional[str] = None,
        texts: Optional[List[str]] = None,
        tweet_id: Optional[str] = None,
        query: Optional[str] = None,
        max_results: int = 10,
    ) -> Dict[str, Any]:
        """
        Execute a Twitter action.

        Args:
            action:      One of post_tweet|post_thread|get_metrics|search_tweets.
            text:        Tweet text (for post_tweet).
            texts:       List of tweet texts (for post_thread).
            tweet_id:    Tweet ID (for get_metrics).
            query:       Search query (for search_tweets).
            max_results: Max results for search (default 10).

        Returns:
            Result dict with ``success`` and action-specific data.
        """
        try:
            import tweepy
        except ImportError:
            return {
                "success": False,
                "error": "tweepy is not installed. Run: pip install tweepy",
            }

        if not self._api_key or not self._access_token:
            return {
                "success": False,
                "error": (
                    "Twitter credentials not configured. "
                    "Set TWITTER_API_KEY, TWITTER_API_SECRET, "
                    "TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET "
                    "in environment or vault."
                ),
            }

        try:
            client = tweepy.Client(
                bearer_token=self._bearer_token or None,
                consumer_key=self._api_key,
                consumer_secret=self._api_secret,
                access_token=self._access_token,
                access_token_secret=self._access_token_secret,
                wait_on_rate_limit=True,
            )

            if action == "post_tweet":
                return await self._post_tweet(client, text)
            elif action == "post_thread":
                return await self._post_thread(client, texts)
            elif action == "get_metrics":
                return await self._get_metrics(client, tweet_id)
            elif action == "search_tweets":
                return await self._search_tweets(client, query, max_results)
            else:
                return {
                    "success": False,
                    "error": f"Unknown action '{action}'. Valid: post_tweet, post_thread, get_metrics, search_tweets",
                }

        except Exception as exc:
            logger.error(f"TwitterTool action '{action}' failed: {exc}", exc_info=True)
            return {"success": False, "action": action, "error": str(exc)}

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _post_tweet(self, client: Any, text: Optional[str]) -> Dict[str, Any]:
        """Post a single tweet."""
        if not text:
            return {"success": False, "action": "post_tweet", "error": "text is required"}

        if len(text) > 280:
            return {
                "success": False,
                "action": "post_tweet",
                "error": f"Tweet exceeds 280 chars ({len(text)} chars). Truncate or use post_thread.",
            }

        response = client.create_tweet(text=text)
        tweet_id = response.data["id"]
        logger.info(f"TwitterTool: posted tweet {tweet_id}")
        return {
            "success": True,
            "action": "post_tweet",
            "tweet_id": tweet_id,
            "url": f"https://twitter.com/i/web/status/{tweet_id}",
            "text": text,
        }

    async def _post_thread(
        self, client: Any, texts: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Post a thread of connected tweets."""
        if not texts or len(texts) == 0:
            return {"success": False, "action": "post_thread", "error": "texts list is required"}

        tweet_ids = []
        reply_to: Optional[str] = None

        for i, text in enumerate(texts):
            if len(text) > 280:
                return {
                    "success": False,
                    "action": "post_thread",
                    "error": f"Tweet {i + 1} exceeds 280 chars ({len(text)} chars).",
                }

            kwargs: Dict[str, Any] = {"text": text}
            if reply_to:
                kwargs["in_reply_to_tweet_id"] = reply_to

            response = client.create_tweet(**kwargs)
            tweet_id = response.data["id"]
            tweet_ids.append(tweet_id)
            reply_to = tweet_id

        logger.info(f"TwitterTool: posted thread of {len(tweet_ids)} tweets")
        return {
            "success": True,
            "action": "post_thread",
            "tweet_ids": tweet_ids,
            "count": len(tweet_ids),
            "first_url": f"https://twitter.com/i/web/status/{tweet_ids[0]}" if tweet_ids else None,
        }

    async def _get_metrics(
        self, client: Any, tweet_id: Optional[str]
    ) -> Dict[str, Any]:
        """Get engagement metrics for a tweet."""
        if not tweet_id:
            return {"success": False, "action": "get_metrics", "error": "tweet_id is required"}

        tweet = client.get_tweet(
            tweet_id,
            tweet_fields=["public_metrics", "created_at", "text"],
        )
        if not tweet.data:
            return {"success": False, "action": "get_metrics", "error": f"Tweet {tweet_id} not found"}

        metrics = tweet.data.public_metrics or {}
        return {
            "success": True,
            "action": "get_metrics",
            "tweet_id": tweet_id,
            "text": tweet.data.text,
            "created_at": str(tweet.data.created_at),
            "likes": metrics.get("like_count", 0),
            "retweets": metrics.get("retweet_count", 0),
            "replies": metrics.get("reply_count", 0),
            "impressions": metrics.get("impression_count", 0),
        }

    async def _search_tweets(
        self, client: Any, query: Optional[str], max_results: int
    ) -> Dict[str, Any]:
        """Search recent tweets."""
        if not query:
            return {"success": False, "action": "search_tweets", "error": "query is required"}

        # Clamp max_results to Twitter API limits (10-100)
        max_results = max(10, min(100, max_results))

        response = client.search_recent_tweets(
            query=query,
            max_results=max_results,
            tweet_fields=["public_metrics", "created_at", "author_id"],
        )

        tweets = []
        if response.data:
            for tweet in response.data:
                metrics = tweet.public_metrics or {}
                tweets.append({
                    "id": tweet.id,
                    "text": tweet.text,
                    "created_at": str(tweet.created_at),
                    "likes": metrics.get("like_count", 0),
                    "retweets": metrics.get("retweet_count", 0),
                })

        return {
            "success": True,
            "action": "search_tweets",
            "query": query,
            "count": len(tweets),
            "tweets": tweets,
        }
