# Qualitative Research Provenance Notes

**Recorded:** 2026-08-24

This document records researcher recollection and conceptual history. It is qualitative provenance, not empirical evidence for the study hypotheses.

## Researcher development history

From approximately 2020 through 2026, 1DevTeam's development experimentation with AI repeatedly encountered a core software-coherence problem: an AI could produce a plausible or locally correct fix while failing to account for relationships elsewhere in the system.

Several approaches were attempted before the current dependency-graph framing became explicit.

### System-wide procedural reasoning

Development instructions increasingly emphasized reading relevant files completely, understanding the system before modifying it, searching for all instances, considering system-wide impact and edge cases, avoiding assumptions, producing complete solutions rather than patches, testing thoroughly, and reviewing the result.

These ideas became formalized in the PRIDE development protocol. In retrospect, PRIDE can be viewed as a procedural attempt to increase reasoning scope and first-pass completeness without yet having an explicit machine-readable representation of the system's dependency relationships.

### Whole-system generation

Another attempted strategy was to generate/build a complete system or major architecture in one coherent pass. The intuition was that early architecture could become malformed when developed through many isolated local changes and that broader simultaneous construction might preserve coherence.

This approach increased scope but did not provide a formal mechanism for identifying which relationships actually mattered, measuring blast radius, or maintaining an explicit structural model as the system evolved.

### Dependency-graph realization

In August 2026, Ajenda began leveraging an extended dependency/architecture graph. This provided a more explicit structural framing of a problem that earlier methods had approached procedurally or intuitively: software consists of interacting nodes, contracts, boundaries, and mechanisms whose relationships determine the true impact of a change.

The emerging conceptual progression is:

`instruction -> process -> broad scope -> structural representation -> simulation/optimization`

This progression is a research hypothesis about the evolution of the development methodology, not evidence that the later stages are superior.

## Current conceptual distinction

A procedural instruction such as "consider the entire system" tells an AI how it should behave. A dependency/semantic graph provides an external representation that can help determine what the affected system actually is.

The study will investigate whether explicit structural representation materially improves outcomes beyond procedural system-wide reasoning alone.

## Attribution

The research questions, methodology development, and resulting empirical analysis are being developed under 1DevTeam using Ajenda AI's longitudinal repository history as the initial system of study.
