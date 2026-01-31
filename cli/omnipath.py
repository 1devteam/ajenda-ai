#!/usr/bin/env python3
"""
Omnipath CLI - Command Line Interface for Omnipath v5.0
Professional CLI for managing agents, missions, and the agent economy
"""
import typer
import httpx
import json
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint
from pathlib import Path
import os

# Initialize Typer app and Rich console
app = typer.Typer(
    name="omnipath",
    help="🚀 Omnipath CLI - Manage your AI agent economy",
    add_completion=False
)
console = Console()

# API Configuration
API_BASE_URL = os.getenv("OMNIPATH_API_URL", "http://localhost:8000")
CONFIG_FILE = Path.home() / ".omnipath" / "config.json"


# ============================================================================
# Configuration Management
# ============================================================================

def load_config() -> dict:
    """Load CLI configuration"""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def save_config(config: dict):
    """Save CLI configuration"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_auth_headers() -> dict:
    """Get authentication headers from config"""
    config = load_config()
    token = config.get("auth_token")
    if not token:
        console.print("[red]❌ Not authenticated. Run 'omnipath auth login' first.[/red]")
        raise typer.Exit(1)
    return {"Authorization": f"Bearer {token}"}


# ============================================================================
# Auth Commands
# ============================================================================

@app.command()
def login(
    email: str = typer.Option(..., prompt=True, help="Your email"),
    password: str = typer.Option(..., prompt=True, hide_input=True, help="Your password")
):
    """🔐 Login to Omnipath"""
    try:
        with httpx.Client() as client:
            response = client.post(
                f"{API_BASE_URL}/api/v1/auth/login",
                json={"email": email, "password": password}
            )
            response.raise_for_status()
            data = response.json()
            
            # Save token
            config = load_config()
            config["auth_token"] = data["access_token"]
            config["user"] = data["user"]
            save_config(config)
            
            console.print(f"[green]✅ Logged in as {data['user']['email']}[/green]")
    except httpx.HTTPStatusError as e:
        console.print(f"[red]❌ Login failed: {e.response.text}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command()
def logout():
    """🚪 Logout from Omnipath"""
    config = load_config()
    if "auth_token" in config:
        del config["auth_token"]
        del config["user"]
        save_config(config)
        console.print("[green]✅ Logged out successfully[/green]")
    else:
        console.print("[yellow]⚠️  Not logged in[/yellow]")


@app.command()
def whoami():
    """👤 Show current user"""
    config = load_config()
    if "user" in config:
        user = config["user"]
        panel = Panel(
            f"[bold]Email:[/bold] {user['email']}\\n"
            f"[bold]Role:[/bold] {user['role']}\\n"
            f"[bold]Tenant:[/bold] {user['tenant_id']}",
            title="Current User",
            border_style="green"
        )
        console.print(panel)
    else:
        console.print("[yellow]⚠️  Not logged in[/yellow]")


# ============================================================================
# Agent Commands
# ============================================================================

agent_app = typer.Typer(help="🤖 Manage AI agents")
app.add_typer(agent_app, name="agent")


@agent_app.command("list")
def agent_list():
    """📋 List all agents"""
    try:
        headers = get_auth_headers()
        with httpx.Client() as client:
            response = client.get(
                f"{API_BASE_URL}/api/v1/agents",
                headers=headers
            )
            response.raise_for_status()
            agents = response.json()
            
            if not agents:
                console.print("[yellow]No agents found[/yellow]")
                return
            
            table = Table(title="🤖 Agents", show_header=True, header_style="bold magenta")
            table.add_column("ID", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Type", style="blue")
            table.add_column("Status", style="yellow")
            table.add_column("Model")
            
            for agent in agents:
                table.add_row(
                    agent["id"],
                    agent["name"],
                    agent["type"],
                    agent["status"],
                    agent["model"]
                )
            
            console.print(table)
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


@agent_app.command("create")
def agent_create(
    name: str = typer.Option(..., help="Agent name"),
    agent_type: str = typer.Option("commander", help="Agent type (commander/guardian/archivist/fork)"),
    model: str = typer.Option("gpt-4", help="LLM model to use"),
    temperature: float = typer.Option(0.7, help="Model temperature (0.0-1.0)")
):
    """➕ Create a new agent"""
    try:
        headers = get_auth_headers()
        with httpx.Client() as client:
            response = client.post(
                f"{API_BASE_URL}/api/v1/agents",
                headers=headers,
                json={
                    "name": name,
                    "type": agent_type,
                    "model": model,
                    "temperature": temperature
                }
            )
            response.raise_for_status()
            agent = response.json()
            
            console.print(f"[green]✅ Agent created: {agent['id']}[/green]")
            console.print(f"   Name: {agent['name']}")
            console.print(f"   Type: {agent['type']}")
            console.print(f"   Model: {agent['model']}")
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


@agent_app.command("delete")
def agent_delete(
    agent_id: str = typer.Argument(..., help="Agent ID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")
):
    """🗑️  Delete an agent"""
    if not force:
        confirm = typer.confirm(f"Are you sure you want to delete agent {agent_id}?")
        if not confirm:
            console.print("[yellow]Cancelled[/yellow]")
            return
    
    try:
        headers = get_auth_headers()
        with httpx.Client() as client:
            response = client.delete(
                f"{API_BASE_URL}/api/v1/agents/{agent_id}",
                headers=headers
            )
            response.raise_for_status()
            console.print(f"[green]✅ Agent {agent_id} deleted[/green]")
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ============================================================================
# Mission Commands
# ============================================================================

mission_app = typer.Typer(help="🎯 Manage missions")
app.add_typer(mission_app, name="mission")


@mission_app.command("launch")
def mission_launch(
    agent_id: str = typer.Option(..., help="Agent ID to run the mission"),
    objective: str = typer.Option(..., help="Mission objective"),
    priority: str = typer.Option("normal", help="Priority (low/normal/high/critical)")
):
    """🚀 Launch a new mission"""
    try:
        headers = get_auth_headers()
        with httpx.Client() as client:
            response = client.post(
                f"{API_BASE_URL}/api/v1/missions",
                headers=headers,
                json={
                    "agent_id": agent_id,
                    "objective": objective,
                    "priority": priority
                }
            )
            response.raise_for_status()
            mission = response.json()
            
            console.print(f"[green]✅ Mission launched: {mission['id']}[/green]")
            console.print(f"   Objective: {mission['objective']}")
            console.print(f"   Status: {mission['status']}")
            console.print(f"   Priority: {mission['priority']}")
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


@mission_app.command("list")
def mission_list(
    agent_id: Optional[str] = typer.Option(None, help="Filter by agent ID"),
    status: Optional[str] = typer.Option(None, help="Filter by status")
):
    """📋 List missions"""
    try:
        headers = get_auth_headers()
        params = {}
        if agent_id:
            params["agent_id"] = agent_id
        if status:
            params["status"] = status
        
        with httpx.Client() as client:
            response = client.get(
                f"{API_BASE_URL}/api/v1/missions",
                headers=headers,
                params=params
            )
            response.raise_for_status()
            missions = response.json()
            
            if not missions:
                console.print("[yellow]No missions found[/yellow]")
                return
            
            table = Table(title="🎯 Missions", show_header=True, header_style="bold magenta")
            table.add_column("ID", style="cyan")
            table.add_column("Objective", style="green")
            table.add_column("Agent", style="blue")
            table.add_column("Status", style="yellow")
            table.add_column("Priority")
            
            for mission in missions:
                table.add_row(
                    mission["id"][:8],
                    mission["objective"][:50],
                    mission["agent_id"][:8],
                    mission["status"],
                    mission["priority"]
                )
            
            console.print(table)
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


@mission_app.command("status")
def mission_status(mission_id: str = typer.Argument(..., help="Mission ID")):
    """📊 Get mission status"""
    try:
        headers = get_auth_headers()
        with httpx.Client() as client:
            response = client.get(
                f"{API_BASE_URL}/api/v1/missions/{mission_id}",
                headers=headers
            )
            response.raise_for_status()
            mission = response.json()
            
            panel = Panel(
                f"[bold]ID:[/bold] {mission['id']}\\n"
                f"[bold]Objective:[/bold] {mission['objective']}\\n"
                f"[bold]Status:[/bold] {mission['status']}\\n"
                f"[bold]Priority:[/bold] {mission['priority']}\\n"
                f"[bold]Agent:[/bold] {mission['agent_id']}\\n"
                f"[bold]Created:[/bold] {mission['created_at']}",
                title="Mission Details",
                border_style="green"
            )
            console.print(panel)
            
            if mission.get("result"):
                console.print("\\n[bold]Result:[/bold]")
                console.print(json.dumps(mission["result"], indent=2))
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ============================================================================
# Economy Commands
# ============================================================================

economy_app = typer.Typer(help="💰 Manage agent economy")
app.add_typer(economy_app, name="economy")


@economy_app.command("balance")
def economy_balance(agent_id: Optional[str] = typer.Option(None, help="Specific agent ID")):
    """💵 Check agent balances"""
    try:
        headers = get_auth_headers()
        with httpx.Client() as client:
            response = client.get(
                f"{API_BASE_URL}/api/v1/economy/balance",
                headers=headers
            )
            response.raise_for_status()
            balances = response.json()
            
            if not balances:
                console.print("[yellow]No balances found[/yellow]")
                return
            
            # Filter by agent_id if specified
            if agent_id:
                balances = [b for b in balances if b["agent_id"] == agent_id]
            
            table = Table(title="💰 Agent Balances", show_header=True, header_style="bold magenta")
            table.add_column("Agent ID", style="cyan")
            table.add_column("Balance", style="green", justify="right")
            table.add_column("Total Earned", style="blue", justify="right")
            table.add_column("Total Spent", style="red", justify="right")
            
            for balance in balances:
                table.add_row(
                    balance["agent_id"][:12],
                    f"{balance['balance']:.2f}",
                    f"{balance.get('total_earned', 0):.2f}",
                    f"{balance.get('total_spent', 0):.2f}"
                )
            
            console.print(table)
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


@economy_app.command("transactions")
def economy_transactions(
    agent_id: Optional[str] = typer.Option(None, help="Filter by agent ID"),
    limit: int = typer.Option(20, help="Number of transactions to show")
):
    """📜 View transaction history"""
    try:
        headers = get_auth_headers()
        params = {"limit": limit}
        if agent_id:
            params["agent_id"] = agent_id
        
        with httpx.Client() as client:
            response = client.get(
                f"{API_BASE_URL}/api/v1/economy/transactions",
                headers=headers,
                params=params
            )
            response.raise_for_status()
            transactions = response.json()
            
            if not transactions:
                console.print("[yellow]No transactions found[/yellow]")
                return
            
            table = Table(title="📜 Transactions", show_header=True, header_style="bold magenta")
            table.add_column("Time", style="cyan")
            table.add_column("Agent", style="blue")
            table.add_column("Type", style="yellow")
            table.add_column("Amount", justify="right")
            table.add_column("Resource")
            
            for tx in transactions:
                amount_color = "green" if tx["type"] == "reward" else "red"
                amount_prefix = "+" if tx["type"] == "reward" else "-"
                table.add_row(
                    tx["timestamp"][:19],
                    tx["agent_id"][:12],
                    tx["type"],
                    f"[{amount_color}]{amount_prefix}{tx['amount']:.2f}[/{amount_color}]",
                    tx["resource_type"]
                )
            
            console.print(table)
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


@economy_app.command("stats")
def economy_stats():
    """📊 View economy statistics"""
    try:
        headers = get_auth_headers()
        with httpx.Client() as client:
            response = client.get(
                f"{API_BASE_URL}/api/v1/economy/stats",
                headers=headers
            )
            response.raise_for_status()
            stats = response.json()
            
            panel = Panel(
                f"[bold]Total Balance:[/bold] {stats['total_balance']:.2f} credits\\n"
                f"[bold]Total Agents:[/bold] {stats['total_agents']}\\n"
                f"[bold]Total Transactions:[/bold] {stats['total_transactions']}\\n"
                f"[bold]Avg Balance/Agent:[/bold] {stats['avg_balance_per_agent']:.2f} credits",
                title="💰 Economy Statistics",
                border_style="green"
            )
            console.print(panel)
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


@economy_app.command("topup")
def economy_topup(amount: float = typer.Option(..., help="Amount of credits to add")):
    """💳 Add credits to your economy"""
    try:
        headers = get_auth_headers()
        with httpx.Client() as client:
            response = client.post(
                f"{API_BASE_URL}/api/v1/economy/top-up",
                headers=headers,
                params={"amount": amount}
            )
            response.raise_for_status()
            result = response.json()
            
            console.print(f"[green]✅ Added {amount:.2f} credits[/green]")
            console.print(f"   New balance: {result['new_balance']:.2f} credits")
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ============================================================================
# System Commands
# ============================================================================

@app.command()
def status():
    """🏥 Check system status"""
    try:
        with httpx.Client() as client:
            response = client.get(f"{API_BASE_URL}/health")
            response.raise_for_status()
            health = response.json()
            
            console.print(f"[green]✅ Omnipath is running[/green]")
            console.print(f"   Version: {health.get('version', 'unknown')}")
            console.print(f"   Status: {health.get('status', 'unknown')}")
    except Exception as e:
        console.print(f"[red]❌ Omnipath is not reachable: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command()
def version():
    """📦 Show CLI version"""
    console.print("[bold]Omnipath CLI v5.0.0[/bold]")
    console.print("🚀 Professional AI Agent Economy Management")


if __name__ == "__main__":
    app()
