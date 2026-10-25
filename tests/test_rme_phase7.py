"""Regression tests for guarded SATUSEHAT HTTP response handling."""
from __future__ import annotations

import pytest
import requests

from rme.integrations.satusehat.client import SATUSEHATClient, SATUSEHATClientError

ENV = {
    "APP_MODE": "demo",
    "SATUSEHAT_MODE": "sandbox",
    "SATUSEHAT_ENABLE_NETWORK": "true",
    "SATUSEHAT_CLIENT_ID": "fake-client",
    "SATUSEHAT_CLIENT_SECRET": "fake-value",
    "SATUSEHAT_ORG_IHS_ID": "100000004",
    "SATUSEHAT_BASE_URL": "https://api-satusehat-stg.dto.kemkes.go.id/fhir-r4/v1",
    "SATUSEHAT_TOKEN_URL": "https://api-satusehat-stg.dto.kemkes.go.id/oauth2/v1/accesstoken",
    "SATUSEHAT_TLS_VERIFY": "true",
}


class JsonResponse:
    def __init__(self, status_code, payload=None, headers=None, malformed=False):
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}
        self.malformed = malformed

    def json(self):
        if self.malformed:
            raise ValueError("invalid body")
        return self.payload


class Transport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url == ENV["SATUSEHAT_TOKEN_URL"]:
            return JsonResponse(200, {
                "access_token": "fake-token",
                "token_type": "Bearer",
                "expires_in": 300,
            })
        return self.response


def test_fhir_put_accepts_http_204_without_a_json_body():
    transport = Transport(JsonResponse(204, malformed=True))
    client = SATUSEHATClient(ENV, transport=transport)

    result = client.update_resource(
        "Encounter", "N10000001",
        {"resourceType": "Encounter", "id": "N10000001", "status": "finished"},
    )

    assert result.status_code == 204
    assert result.payload == {}


def test_fhir_put_can_use_http_acknowledgement_when_body_is_unreadable():
    transport = Transport(JsonResponse(200, malformed=True))
    client = SATUSEHATClient(ENV, transport=transport)

    result = client.update_resource(
        "Encounter", "N10000001",
        {"resourceType": "Encounter", "id": "N10000001", "status": "finished"},
    )

    assert result.status_code == 200
    assert result.payload == {}


def test_fhir_post_with_unreadable_success_body_is_uncertain():
    transport = Transport(JsonResponse(201, malformed=True))
    client = SATUSEHATClient(ENV, transport=transport)

    with pytest.raises(SATUSEHATClientError) as caught:
        client.post_resource("Condition", {"resourceType": "Condition"})

    assert caught.value.status_code == 201
    assert caught.value.uncertain is True


def test_redirect_is_rejected_before_body_parsing():
    transport = Transport(JsonResponse(
        302, headers={"Location": "https://redirect.invalid/"}, malformed=True
    ))
    client = SATUSEHATClient(ENV, transport=transport)

    with pytest.raises(SATUSEHATClientError, match="Redirect") as caught:
        client.post_resource("Condition", {"resourceType": "Condition"})

    assert caught.value.status_code == 302
    assert caught.value.uncertain is True


def test_non_json_server_error_preserves_status_code_and_uncertainty():
    transport = Transport(JsonResponse(503, malformed=True))
    client = SATUSEHATClient(ENV, transport=transport)

    with pytest.raises(SATUSEHATClientError) as caught:
        client.post_resource("Condition", {"resourceType": "Condition"})

    assert caught.value.status_code == 503
    assert caught.value.uncertain is True


def test_non_json_client_error_preserves_status_without_marking_uncertain():
    transport = Transport(JsonResponse(422, malformed=True))
    client = SATUSEHATClient(ENV, transport=transport)

    with pytest.raises(SATUSEHATClientError) as caught:
        client.post_resource("Condition", {"resourceType": "Condition"})

    assert caught.value.status_code == 422
    assert caught.value.uncertain is False



class TimeoutTransport(Transport):
    def request(self, method, url, **kwargs):
        if url == ENV["SATUSEHAT_TOKEN_URL"]:
            return super().request(method, url, **kwargs)
        self.calls.append((method, url, kwargs))
        raise requests.Timeout("timeout")


def test_fhir_put_timeout_is_uncertain():
    transport = TimeoutTransport(JsonResponse(200, {"resourceType": "Encounter", "id": "N10000001"}))
    client = SATUSEHATClient(ENV, transport=transport)

    with pytest.raises(SATUSEHATClientError) as caught:
        client.update_resource(
            "Encounter", "N10000001",
            {"resourceType": "Encounter", "id": "N10000001", "status": "finished"},
        )

    assert caught.value.uncertain is True
