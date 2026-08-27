"""Presets subpackage.

A preset is a brand-specific bundle of SDK defaults. End users who
want the SDK to behave like a particular product can import a preset
and pass the bundled components to :func:`agent_sdk.create_agent`.

The SDK ships presets in this subpackage. Adding a new preset is a
matter of creating a subdirectory and re-exporting its components.
"""

from agent_sdk.presets import deerflow

__all__ = ["deerflow"]
