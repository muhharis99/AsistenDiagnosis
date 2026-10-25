"""Sandbox-only SATUSEHAT REST client. Network calls are opt-in and never follow redirects."""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlencode

import requests

from rme.integrations.satusehat.mapping import SANDBOX_BASE_URL, SANDBOX_TOKEN_URL


ALLOWED_RESOURCE_TYPES = {
    "Patient", "Practitioner", "Organization", "Location", "Encounter",
    "Condition", "Composition",
}
NIK_PATTERN = re.compile(r"^[0-9]{16}$")
RESOURCE_PATH_PATTERN = re.compile(r"^[A-Za-z]+(?:/[A-Za-z0-9.-]+)?$")


class SATUSEHATClientError(RuntimeError):
    """Error with safe summary only; secrets and raw OperationOutcome never appear in text."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        issue_codes: list[str] | None = None,
        uncertain: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.issue_codes = issue_codes or []
        self.uncertain = uncertain


@dataclass(frozen=True)
class ApiResponse:
    status_code: int
    payload: dict[str, Any]
    headers: Mapping[str, str]


class SATUSEHATClient:
    """Small server-to-server client for the official SATUSEHAT staging URLs only.

    The client refuses to perform a request unless SATUSEHAT_ENABLE_NETWORK=true.
    APP_MODE remains demo, TLS verification is always enabled, and production hosts
    cannot be selected through configuration.
    """

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        *,
        transport: Any | None = None,
        clock=time.monotonic,
    ) -> None:
        self.env = dict(os.environ if env is None else env)
        self.transport = transport or requests.Session()
        self.clock = clock
        self._access_token: str | None = None
        self._token_expires_at = 0.0

        self.app_mode = (self.env.get("APP_MODE") or "demo").strip().lower()
        self.mode = (self.env.get("SATUSEHAT_MODE") or "mock").strip().lower()
        enabled_text = (self.env.get("SATUSEHAT_ENABLE_NETWORK") or "false").strip().lower()
        self.network_enabled = enabled_text in {"true", "1", "yes"}
        self.client_id = (self.env.get("SATUSEHAT_CLIENT_ID") or "").strip()
        self.client_secret = (self.env.get("SATUSEHAT_CLIENT_SECRET") or "").strip()
        self.organization_ihs_id = (self.env.get("SATUSEHAT_ORG_IHS_ID") or "").strip()
        self.base_url = (self.env.get("SATUSEHAT_BASE_URL") or SANDBOX_BASE_URL).strip().rstrip("/")
        self.token_url = (self.env.get("SATUSEHAT_TOKEN_URL") or SANDBOX_TOKEN_URL).strip().rstrip("/")
        tls_text = (self.env.get("SATUSEHAT_TLS_VERIFY") or "true").strip().lower()

        if self.app_mode != "demo":
            raise SATUSEHATClientError("Klien integrasi hanya diizinkan saat APP_MODE=demo.")
        if self.mode != "sandbox":
            raise SATUSEHATClientError("SATUSEHAT_MODE harus sandbox; mode mock tidak membuka jaringan.")
        if not self.network_enabled:
            raise SATUSEHATClientError("Jaringan SATUSEHAT nonaktif; set SATUSEHAT_ENABLE_NETWORK=true secara eksplisit.")
        if not self.client_id or not self.client_secret:
            raise SATUSEHATClientError("SATUSEHAT_CLIENT_ID/SECRET belum dikonfigurasi.")
        if not re.fullmatch(r"[0-9]{6,20}", self.organization_ihs_id):
            raise SATUSEHATClientError("SATUSEHAT_ORG_IHS_ID tidak memenuhi format lokal yang diharapkan.")
        if self.base_url != SANDBOX_BASE_URL or self.token_url != SANDBOX_TOKEN_URL:
            raise SATUSEHATClientError("URL tidak termasuk endpoint staging SATUSEHAT yang diizinkan.")
        if tls_text not in {"true", "1", "yes"}:
            raise SATUSEHATClientError("Verifikasi TLS wajib aktif.")
        self.verify_tls = True

    @staticmethod
    def _issue_codes(payload: Any) -> list[str]:
        if not isinstance(payload, dict) or payload.get("resourceType") != "OperationOutcome":
            return []
        codes: list[str] = []
        for issue in payload.get("issue", [])[:20]:
            if isinstance(issue, dict):
                code = issue.get("code")
                if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9.-]{1,80}", code):
                    codes.append(code)
        return codes

    @staticmethod
    def _json_payload(response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except (ValueError, requests.JSONDecodeError) as exc:
            raise SATUSEHATClientError(
                "Respons SATUSEHAT bukan JSON yang dapat diproses.",
                status_code=getattr(response, "status_code", None),
                uncertain=True,
            ) from exc
        if not isinstance(payload, dict):
            raise SATUSEHATClientError(
                "Struktur respons SATUSEHAT tidak sesuai.",
                status_code=getattr(response, "status_code", None),
                uncertain=True,
            )
        return payload

    def obtain_access_token(self, *, force_refresh: bool = False) -> str:
        now = self.clock()
        if not force_refresh and self._access_token and now < self._token_expires_at:
            return self._access_token
        try:
            response = self.transport.request(
                "POST",
                self.token_url,
                params={"grant_type": "client_credentials"},
                data={"client_id": self.client_id, "client_secret": self.client_secret},
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                timeout=(3.05, 15),
                verify=True,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise SATUSEHATClientError("Tidak dapat menjangkau endpoint token sandbox.") from exc
        status = int(getattr(response, "status_code", 0))
        payload = self._json_payload(response)
        if status < 200 or status >= 300:
            raise SATUSEHATClientError(
                "Autentikasi sandbox ditolak.",
                status_code=status,
                issue_codes=self._issue_codes(payload),
            )
        token = payload.get("access_token")
        token_type = str(payload.get("token_type") or "").casefold()
        if not isinstance(token, str) or not token.strip() or token_type not in {"bearertoken", "bearer"}:
            raise SATUSEHATClientError("Respons token sandbox tidak berisi access_token/tipe bearer yang valid.")
        try:
            expires_in = int(payload.get("expires_in", 300))
        except (TypeError, ValueError):
            expires_in = 300
        if expires_in <= 0:
            raise SATUSEHATClientError("Masa berlaku token sandbox tidak valid.")
        self._access_token = token
        self._token_expires_at = now + max(1, expires_in - min(60, max(5, expires_in // 10)))
        return token

    def request(
        self,
        method: str,
        resource_path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> ApiResponse:
        verb = method.strip().upper()
        path = (resource_path or "").strip().strip("/")
        if verb not in {"GET", "POST"}:
            raise SATUSEHATClientError("Metode HTTP tidak diizinkan pada fase ini.")
        if not RESOURCE_PATH_PATTERN.fullmatch(path):
            raise SATUSEHATClientError("Resource path tidak valid.")
        parts = path.split("/")
        if parts[0] not in ALLOWED_RESOURCE_TYPES or len(parts) > 2:
            raise SATUSEHATClientError("Resource type/path tidak diizinkan.")
        if len(parts) == 2 and parts[1] in {".", ".."}:
            raise SATUSEHATClientError("ID resource tidak valid.")
        if verb == "POST" and (len(parts) != 1 or json_body is None):
            raise SATUSEHATClientError("POST hanya boleh ke endpoint koleksi resource dengan body FHIR.")
        if verb == "GET" and json_body is not None:
            raise SATUSEHATClientError("GET tidak menerima body.")

        token = self.obtain_access_token()
        url = f"{self.base_url}/{path}"
        query = dict(params or {})
        try:
            response = self.transport.request(
                verb,
                url,
                params=query or None,
                json=json_body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/fhir+json, application/json",
                    **({"Content-Type": "application/fhir+json"} if verb == "POST" else {}),
                },
                timeout=(3.05, 20),
                verify=True,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise SATUSEHATClientError(
                "Request sandbox gagal; status penerimaan resource belum dapat dipastikan.",
                uncertain=verb == "POST",
            ) from exc
        status = int(getattr(response, "status_code", 0))
        payload = self._json_payload(response)
        if 300 <= status < 400:
            raise SATUSEHATClientError(
                "Redirect dari endpoint sandbox ditolak.",
                status_code=status,
                uncertain=verb == "POST",
            )
        if status < 200 or status >= 300:
            raise SATUSEHATClientError(
                "Permintaan ke API sandbox ditolak.",
                status_code=status,
                issue_codes=self._issue_codes(payload),
                uncertain=(verb == "POST" and status >= 500),
            )
        return ApiResponse(status, payload, dict(getattr(response, "headers", {}) or {}))

    def search_patient_by_nik(self, nik: str) -> ApiResponse:
        """Search Patient through MPI using the documented NIK identifier query."""
        value = (nik or "").strip()
        if not re.fullmatch(r"[0-9]{16}", value):
            raise SATUSEHATClientError("Pencarian MPI memerlukan NIK uji 16 digit.")
        return self.request(
            "GET",
            "Patient",
            params={"identifier": f"https://fhir.kemkes.go.id/id/nik|{value}"},
        )

    def post_resource(self, resource_type: str, payload: dict[str, Any]) -> ApiResponse:
        if resource_type not in {"Condition", "Composition"}:
            raise SATUSEHATClientError("Fase ini hanya mengirim Condition dan Composition.")
        if payload.get("resourceType") != resource_type:
            raise SATUSEHATClientError("Tipe resource tidak cocok dengan antrean.")
        return self.request("POST", resource_type, json_body=payload)
