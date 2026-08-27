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
FORBIDDEN_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def live_url() -> str | None:
    raw = os.environ.get("SIDECAR_URL", "").strip().rstrip("/")
    return raw or None


class ContractMatrix(unittest.TestCase):
    def test_probe_paths_are_explicit(self):
        self.assertIn("/healthz", ALLOWED_GET)
        self.assertIn("/readyz", ALLOWED_GET)
        self.assertIn("/metrics", ALLOWED_GET)
        self.assertNotIn("/", ALLOWED_GET)
        self.assertNotIn("/admin", ALLOWED_GET)

    def test_mutation_methods_are_forbidden(self):
        self.assertIn("POST", FORBIDDEN_METHODS)
        self.assertNotIn("GET", FORBIDDEN_METHODS)
        self.assertNotIn("HEAD", FORBIDDEN_METHODS)

    def test_health_json_shape(self):
        sample = {"ok": True, "service": "example-sidecar"}
        self.assertTrue(sample["ok"])
        self.assertIsInstance(sample["service"], str)
        self.assertNotIn("token", sample)
        self.assertNotIn("password", sample)


@unittest.skipUnless(live_url(), "SIDECAR_URL not set")
class LiveSidecar(unittest.TestCase):
    def _request(self, method: str, path: str, data: bytes | None = None) -> tuple[int, str, str]:
        req = urllib.request.Request(f"{live_url()}{path}", data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                body = resp.read().decode("utf-8")
                return resp.status, resp.headers.get("content-type", ""), body
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8")
            return err.code, err.headers.get("content-type", ""), body

    def test_healthz_ok_json(self):
        status, ctype, body = self._request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertIn("json", ctype)
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["service"])

    def test_metrics_exposes_up_gauge(self):
        status, _, body = self._request("GET", "/metrics")
        self.assertEqual(status, 200)
        self.assertIn("ores_otel_sidecar_up", body)

    def test_post_healthz_is_rejected(self):
        status, _, _ = self._request("POST", "/healthz", data=b"{}")
        self.assertIn(status, {400, 405})

    def test_unknown_path_is_404(self):
        status, _, _ = self._request("GET", "/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
