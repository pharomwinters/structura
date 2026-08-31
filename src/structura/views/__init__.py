"""Views: saved pipelines, and the export renderers that reproduce the
generated registers.

Phase 1 ships the renderers only -- they are what acceptance test 1 measures.
Saved pipelines arrive in phase 2, once there is a pipeline to save.
"""

from .render import (
    LEGACY_GENERATOR,
    org_affiliations,
    render_assets,
    render_contacts,
    render_open_items,
    render_placeholders,
)

__all__ = [
    "LEGACY_GENERATOR",
    "org_affiliations",
    "render_assets",
    "render_contacts",
    "render_open_items",
    "render_placeholders",
]
