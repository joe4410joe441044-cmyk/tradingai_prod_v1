from typing import Dict
from threading import Lock

class ConfigStore:
    def __init__(self):
        self._config: Dict = {}
        self._lock = Lock()

    def update(self, new_config: Dict):
        with self._lock:
            self._config = new_config

    def get(self) -> Dict:
        with self._lock:
            return dict(self._config)

config_store = ConfigStore()