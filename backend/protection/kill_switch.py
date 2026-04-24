class KillSwitch:

    def __init__(self):
        self.active = False

    def trigger(self):
        self.active = True

    def reset(self):
        self.active = False