"""
ATLAS — Knowledge context loader for AI prompts.

Provides the KnowledgeContextLoader class that builds a KnowledgeContext object
for injection into Granite prompts.

Rules (docs/methodology.md Section 7 / docs/architecture.md Section 3.2):
- Reads spacecraft_spec.md and fault_modes.md by subsystem.
- NEVER reads or returns procedures.md content.
- Injects LIVE MissionContext values for current-state fields (phase,
  next_maneuver_time, thruster status, constraints) — not static
  mission_context.md text for these fields.
- Static mission_context.md content (mission type, orbit parameters, priorities)
  MAY be injected as background context.
- Returns a KnowledgeContext dataclass with a to_prompt_block() method.
"""

from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.models.mission import MissionContext

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
# Resolve the knowledge directory relative to this file's location so the loader
# works regardless of the working directory.
_HERE = Path(__file__).resolve().parent          # backend/app/ai/
_KNOWLEDGE_DIR = _HERE.parent.parent / "knowledge"  # backend/knowledge/

_SPACECRAFT_SPEC_PATH = _KNOWLEDGE_DIR / "spacecraft_spec.md"
_FAULT_MODES_PATH     = _KNOWLEDGE_DIR / "fault_modes.md"
_MISSION_CONTEXT_PATH = _KNOWLEDGE_DIR / "mission_context.md"
# procedures.md is intentionally NOT listed here — it must never be loaded.

# ── Subsystem → markdown section heading map ──────────────────────────────────
# Keys match the `subsystem` field values used in normal_ranges.json and models.
_SUBSYSTEM_SECTION_MAP: dict[str, str] = {
    "propulsion":  "Propulsion Subsystem",
    "power":       "Power Subsystem",
    "computing":   "Computing Subsystem",
    "attitude":    "Attitude Control Subsystem",
    "comms":       "Communications Subsystem",
    "environment": "Environment",
}

# ── Fault mode section keywords ────────────────────────────────────────────────
_FAULT_SECTION_MAP: dict[str, str] = {
    "propulsion":  "FAULT-01",
    "power":       "FAULT-03",
    "comms":       "FAULT-02",
}

# ── Static mission_context.md sections to include ────────────────────────────
# Only background / profile sections — NOT "Current Mission State" (that comes
# from the live MissionContext object at runtime).
_STATIC_MISSION_SECTIONS = ["Mission Profile", "Mission Priorities (in order)"]


# ─────────────────────────────────────────────────────────────────────────────
# KnowledgeContext dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class KnowledgeContext:
    """
    Structured knowledge context for Granite prompt injection.

    Fields
    ------
    subsystem_spec   : Relevant section from spacecraft_spec.md.
    fault_mode_info  : Relevant fault mode section from fault_modes.md.
    mission_profile  : Static mission profile text (mission type, orbit params).
    mission_priorities : Static mission priorities text.

    Current-state fields (phase, thruster status, timing, constraints) are
    NOT stored here — they come from the live MissionContext object and are
    formatted directly in prompts.py.
    """

    subsystem_spec: str = ""
    fault_mode_info: str = ""
    mission_profile: str = ""
    mission_priorities: str = ""

    def to_prompt_block(self) -> str:
        """Render non-empty fields into a single readable block for prompt injection."""
        parts: list[str] = []
        if self.subsystem_spec:
            parts.append(f"[SUBSYSTEM SPECIFICATION]\n{self.subsystem_spec.strip()}")
        if self.fault_mode_info:
            parts.append(f"[KNOWN FAULT MODE]\n{self.fault_mode_info.strip()}")
        if self.mission_profile:
            parts.append(f"[MISSION PROFILE]\n{self.mission_profile.strip()}")
        if self.mission_priorities:
            parts.append(f"[MISSION PRIORITIES]\n{self.mission_priorities.strip()}")
        return "\n\n".join(parts) if parts else "(no additional knowledge context)"


# ─────────────────────────────────────────────────────────────────────────────
# KnowledgeContextLoader
# ─────────────────────────────────────────────────────────────────────────────

class KnowledgeContextLoader:
    """
    Loads and caches knowledge Markdown files and extracts relevant sections
    for a given subsystem.

    procedures.md is explicitly excluded and must never be read or returned.
    """

    def __init__(self, knowledge_dir: Optional[Path] = None) -> None:
        self._knowledge_dir = knowledge_dir or _KNOWLEDGE_DIR
        self._cache: dict[str, str] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def load(
        self,
        subsystem: str,
        mission_context: "MissionContext",
    ) -> KnowledgeContext:
        """
        Build a KnowledgeContext for the given subsystem and live mission context.

        Parameters
        ----------
        subsystem       : Subsystem key (e.g. "propulsion").
        mission_context : Live MissionContext — used for current-state fields only
                          (this method does not read those from Markdown).

        Returns
        -------
        KnowledgeContext ready for injection into a prompt builder.
        """
        spec_section     = self._extract_spec_section(subsystem)
        fault_section    = self._extract_fault_section(subsystem)
        mission_profile  = self._extract_static_mission_section("Mission Profile")
        mission_prios    = self._extract_static_mission_section("Mission Priorities (in order)")

        return KnowledgeContext(
            subsystem_spec=spec_section,
            fault_mode_info=fault_section,
            mission_profile=mission_profile,
            mission_priorities=mission_prios,
        )

    # ── Section extractors ─────────────────────────────────────────────────────

    def _extract_spec_section(self, subsystem: str) -> str:
        """Extract the spacecraft spec section relevant to the given subsystem."""
        heading = _SUBSYSTEM_SECTION_MAP.get(subsystem.lower())
        if not heading:
            return ""
        content = self._read_file("spacecraft_spec.md")
        return _extract_markdown_section(content, heading)

    def _extract_fault_section(self, subsystem: str) -> str:
        """Extract the fault mode section relevant to the given subsystem."""
        keyword = _FAULT_SECTION_MAP.get(subsystem.lower())
        if not keyword:
            return ""
        content = self._read_file("fault_modes.md")
        # Use first matching section that contains the keyword
        return _extract_section_containing(content, keyword)

    def _extract_static_mission_section(self, section_heading: str) -> str:
        """
        Extract a named section from mission_context.md.

        Only sections listed in _STATIC_MISSION_SECTIONS are permitted —
        'Current Mission State' is excluded because those values come from the
        live MissionContext object, not this static file.
        """
        if section_heading not in _STATIC_MISSION_SECTIONS:
            return ""
        content = self._read_file("mission_context.md")
        return _extract_markdown_section(content, section_heading)

    # ── File reader ────────────────────────────────────────────────────────────

    def _read_file(self, filename: str) -> str:
        """
        Read a knowledge file and cache its content.

        SAFETY: Raises ValueError if the filename is 'procedures.md' — that file
        must never be loaded by this class under any circumstances.
        """
        if filename.lower() == "procedures.md":
            raise ValueError(
                "KnowledgeContextLoader must never load procedures.md. "
                "That file contains action-guiding language forbidden in prompts."
            )
        if filename in self._cache:
            return self._cache[filename]
        path = self._knowledge_dir / filename
        try:
            text = path.read_text(encoding="utf-8")
            self._cache[filename] = text
            return text
        except FileNotFoundError:
            logger.warning("KnowledgeContextLoader: file not found: %s", path)
            return ""
        except OSError as exc:
            logger.error("KnowledgeContextLoader: error reading %s: %s", path, exc)
            return ""


# ─────────────────────────────────────────────────────────────────────────────
# Markdown parsing helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_markdown_section(document: str, heading: str) -> str:
    """
    Extract the text of a markdown section with the given heading.

    Extracts from the line after the heading until the next heading of equal
    or higher level (i.e. same number of leading # characters or fewer).
    """
    lines = document.splitlines()
    inside = False
    section_lines: list[str] = []
    heading_pattern: Optional[re.Pattern] = None

    for line in lines:
        if not inside:
            # Match headings like "## Propulsion Subsystem" or "# Propulsion Subsystem"
            m = re.match(r"^(#{1,6})\s+(.*)", line)
            if m and m.group(2).strip() == heading:
                inside = True
                heading_level = len(m.group(1))
                # Next heading of equal or higher level ends the section
                heading_pattern = re.compile(r"^#{1," + str(heading_level) + r"}\s+")
                continue
        else:
            if heading_pattern and heading_pattern.match(line):
                break
            section_lines.append(line)

    return "\n".join(section_lines).strip()


def _extract_section_containing(document: str, keyword: str) -> str:
    """
    Extract the first level-2 section (##) whose content contains the keyword.
    Used to find fault mode sections by FAULT-ID.
    """
    lines = document.splitlines()
    inside = False
    section_lines: list[str] = []
    collected: list[str] = []

    for line in lines:
        m = re.match(r"^(#{1,2})\s+(.*)", line)
        if m and len(m.group(1)) <= 2:
            # Save previous section if it contained the keyword
            if inside and any(keyword in l for l in section_lines):
                collected = section_lines[:]
                break
            # Start new candidate section
            inside = True
            section_lines = []
            continue
        if inside:
            section_lines.append(line)

    # Handle last section in file
    if not collected and inside and any(keyword in l for l in section_lines):
        collected = section_lines

    return "\n".join(collected).strip()
