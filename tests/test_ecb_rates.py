import os
from datetime import date
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

import httpx

from src.ecb_rates import load_ecb_rates


def archive(usd: float) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as output:
        output.writestr(
            "eurofxref-hist.csv",
            f"Date,USD,GBP,\n2026-11-20,{usd},0.8,\n2026-11-19,1.25,N/A,\n",
        )
    return buffer.getvalue()


class EcbRatesTest(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"PP_ECB_CACHE_DIR": directory}))
        self.cached_file = Path(directory) / "ecb-rates.zip"
        self.fetch = self.enterContext(patch("src.ecb_rates.httpx.get"))

    def respond(self, content):
        self.fetch.return_value = httpx.Response(
            200, content=content, request=httpx.Request("GET", "https://www.ecb.europa.eu"),
        )

    def test_missing_cache_downloads_and_reuses_historical_rates(self):
        self.respond(archive(1.25))
        rates = load_ecb_rates()
        self.assertEqual(rates.history("USD", "GBP"), {date(2026, 11, 20): 0.64})
        self.assertIs(load_ecb_rates(), rates)
        self.fetch.assert_called_once()

        os.utime(self.cached_file, (0, 0))
        self.respond(archive(2))
        self.assertEqual(load_ecb_rates().history("USD", "EUR")[date(2026, 11, 20)], 0.5)

    def test_bad_download_keeps_stale_cache(self):
        original = archive(1.25)
        self.cached_file.write_bytes(original)
        os.utime(self.cached_file, (0, 0))
        self.respond(b"not a ZIP")

        with self.assertLogs("src.ecb_rates", level="WARNING"):
            rates = load_ecb_rates()
        self.assertIs(load_ecb_rates(), rates)
        self.assertEqual(self.cached_file.read_bytes(), original)
        self.fetch.assert_called_once()

    def test_explicit_snapshot_can_be_used_offline(self):
        self.cached_file.write_bytes(archive(2))
        rates = load_ecb_rates(self.cached_file)
        self.assertEqual(rates.history("EUR", "USD")[date(2026, 11, 20)], 2)
        self.fetch.assert_not_called()
