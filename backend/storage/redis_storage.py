# -*- coding: utf-8 -*-

from .base import BaseStorage


class RedisStorage(BaseStorage):

    def __init__(self, client):
        self.client = client

    def save_event(self, data):
        self.client.set("event", str(data))

    def get_state(self):
        return self.client.get("event")