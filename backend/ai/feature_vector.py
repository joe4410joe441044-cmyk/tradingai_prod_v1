from dataclasses import dataclass, field


@dataclass
class FeatureVector:

    numeric_vector: list

    feature_map: dict = field(default_factory=dict)