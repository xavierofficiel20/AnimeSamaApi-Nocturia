import unittest
from unittest.mock import patch

from src.utils import utils

utils.Utils.findLink = lambda: "https://anime-sama.to"

from src import backend


class FakeResponse:
    status_code = 200

    def __init__(self, *, text="", payload=None):
        self.text = text
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeScraper:
    def __init__(self, media_by_id):
        self.media_by_id = media_by_id
        self.resolver_calls = []

    def get(self, url, *, params=None, **kwargs):
        if url.endswith("/api/lien.php"):
            self.resolver_calls.append(params)
            return FakeResponse(payload={"u": self.media_by_id[params["l"]]})
        return FakeResponse(
            text=(
                '<script data-source="bdd">'
                'var eps1 = ["lien:2433"];'
                'var eps2 = ["lien:2432"];'
                'var epsJeton = "temporary-token";'
                "</script>"
            )
        )


class AnimeSamaEpisodeLinksTests(unittest.TestCase):
    def test_resolves_current_page_episode_references_for_each_language(self):
        for language in ("vostfr", "vf"):
            with self.subTest(language=language):
                scraper = FakeScraper(
                    {
                        "2433": "https://ansembed.net/embed/primary",
                        "2432": "https://uqload.vc/embed/backup",
                    }
                )
                season = {
                    "base_url": "https://anime-sama.to/catalogue/example",
                    "url": f"https://anime-sama.to/catalogue/example/saison1/{language}",
                }
                with (
                    patch.object(backend.Cardinal, "getSpecificAnime", return_value=season),
                    patch.object(backend.cloudscraper, "create_scraper", return_value=scraper),
                    patch.object(backend, "resolve_video_url", return_value=None),
                ):
                    result = backend.Cardinal.getAnimeLink("Example", "saison1", language, "1")

                self.assertEqual(result, {"episode": 1, "url": "https://ansembed.net/embed/primary"})
                self.assertEqual(
                    scraper.resolver_calls,
                    [
                        {"j": "temporary-token", "l": "2433"},
                        {"j": "temporary-token", "l": "2432"},
                    ],
                )


if __name__ == "__main__":
    unittest.main()
