# -*- coding: utf-8 -*-

from abc import ABC
from abc import abstractmethod


class BaseMarketWS(ABC):

    def __init__(
        self,
        symbol,
        on_update
    ):

        self.symbol = symbol

        self.on_update = on_update

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def stop(self):
        pass
