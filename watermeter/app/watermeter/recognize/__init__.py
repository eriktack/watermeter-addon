"""Digit recognition (plan §5.3) and the multi-frame vote (§5.4)."""
from .base import Recognizer
from .vote import vote_line

__all__ = ["Recognizer", "vote_line"]
