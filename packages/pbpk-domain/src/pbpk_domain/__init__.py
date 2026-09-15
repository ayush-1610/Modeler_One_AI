"""Deterministic PBPK domain logic for Modeler One.

Nothing in this package performs I/O beyond reading packaged rulesets, calls an LLM, or depends
on the simulation engine. Every function is versioned with the package so results stored in
regulated records can name the exact implementation that produced them.
"""

__version__ = "0.1.0"
