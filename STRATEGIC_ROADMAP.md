# Citadel Strategic Roadmap — v6.0

**Date**: March 2, 2026  
**Author**: Manus AI (for Obex Blackvault)  
**Status**: DRAFT

---

## 1. The Vision: From Citadel to Workforce

The current platform, Citadel, is a robust multi-agent reasoning system. It can execute complex missions, it is governed by the Pride Protocol, and it has a complete observability and deployment stack. It is a production-grade foundation.

The vision you have articulated is to evolve Citadel from a mission-based system into a **self-sustaining AI workforce**. This means agents that are not just assigned one-off tasks, but are capable of holding ongoing roles, performing scheduled duties, and actively marketing their own capabilities to generate real-world value.

This document is the map from here to there. It is based on a complete reading of the existing `PROJECT_SPEC.md` and a full audit of the live codebase. It identifies the capability gaps and lays out a phased plan to close them.

---

## 2. Current State vs. Spec: The Honesty Audit

The `PROJECT_SPEC.md` is an excellent document, but it is aspirational. It describes a system where all 7 phases of development are complete. The reality is that while the core infrastructure is solid, several key architectural components listed as "Complete" are actually stubs or are missing entirely.

| Component | Spec Status | Actual Status | Gap Analysis |
|---|---|---|---|
| **Event Sourcing** | ✅ Complete | ⚠️ **Stub** | The `EventStore` is a placeholder. No events are actually being stored. State is not being rebuilt from an event stream. This is the single largest architectural gap. |
| **CQRS** | ✅ Complete | ⚠️ **Stub** | The command/query handlers exist, but without a real event store, they are not operating on a true read/write separated model. |
| **Saga Orchestration** | ✅ Complete | ⚠️ **Stub** | The `SagaOrchestrator` is a placeholder. No long-running business processes are being managed. |
| **MCP Integration** | ✅ Complete | ⚠️ **Partial** | The MCP client and tool registry exist, but the only tools are built-in (`web_search`, `python_executor`, etc.). No external APIs or browser automation tools are integrated. |
| **Economy Persistence** | (Not specified) | ❌ **Missing** | The agent economy is in-memory only. All balances and transactions are lost on restart. |
| **Task Scheduling** | (Not specified) | ❌ **Missing** | There is no mechanism to schedule recurring tasks or missions for agents. |

**Conclusion**: The foundation is strong, but the advanced architectural patterns that enable a true workforce (event sourcing, sagas, persistent state) are not yet implemented. The spec is a good guide for what *to build*, not a description of what *is built*.

---

## 3. The Roadmap: Three Phases to a Workforce

This roadmap is designed to close the gaps and deliver the workforce vision. It is broken into three distinct, sequential phases.

### Phase 1: The Persistent Agent (v6.0)

**Goal**: Give agents memory and identity. Make them persistent entities, not ephemeral processes.

| Feature | Why it matters | Implementation Plan |
|---|---|---|
| **Full Event Sourcing** | Agents need a memory. An event stream is the canonical history of everything an agent has ever done, thought, or learned. It is the foundation of identity. | Implement a real `EventStore` using PostgreSQL. Convert all agent and mission state changes to be event-driven. |
| **Persistent Economy** | An agent cannot be held accountable if its performance record is wiped on every restart. | Move the economy from in-memory to Redis. All balances and transactions will survive restarts. |
| **Agent Profile API** | The frontend needs to be able to see an agent's history, skills, and performance. | Build API endpoints to query the new event store and expose an agent's full history. |

**First Mission (Post-v6.0)**: *"Analyze your own event stream and report on your three most common reasoning patterns."* This proves the agent has a memory and can reflect on it.

### Phase 2: The Scheduled Agent (v6.1)

**Goal**: Give agents the ability to work on a schedule. Move from reactive missions to proactive duties.

| Feature | Why it matters | Implementation Plan |
|---|---|---|
| **Task Scheduler** | A workforce needs to be able to perform recurring tasks — weekly reports, daily checks, hourly monitoring. | Integrate a battle-tested scheduler like `APScheduler`. Add API endpoints to create, manage, and view scheduled jobs. |
| **External Tool Integration (MCP)** | To interact with the world, agents need tools beyond `web_search`. They need to be able to use APIs. | Add a secure mechanism for storing and using external API keys (e.g., social media, CRM, email). Build the first external tool integration (e.g., Reddit API). |
| **Saga Orchestration** | Long-running tasks like "post content every day for a week" need to be managed as a single, stateful process. | Implement a real `SagaOrchestrator` to manage multi-step, long-running missions. |

**First Mission (Post-v6.1)**: *"Using the Reddit API, post the top 3 AI-related news articles to the /r/artificial subreddit every day at 9 AM EST for one week."* This proves the agent can perform a scheduled, multi-day task using an external tool.

### Phase 3: The Self-Marketing Agent (v6.2)

**Goal**: The agent can now market itself. It has memory, it can run on a schedule, and it can use external tools.

| Feature | Why it matters | Implementation Plan |
|---|---|---|
| **Browser Automation (MCP)** | Many platforms (LinkedIn, Facebook, Craigslist) do not have posting APIs. Browser automation is the only way to interact with them. | Integrate a browser automation tool (e.g., Playwright or Selenium) as a new MCP tool. |
| **Lead Generation Workflow** | The agent needs a structured process for finding and qualifying leads. | Build a new agent type or workflow specifically for lead generation, combining web search, browser automation, and analysis. |
| **Outreach & Posting Sagas** | A full marketing campaign is a long-running saga — create accounts, build a profile, make posts, respond to replies. | Design and implement sagas for social media account creation and content posting campaigns. |

**First Mission (Post-v6.2)**: *"Create a LinkedIn profile for Citadel. Find 10 companies in the retail loss-prevention space. Write and publish three posts on the Citadel profile about the ROI of using AI for shrink reduction, referencing the WalX analysis. Report back with the URLs of the posts and any engagement metrics."* This is the ultimate proof of a self-sustaining, self-marketing system.

---

## 4. The First Step: Approve the Roadmap

This document is the proposed plan. It is based on a complete understanding of the current system and your stated vision. If you approve this roadmap, I will commit it to the repo as `STRATEGIC_ROADMAP.md` and it will become the single source of truth for all future work. Every session will start by reading it. Every plan will be a step within it.

This is the path from Citadel to a true AI workforce. Say the word and we begin Phase 1.
