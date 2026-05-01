# -*- coding: utf-8 -*-

from .base import BaseStorage


class MemoryStorage(BaseStorage):

    def __init__(self):
        self.events = []

    def save_event(self, data):
        self.events.append(data)

    def get_state(self):
        return self.events