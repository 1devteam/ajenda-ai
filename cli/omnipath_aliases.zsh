# ============================================================================
# OMNIPATH V5.0 - ZSH ALIASES
# 
# INSTALLATION:
# 1. Copy this file to: ~/.config/omnipath/aliases.zsh
# 2. Add to your ~/.zshrc: source ~/.config/omnipath/aliases.zsh
# 3. Reload: source ~/.zshrc
#
# QUICK INSTALL:
# mkdir -p ~/.config/omnipath
# cp omnipath_aliases.zsh ~/.config/omnipath/aliases.zsh
# echo "source ~/.config/omnipath/aliases.zsh" >> ~/.zshrc
# source ~/.zshrc
# ============================================================================

# Project Navigation
alias op='cd ~/projects/omnipath_v2'
alias opc='cd ~/projects/omnipath_v2/cli'
alias opb='cd ~/projects/omnipath_v2/backend'

# Docker Management
alias opup='cd ~/projects/omnipath_v2 && docker-compose -f docker-compose.v3.yml up -d'
alias opdown='cd ~/projects/omnipath_v2 && docker-compose -f docker-compose.v3.yml down'
alias oprestart='cd ~/projects/omnipath_v2 && docker-compose -f docker-compose.v3.yml restart'
alias oprebuild='cd ~/projects/omnipath_v2 && docker-compose -f docker-compose.v3.yml down && docker-compose -f docker-compose.v3.yml build --no-cache && docker-compose -f docker-compose.v3.yml up -d'
alias oplogs='cd ~/projects/omnipath_v2 && docker-compose -f docker-compose.v3.yml logs -f'
alias opps='cd ~/projects/omnipath_v2 && docker-compose -f docker-compose.v3.yml ps'

# Service-Specific Logs
alias oplogs-backend='docker logs -f omnipath-backend'
alias oplogs-grafana='docker logs -f omnipath-grafana'
alias oplogs-postgres='docker logs -f omnipath-postgres'

# CLI Shortcuts
alias opcli='cd ~/projects/omnipath_v2/cli && python omnipath.py'
alias opstatus='cd ~/projects/omnipath_v2/cli && python omnipath.py status'
alias opagents='cd ~/projects/omnipath_v2/cli && python omnipath.py agent list'
alias opmissions='cd ~/projects/omnipath_v2/cli && python omnipath.py mission list'
alias opleaderboard='cd ~/projects/omnipath_v2/cli && python omnipath.py learning leaderboard'
alias opinsights='cd ~/projects/omnipath_v2/cli && python omnipath.py learning insights'

# Quick Access URLs (opens in browser)
alias opgrafana='open http://localhost:3000'  # Use 'xdg-open' on Linux
alias opapi='open http://localhost:8000/docs'
alias opjaeger='open http://localhost:16686'
alias opprom='open http://localhost:9090'

# Health Checks
alias ophealth='curl -s http://localhost:8000/health | jq'
alias opmetrics='curl -s http://localhost:8000/metrics | head -50'

# Git Shortcuts
alias opgit='cd ~/projects/omnipath_v2 && git status'
alias oppull='cd ~/projects/omnipath_v2 && git pull origin v5.0-rewrite'
alias oppush='cd ~/projects/omnipath_v2 && git push origin v5.0-rewrite'

# Development
alias optest='cd ~/projects/omnipath_v2 && pytest tests/ -v'
alias opclean='cd ~/projects/omnipath_v2 && find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null'

# Quick Functions
opexec() {
    # Execute command in backend container
    docker exec -it omnipath-backend "$@"
}

opsql() {
    # Connect to PostgreSQL
    docker exec -it omnipath-postgres psql -U omnipath -d omnipath
}

opredis() {
    # Connect to Redis CLI
    docker exec -it omnipath-redis redis-cli
}

# ============================================================================
# USAGE EXAMPLES:
# 
# op          - Go to project directory
# opup        - Start all services
# opstatus    - Check system status
# opagents    - List all agents
# opgrafana   - Open Grafana in browser
# ophealth    - Check API health
# oplogs      - Follow all container logs
# opsql       - Open PostgreSQL shell
# ============================================================================
