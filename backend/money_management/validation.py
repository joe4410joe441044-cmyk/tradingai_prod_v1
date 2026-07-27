from dataclasses import dataclass
from .models import _serialize
@dataclass(frozen=True)
class ValidationIssue:
    code: str
    field: str
    message: str
    severity: str = "ERROR"
    def to_dict(self): return _serialize(self)
class ValidationError(ValueError):
    def __init__(self, issues):
        self.issues=tuple(issues); super().__init__("; ".join(i.message for i in self.issues))
def validate_model(factory, payload):
    try: return factory(**payload)
    except (TypeError, ValueError) as exc:
        raise ValidationError((ValidationIssue("MM_INVALID_VALUE","$",str(exc)),)) from exc
