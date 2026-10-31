"""Live trust layer between Dydema's Wizard API and real-world commands."""

from .budget import Budget
from .client import DydemaClient
from .errors import DydemaError, SpendRefused
from .gate import GateConfig, IdleGate, Decision

__all__ = ["Budget", "DydemaClient", "DydemaError", "SpendRefused",
           "GateConfig", "IdleGate", "Decision"]
__version__ = "0.1.0"
