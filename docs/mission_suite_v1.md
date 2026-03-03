# Mission Suite v1: Agent Skills & Tools Assessment

**Author**: Manus AI (for Obex Blackvault)
**Status**: Final

---

## 1. Overview

This document defines a suite of three live missions designed to stress-test the Citadel agent workforce. The goal is to move beyond unit tests and evaluate how the agents perform on real, multi-step tasks that require them to use their full toolset and reasoning capabilities.

Each mission is designed to test a specific combination of agent roles, tools, and skills. The results will be used to identify concrete gaps and build a prioritized backlog for the next development phase.

## 2. The Missions

### Mission 1: The Market Analyst

- **Objective**: Produce a competitive analysis report on a publicly traded company.
- **Agent Role**: `ANALYST`
- **Tools Required**: `web_search`, `file_writer`
- **Skills Tested**:
    - Information retrieval from financial news sources.
    - Data extraction and synthesis.
    - Structured report generation.
- **Goal Statement**:
  ```
  Research the financial performance of Snowflake Inc. (NYSE: SNOW) for Q3 2025. Find their latest quarterly earnings report, identify the key financial metrics (Revenue, Net Income, Free Cash Flow), and find two significant news articles or analyst opinions related to their performance. Write a 300-word summary of your findings and save it to /home/ubuntu/mission_1_report.md.
  ```

### Mission 2: The Code Debugger

- **Objective**: Identify and fix a bug in a Python script.
- **Agent Role**: `DEVELOPER`
- **Tools Required**: `file_reader`, `python_executor`, `file_writer`
- **Skills Tested**:
    - Code comprehension and debugging.
    - Using the Python executor to reproduce errors.
    - Proposing and applying a code fix.
- **Goal Statement**:
  ```
  The Python script at /home/ubuntu/buggy_script.py is failing. Read the script, identify the bug, and fix it. The script is supposed to calculate the average of a list of numbers, but it is producing an incorrect result. Save the corrected script back to the same path.
  ```

### Mission 3: The Fact-Checker

- **Objective**: Verify a complex factual claim using multiple sources and perform a calculation.
- **Agent Role**: `RESEARCHER`
- **Tools Required**: `web_search`, `calculator`
- **Skills Tested**:
    - Multi-source fact verification.
    - Numerical data extraction.
    - Using the calculator for a non-trivial calculation.
    - Synthesizing a clear, concise answer.
- **Goal Statement**:
  ```
  Verify the following claim: "The total distance from the Earth to the Moon is less than the combined diameters of all the other planets in our solar system." Use at least two reliable sources for the planetary diameter and Earth-Moon distance data. Show your work by listing the diameter of each planet, summing them, and comparing the total to the Earth-Moon distance. State whether the claim is true or false.
  ```

## 3. Execution & Evaluation

These missions will be executed sequentially using the `MissionExecutor`. The raw output of each mission (files, stdout, final result) will be captured. Each mission will be evaluated on:

- **Success**: Did the agent achieve the goal?
- **Pride**: Were the actions proper? Was the output high quality?
- **Tool Use**: Were the correct tools used effectively?

The findings will be compiled into a final report for Obex, including a prioritized list of gaps and recommended improvements.
