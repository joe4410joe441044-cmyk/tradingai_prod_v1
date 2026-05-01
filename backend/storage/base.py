# -*- coding: utf-8 -*-

class BaseStorage:
    def save_event(self, data):
        raise NotImplementedError

    def get_state(self):
        raise NotImplementedError