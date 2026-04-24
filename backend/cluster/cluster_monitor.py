class ClusterMonitor:

    def __init__(self):

        self.nodes = {
            "vps_a": True,
            "vps_b": True,
            "execution": True
        }

    def update(self, node: str, status: bool):

        self.nodes[node] = status

    def health(self):

        ok = sum(self.nodes.values())
        return ok / len(self.nodes)

    def is_safe(self):

        return self.health() > 0.7