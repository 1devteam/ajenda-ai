# LLM Provider Guide for Omnipath v3.0

**Author:** Manus AI  
**Date:** January 28, 2026

---

## Overview

Omnipath v3.0 is **LLM-agnostic**, meaning you can use any LLM provider you prefer. The system is designed to work with multiple providers, and you can even use different models for different agents based on their specific needs.

---

## Supported LLM Providers

Omnipath v3.0 supports any provider that is compatible with the **LangChain** framework. The most popular options are:

### 1. OpenAI

**Models**: GPT-4, GPT-4 Turbo, GPT-3.5 Turbo

**Strengths**:
- Industry-leading performance on complex reasoning tasks
- Excellent for general-purpose agent decision-making
- Strong tool-calling capabilities
- Large context windows (up to 128k tokens)

**Cost**: Moderate to high (varies by model)

**Setup**:
```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="gpt-4-turbo",
    temperature=0.7,
    api_key=settings.OPENAI_API_KEY
)
```

**Recommended For**: Commander Agent (decision-making), complex reasoning tasks

---

### 2. Anthropic (Claude)

**Models**: Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku

**Strengths**:
- Excellent at following complex instructions
- Strong safety and alignment
- Very large context windows (up to 200k tokens)
- Great for nuanced, ethical decision-making

**Cost**: Moderate

**Setup**:
```python
from langchain_anthropic import ChatAnthropic

llm = ChatAnthropic(
    model="claude-3-5-sonnet-20241022",
    temperature=0.7,
    api_key=settings.ANTHROPIC_API_KEY
)
```

**Recommended For**: Guardian Agent (safety validation), ethical reasoning

---

### 3. Google (Gemini)

**Models**: Gemini 2.0 Flash, Gemini 1.5 Pro

**Strengths**:
- Very fast inference (especially Flash models)
- Competitive pricing
- Multimodal capabilities (text, images, video)
- Large context windows

**Cost**: Low to moderate

**Setup**:
```python
from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash-exp",
    temperature=0.7,
    google_api_key=settings.GOOGLE_API_KEY
)
```

**Recommended For**: High-volume tasks, cost-sensitive deployments

---

### 4. Open-Source Models (via Ollama or Together AI)

**Models**: Llama 3.1, Mixtral, Qwen, DeepSeek

**Strengths**:
- Full control and privacy (self-hosted)
- No API costs (if self-hosted)
- Customizable and fine-tunable

**Cost**: Infrastructure costs only (if self-hosted)

**Setup (Ollama)**:
```python
from langchain_ollama import ChatOllama

llm = ChatOllama(
    model="llama3.1:70b",
    temperature=0.7,
    base_url="http://localhost:11434"
)
```

**Recommended For**: Privacy-sensitive deployments, cost optimization at scale

---

## My Recommendation for Omnipath

Based on the unique requirements of the Omnipath platform, here's my recommended LLM strategy:

### Multi-Model Strategy

Use **different models for different agents** based on their specific needs:

| Agent Type       | Recommended Model         | Reasoning                                                                 |
| ---------------- | ------------------------- | ------------------------------------------------------------------------- |
| **Commander**    | GPT-4 Turbo or Claude 3.5 | Requires strong reasoning for emotional intelligence and risk assessment  |
| **Guardian**     | Claude 3.5 Sonnet         | Excellent at safety validation and following strict rules                 |
| **Archivist**    | Gemini 2.0 Flash          | Fast, cost-effective for logging and memory management                    |
| **Fork Agents**  | Gemini Flash or GPT-3.5   | Balance of performance and cost for routine tasks                         |

### Cost Optimization

For high-volume production use, consider this hybrid approach:

1.  **Primary**: Use **Gemini 2.0 Flash** for 80% of tasks (fast, cheap, good quality)
2.  **Fallback**: Use **GPT-4 Turbo** for complex decisions that require deeper reasoning
3.  **Safety**: Always use **Claude 3.5** for the Guardian agent

This strategy can reduce costs by **60-70%** compared to using GPT-4 for everything, while maintaining high quality where it matters most.

---

## Configuration in Omnipath

To use multiple models, update your agent implementations to specify the model:

```python
# backend/agents/implementations/commander_agent_v3.py

from langchain_openai import ChatOpenAI
from backend.config.settings import settings

class CommanderAgentV3(BaseAgent):
    def __init__(self, ...):
        super().__init__(...)
        
        # Use GPT-4 for Commander
        self.llm = ChatOpenAI(
            model="gpt-4-turbo",
            temperature=0.7,
            api_key=settings.OPENAI_API_KEY
        )
```

```python
# backend/agents/implementations/guardian_agent.py

from langchain_anthropic import ChatAnthropic

class GuardianAgent(BaseAgent):
    def __init__(self, ...):
        super().__init__(...)
        
        # Use Claude for Guardian
        self.llm = ChatAnthropic(
            model="claude-3-5-sonnet-20241022",
            api_key=settings.ANTHROPIC_API_KEY
        )
```

---

## Environment Variables

Add these to your `.env` file:

```env
# LLM Providers
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...

# Model Selection (optional, for easy switching)
COMMANDER_MODEL=gpt-4-turbo
GUARDIAN_MODEL=claude-3-5-sonnet-20241022
ARCHIVIST_MODEL=gemini-2.0-flash-exp
```

---

## Bottom Line

**You can use any LLM you want**. For the best balance of performance, cost, and capability, I recommend:

-   **Start with OpenAI GPT-4 Turbo** for all agents (simplest setup)
-   **Optimize later** by moving to a multi-model strategy once you understand your usage patterns
-   **For production at scale**, use Gemini Flash for routine tasks and GPT-4/Claude for critical decisions

The Omnipath architecture is designed to make switching between models trivial, so you can experiment and find what works best for your use case.
