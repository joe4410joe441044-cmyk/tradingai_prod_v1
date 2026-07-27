import json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from backend.money_management.loss_persistence_adapter import *
from tests.test_money_management_loss_persistence_contract import state

class PersistenceSecurityTests(unittest.TestCase):
    def test_parent_symlink_and_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); real=root/"real"; real.mkdir(); os.symlink(real,root/"link")
            self.assertEqual(save_loss_state(state(),root/"link").failure_code,SaveFailureCode.UNSAFE_PATH)
            self.assertEqual(load_loss_state(Path("relative")).status,LoadStatus.UNSAFE_PATH)

    def test_duplicate_json_and_trailing_content_are_corrupt(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/TARGET_FILENAME
            p.write_text('{"envelope_version":"x","envelope_version":"y"}')
            os.chmod(p,0o600)
            self.assertEqual(load_loss_state(Path(d)).status,LoadStatus.CORRUPT)
            p.write_text('{"x":1} trailing'); self.assertEqual(load_loss_state(Path(d)).status,LoadStatus.CORRUPT)

    def test_unknown_version_and_digest_bypass_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            save_loss_state(state(),Path(d)); p=Path(d)/TARGET_FILENAME; obj=json.loads(p.read_text())
            obj["envelope_version"]="future"; p.write_text(json.dumps(obj,separators=(",",":"))); os.chmod(p,0o600)
            self.assertEqual(load_loss_state(Path(d)).status,LoadStatus.INCOMPATIBLE_VERSION)
            save_loss_state(state(),Path(d))
            obj=json.loads(p.read_text()); obj["payload"]["account_scope"]="tampered"; p.write_text(json.dumps(obj,separators=(",",":"))); os.chmod(p,0o600)
            self.assertEqual(load_loss_state(Path(d)).status,LoadStatus.CORRUPT)

    def test_fsync_and_replace_failures_are_typed(self):
        with tempfile.TemporaryDirectory() as d:
            with patch("backend.money_management.loss_persistence_adapter.os.fsync", side_effect=OSError("fsync")):
                self.assertEqual(save_loss_state(state(),Path(d)).failure_code,SaveFailureCode.FSYNC_FAILED)
        with tempfile.TemporaryDirectory() as d:
            with patch("backend.money_management.loss_persistence_adapter.os.replace", side_effect=OSError("replace")):
                self.assertEqual(save_loss_state(state(),Path(d)).failure_code,SaveFailureCode.REPLACE_FAILED)

    def test_temp_residue_and_permission_are_not_repaired(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); (base/TEMP_FILENAME).write_text("residue")
            self.assertEqual(save_loss_state(state(),base).failure_code,SaveFailureCode.TEMPORARY_FILE_EXISTS)
            (base/TARGET_FILENAME).write_text("{}"); os.chmod(base/TARGET_FILENAME,0o644)
            self.assertEqual(load_loss_state(base).status,LoadStatus.UNSAFE_FILE)

if __name__=="__main__": unittest.main()
