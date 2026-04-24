# -*- coding: utf-8 -*-
import time
import requests


class FailoverManager:

    def __init__(self, primary_url: str, backup_url: str):

        self.primary = primary_url
        self.backup = backup_url

        self.active = "primary"
        self.last_check = time.time()

    # =====================================================
    # HEARTBEAT CHECK
    # =====================================================
    def check(self):

        try:
            r = requests.get(f"{self.primary}/health", timeout=2)

            if r.status_code != 200:
                raise Exception("primary unhealthy")

            self.active = "primary"

        except Exception:

            self.active = "backup"
            self._switch_to_backup()

        self.last_check = time.time()

    # =====================================================
    # SWITCH
    # =====================================================
    def _switch_to_backup(self):

        try:
            requests.post(f"{self.backup}/activate", timeout=2)

        except Exception:
            pass

    # =====================================================
    # STATUS
    # =====================================================
    def get_active(self):

        return {
            "active": self.active,
            "last_check": self.last_check
        }