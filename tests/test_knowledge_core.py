"""Focused tests for the READ-ONLY TradingAI Knowledge Core foundation.

These tests verify determinism, uniqueness, read-only immutability, honest
UNKNOWN handling, provenance, and the absence of execution / mutation
authority on every Knowledge Core object.
"""

import unittest

from backend.knowledge_core import (
    UNKNOWN,
    KnowledgeAuthority,
    KnowledgeCore,
    build_default_knowledge_core,
    mutation_interface_names,
)
from backend.knowledge_core.provenance import ProvenanceRecord


class KnowledgeCoreDeterminismTest(unittest.TestCase):
    def test_system_map_deterministic(self):
        first = KnowledgeCore().system_map
        second = KnowledgeCore().system_map
        self.assertEqual(first.stable_json(), second.stable_json())
        self.assertEqual(tuple(d.value for d in first.domains),
                         tuple(d.value for d in second.domains))

    def test_source_index_deterministic(self):
        first = KnowledgeCore().sources.stable_json()
        second = KnowledgeCore().sources.stable_json()
        self.assertEqual(first, second)

    def test_repeated_construction_stable(self):
        first = build_default_knowledge_core().stable_json()
        second = build_default_knowledge_core().stable_json()
        third = KnowledgeCore().stable_json()
        self.assertEqual(first, second)
        self.assertEqual(first, third)

    def test_reason_catalog_stable(self):
        self.assertEqual(KnowledgeCore().reasons.stable_json(),
                         KnowledgeCore().reasons.stable_json())

    def test_snapshot_read_only(self):
        snap = KnowledgeCore().snapshot()
        with self.assertRaises(TypeError):
            snap["system_map"] = "mutated"


class KnowledgeCoreUniquenessTest(unittest.TestCase):
    def test_component_ids_unique(self):
        registry = KnowledgeCore().components
        ids = [record.component_id for record in registry.entries]
        self.assertEqual(len(ids), len(set(ids)))

    def test_runtime_semantic_field_ids_unique(self):
        semantics = KnowledgeCore().semantics
        field_ids = [record.field_id for record in semantics.entries]
        self.assertEqual(len(field_ids), len(set(field_ids)))

    def test_source_concept_index_deterministic_and_field_variant_count(self):
        # The dual-symbol executionEntryAllowed must be disambiguated, not merged.
        semantics = KnowledgeCore().semantics
        self.assertEqual(
            [s.field_id for s in semantics.by_field_name("executionEntryAllowed")],
            ["executionEntryAllowed.config", "executionEntryAllowed.runtime"],
        )


class KnowledgeCoreReadOnlyTest(unittest.TestCase):
    def test_registry_read_only(self):
        kc = KnowledgeCore()
        for registry in (kc.components, kc.sources, kc.semantics, kc.reasons):
            for record in registry.entries:
                with self.assertRaises((TypeError, AttributeError)):
                    record.component_id = "mutated" if hasattr(record, "component_id") else \
                        record.field_id

    def test_no_internal_mapping_mutation(self):
        kc = KnowledgeCore()
        with self.assertRaises(TypeError):
            kc.components._by_id["x"] = object()
        with self.assertRaises(TypeError):
            kc.system_map.entries["MARKET"] = object()


class KnowledgeCoreUnknownTest(unittest.TestCase):
    def test_unknown_remains_unknown_and_not_guessed(self):
        kc = KnowledgeCore()
        # Reason codes with no supported meaning must be the sentinel, not a hero
        # description invented for them.
        unknown = [r for r in kc.reasons.entries if r.meaning == UNKNOWN]
        self.assertGreater(len(unknown), 0)
        for record in unknown:
            self.assertEqual(record.meaning, UNKNOWN)
            self.assertTrue(record.provenance.source_reference)

    def test_optional_unknown_is_none_for_market_intelligence(self):
        mi = KnowledgeCore().components.get("market_intelligence")
        # No backend runtime producer is known for the read-only MI layer.
        self.assertIsNone(mi.runtime_source)


class KnowledgeCoreReasonCodeConflictTest(unittest.TestCase):
    def test_conflicts_surfaced_not_silently_merged(self):
        catalog = KnowledgeCore().reasons
        self.assertTrue(catalog.conflicts)
        for code, domain, producers in catalog.conflicts:
            matches = catalog.lookup(code, domain)
            # Duplicate picks within a domain are all returned (not deduped).
            self.assertGreaterEqual(len(matches), 2)

    def test_no_exact_duplicate_records(self):
        catalog = KnowledgeCore().reasons
        seen = set()
        for record in catalog.entries:
            key = (record.code, record.domain.value, record.meaning,
                   record.producer, record.provenance.source_reference)
            self.assertNotIn(key, seen)
            seen.add(key)


class KnowledgeCoreProvenanceTest(unittest.TestCase):
    def test_provenance_exists_for_registered_canonical_knowledge(self):
        for record in KnowledgeCore().reasons.entries:
            self.assertIsInstance(record.provenance, ProvenanceRecord)
            self.assertTrue(record.provenance.source_reference)
            self.assertFalse(record.provenance.source_reference == "?")

    def test_spec_backed_records_are_canonical(self):
        # MM RiskState / DecisionResult are documented in the master spec.
        catalog = KnowledgeCore().reasons
        for code in ("NORMAL", "DEFENSIVE", "APPROVED", "SIZE_REDUCED"):
            record = catalog.lookup(code, "MONEY_MANAGEMENT")[0]
            self.assertEqual(record.provenance.truth_level.value, "CANONICAL_SPECIFICATION")
            self.assertEqual(record.provenance.source_category.value, "SPECIFICATION")


class KnowledgeCoreAuthorityTest(unittest.TestCase):
    def test_no_execution_authority(self):
        kc = KnowledgeCore()
        report = kc.authority_report
        self.assertFalse(report.execution_authority)
        self.assertFalse(report.configuration_authority)
        self.assertFalse(report.governance_authority)
        self.assertFalse(report.mm_authority)
        self.assertFalse(report.emergency_authority)
        self.assertFalse(report.paper_live_lifecycle_authority)
        self.assertFalse(report.bot_authority)
        self.assertFalse(report.loop_authority)
        self.assertFalse(report.auto_trade_authority)
        self.assertFalse(report.grants_any_authority)
        self.assertEqual(report.authority, KnowledgeAuthority.INFORMATION_ONLY)
        self.assertEqual(kc.authority, KnowledgeAuthority.INFORMATION_ONLY)

    def test_no_mutation_or_action_interface(self):
        kc = KnowledgeCore()
        for registry in (kc.components, kc.sources, kc.semantics, kc.reasons,
                         kc.system_map):
            self.assertEqual(
                mutation_interface_names(registry), (),
                f"mutation interface found on {type(registry).__name__}",
            )

    def test_no_order_governance_mm_emergency_bot_loop_auto_trade_mutation(self):
        # Convenience proxy: scanning the facade and each registry proves none
        # exposes an order/governance/MM/emergency/bot/loop/auto-trade action.
        kc = KnowledgeCore()
        verbs = {"submit", "cancel", "replace", "order", "enable", "disable",
                 "start", "stop", "lock", "unlock", "override", "place",
                 "execute", "mutate", "dispatch", "apply", "force", "promote"}
        for registry in (kc, kc.components, kc.sources, kc.semantics, kc.reasons,
                         kc.system_map):
            for name in dir(registry):
                if name.startswith("_"):
                    continue
                first = name.lower().rstrip("_s").split("_")[0]
                self.assertNotIn(first, verbs)


class KnowledgeCoreImportCompatibilityTest(unittest.TestCase):
    def test_advisor_and_supervisor_import_cleanly_after_knowledge_core(self):
        # D-1 does not wire the Knowledge Core into Advisor/Supervisor, but the
        # dependency direction must hold: they may import it or coexist without
        # a circular import, and their public modules still import.
        # (Import order deliberately exercises no-knowledge_core -> AI cycle.)
        import backend.ai_advisor  # noqa: F401
        import backend.supervisor  # noqa: F401
        # knowledge_core must never import from either (proved by build).
        kc = KnowledgeCore()  # still builds independently
        self.assertTrue(kc.stable_json())


if __name__ == "__main__":
    unittest.main()
