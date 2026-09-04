"""Focused tests for the shared canonical Knowledge Loader (D-2).

These tests verify the one shared loading/verification boundary:

* allowlist-only loading, fail-closed SHA-256, path security
* deterministic ordering and repeated load stability
* Knowledge Provenance integration (CANONICAL_SPECIFICATION / SPECIFICATION)
* INFORMATION_ONLY authority and the absence of any mutation interface
* no Advisor / Supervisor dependency, no provider / network dependency
* preservation of the existing six-document trust set and its pinned hashes
"""

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from backend.knowledge_core import (
    KnowledgeAuthority,
    KnowledgeCore,
    mutation_interface_names,
)
from backend.knowledge_core.canonical_loader import (
    CanonicalKnowledgeAuthority,
    CanonicalKnowledgeDocument,
    CanonicalKnowledgeEntry,
    CanonicalKnowledgeLoadError,
    CanonicalKnowledgeLoader,
    CanonicalKnowledgeLoadResult,
    CanonicalKnowledgeManifest,
    VerificationState,
    default_repository_root,
    load_canonical_knowledge,
    production_canonical_knowledge_manifest,
    sha256_digest,
)

_SIX_DOCUMENTS = (
    "docs/00_CONSTITUTION/00_TradingAI_Constitution.md",
    "docs/ai_advisor/01_AI_Advisor_Master_Specification.md",
    "docs/money_management/01_Money_Management_Master_Specification.md",
    "docs/market_recorder/01_Market_Recorder_Master_Specification.md",
    "docs/SUPERVISOR/01_SUPERVISOR_Master_Specification.md",
    "docs/market_intelligence/02_MARKET_INTELLIGENCE_COMPONENT_SPEC.md",
)

_SIX_DOCUMENT_IDS = {
    "tradingai-constitution-v0.1",
    "ai-advisor-master-v1.0",
    "market-intelligence-component-v1.0",
    "money-management-master-v1.0",
    "market-recorder-master-v1.0",
    "supervisor-master-v1.1",
}


def _entry(
    *,
    document_id="doc-a",
    relative_path="docs/appr.md",
    content=b"approved bounded knowledge",
    authority=CanonicalKnowledgeAuthority.MASTER_SPEC,
):
    return CanonicalKnowledgeEntry(
        document_id=document_id,
        knowledge_key="component-test",
        authority=authority,
        title="Approved",
        relative_path=relative_path,
        version="1.0",
        topics=("TEST",),
        excerpt="Approved bounded knowledge.",
        expected_sha256=sha256_digest(content),
    )


class CanonicalLoaderHappyPathTest(unittest.TestCase):
    def _root_with_doc(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "docs").mkdir()
        body = b"# Approved\nsafe bounded content.\n"
        (root / "docs" / "approved.md").write_bytes(body)
        return tmp, root, body

    def test_approved_document_loads_successfully(self):
        tmp, root, body = self._root_with_doc()
        try:
            entry = _entry(relative_path="docs/approved.md", content=body)
            manifest = CanonicalKnowledgeManifest(name="m", entries=(entry,))
            result = CanonicalKnowledgeLoader(repository_root=root).load(manifest)
            self.assertTrue(result.all_verified)
            doc = result.verified_documents[0]
            self.assertEqual(doc.document_id, "doc-a")
            self.assertEqual(doc.approved_path, "docs/approved.md")
            self.assertEqual(doc.content, body.decode("utf-8"))
        finally:
            tmp.cleanup()

    def test_correct_sha256_verifies(self):
        tmp, root, body = self._root_with_doc()
        try:
            entry = _entry(relative_path="docs/approved.md", content=body)
            manifest = CanonicalKnowledgeManifest(name="m", entries=(entry,))
            result = load_canonical_knowledge(manifest, repository_root=root)
            doc = result.verified_documents[0]
            self.assertEqual(doc.verification_state, VerificationState.VERIFIED)
            self.assertEqual(doc.actual_sha256, sha256_digest(body))
            self.assertEqual(doc.expected_sha256, doc.actual_sha256)
        finally:
            tmp.cleanup()


class CanonicalLoaderFailClosedTest(unittest.TestCase):
    def _root_and_body(self, body):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "docs").mkdir()
        (root / "docs" / "approved.md").write_bytes(body)
        return tmp, root

    def test_hash_mismatch_fails_closed(self):
        present = b"actual content"
        tmp, root = self._root_and_body(present)
        try:
            entry = _entry(
                relative_path="docs/approved.md",
                content=b"different pinned content",
            )
            manifest = CanonicalKnowledgeManifest(name="m", entries=(entry,))
            result = CanonicalKnowledgeLoader(repository_root=root).load(manifest)
            self.assertFalse(result.all_verified)
            self.assertEqual(result.verified_documents, ())
            failure = result.failures[0]
            self.assertEqual(failure.verification_state, VerificationState.HASH_MISMATCH)
            self.assertIsNotNone(failure.actual_sha256)
            with self.assertRaises(CanonicalKnowledgeLoadError) as ctx:
                CanonicalKnowledgeLoader(repository_root=root).load(
                    manifest, strict=True
                )
            self.assertEqual(ctx.exception.code, "HASH_MISMATCH")
        finally:
            tmp.cleanup()

    def test_missing_approved_file_fails_closed(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "docs").mkdir()
        try:
            entry = _entry(
                relative_path="docs/absent.md",
                content=b"never written",
            )
            manifest = CanonicalKnowledgeManifest(name="m", entries=(entry,))
            result = CanonicalKnowledgeLoader(repository_root=root).load(manifest)
            self.assertFalse(result.all_verified)
            self.assertEqual(result.failures[0].verification_state, VerificationState.MISSING)
            with self.assertRaises(CanonicalKnowledgeLoadError) as ctx:
                CanonicalKnowledgeLoader(repository_root=root).load(
                    manifest, strict=True
                )
            self.assertEqual(ctx.exception.code, "MISSING")
        finally:
            tmp.cleanup()


class CanonicalLoaderPathSecurityTest(unittest.TestCase):
    def test_symlink_leaf_rejected(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "docs").mkdir()
        target = root / "outside.txt"
        target.write_bytes(b"secret outside data")
        (root / "docs" / "link.md").symlink_to(target)
        try:
            entry = _entry(relative_path="docs/link.md", content=b"secret outside data")
            manifest = CanonicalKnowledgeManifest(name="m", entries=(entry,))
            result = CanonicalKnowledgeLoader(repository_root=root).load(manifest)
            self.assertEqual(result.failures[0].verification_state, VerificationState.REJECTED_PATH)
            self.assertEqual(result.verified_documents, ())
        finally:
            tmp.cleanup()

    def test_directory_symlink_escape_rejected(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "docs").mkdir()
        outside = tempfile.mkdtemp()
        (root / "docs" / "sub").symlink_to(outside, target_is_directory=True)
        Path(outside, "secret.md").write_bytes(b"escape data")
        try:
            entry = _entry(relative_path="docs/sub/secret.md", content=b"escape data")
            manifest = CanonicalKnowledgeManifest(name="m", entries=(entry,))
            result = CanonicalKnowledgeLoader(repository_root=root).load(manifest)
            self.assertEqual(result.failures[0].verification_state, VerificationState.REJECTED_PATH)
            self.assertEqual(result.verified_documents, ())
        finally:
            Path(outside, "secret.md").unlink(missing_ok=True)
            os.rmdir(outside)
            tmp.cleanup()

    def test_path_traversal_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            _entry(relative_path="docs/../secret.md")
        with self.assertRaises(ValueError):
            _entry(relative_path="docs/../../etc/passwd")

    def test_absolute_path_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            _entry(relative_path="/etc/passwd")

    def test_unapproved_path_outside_docs_rejected(self):
        # The loader is not a generic filesystem reader: only entries under
        # ``docs/`` can even be represented, and there is no path-based read API.
        with self.assertRaises(ValueError):
            _entry(relative_path="backend/secrets.env")
        loader = CanonicalKnowledgeLoader(repository_root=default_repository_root())
        for name in dir(loader):
            if name.startswith("_"):
                continue
            self.assertNotIn(name.lower(), {"read", "open", "cat", "load_file"})


class CanonicalLoaderDeterminismTest(unittest.TestCase):
    def test_manifest_order_and_repeat_load_stable(self):
        root = default_repository_root()
        first = CanonicalKnowledgeLoader(repository_root=root).load_production_manifest()
        second = CanonicalKnowledgeLoader(repository_root=root).load_production_manifest()
        self.assertEqual(first.stable_json(), second.stable_json())
        self.assertEqual(first.verified_document_ids, second.verified_document_ids)
        self.assertEqual(
            first.verified_document_ids,
            tuple(doc.document_id for doc in first.verified_documents),
        )

    def test_production_manifest_deterministic_ordering(self):
        manifest = production_canonical_knowledge_manifest()
        # Order is the deterministic allowlist order (fixed literal), and
        # repeated construction is byte-for-byte stable.
        self.assertEqual(
            manifest.stable_json(),
            production_canonical_knowledge_manifest().stable_json(),
        )
        self.assertEqual(len(manifest.entries), 6)


class CanonicalLoaderProvenanceTest(unittest.TestCase):
    def test_provenance_is_canonical_specification(self):
        result = CanonicalKnowledgeLoader(repository_root=default_repository_root()) \
            .load_production_manifest()
        for doc in result.verified_documents:
            prov = doc.provenance
            self.assertEqual(prov.truth_level.value, "CANONICAL_SPECIFICATION")
            self.assertEqual(prov.source_category.value, "SPECIFICATION")
            self.assertEqual(prov.source_path, doc.approved_path)
            self.assertEqual(prov.content_hash, doc.actual_sha256)
            self.assertTrue(prov.verified)


class CanonicalLoaderAuthorityTest(unittest.TestCase):
    def test_information_only_authority(self):
        loader = CanonicalKnowledgeLoader(repository_root=default_repository_root())
        self.assertEqual(loader.authority, KnowledgeAuthority.INFORMATION_ONLY)
        self.assertFalse(loader.grants_any_authority)
        self.assertEqual(loader.load_production_manifest().all_verified, True)

    def test_no_mutation_interface_anywhere(self):
        loader = CanonicalKnowledgeLoader(repository_root=default_repository_root())
        manifest = production_canonical_knowledge_manifest()
        result = loader.load_production_manifest()
        doc = result.verified_documents[0]
        entry = manifest.entries[0]
        for obj in (loader, manifest, result, doc, entry):
            self.assertEqual(mutation_interface_names(obj), (),
                             f"mutation interface found on {type(obj).__name__}")

    def test_forbidden_operational_verbs_absent(self):
        loader = CanonicalKnowledgeLoader(repository_root=default_repository_root())
        objects = [
            loader,
            production_canonical_knowledge_manifest(),
            loader.load_production_manifest(),
            loader.load_production_manifest().verified_documents[0],
        ]
        forbidden = {
            "write", "save", "update", "delete", "execute", "submit", "cancel",
            "start", "stop", "unlock", "approve",
        }
        for obj in objects:
            for name in dir(obj):
                if name.startswith("_"):
                    continue
                first = name.lower().rstrip("_s").split("_")[0]
                self.assertNotIn(first, forbidden,
                                 f"operational verb '{name}' on {type(obj).__name__}")


class CanonicalLoaderIndependenceTest(unittest.TestCase):
    @staticmethod
    def _run(code):
        return subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
        )

    def test_loader_does_not_import_advisor_or_supervisor(self):
        proc = self._run(
            "import sys; "
            "import backend.knowledge_core.canonical_loader as m; "
            "assert 'backend.ai_advisor' not in sys.modules, 'imported ai_advisor'; "
            "assert 'backend.supervisor' not in sys.modules, 'imported supervisor'; "
            "print('OK')"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK", proc.stdout)

    def test_loader_has_no_provider_or_network_dependency(self):
        code = (
            "import sys\n"
            "import backend.knowledge_core.canonical_loader as m\n"
            "for mod in ('openai','ollama','requests','http.client','socket'):\n"
            "    assert mod not in sys.modules, 'unexpected dependency ' + mod\n"
            "print('OK')\n"
        )
        proc = self._run(code)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK", proc.stdout)

    def test_source_has_no_provider_substring(self):
        source = Path(__file__).resolve().parents[1] / "backend/knowledge_core/canonical_loader.py"
        text = source.read_text(encoding="utf-8")
        for token in ("openai", "ollama", "nvidia", "byteplus", "requests", "api_key"):
            self.assertNotIn(token.lower(), text.lower())


class CanonicalLoaderTrustSetTest(unittest.TestCase):
    def test_six_document_set_preserved(self):
        manifest = production_canonical_knowledge_manifest()
        self.assertEqual({doc.document_id for doc in manifest.entries}, _SIX_DOCUMENT_IDS)
        paths = {doc.relative_path for doc in manifest.entries}
        self.assertEqual(paths, set(_SIX_DOCUMENTS))

    def test_expected_hashes_match_repository_files(self):
        root = default_repository_root()
        for path in _SIX_DOCUMENTS:
            content = (root / path).read_bytes()
            self.assertEqual(
                sha256_digest(content),
                production_canonical_knowledge_manifest().by_id(
                    _document_id_for_path(path)
                ).expected_sha256,
                f"hash drift for {path}",
            )


def _document_id_for_path(path):
    mapping = {
        "docs/00_CONSTITUTION/00_TradingAI_Constitution.md": "tradingai-constitution-v0.1",
        "docs/ai_advisor/01_AI_Advisor_Master_Specification.md": "ai-advisor-master-v1.0",
        "docs/money_management/01_Money_Management_Master_Specification.md": "money-management-master-v1.0",
        "docs/market_recorder/01_Market_Recorder_Master_Specification.md": "market-recorder-master-v1.0",
        "docs/SUPERVISOR/01_SUPERVISOR_Master_Specification.md": "supervisor-master-v1.1",
        "docs/market_intelligence/02_MARKET_INTELLIGENCE_COMPONENT_SPEC.md": "market-intelligence-component-v1.0",
    }
    return mapping[path]


if __name__ == "__main__":
    unittest.main()
