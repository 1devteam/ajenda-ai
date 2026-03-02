"""
Reddit Tool — Omnipath v6.1 (The Scheduled Agent)

LangChain-compatible tool for Reddit interactions via PRAW.

Capabilities:
  - Post a new submission to a subreddit (text or link)
  - Comment on an existing post
  - Search a subreddit for posts
  - Get hot/new/top posts from a subreddit

The tool retrieves Reddit credentials from the VaultService at call time,
ensuring credentials are never cached in memory longer than necessary.

Built with Pride for Obex Blackvault
"""

import asyncio
from typing import Any, Dict, Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from backend.core.logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# Input schemas
# =============================================================================


class RedditPostInput(BaseModel):
    """Input for posting a new Reddit submission."""

    subreddit: str = Field(..., description="Subreddit name (without r/ prefix)")
    title: str = Field(..., min_length=1, max_length=300, description="Post title")
    body: str = Field(default="", description="Post body text (for text posts)")
    url: Optional[str] = Field(None, description="URL (for link posts; omit for text posts)")
    flair: Optional[str] = Field(None, description="Optional post flair text")


class RedditCommentInput(BaseModel):
    """Input for commenting on a Reddit post."""

    post_id: str = Field(..., description="Reddit post ID (e.g. 't3_abc123' or just 'abc123')")
    body: str = Field(..., min_length=1, description="Comment text")


class RedditSearchInput(BaseModel):
    """Input for searching Reddit."""

    subreddit: str = Field(..., description="Subreddit to search (use 'all' for all of Reddit)")
    query: str = Field(..., description="Search query")
    sort: str = Field(default="relevance", description="Sort: relevance, hot, top, new, comments")
    limit: int = Field(default=10, ge=1, le=100, description="Number of results to return")


class RedditHotPostsInput(BaseModel):
    """Input for fetching hot posts from a subreddit."""

    subreddit: str = Field(..., description="Subreddit name")
    limit: int = Field(default=10, ge=1, le=100, description="Number of posts to return")


# =============================================================================
# Reddit Tool
# =============================================================================


class RedditTool(BaseTool):
    """
    Multi-action Reddit tool for agent use.

    Actions (specified in the ``action`` field of the input dict):
      - ``post``    — Create a new submission
      - ``comment`` — Comment on an existing post
      - ``search``  — Search a subreddit
      - ``hot``     — Get hot posts from a subreddit

    Credentials are fetched from the VaultService on each call.
    """

    name: str = "reddit"
    description: str = (
        "Interact with Reddit. Actions: post (create submission), comment (reply to post), "
        "search (find posts), hot (get trending posts). "
        "Input must be a JSON dict with 'action' key and action-specific fields."
    )

    # Injected at construction time — not serialised
    vault_service: Any = Field(default=None, exclude=True)
    tenant_id: str = Field(default="", exclude=True)

    class Config:
        arbitrary_types_allowed = True

    def _run(self, tool_input: str, **kwargs) -> str:
        """Synchronous wrapper — runs the async implementation in the event loop."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're inside an async context — use a new thread
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self._arun(tool_input))
                    return future.result()
            else:
                return loop.run_until_complete(self._arun(tool_input))
        except Exception as exc:
            logger.error(f"RedditTool._run failed: {exc}", exc_info=True)
            return f"Error: {exc}"

    async def _arun(self, tool_input: str, **kwargs) -> str:
        """
        Async implementation of the Reddit tool.

        Args:
            tool_input: JSON string with ``action`` and action-specific fields.

        Returns:
            Human-readable result string.
        """
        import json

        try:
            data = json.loads(tool_input) if isinstance(tool_input, str) else tool_input
        except Exception:
            return "Error: tool_input must be a valid JSON string"

        action = data.get("action", "").lower()
        if not action:
            return "Error: 'action' field is required (post, comment, search, hot)"

        # Fetch credentials from vault
        creds = await self._get_credentials()
        if creds is None:
            return (
                "Error: Reddit credentials not found in vault. "
                "Store credentials via POST /api/v1/vault/keys with service='reddit'."
            )

        try:
            reddit = self._build_client(creds)
        except Exception as exc:
            return f"Error: Failed to initialise Reddit client: {exc}"

        try:
            if action == "post":
                return await self._post(reddit, data)
            elif action == "comment":
                return await self._comment(reddit, data)
            elif action == "search":
                return await self._search(reddit, data)
            elif action == "hot":
                return await self._hot(reddit, data)
            else:
                valid = "post, comment, search, hot"
                return f"Error: Unknown action '{action}'. Valid actions: {valid}"
        except Exception as exc:
            logger.error(f"RedditTool action '{action}' failed: {exc}", exc_info=True)
            return f"Error executing Reddit action '{action}': {exc}"

    # =========================================================================
    # Action implementations
    # =========================================================================

    async def _post(self, reddit: Any, data: Dict[str, Any]) -> str:
        """Create a new Reddit submission."""
        try:
            inp = RedditPostInput(**data)
        except Exception as exc:
            return f"Error: Invalid input for 'post' action: {exc}"

        subreddit = reddit.subreddit(inp.subreddit)

        if inp.url:
            submission = subreddit.submit(title=inp.title, url=inp.url)
        else:
            submission = subreddit.submit(title=inp.title, selftext=inp.body)

        if inp.flair:
            try:
                submission.flair.select(inp.flair)
            except Exception:
                pass  # Flair selection is best-effort

        return (
            f"Posted to r/{inp.subreddit}: '{inp.title}'\n"
            f"URL: https://reddit.com{submission.permalink}\n"
            f"Post ID: {submission.id}"
        )

    async def _comment(self, reddit: Any, data: Dict[str, Any]) -> str:
        """Comment on an existing Reddit post."""
        try:
            inp = RedditCommentInput(**data)
        except Exception as exc:
            return f"Error: Invalid input for 'comment' action: {exc}"

        # Normalise post ID (strip t3_ prefix if present)
        post_id = inp.post_id.replace("t3_", "")
        submission = reddit.submission(id=post_id)
        comment = submission.reply(inp.body)

        return (
            f"Commented on post '{submission.title}'\n"
            f"Comment ID: {comment.id}\n"
            f"URL: https://reddit.com{comment.permalink}"
        )  # noqa: E501

    async def _search(self, reddit: Any, data: Dict[str, Any]) -> str:
        """Search Reddit for posts."""
        try:
            inp = RedditSearchInput(**data)
        except Exception as exc:
            return f"Error: Invalid input for 'search' action: {exc}"

        subreddit = reddit.subreddit(inp.subreddit)
        results = list(subreddit.search(inp.query, sort=inp.sort, limit=inp.limit))

        if not results:
            return f"No results found for '{inp.query}' in r/{inp.subreddit}"

        lines = [f"Search results for '{inp.query}' in r/{inp.subreddit}:"]
        for i, post in enumerate(results, 1):
            lines.append(
                f"{i}. [{post.score}↑] {post.title}\n"
                f"   https://reddit.com{post.permalink}"
            )
        return "\n".join(lines)

    async def _hot(self, reddit: Any, data: Dict[str, Any]) -> str:
        """Get hot posts from a subreddit."""
        try:
            inp = RedditHotPostsInput(**data)
        except Exception as exc:
            return f"Error: Invalid input for 'hot' action: {exc}"

        subreddit = reddit.subreddit(inp.subreddit)
        posts = list(subreddit.hot(limit=inp.limit))

        if not posts:
            return f"No posts found in r/{inp.subreddit}"

        lines = [f"Hot posts in r/{inp.subreddit}:"]
        for i, post in enumerate(posts, 1):
            lines.append(
                f"{i}. [{post.score}↑] {post.title}\n"
                f"   https://reddit.com{post.permalink}"
            )
        return "\n".join(lines)

    # =========================================================================
    # Helpers
    # =========================================================================

    async def _get_credentials(self) -> Optional[Dict[str, Any]]:
        """Fetch Reddit credentials from the VaultService."""
        if self.vault_service is None:
            return None
        try:
            return await self.vault_service.get_key(
                tenant_id=self.tenant_id,
                service="reddit",
                key_name="production",
            )
        except Exception as exc:
            logger.error(f"Failed to fetch Reddit credentials from vault: {exc}", exc_info=True)
            return None

    @staticmethod
    def _build_client(creds: Dict[str, Any]) -> Any:
        """
        Build and return a PRAW Reddit client from credentials.

        Expected credential keys:
            client_id:     Reddit app client ID
            client_secret: Reddit app client secret
            username:      Reddit account username
            password:      Reddit account password
            user_agent:    User-agent string (optional)
        """
        import praw

        return praw.Reddit(
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
            username=creds.get("username"),
            password=creds.get("password"),
            user_agent=creds.get("user_agent", "Omnipath/6.1 by Citadel"),
        )


def create_reddit_tool(vault_service: Any, tenant_id: str) -> RedditTool:
    """
    Factory function to create a RedditTool instance.

    Args:
        vault_service: VaultService instance for credential retrieval.
        tenant_id:     Tenant ID for vault key lookup.

    Returns:
        Configured RedditTool instance.
    """
    return RedditTool(vault_service=vault_service, tenant_id=tenant_id)
