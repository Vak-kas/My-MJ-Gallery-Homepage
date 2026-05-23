"""Backward-compatible view module.

All studio views are now implemented in studio.view_handlers.
This file re-exports them to avoid breaking any legacy imports.
"""

from .view_handlers import *  # noqa: F401,F403