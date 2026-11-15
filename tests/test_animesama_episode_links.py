import unittest
from unittest.mock import Mock, patch

from src.utils import utils

utils.Utils.findLink = lambda: "https://anime-sama.to"

from src import backend
from src import api


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
    def test_stream_proxy_returns_one_cors_origin_header(self):
        upstream = Mock()
        upstream.status_code = 200
        upstream.raw.headers.items.return_value = [("Content-Type", "video/MP2T")]
        upstream.iter_content.return_value = iter([b"mpeg-ts-segment"])
        with patch.object(api.requests, "get", return_value=upstream):
            response = api.app.test_client().get(
                "/api/proxy?url=https%3A%2F%2Fvideo.example%2Fsegment.ts",
                headers={"Origin": "http://localhost:5173"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.getlist("Access-Control-Allow-Origin"), ["http://localhost:5173"])
        self.assertEqual(response.data, b"mpeg-ts-segment")

    def test_episode_list_route_returns_episode_data(self):
        episodes = [{"episode": 1, "title": "Episode 1"}]
        with patch.object(backend.Cardinal, "getAnimeEpisodes", return_value=episodes) as get_episodes:
            response = api.app.test_client().get(
                "/api/getAnimeEpisodes?n=Example&s=saison2&v=vf"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), episodes)
        get_episodes.assert_called_once_with("Example", "saison2", "vf")

    def test_episode_list_route_requires_an_anime_name(self):
        response = api.app.test_client().get("/api/getAnimeEpisodes")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "Paramètre 'n' manquant"})

    def test_lists_episode_numbers_for_current_page_data(self):
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
                ):
                    result = backend.Cardinal.getAnimeEpisodes("Example", "saison1", language)

                self.assertEqual(
                    result,
                    [{"episode": 1, "title": "Episode 1"}],
                )

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

                self.assertEqual(
                    result,
                    {
                        "episode": 1,
                        "url": "https://ansembed.net/embed/primary",
                        "type": "embed",
                        "server": "ansembed",
                        "streams": [
                            {
                                "url": "https://ansembed.net/embed/primary",
                                "type": "embed",
                                "server": "ansembed",
                            },
                            {
                                "url": "https://uqload.vc/embed/backup",
                                "type": "embed",
                                "server": "uqload",
                            },
                        ],
                    },
                )
                self.assertEqual(
                    scraper.resolver_calls,
                    [
                        {"j": "temporary-token", "l": "2433"},
                        {"j": "temporary-token", "l": "2432"},
                    ],
                )


if __name__ == "__main__":
    unittest.main()
