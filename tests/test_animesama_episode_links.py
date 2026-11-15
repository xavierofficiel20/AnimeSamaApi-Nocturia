import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, quote, urlparse

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
        upstream.raw.headers.items.return_value = [
            ("Content-Type", "video/MP2T"),
            ("Access-Control-Allow-Origin", "*"),
        ]
        upstream.iter_content.return_value = iter([b"mpeg-ts-segment"])
        with patch.object(api.requests, "get", return_value=upstream):
            response = api.app.test_client().get(
                "/api/proxy?url=https%3A%2F%2Fvideo.example%2Fsegment.ts",
                headers={"Origin": "http://localhost:5173"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.getlist("Access-Control-Allow-Origin"), ["http://localhost:5173"])
        self.assertEqual(response.data, b"mpeg-ts-segment")

    def test_audio_compatibility_mode_transcodes_allowed_hls_segments(self):
        upstream = Mock()
        upstream.status_code = 200
        upstream.url = "https://prx-1476-ant.vmpx.online/hls/segment.ts"
        upstream.headers = {"Content-Type": "video/MP2T"}
        upstream.raw.headers.items.return_value = [("Content-Type", "video/MP2T")]
        upstream.content = b"original-segment"
        converted = b"\x47converted-segment"
        target = "https://prx-1476-ant.vmpx.online/hls/segment.ts?token=temporary"
        with (
            patch.object(api.requests, "get", return_value=upstream),
            patch.object(api, "_transcode_segment_audio_to_aac", return_value=converted) as transcode,
        ):
            response = api.app.test_client().get(
                f"/api/proxy?url={quote(target, safe='')}&audio=aac"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Content-Type"), "video/MP2T")
        self.assertEqual(response.data, converted)
        transcode.assert_called_once_with(b"original-segment")

    def test_hls_playlist_routes_transport_stream_segments_through_aac_conversion(self):
        upstream = Mock()
        upstream.status_code = 200
        upstream.content = (
            b"#EXTM3U\n"
            b"#EXTINF:10,\n"
            b"segment.ts?token=temporary\n"
            b"#EXT-X-ENDLIST\n"
        )
        playlist_url = "https://prx-1476-ant.vmpx.online/hls/index.m3u8"
        with patch.object(api.requests, "get", return_value=upstream):
            response = api.app.test_client().get(
                f"/api/proxy?url={quote(playlist_url, safe='')}"
            )

        self.assertEqual(response.status_code, 200)
        manifest = response.get_data(as_text=True)
        segment_url = next(line for line in manifest.splitlines() if line.startswith("https://"))
        parsed_segment_url = urlparse(segment_url)
        self.assertEqual(
            parsed_segment_url.netloc,
            "animesamaapi-nocturia-ufs2.onrender.com",
        )
        self.assertEqual(parsed_segment_url.path, "/api/proxy")
        self.assertEqual(
            parse_qs(parsed_segment_url.query)["audio"],
            ["aac"],
        )

    def test_audio_compatibility_mode_rejects_non_animesama_hosts(self):
        with patch.object(api.requests, "get") as fetch:
            response = api.app.test_client().get(
                "/api/proxy?url=https%3A%2F%2Fexample.com%2Fsegment.ts&audio=aac"
            )

        self.assertEqual(response.status_code, 403)
        fetch.assert_not_called()

    def test_audio_compatibility_mode_rejects_unauthorized_redirect_hosts(self):
        upstream = Mock()
        upstream.status_code = 200
        upstream.url = "https://example.com/segment.ts"
        with patch.object(api.requests, "get", return_value=upstream):
            response = api.app.test_client().get(
                "/api/proxy?url=https%3A%2F%2Fprx-1476-ant.vmpx.online%2Fsegment.ts&audio=aac"
            )

        self.assertEqual(response.status_code, 403)

    def test_audio_compatibility_mode_reports_transcoder_failure(self):
        upstream = Mock()
        upstream.status_code = 200
        upstream.url = "https://prx-1476-ant.vmpx.online/hls/segment.ts"
        upstream.headers = {"Content-Type": "video/MP2T"}
        upstream.raw.headers.items.return_value = [("Content-Type", "video/MP2T")]
        upstream.content = b"original-segment"
        with (
            patch.object(api.requests, "get", return_value=upstream),
            patch.object(api, "_transcode_segment_audio_to_aac", return_value=None),
        ):
            response = api.app.test_client().get(
                "/api/proxy?url=https%3A%2F%2Fprx-1476-ant.vmpx.online%2Fhls%2Fsegment.ts&audio=aac"
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.get_json(),
            {"error": "La conversion audio du segment HLS a échoué."},
        )

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
