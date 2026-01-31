# Omnipath CLI v5.0

Professional command-line interface for managing the Omnipath AI agent economy.

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Make CLI executable
chmod +x omnipath.py

# Optional: Create symlink for easy access
sudo ln -s $(pwd)/omnipath.py /usr/local/bin/omnipath
```

## Quick Start

```bash
# Check system status
./omnipath.py status

# Login (if authentication is enabled)
./omnipath.py login

# Create an agent
./omnipath.py agent create --name "MyAgent" --model gpt-4

# Launch a mission
./omnipath.py mission launch --agent-id <agent-id> --objective "Analyze market trends"

# Check economy balance
./omnipath.py economy balance

# View all commands
./omnipath.py --help
```

## Configuration

The CLI stores configuration in `~/.omnipath/config.json`, including:
- Authentication tokens
- API endpoint (default: http://localhost:8000)
- User preferences

To use a different API endpoint:
```bash
export OMNIPATH_API_URL=https://your-omnipath-instance.com
```

## Commands

### Authentication
- `login` - Login to Omnipath
- `logout` - Logout from Omnipath
- `whoami` - Show current user

### Agent Management
- `agent list` - List all agents
- `agent create` - Create a new agent
- `agent delete` - Delete an agent

### Mission Management
- `mission launch` - Launch a new mission
- `mission list` - List missions
- `mission status` - Get mission details

### Economy Management
- `economy balance` - Check agent balances
- `economy transactions` - View transaction history
- `economy stats` - View economy statistics
- `economy topup` - Add credits to economy

### System
- `status` - Check system health
- `version` - Show CLI version

## Examples

### Create and run a mission
```bash
# Create a commander agent
./omnipath.py agent create --name "Commander-1" --agent-type commander --model gpt-4

# Launch a mission
./omnipath.py mission launch --agent-id <agent-id> --objective "Research AI trends" --priority high

# Check mission status
./omnipath.py mission status <mission-id>
```

### Monitor economy
```bash
# View all balances
./omnipath.py economy balance

# View specific agent balance
./omnipath.py economy balance --agent-id <agent-id>

# View recent transactions
./omnipath.py economy transactions --limit 50

# View economy statistics
./omnipath.py economy stats
```

## Features

- **Rich Terminal UI**: Beautiful tables and panels using Rich library
- **Authentication**: Secure token-based authentication
- **Configuration Management**: Persistent config storage
- **Error Handling**: Clear error messages and status codes
- **Filtering**: Filter agents, missions, and transactions
- **Confirmation Prompts**: Safe deletion with confirmation
- **Environment Variables**: Configurable API endpoint

## Development

The CLI is built with:
- **Typer**: Modern CLI framework with type hints
- **httpx**: Async-capable HTTP client
- **Rich**: Beautiful terminal formatting

## Troubleshooting

**Connection refused:**
```bash
# Make sure the backend is running
docker-compose -f docker-compose.v3.yml ps

# Check if backend is accessible
curl http://localhost:8000/health
```

**Authentication errors:**
```bash
# Re-login
./omnipath.py logout
./omnipath.py login
```

**API endpoint issues:**
```bash
# Set custom endpoint
export OMNIPATH_API_URL=http://your-host:8000
```

## License

Part of the Omnipath v5.0 project.
