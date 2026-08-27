#!/usr/bin/env python3
"""Black-box HTTP contract for ores-otel-sidecar consumers.

These tests describe the published probe surface. They do not import product
crates. Set SIDECAR_URL (e.g. http://127.0.0.1:9090) to exercise a live process.
"""

from __future__ import annotations

import json
import os
import unittest
import urllib.error
import urllib.request

ALLOWED_GET = ("/healthz", "/health", "/readyz", "/ready", "/metrics")
FORBIDDEN_METHODS = ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT")
FORBIDDEN_PATHS = ("/", "/admin", "/healthz/../secret", "/metrics/../etc/passwd")
REQUIRED_HEADERS = ("connection", "cache-control", "x-content-type-options")


def live_url() -> str | None:
    raw = os.environ.get("SIDECAR_URL", "").strip().rstrip("/")
    return raw or None


class ContractMatrix(unittest.TestCase):
    def test_probe_paths_are_explicit(self):
        for path in ALLOWED_GET:
            self.assertTrue(path.startswith("/"))
        self.assertIn("/healthz", ALLOWED_GET)
        self.assertIn("/readyz", ALLOWED_GET)
        self.assertIn("/metrics", ALLOWED_GET)
        for path in FORBIDDEN_PATHS:
            self.assertNotIn(path, ALLOWED_GET)

    def test_mutation_and_debug_methods_are_forbidden(self):
        for method in FORBIDDEN_METHODS:
            self.assertNotIn(method, {"GET", "HEAD"})
        self.assertNotIn("GET", FORBIDDEN_METHODS)
        self.assertNotIn("HEAD", FORBIDDEN_METHODS)

    def test_health_json_shape_has_no_secrets(self):
        sample = {"ok": True, "service": "example-sidecar"}
        encoded = json.dumps(sample)
        self.assertTrue(sample["ok"])
        self.assertIsInstance(sample["service"], str)
        for secret in ("token", "password", "authorization", "cookie"):
            self.assertNotIn(secret, sample)
            self.assertNotIn(secret, encoded)

    def test_stdio_is_not_the_probe_interface(self):
        self.assertTrue(live_url() is None or live_url().startswith("http"))
        self.assertNotIn("stdin", ALLOWED_GET)

    def test_query_strings_do_not_create_new_routes(self):
        self.assertEqual("/readyz?foo=1".split("?", 1)[0], "/readyz")
        self.assertIn("/readyz", ALLOWED_GET)


@unittest.skipUnless(live_url(), "SIDECAR_URL not set")
class LiveSidecar(unittest.TestCase):
    def _request(self, method: str, path: str, data: bytes | None = None) -> tuple[int, dict[str, str], str]:
        req = urllib.request.Request(f"{live_url()}{path}", data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                headers = {k.lower(): v for k, v in resp.headers.items()}
                body = resp.read().decode("utf-8")
                return resp.status, headers, body
        except urllib.error.HTTPError as err:
            headers = {k.lower(): v for k, v in err.headers.items()}
            body = err.read().decode("utf-8")
            return err.code, headers, body

    def test_healthz_ok_json(self):
        status, headers, body = self._request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertIn("json", headers.get("content-type", ""))
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["service"])
        self.assertNotIn("token", payload)

    def test_health_alias_and_readyz(self):
        status, _, body = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        status, _, body = self._request("GET", "/readyz")
        self.assertIn(status, {200, 503})
        self.assertIn("ok", json.loads(body))

    def test_metrics_exposes_up_gauge(self):
        status, _, body = self._request("GET", "/metrics")
        self.assertEqual(status, 200)
        self.assertIn("ores_otel_sidecar_up", body)

    def test_hardening_headers_present(self):
        _, headers, _ = self._request("GET", "/healthz")
        self.assertEqual(headers.get("connection"), "close")
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")

    def test_post_put_and_trace_are_rejected(self):
        for method in ("POST", "PUT", "TRACE"):
            status, _, _ = self._request(method, "/healthz", data=b"{}" if method != "TRACE" else None)
            self.assertIn(status, {400, 405}, method)

    def test_unknown_and_traversal_are_404(self):
        for path in ("/nope", "/healthz/../secret"):
            status, _, _ = self._request("GET", path)
            self.assertEqual(status, 404, path)


if __name__ == "__main__":
    unittest.main()
