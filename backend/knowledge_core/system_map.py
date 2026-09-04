"""Deterministic TradingAI System Map.

The System Map is a read-only index of domains and the components that belong
to them.  Domain-level metadata comes from :mod:`domain`; the per-domain
component sets are derived from the :class:`ComponentRegistry`.  It is a
descriptive map and carries no authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ._base import freeze_mapping, stable_json
from .component_registry import ComponentRecord, ComponentRegistry
from .domain import DOMAIN_RECORDS, Domain, DomainRecord


@dataclass(frozen=True)
class DomainComponentIndex:
    """A domain and its registered components (sorted, read-only)."""

    domain: Domain
    display_name: str
    purpose: str
    notes: str = ""
    components: tuple[ComponentRecord, ...] = ()

    @property
    def component_ids(self) -> tuple[str, ...]:
        return tuple(record.component_id for record in self.components)


@dataclass(frozen=True)
class SystemMap:
    """Immutable System Map.  Deterministic ordering by domain + component."""

    domains: tuple[Domain, ...]
    entries: Mapping[str, DomainComponentIndex]
    _component_registry: ComponentRegistry = field(repr=False)

    def domain(self, name: Domain | str) -> DomainComponentIndex:
        key = name if isinstance(name, str) else name.value
        return self.entries[key]

    @property
    def component_count(self) -> int:
        return len(self._component_registry.entries)

    def to_dict(self) -> dict:
        return {
            "domains": [domain.value for domain in self.domains],
            "entries": {
                key: {
                    "domain": index.domain.value,
                    "display_name": index.display_name,
                    "purpose": index.purpose,
                    "notes": index.notes,
                    "components": [record.component_id for record in index.components],
                }
                for key, index in self.entries.items()
            },
        }

    def stable_json(self) -> str:
        return stable_json(self.to_dict())


def _domain_lookup() -> dict[str, DomainRecord]:
    return {record.domain.value: record for record in DOMAIN_RECORDS}


def default_system_map(
    registry: ComponentRegistry | None = None,
) -> SystemMap:
    """Construct the production System Map deterministically."""
    registry = registry or ComponentRegistry()
    domain_meta = _domain_lookup()
    # Every domain in the Domain enum is registered even if it has no
    # dedicated component, so the map is complete and stable.
    ordered_domains = tuple(
        sorted(Domain, key=lambda domain: domain.value)
    )
    indexes: dict[str, DomainComponentIndex] = {}
    for domain in ordered_domains:
        meta = domain_meta[domain.value]
        components = registry.by_domain(domain)
        indexes[domain.value] = DomainComponentIndex(
            domain=domain,
            display_name=meta.display_name,
            purpose=meta.purpose,
            notes=meta.notes,
            components=components,
        )
    entries = freeze_mapping(indexes)
    return SystemMap(
        domains=ordered_domains,
        entries=entries,
        _component_registry=registry,
    )
