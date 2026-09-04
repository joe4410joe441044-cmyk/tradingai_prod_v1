"""KnowledgeCore facade: a read-only, deterministic aggregate of all registries.

The KnowledgeCore is INFORMATION AUTHORITY only.  It aggregates the System Map,
Component Registry, Source Index, Runtime Semantics registry and Reason Code
Catalog.  It exposes no execution/action interface and carries no runtime
authority.  Consumers may read; they may not mutate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Mapping

from ._base import freeze_mapping, stable_json
from .authority import KnowledgeAuthority
from .component_registry import ComponentRegistry
from .reason_codes import ReasonCodeCatalog
from .runtime_semantics import RuntimeSemanticsRegistry
from .source_index import SourceIndex
from .system_map import SystemMap, default_system_map

# Mutation/action verbs that must never appear on a Knowledge Core object.
_MUTATION_VERBS = frozenset({
    "submit", "cancel", "replace", "order", "enable", "disable", "start", "stop",
    "lock", "unlock", "override", "place", "execute", "mutate", "set", "update",
    "delete", "remove", "append", "add", "put", "promote", "change", "force",
    "write", "clear", "reset", "restore", "recover", "dispatch", "apply",
})


def mutation_interface_names(obj: Any) -> tuple[str, ...]:
    """Return the public attribute names of ``obj`` that look like mutation verbs.

    Used by the authority proof only.  An empty tuple proves no mutation surface.
    """
    found = set()
    for name in dir(obj):
        if name.startswith("_"):
            continue
        member = getattr(obj, name)
        if callable(member) or isinstance(member, Mapping):
            stem = name.lower().rstrip("_s")
            # Check leading stem and compound-leading tokens.
            first_token = stem.split("_")[0]
            if first_token in _MUTATION_VERBS:
                found.add(name)
    return tuple(sorted(found))


@dataclass(frozen=True)
class KnowledgeAuthorityReport:
    """Rendered authority proof for the Knowledge Core.

    Every boolean is False and ``mutation_interfaces`` is empty: the Knowledge
    Core has no runtime authority of any kind.
    """

    execution_authority: bool = False
    configuration_authority: bool = False
    governance_authority: bool = False
    mm_authority: bool = False
    emergency_authority: bool = False
    paper_live_lifecycle_authority: bool = False
    bot_authority: bool = False
    loop_authority: bool = False
    auto_trade_authority: bool = False
    mutation_interfaces: tuple[str, ...] = ()

    @property
    def authority(self) -> KnowledgeAuthority:
        return KnowledgeAuthority.INFORMATION_ONLY

    @property
    def grants_any_authority(self) -> bool:
        return False


class KnowledgeCore:
    """Deterministic, read-only aggregate of the Knowledge Core registries."""

    KNOWLEDGE_AUTHORITY: ClassVar[KnowledgeAuthority] = KnowledgeAuthority.INFORMATION_ONLY

    def __init__(self) -> None:
        self._components = ComponentRegistry()
        self._sources = SourceIndex()
        self._semantics = RuntimeSemanticsRegistry()
        self._reasons = ReasonCodeCatalog()
        self._system_map = default_system_map(self._components)
        self._authority_report = KnowledgeAuthorityReport(
            mutation_interfaces=sum(
                (mutation_interface_names(reg) for reg in (
                    self._components, self._sources, self._semantics,
                    self._reasons, self._system_map,
                )),
                (),
            ),
        )

    @property
    def system_map(self) -> SystemMap:
        return self._system_map

    @property
    def components(self) -> ComponentRegistry:
        return self._components

    @property
    def sources(self) -> SourceIndex:
        return self._sources

    @property
    def semantics(self) -> RuntimeSemanticsRegistry:
        return self._semantics

    @property
    def reasons(self) -> ReasonCodeCatalog:
        return self._reasons

    @property
    def authority(self) -> KnowledgeAuthority:
        return KnowledgeAuthority.INFORMATION_ONLY

    @property
    def authority_report(self) -> KnowledgeAuthorityReport:
        return self._authority_report

    def snapshot(self) -> Mapping[str, Any]:
        """Read-only aggregated view of all registries."""
        return freeze_mapping({
            "system_map": self._system_map.to_dict(),
            "components": [record for record in self._components.entries],
            "source_index": [record for record in self._sources.entries],
            "runtime_semantics": [record for record in self._semantics.entries],
            "reason_codes": [record for record in self._reasons.entries],
        })

    def stable_json(self) -> str:
        """Deterministic serialization of the whole Knowledge Core."""
        return stable_json({
            "authority": self.authority.value,
            "authority_report": self._authority_report,
            "system_map": self._system_map.to_dict(),
            "components": [record for record in self._components.entries],
            "source_index": [record for record in self._sources.entries],
            "runtime_semantics": [record for record in self._semantics.entries],
            "reason_codes": [record for record in self._reasons.entries],
        })


def build_default_knowledge_core() -> KnowledgeCore:
    return KnowledgeCore()
