# Phase 6 (v6.5) Proof Missions: The Self-Auditing Workforce

**Objective**: To define and execute a series of real-world, complex missions that force the agent workforce to test its own capabilities, expose architectural and tooling gaps, and provide a clear mandate for the next stage of development. This is not a test of individual components; it is a test of the integrated system's ability to perform meaningful, multi-step work and, ultimately, to improve itself.

---

## Guiding Principle: The Agent as the First QA Engineer

Instead of writing abstract unit tests, we will give the agents real-world engineering tasks. Their success, failure, and the nature of their struggles will provide a more authentic and valuable signal about the system's true capabilities and limitations than any isolated test could.

## The Three Proof Missions

These missions are designed to be executed sequentially by the `WorkforceCoordinator`. Each mission builds on the last, testing a different facet of the system's intelligence and robustness.

### Proof Mission 1: The Code Auditor

*   **Goal**: "Audit the entire `onmiapath_v2` codebase for test coverage gaps. Identify all Python files within the `backend/` directory that do not have a corresponding test file in the `tests/` directory. Produce a markdown report named `test_coverage_gaps.md` listing the untested files, their line counts, and a prioritized plan to write tests for them, starting with the largest and most critical files."
*   **What It Tests**:
    *   **System Understanding**: Can the agents navigate and comprehend the project's file structure?
    *   **Tool Orchestration**: Requires extensive use of `file_reader` (to list files) and `python_executor` (to count lines, e.g., using `wc -l`).
    *   **Analytical Reasoning (Analyst Agent)**: The core of the task is comparing two lists of files and finding the difference.
    *   **Structured Reporting (Writer Agent)**: The final output must be a well-formatted and actionable markdown document.
*   **Acceptance Criteria**:
    *   A file named `test_coverage_gaps.md` is created.
    *   The report correctly identifies all Python files in `backend/` that lack a corresponding `tests/test_*.py` file.
    *   The report includes accurate line counts for each identified file.
    *   The report contains a logical, prioritized plan for adding test coverage.

### Proof Mission 2: The Issue Reproducer

*   **Goal**: "The test suite has 5 known failures when run together, including an `AttributeError` in the `VaultService` tests. Analyze the test files `tests/test_phase2_scheduled_agent.py` and `tests/test_month5_implementations.py`, and the related application code in `backend/core/vault/vault_service.py` and `backend/core/event_sourcing/event_store_impl.py`. Write a minimal, standalone Python script named `reproduce_failures.py` that reliably reproduces at least one of the test failures outside of the `pytest` runner. Add comments to the script explaining the root cause of the failure."
*   **What It Tests**:
    *   **Deep Code Comprehension**: Can the agents understand not just code, but the *interaction* between code and its tests, including mocking and patching?
    *   **Causal Reasoning (Analyst Agent)**: This requires the agent to form a hypothesis about a bug (e.g., "a mock from one test is leaking into another") and design an experiment to prove it.
    *   **Code Generation (Developer Agent)**: The agent must write new, functional Python code to isolate and demonstrate the bug.
*   **Acceptance Criteria**:
    *   A file named `reproduce_failures.py` is created.
    *   Running `python3 reproduce_failures.py` from the command line produces a traceback containing one of the known errors (e.g., `TypeError: EventStore.__init__() got an unexpected keyword argument 'session'` or `AttributeError: Mock object has no attribute 'encrypt'`).
    *   The script contains comments that accurately diagnose the root cause of the test failure (e.g., test isolation issues, incorrect mocking). 

### Proof Mission 3: The Roadmap Updater

*   **Goal**: "The project's `STRATEGIC_ROADMAP.md` is out of date. It only defines Phases 1-3. Read the git log to identify the feature commits for Phases 4 and 5. Then, read the code for the `WorkforceCoordinator` (Phase 4) and `RevenueAgent` (Phase 5) to understand what was built. Update `STRATEGIC_ROADMAP.md` to include accurate, detailed sections for Phase 4 (v6.3) and Phase 5 (v6.4), and define a new placeholder for Phase 6 (v6.5). The updated document must be well-formatted and reflect the true state of the completed work."
*   **What It Tests**:
    *   **Historical Context**: Can the agent use `git` and the filesystem to reconstruct the project's history?
    *   **Code-to-Concept Mapping**: Can the agent read hundreds of lines of code and synthesize a high-level, human-readable summary of what a component does?
    *   **Technical Writing (Writer Agent)**: This is the most advanced test of the Writer agent, requiring it to produce documentation that is both technically accurate and stylistically consistent with the existing document.
    *   **Self-Correction**: This task is the ultimate act of self-improvement: the agent is updating its own mission-critical documentation.
*   **Acceptance Criteria**:
    *   The `STRATEGIC_ROADMAP.md` file is modified in place.
    *   The file now contains accurate and detailed sections for "Phase 4: The Coordinating Agent (v6.3)" and "Phase 5: The Revenue Agent (v6.4)".
    *   The descriptions for these phases accurately reflect the functionality present in the codebase.
    *   A new, empty section for "Phase 6: The Self-Auditing Workforce (v6.5)" is added.

---

## Next Steps

With the missions defined, the next phase is to fix the pre-existing test failures to ensure we have a stable baseline before executing these proof missions. This is a prerequisite proper action.
