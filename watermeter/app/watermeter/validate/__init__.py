"""Validation of readings (plan §6). Pure functions: no I/O, no clock; everything comes in as arguments."""
from .rules import matches_reject_pattern, set_current_value, validate

__all__ = ["matches_reject_pattern", "set_current_value", "validate"]
