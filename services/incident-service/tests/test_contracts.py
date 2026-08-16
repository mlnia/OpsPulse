import pytest
from pydantic import ValidationError

from app.main import IncidentCreate, IncidentStatus


def test_incident_accepts_a_valid_payload() -> None:
    incident = IncidentCreate(title="Checkout latency exceeds SLO", service="checkout-api", severity="high")
    assert incident.severity == "high"


@pytest.mark.parametrize("severity", ["urgent", "", "P1"])
def test_incident_rejects_unknown_severity(severity: str) -> None:
    with pytest.raises(ValidationError):
        IncidentCreate(title="Checkout latency exceeds SLO", service="checkout-api", severity=severity)


def test_incident_statuses_are_explicit() -> None:
    assert {status.value for status in IncidentStatus} == {"open", "investigating", "resolved"}
