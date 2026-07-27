import json
import os
import tempfile
import unittest
from pathlib import Path
from backend.money_management.loss_persistence_adapter import (
    TARGET_FILENAME, TEMP_FILENAME, ENVELOPE_VERSION, INTEGRITY_ALGORITHM,
    LoadStatus, SaveStatus, SaveFailureCode, load_loss_state, save_loss_state)
from backend.money_management.loss_persistence_serialization import (
    build_canonical_loss_state_json, serialize_loss_persistence_envelope)
from tests.test_money_management_loss_persistence_contract import state

class AdapterTests(unittest.TestCase):
    def test_canonical_and_envelope_deterministic(self):
        s=state()
        self.assertEqual(build_canonical_loss_state_json(s),build_canonical_loss_state_json(s))
        raw=serialize_loss_persistence_envelope(s)
        obj=json.loads(raw)
        self.assertEqual(set(obj),{"envelope_version","integrity_algorithm","integrity_digest","payload"})
        self.assertEqual(obj["envelope_version"],ENVELOPE_VERSION)
        self.assertEqual(obj["integrity_algorithm"],INTEGRITY_ALGORITHM)
        self.assertEqual(len(obj["integrity_digest"]),64)

    def test_save_load_round_trip_and_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            s=state(); result=save_loss_state(s,Path(d))
            self.assertEqual(result.status,SaveStatus.SAVED)
            p=Path(d)/TARGET_FILENAME
            self.assertEqual(p.stat().st_mode & 0o777,0o600)
            self.assertFalse((Path(d)/TEMP_FILENAME).exists())
            loaded=load_loss_state(Path(d))
            self.assertEqual(loaded.status,LoadStatus.VALID)
            self.assertEqual(loaded.state.to_dict(),s.to_dict())

    def test_missing_and_tamper_are_typed_failures(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_loss_state(Path(d)).status,LoadStatus.MISSING)
            save_loss_state(state(),Path(d))
            p=Path(d)/TARGET_FILENAME
            obj=json.loads(p.read_text())
            obj["payload"]["account_scope"]="tampered"
            p.write_text(json.dumps(obj,separators=(",",":")))
            self.assertEqual(load_loss_state(Path(d)).status,LoadStatus.CORRUPT)

    def test_temp_collision_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); (base/TEMP_FILENAME).write_text("x")
            r=save_loss_state(state(),base)
            self.assertEqual(r.failure_code,SaveFailureCode.TEMPORARY_FILE_EXISTS)
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); outside=base/"outside"; outside.write_text("x")
            os.symlink(outside,base/TARGET_FILENAME)
            r=save_loss_state(state(),base)
            self.assertEqual(r.failure_code,SaveFailureCode.UNSAFE_FILE)
            self.assertEqual(load_loss_state(base).status,LoadStatus.UNSAFE_FILE)

    def test_unsafe_path_and_size(self):
        self.assertEqual(save_loss_state(state(), Path("relative")).failure_code, SaveFailureCode.UNSAFE_PATH)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/TARGET_FILENAME; p.write_bytes(b"x"*(256*1024+1)); os.chmod(p,0o600)
            self.assertEqual(load_loss_state(Path(d)).status,LoadStatus.TOO_LARGE)

if __name__=="__main__": unittest.main()
