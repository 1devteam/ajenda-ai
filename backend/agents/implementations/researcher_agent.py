"""
Researcher Agent for Omnipath V2
Built with Pride for Obex Blackvault

Specialized agent for conducting research, gathering information,
and synthesizing findings from multiple sources.
"""

from typing import Dict, Any, List
import logging

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.language_models import BaseChatModel

from backend.agents.workflows.reasoning_graph import ReasoningWorkflow
from backend.agents.tools.tool_registry import get_tool_registry, ToolCategory
from backend.integrations.observability.prometheus_metrics import get_metrics
from backend.agents.implementations.compliance_wrapper import ComplianceAwareMixin

logger = logging.getLogger(__name__)


class ResearcherAgent(ComplianceAwareMixin):
    """
    Specialized agent for research tasks.
    
    Capabilities:
    - Web search and information gathering
    - Multi-source synthesis
    - Fact verification
    - Citation management
    """
    
    def __init__(
        self,
        agent_id: str,
        llm: BaseChatModel,
        tenant_id: str,
        **kwargs
    ):
        self.agent_id = agent_id
        self.agent_type = "researcher"
        self.llm = llm
        self.tenant_id = tenant_id
        
        # Initialize reasoning workflow
        self.reasoning_workflow = ReasoningWorkflow(llm=llm, max_iterations=7)
        
        # Get tools
        self.tool_registry = get_tool_registry()
        self.web_search = self.tool_registry.get_tool("web_search")
        self.calculator = self.tool_registry.get_tool("calculator")
        
        # Metrics
        self.metrics = get_metrics()
        
        # Initialize compliance (baked in!)
        self._init_compliance()
        
        logger.info(f"Researcher agent {agent_id} initialized with compliance")
    
    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a research task.
        
        Args:
            task: Research task with 'query' and optional 'depth'
            
        Returns:
            Research findings with sources
        """
        query = task.get("query", "")
        depth = task.get("depth", "standard")  # shallow, standard, deep
        
        if not query:
            return {
                "success": False,
                "error": "No research query provided"
            }
        
        try:
            # Record agent invocation
            self.metrics.record_agent_invocation(
                agent_type="researcher",
                model=self.llm.model_name if hasattr(self.llm, 'model_name') else "unknown"
            )
            
            # Step 1: Conduct initial web search (with compliance)
            search_results = await self._execute_tool_with_compliance(
                tool_name="web_search",
                tool_instance=self.web_search,
                parameters={
                    "query": query,
                    "max_results": 10 if depth == "deep" else 5
                },
                mission_payload={"task": query, "depth": depth}
            )
            
            if not search_results.get("success"):
                return {
                    "success": False,
                    "error": f"Web search failed: {search_results.get('error')}"
                }
            
            # Step 2: Analyze and synthesize findings
            synthesis_prompt = self._build_synthesis_prompt(query, search_results)
            
            # Use reasoning workflow for deep analysis
            if depth == "deep":
                analysis = await self.reasoning_workflow.run(synthesis_prompt)
                final_answer = analysis["final_answer"]
            else:
                # Quick synthesis for shallow/standard depth
                messages = [
                    SystemMessage(content=self._get_system_prompt()),
                    HumanMessage(content=synthesis_prompt)
                ]
                response = await self.llm.ainvoke(messages)
                final_answer = response.content
            
            # Step 3: Extract key findings and citations
            findings = self._extract_findings(final_answer, search_results)
            
            return {
                "success": True,
                "query": query,
                "depth": depth,
                "findings": findings,
                "sources": search_results["results"],
                "synthesis": final_answer
            }
        
        except Exception as e:
            logger.error(f"Research task failed: {e}")
            self.metrics.record_agent_error(
                agent_type="researcher",
                error_type=type(e).__name__
            )
            return {
                "success": False,
                "error": str(e)
            }
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for the researcher agent."""
        return """You are an expert research analyst. Your role is to:
1. Synthesize information from multiple sources
2. Identify key insights and patterns
3. Verify facts and cross-reference claims
4. Provide clear, well-cited conclusions

Always maintain objectivity and distinguish between facts and opinions."""
    
    def _build_synthesis_prompt(self, query: str, search_results: Dict[str, Any]) -> str:
        """Build a prompt for synthesizing search results."""
        sources_text = "\n\n".join([
            f"Source {i+1}: {result['title']}\nURL: {result['url']}\n{result['snippet']}"
            for i, result in enumerate(search_results["results"])
        ])
        
        return f"""Research Query: {query}

Sources:
{sources_text}

Task: Analyze these sources and provide a comprehensive answer to the research query. Include:
1. Key findings
2. Supporting evidence from sources
3. Any conflicting information
4. Confidence level in the findings
5. Recommendations for further research if needed"""
    
    def _extract_findings(self, synthesis: str, search_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract structured findings from synthesis."""
        # Simple extraction (could be enhanced with NLP)
        findings = []
        
        # Split synthesis into sentences
        sentences = [s.strip() for s in synthesis.split('.') if s.strip()]
        
        for i, sentence in enumerate(sentences[:5]):  # Top 5 findings
            findings.append({
                "id": i + 1,
                "statement": sentence,
                "confidence": "high" if i < 2 else "medium"  # Simplified confidence
            })
        
        return findings


class AnalystAgent(ComplianceAwareMixin):
    """
    Specialized agent for data analysis and insights.
    
    Capabilities:
    - Data processing and analysis
    - Statistical calculations
    - Trend identification
    - Visualization recommendations
    """
    
    def __init__(
        self,
        agent_id: str,
        llm: BaseChatModel,
        tenant_id: str,
        **kwargs
    ):
        self.agent_id = agent_id
        self.agent_type = "analyst"
        self.llm = llm
        self.tenant_id = tenant_id
        
        # Initialize reasoning workflow
        self.reasoning_workflow = ReasoningWorkflow(llm=llm, max_iterations=5)
        
        # Get tools
        self.tool_registry = get_tool_registry()
        self.calculator = self.tool_registry.get_tool("calculator")
        self.python_executor = self.tool_registry.get_tool("python_executor")
        
        # Metrics
        self.metrics = get_metrics()
        
        # Initialize compliance (baked in!)
        self._init_compliance()
        
        logger.info(f"Analyst agent {agent_id} initialized with compliance")
    
    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an analysis task.
        
        Args:
            task: Analysis task with 'data' and 'analysis_type'
            
        Returns:
            Analysis results with insights
        """
        data = task.get("data", {})
        analysis_type = task.get("analysis_type", "descriptive")
        
        try:
            # Record agent invocation
            self.metrics.record_agent_invocation(
                agent_type="analyst",
                model=self.llm.model_name if hasattr(self.llm, 'model_name') else "unknown"
            )
            
            # Step 1: Understand the data structure
            data_summary = self._summarize_data(data)
            
            # Step 2: Perform analysis using reasoning workflow
            analysis_objective = f"""Analyze the following data and provide {analysis_type} insights:

Data Summary: {data_summary}

Provide:
1. Key metrics and statistics
2. Notable patterns or trends
3. Anomalies or outliers
4. Actionable recommendations"""
            
            analysis = await self.reasoning_workflow.run(analysis_objective)
            
            # Step 3: Perform calculations if needed
            calculations = await self._perform_calculations(data)
            
            return {
                "success": True,
                "analysis_type": analysis_type,
                "insights": analysis["final_answer"],
                "calculations": calculations,
                "data_summary": data_summary
            }
        
        except Exception as e:
            logger.error(f"Analysis task failed: {e}")
            self.metrics.record_agent_error(
                agent_type="analyst",
                error_type=type(e).__name__
            )
            return {
                "success": False,
                "error": str(e)
            }
    
    def _summarize_data(self, data: Dict[str, Any]) -> str:
        """Create a summary of the data structure."""
        if isinstance(data, dict):
            return f"Dictionary with {len(data)} keys: {list(data.keys())}"
        elif isinstance(data, list):
            return f"List with {len(data)} items"
        else:
            return f"Data type: {type(data).__name__}"
    
    async def _perform_calculations(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Perform statistical calculations on the data."""
        calculations = {}
        
        # Extract numeric values
        numeric_values = []
        if isinstance(data, dict):
            numeric_values = [v for v in data.values() if isinstance(v, (int, float))]
        elif isinstance(data, list):
            numeric_values = [v for v in data if isinstance(v, (int, float))]
        
        if numeric_values:
            # Calculate basic statistics
            calculations["mean"] = sum(numeric_values) / len(numeric_values)
            calculations["min"] = min(numeric_values)
            calculations["max"] = max(numeric_values)
            calculations["count"] = len(numeric_values)
        
        return calculations


class DeveloperAgent(ComplianceAwareMixin):
    """
    Specialized agent for code generation and debugging.
    
    Capabilities:
    - Code generation
    - Debugging and error analysis
    - Code review
    - Test generation
    """
    
    def __init__(
        self,
        agent_id: str,
        llm: BaseChatModel,
        tenant_id: str,
        **kwargs
    ):
        self.agent_id = agent_id
        self.agent_type = "developer"
        self.llm = llm
        self.tenant_id = tenant_id
        
        # Initialize reasoning workflow
        self.reasoning_workflow = ReasoningWorkflow(llm=llm, max_iterations=5)
        
        # Get tools
        self.tool_registry = get_tool_registry()
        self.python_executor = self.tool_registry.get_tool("python_executor")
        self.file_reader = self.tool_registry.get_tool("file_reader")
        self.file_writer = self.tool_registry.get_tool("file_writer")
        
        # Metrics
        self.metrics = get_metrics()
        
        # Initialize compliance (baked in!)
        self._init_compliance()
        
        logger.info(f"Developer agent {agent_id} initialized with compliance")
    
    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a development task.
        
        Args:
            task: Development task with 'task_type' and 'specification'
            
        Returns:
            Generated code or analysis results
        """
        task_type = task.get("task_type", "generate")  # generate, debug, review, test
        specification = task.get("specification", "")
        
        try:
            # Record agent invocation
            self.metrics.record_agent_invocation(
                agent_type="developer",
                model=self.llm.model_name if hasattr(self.llm, 'model_name') else "unknown"
            )
            
            if task_type == "generate":
                return await self._generate_code(specification)
            elif task_type == "debug":
                return await self._debug_code(task.get("code", ""), task.get("error", ""))
            elif task_type == "review":
                return await self._review_code(task.get("code", ""))
            elif task_type == "test":
                return await self._generate_tests(task.get("code", ""))
            else:
                return {
                    "success": False,
                    "error": f"Unknown task type: {task_type}"
                }
        
        except Exception as e:
            logger.error(f"Development task failed: {e}")
            self.metrics.record_agent_error(
                agent_type="developer",
                error_type=type(e).__name__
            )
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _generate_code(self, specification: str) -> Dict[str, Any]:
        """Generate code based on specification."""
        system_prompt = """You are an expert software developer. Generate clean, well-documented, production-ready code.
Follow best practices:
- Type hints
- Docstrings
- Error handling
- Clear variable names"""
        
        user_prompt = f"""Generate Python code for the following specification:

{specification}

Provide complete, runnable code with comments."""
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = await self.llm.ainvoke(messages)
        generated_code = response.content
        
        # Test the generated code (with compliance)
        test_result = await self._execute_tool_with_compliance(
            tool_name="python_executor",
            tool_instance=self.python_executor,
            parameters={"code": generated_code},
            mission_payload={"task_type": "generate", "specification": specification}
        )
        
        return {
            "success": True,
            "code": generated_code,
            "test_result": test_result
        }
    
    async def _debug_code(self, code: str, error: str) -> Dict[str, Any]:
        """Debug code and provide fixes."""
        debug_objective = f"""Debug the following code that produces this error:

Error: {error}

Code:
{code}

Identify the issue and provide a corrected version."""
        
        analysis = await self.reasoning_workflow.run(debug_objective)
        
        return {
            "success": True,
            "analysis": analysis["final_answer"],
            "original_error": error
        }
    
    async def _review_code(self, code: str) -> Dict[str, Any]:
        """Review code and provide feedback."""
        system_prompt = """You are a senior code reviewer. Provide constructive feedback on:
1. Code quality and style
2. Potential bugs
3. Performance issues
4. Security concerns
5. Suggestions for improvement"""
        
        user_prompt = f"""Review this code:

{code}"""
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = await self.llm.ainvoke(messages)
        
        return {
            "success": True,
            "review": response.content
        }
    
    async def _generate_tests(self, code: str) -> Dict[str, Any]:
        """Generate unit tests for code."""
        system_prompt = """You are a test automation expert. Generate comprehensive unit tests using pytest."""
        
        user_prompt = f"""Generate unit tests for this code:

{code}

Include:
- Happy path tests
- Edge cases
- Error handling tests"""
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = await self.llm.ainvoke(messages)
        
        return {
            "success": True,
            "tests": response.content
        }
