# Multi-Model LLM Strategy Guide

**Omnipath v3.0**  
**Author:** Manus AI  
**Date:** January 28, 2026

---

## Overview

Omnipath v3.0 implements a **flexible multi-model LLM strategy** that allows you to use different AI models for different agents, optimizing for performance, cost, and capability. You can easily switch between providers without changing code.

---

## Supported Providers

| Provider     | Models                                    | Best For                          | Cost     |
| ------------ | ----------------------------------------- | --------------------------------- | -------- |
| **OpenAI**   | GPT-4 Turbo, GPT-4, GPT-3.5 Turbo         | Complex reasoning, general tasks  | High     |
| **Anthropic**| Claude 3.5 Sonnet, Claude 3 Opus/Haiku    | Safety, ethical reasoning         | Medium   |
| **Google**   | Gemini 2.0 Flash, Gemini 1.5 Pro          | Fast inference, cost-effective    | Low      |
| **xAI**      | Grok Beta                                 | Real-time data, humor             | Medium   |
| **Ollama**   | Llama 3.1, Mixtral, Qwen, DeepSeek        | Privacy, no API costs             | Free*    |

*Ollama runs locally, so you only pay for infrastructure.

---

## Quick Start

### 1. Add API Keys to `.env`

```env
# OpenAI
OPENAI_API_KEY=sk-...

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Google
GOOGLE_API_KEY=...

# xAI (Grok)
XAI_API_KEY=xai-...

# Ollama (local)
OLLAMA_BASE_URL=http://localhost:11434
```

### 2. Configure Models Per Agent

```env
# Commander Agent (complex reasoning)
COMMANDER_PROVIDER=openai
COMMANDER_MODEL=gpt-4-turbo
COMMANDER_TEMPERATURE=0.7

# Guardian Agent (safety validation)
GUARDIAN_PROVIDER=anthropic
GUARDIAN_MODEL=claude-3-5-sonnet-20241022
GUARDIAN_TEMPERATURE=0.3

# Archivist Agent (memory/logging)
ARCHIVIST_PROVIDER=google
ARCHIVIST_MODEL=gemini-2.0-flash-exp
ARCHIVIST_TEMPERATURE=0.5

# Fork Agents (workers)
FORK_PROVIDER=google
FORK_MODEL=gemini-2.0-flash-exp
FORK_TEMPERATURE=0.7
```

### 3. Start Omnipath

```bash
docker-compose -f docker-compose.v3.yml up -d
```

That's it! Each agent will now use its configured model automatically.

---

## Easy Model Switching

### Switch All Agents to One Provider

**Use Claude for everything (highest quality):**
```env
COMMANDER_PROVIDER=anthropic
GUARDIAN_PROVIDER=anthropic
ARCHIVIST_PROVIDER=anthropic
FORK_PROVIDER=anthropic
```

**Use Gemini for everything (most cost-effective):**
```env
COMMANDER_PROVIDER=google
GUARDIAN_PROVIDER=google
ARCHIVIST_PROVIDER=google
FORK_PROVIDER=google
```

**Use Grok for everything (real-time data):**
```env
COMMANDER_PROVIDER=xai
COMMANDER_MODEL=grok-beta
GUARDIAN_PROVIDER=xai
ARCHIVIST_PROVIDER=xai
FORK_PROVIDER=xai
```

**Use Ollama for everything (privacy/cost):**
```env
COMMANDER_PROVIDER=ollama
COMMANDER_MODEL=llama3.1:70b
GUARDIAN_PROVIDER=ollama
ARCHIVIST_PROVIDER=ollama
FORK_PROVIDER=ollama
```

### Switch at Runtime (Advanced)

You can also switch models programmatically:

```python
# In your agent code
agent.switch_model(provider="anthropic", model="claude-3-5-sonnet-20241022")

# Or use Grok
agent.switch_model(provider="xai", model="grok-beta")

# Or use local Ollama
agent.switch_model(provider="ollama", model="llama3.1:70b")
```

---

## Recommended Strategies

### Strategy 1: Balanced (Default)

Best balance of performance, cost, and capability.

```env
COMMANDER_PROVIDER=openai          # GPT-4 for complex decisions
GUARDIAN_PROVIDER=anthropic        # Claude for safety
ARCHIVIST_PROVIDER=google          # Gemini for logging
FORK_PROVIDER=google               # Gemini for workers
```

**Cost:** ~$0.10 per 1000 agent actions  
**Performance:** Excellent

---

### Strategy 2: Cost-Optimized

Minimize costs while maintaining good quality.

```env
COMMANDER_PROVIDER=google          # Gemini for decisions
GUARDIAN_PROVIDER=google           # Gemini for safety
ARCHIVIST_PROVIDER=google          # Gemini for logging
FORK_PROVIDER=google               # Gemini for workers
```

**Cost:** ~$0.02 per 1000 agent actions (80% savings)  
**Performance:** Very good

---

### Strategy 3: Maximum Quality

Best possible performance, cost is secondary.

```env
COMMANDER_PROVIDER=openai          # GPT-4 for decisions
GUARDIAN_PROVIDER=anthropic        # Claude for safety
ARCHIVIST_PROVIDER=anthropic       # Claude for logging
FORK_PROVIDER=openai               # GPT-4 for workers
```

**Cost:** ~$0.30 per 1000 agent actions  
**Performance:** Exceptional

---

### Strategy 4: Privacy-First

All processing happens locally, no data leaves your infrastructure.

```env
COMMANDER_PROVIDER=ollama
COMMANDER_MODEL=llama3.1:70b
GUARDIAN_PROVIDER=ollama
GUARDIAN_MODEL=llama3.1:70b
ARCHIVIST_PROVIDER=ollama
ARCHIVIST_MODEL=llama3.1:8b
FORK_PROVIDER=ollama
FORK_MODEL=llama3.1:8b
```

**Cost:** Infrastructure only (no API costs)  
**Performance:** Good (depends on hardware)

---

### Strategy 5: Hybrid (Recommended for Production)

Use the right model for each task.

```env
COMMANDER_PROVIDER=openai          # GPT-4 for critical decisions
GUARDIAN_PROVIDER=anthropic        # Claude for safety (best alignment)
ARCHIVIST_PROVIDER=google          # Gemini for high-volume logging
FORK_PROVIDER=ollama               # Local models for routine tasks
FORK_MODEL=llama3.1:8b
```

**Cost:** ~$0.05 per 1000 agent actions  
**Performance:** Excellent where it matters

---

## Setting Up Ollama (Local Models)

### 1. Install Ollama

```bash
# Linux/Mac
curl -fsSL https://ollama.com/install.sh | sh

# Or use Docker
docker run -d -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
```

### 2. Pull Models

```bash
# Llama 3.1 (70B - best quality)
ollama pull llama3.1:70b

# Llama 3.1 (8B - fast, good for workers)
ollama pull llama3.1:8b

# Mixtral (great for reasoning)
ollama pull mixtral:8x7b

# Qwen (multilingual)
ollama pull qwen2.5:72b
```

### 3. Configure Omnipath

```env
OLLAMA_BASE_URL=http://localhost:11434
FORK_PROVIDER=ollama
FORK_MODEL=llama3.1:8b
```

---

## Model Comparison

### OpenAI GPT-4 Turbo

**Strengths:**
- Industry-leading reasoning
- Excellent tool calling
- Large context (128k tokens)

**Weaknesses:**
- Expensive
- Rate limits

**Best For:** Commander Agent, complex decisions

---

### Anthropic Claude 3.5 Sonnet

**Strengths:**
- Best safety and alignment
- Excellent instruction following
- Huge context (200k tokens)

**Weaknesses:**
- Moderate cost
- Slower than Gemini

**Best For:** Guardian Agent, ethical reasoning

---

### Google Gemini 2.0 Flash

**Strengths:**
- Very fast inference
- Low cost
- Multimodal

**Weaknesses:**
- Slightly less capable than GPT-4

**Best For:** Archivist Agent, Fork Agents, high-volume tasks

---

### xAI Grok

**Strengths:**
- Real-time data access
- Unique personality
- Good reasoning

**Weaknesses:**
- Still in beta
- Limited availability

**Best For:** Agents needing current information

---

### Ollama (Llama 3.1)

**Strengths:**
- Complete privacy
- No API costs
- Customizable

**Weaknesses:**
- Requires local infrastructure
- Slower without GPU

**Best For:** Privacy-sensitive deployments, cost optimization

---

## Troubleshooting

### "API key not found"

Make sure you've added the API key to your `.env` file and restarted the services:

```bash
docker-compose -f docker-compose.v3.yml down
docker-compose -f docker-compose.v3.yml up -d
```

### "Connection refused" (Ollama)

Make sure Ollama is running:

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama if needed
ollama serve
```

### "Model not found"

Pull the model first:

```bash
ollama pull llama3.1:70b
```

---

## Next Steps

1. **Experiment**: Try different providers and see what works best for your use case
2. **Monitor**: Use Langfuse to track LLM costs and performance
3. **Optimize**: Switch to cheaper models for routine tasks, keep expensive models for critical decisions
4. **Scale**: Use Ollama for high-volume, low-stakes tasks to reduce costs

For more information, see the [LLM Provider Guide](LLM_PROVIDER_GUIDE.md).
