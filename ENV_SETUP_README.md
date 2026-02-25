# Environment Setup Guide

## Quick Start

### 1. Copy the Example File

```bash
cp .env.example .env
```

### 2. Generate Security Secrets

```bash
# Generate SECRET_KEY
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32))"

# Generate JWT_SECRET_KEY
python3 -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(32))"
```

Copy the output and paste into your `.env` file.

### 3. Add Your OpenAI API Key

Get your API key from: https://platform.openai.com/api-keys

Add to `.env`:
```
OPENAI_API_KEY=sk-proj-your-actual-key-here
```

### 4. Test Your Setup

```bash
# Run specialized agent tests
pytest tests/integration/test_specialized_agents.py -v

# Or run all tests
pytest
```

---

## API Keys Status

### ✅ Required

| Provider | Required? | Get Key From | Used By |
|----------|-----------|--------------|---------|
| **OpenAI** | ✅ Yes | https://platform.openai.com/api-keys | ResearcherAgent, AnalystAgent, DeveloperAgent |

### ⚠️ Optional

| Provider | Required? | Get Key From | Used By | Notes |
|----------|-----------|--------------|---------|-------|
| **Anthropic** | ⚠️ Optional | https://console.anthropic.com/settings/keys | Guardian Agent | Requires active billing |
| **Google** | ⚠️ Optional | https://makersuite.google.com/app/apikey | Archivist, Fork Agents | Requires Gemini API enabled |
| **Langfuse** | ⚠️ Optional | https://cloud.langfuse.com | LLM Observability | For monitoring only |

---

## Minimal Setup

For testing, you only need:

```bash
# .env (minimal)
SECRET_KEY=any-random-string-here-at-least-32-chars
JWT_SECRET_KEY=another-random-string-at-least-32-chars
OPENAI_API_KEY=sk-proj-your-actual-key-here

# Disable optional services
OTEL_ENABLED=False
LANGFUSE_ENABLED=False
RATE_LIMIT_ENABLED=False
PROMETHEUS_ENABLED=False
```

---

## Troubleshooting

### "No module named 'dotenv'"

```bash
pip3 install python-dotenv
```

### "Invalid API key"

- Check for extra spaces in `.env`
- Verify key is active on provider's dashboard
- Make sure you're using the correct key format

### "Anthropic credit balance too low"

- Add credits at https://console.anthropic.com/settings/billing
- Or disable Guardian agent by using OpenAI for all agents

### "Google Gemini API not found"

- Enable Gemini API in Google Cloud Console
- Or use OpenAI for all agents instead

---

## Testing Individual Providers

### Test OpenAI

```python
from openai import OpenAI
client = OpenAI()  # Uses OPENAI_API_KEY from environment
response = client.chat.completions.create(
    model="gpt-4-turbo",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

### Test Anthropic

```python
from anthropic import Anthropic
client = Anthropic()  # Uses ANTHROPIC_API_KEY from environment
response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=100,
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.content[0].text)
```

---

## Security Best Practices

✅ **DO:**
- Keep `.env` file local only (never commit to git)
- Use different keys for development and production
- Rotate keys regularly
- Use environment variables in production

❌ **DON'T:**
- Commit `.env` to git (it's gitignored, but be careful)
- Share your `.env` file
- Use production keys in development
- Hardcode keys in source code

---

## Next Steps

Once your `.env` is configured:

1. **Run tests:** `pytest tests/integration/test_specialized_agents.py -v`
2. **Start server:** `uvicorn backend.main:app --reload`
3. **View docs:** http://localhost:8000/docs
4. **Test agents:** Use the API endpoints at `/api/v1/agents/`

---

## Support

For issues with:
- **API keys:** Contact the respective provider (OpenAI, Anthropic, Google)
- **Omnipath setup:** Check the main README.md
- **Test failures:** Run with `-v` flag for detailed output
