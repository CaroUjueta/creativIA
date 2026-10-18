"""Pruebas con datos sintéticos: no tocan la red ni requieren claves.

    .venv/bin/python -m unittest discover tests
"""

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from radar import analysis, config, sources
from radar.models import Post, anonymize_author, scrub

END = datetime(2026, 10, 17, tzinfo=timezone.utc)
START = END - timedelta(days=21)


def labels(topic: str, fit: float = 0.67, hook: str = "pregunta") -> dict:
    probs = {t: 0.0 for t in config.TOPICS}
    probs[topic] = 1.0
    return {"classifier": "test", "is_ai": 1.0, "topic": topic, "topic_probs": probs, "topic_confidence": 1.0,
            "hook": hook, "hook_confidence": 1.0, "format": "opinion_o_ensayo", "publisher": "persona_comun",
            "audience_fit": fit, "audience_confidence": 1.0, "practical": 0.5, "technical": 0.2, "hype": 0.1, "latam": 0.0}


def make_posts() -> list[Post]:
    """'agentes_ia' pasa de 1 a 5 piezas diarias en la última semana; 'nuevos_modelos' se mantiene en 10."""
    posts, i = [], 0
    for day in range(21):
        ts = START + timedelta(days=day, hours=12)
        recent = day >= 14
        for topic, n in (("agentes_ia", 5 if recent else 1), ("nuevos_modelos", 10), ("ia_y_sociedad", 4)):
            for _ in range(n):
                i += 1
                posts.append(Post(id=str(i), platform="bluesky", url="", text=f"post {i}", created_at=ts,
                                  author_hash=f"a{i}", likes=i % 7, labels=labels(topic)))
    return posts


class TestAnalysis(unittest.TestCase):
    def setUp(self):
        self.result = analysis.analyze(make_posts(), START, END)
        self.by_id = {t["id"]: t for t in self.result["topics"]}

    def test_growing_topic_detected(self):
        agents = self.by_id["agentes_ia"]
        self.assertGreater(agents["growth"], 2)
        self.assertIn(agents["stage"], {"naciente", "en_crecimiento"})

    def test_large_flat_topic_relative_share_drops(self):
        # El volumen de 'nuevos_modelos' no cambia, pero su participación baja porque otro tema crece.
        self.assertLess(self.by_id["nuevos_modelos"]["growth"], 1)

    def test_growing_topic_ranks_first(self):
        self.assertEqual(self.result["topics"][0]["id"], "agentes_ia")

    def test_stage_rules(self):
        self.assertEqual(analysis.stage_of(2.0, 0.03, 10), "naciente")
        self.assertEqual(analysis.stage_of(1.3, 0.20, 10), "en_crecimiento")
        self.assertEqual(analysis.stage_of(1.0, 0.25, 10), "saturado")
        self.assertEqual(analysis.stage_of(0.5, 0.05, 10), "en_declive")
        self.assertEqual(analysis.stage_of(5.0, 0.01, 1), "estable")  # muy poca evidencia


class TestFeed(unittest.TestCase):
    def test_feed_is_ranked_by_lift_and_has_no_author(self):
        feed = analysis.analyze(make_posts(), START, END)["feed"]
        self.assertTrue(feed)
        self.assertEqual([f["lift"] for f in feed], sorted((f["lift"] for f in feed), reverse=True))
        self.assertNotIn("author_hash", feed[0])

    def test_report_page_renders_feed_and_empty_state(self):
        from radar import report
        result = analysis.analyze(make_posts(), START, END)
        html = report.render_html(result, {}, {"classifier": "test", "adapter": "test", "generated": "x"})
        self.assertIn('"feed": [{', html)
        self.assertIn('id="data">null<', report.render_empty())


class TestPrivacy(unittest.TestCase):
    def test_scrub(self):
        out = scrub("Escríbeme a ana@correo.com o al +57 300 123 4567, cc @ana.perez")
        self.assertNotIn("ana@correo.com", out)
        self.assertNotIn("300 123", out)
        self.assertNotIn("ana.perez", out)

    def test_author_hash_is_stable_and_opaque(self):
        self.assertEqual(anonymize_author("did:plc:x"), anonymize_author("did:plc:x"))
        self.assertNotIn("did", anonymize_author("did:plc:x"))


class TestCommunityCSV(unittest.TestCase):
    def test_reads_rows_in_window(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("platform,url,text,published_at,likes,comments,shares,views,publisher\n")
            f.write("LinkedIn,https://example.com/1,Cómo usar agentes,2026-10-15T10:00:00,120,30,5,,\n")
            f.write("tiktok,https://example.com/2,Fuera de rango,2026-01-01T10:00:00,1,1,1,1,\n")
        posts = sources.community_csv(Path(f.name), START, END)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].platform, "linkedin")
        self.assertEqual(posts[0].likes, 120)


class TestContributions(unittest.TestCase):
    BODY = {"url": "https://www.linkedin.com/posts/x", "platform": "LinkedIn", "published_at": "2026-10-15",
            "text": "Cómo usamos agentes de IA en ventas. Escríbeme a ana@correo.com", "likes": "120", "public": True}

    def test_valid_contribution_is_scrubbed_and_saved(self):
        from radar import web
        row = web.validate_contribution(self.BODY, today=date(2026, 10, 17))
        self.assertEqual(row["platform"], "linkedin")
        self.assertNotIn("ana@correo.com", row["text"])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "comunidad.csv"
            self.assertEqual(sources.append_community(path, row), 1)
            self.assertEqual(sources.append_community(path, row), 2)
            posts = sources.community_csv(path, START, END)
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0].created_at.date(), date(2026, 10, 15))

    def test_rejects_private_or_invalid_contributions(self):
        from radar import web
        for change in ({"public": False}, {"url": "file:///etc/passwd"}, {"text": "corto"},
                       {"published_at": "2025-01-01"}, {"likes": "muchos"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                web.validate_contribution({**self.BODY, **change}, today=date(2026, 10, 17))


class TestYouTubeAPI(unittest.TestCase):
    def test_collects_daily_videos_with_stats_and_no_channel_name(self):
        import asyncio
        import os
        from unittest import mock

        import httpx

        seen_keys = []

        def handler(req):
            seen_keys.append(req.headers.get("x-goog-api-key"))
            self.assertNotIn("key=", str(req.url))  # la clave nunca va en la URL
            if req.url.path.endswith("/search"):
                return httpx.Response(200, json={"items": [{"id": {"videoId": "abc123def45"}, "snippet": {
                    "publishedAt": "2026-10-16T15:00:00Z", "channelId": "UCx", "channelTitle": "Ana Pérez",
                    "title": "Agentes de IA para empresas", "description": "Demo"}}]})
            return httpx.Response(200, json={"items": [{"id": "abc123def45", "statistics": {
                "viewCount": "5000", "likeCount": "300", "commentCount": "12"}}]})

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await sources.youtube_api(client, END - timedelta(days=2), END, 10)

        with mock.patch.dict(os.environ, {"YOUTUBE_API_KEY": "k"}):
            self.assertEqual(sources.youtube_mode(), "api")
            posts = asyncio.run(run())
        self.assertEqual(len(posts), 1)  # el mismo video en varias búsquedas cuenta una vez
        self.assertEqual((posts[0].views, posts[0].likes, posts[0].comments), (5000, 300, 12))
        self.assertEqual(posts[0].publisher, "")
        self.assertNotIn("Ana", posts[0].text)
        self.assertEqual(set(seen_keys), {"k"})


class TestJevFallback(unittest.TestCase):
    def test_falls_back_when_jev_is_unavailable(self):
        import os
        from unittest import mock

        from radar import classify

        async def broken(posts, concurrency):
            raise classify.JevUnavailable("403 Key limit exceeded")

        posts = [Post(id=f"fallback-test-{i}", platform="bluesky", url="", text="Los agentes de IA llegan a las empresas",
                      created_at=END, author_hash="a") for i in range(3)]
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test"}), \
             mock.patch.object(classify, "_classify_jev", broken), \
             mock.patch.object(classify, "_load_cache", lambda: {}), \
             mock.patch.object(classify, "local_available", lambda: False):
            stats = classify.classify(posts, use_jev=True)
        self.assertEqual(stats["classifier"], "heuristico")
        self.assertIn("Key limit", stats["jev_error"])

    def test_tries_next_provider_before_falling_back(self):
        import os
        from unittest import mock

        from radar import classify

        async def first_fails(posts, concurrency):
            if classify.jev_provider() == "digitalocean":
                raise classify.JevUnavailable("403 not available for your subscription tier")
            for p in posts:
                p.labels = {"classifier": "jev"}
            return 10

        posts = [Post(id="provider-test", platform="bluesky", url="", text="x", created_at=END, author_hash="a")]
        with mock.patch.dict(os.environ, {"MODEL_ACCESS_KEY": "a", "OPENROUTER_API_KEY": "b"}), \
             mock.patch.object(classify, "_classify_jev", first_fails), \
             mock.patch.object(classify, "_load_cache", lambda: {}), \
             mock.patch.object(classify, "_append_cache", lambda ps: None):
            stats = classify.classify(posts, use_jev=True)
            self.assertEqual(classify.jev_provider(), "openrouter")
        self.assertEqual((stats["classifier"], stats["input_tokens"]), ("jev", 10))
        self.assertTrue(all(p.labels for p in posts))


class TestBacktest(unittest.TestCase):
    def test_rising_topic_is_predicted_and_holds(self):
        from radar import backtest
        # 28 días: 'agentes_ia' empieza a subir 7 días antes del corte y sigue arriba después.
        end, posts, i = END, [], 0
        for day in range(28):
            ts = end - timedelta(days=28 - day, hours=-12)
            for topic, n in (("agentes_ia", 5 if day >= 14 else 1), ("nuevos_modelos", 10), ("ia_y_sociedad", 4)):
                for _ in range(n):
                    i += 1
                    posts.append(Post(id=str(i), platform="bluesky", url="", text=f"post {i}", created_at=ts,
                                      author_hash=f"a{i}", likes=i % 7, labels=labels(topic)))
        bt = backtest.evaluate(posts, end, weeks=1, top=1)
        fold = bt["folds"][0]
        self.assertEqual(fold["radar_top"], ["agentes_ia"])
        self.assertEqual(fold["radar_hit"], 1.0)
        self.assertEqual(fold["popular_top"], ["nuevos_modelos"])
        self.assertEqual(bt["summary"]["weeks"], 1)
        self.assertIn("¿Siguió arriba?", backtest.render_markdown(bt, {"classifier": "test", "generated": "x"}))


class TestZenAdapter(unittest.TestCase):
    def test_parses_fenced_json_and_fills_missing_topics(self):
        import json
        import os
        from unittest import mock

        import httpx

        from radar import adapt

        topics = analysis.analyze(make_posts(), START, END)["topics"][:2]
        item = {"topic_id": topics[0]["id"], "por_que_funciona": "x", "angulo": "y", "ganchos": ["a", "b", "c"],
                "formatos": {"linkedin": "1", "instagram": "2", "tiktok": "3", "youtube": "4"}, "cuidado": "z"}
        content = "```json\n" + json.dumps({"temas": [item]}) + "\n```"
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"choices": [{"message": {"content": content}}]}))
        real_client = httpx.Client
        with mock.patch.dict(os.environ, {"OPENCODE_API_KEY": "test"}), \
             mock.patch("httpx.Client", lambda **kw: real_client(transport=transport, **kw)):
            out = adapt._with_zen(topics)
        self.assertEqual(out[topics[0]["id"]]["angulo"], "y")
        self.assertIn(topics[1]["id"], out)  # completado con plantilla


class TestOpenRouterWriter(unittest.TestCase):
    def test_falls_back_to_free_open_model(self):
        import json
        import os
        from unittest import mock

        import httpx

        from radar import adapt

        topics = analysis.analyze(make_posts(), START, END)["topics"][:1]
        item = {"topic_id": topics[0]["id"], "por_que_funciona": "x", "angulo": "y", "ganchos": ["a", "b", "c"],
                "formatos": {"linkedin": "1", "instagram": "2", "tiktok": "3", "youtube": "4"}, "cuidado": "z"}

        def handler(req):
            model = json.loads(req.content)["model"]
            if model == adapt.OPENROUTER_MODELS[0]:
                return httpx.Response(403, json={"error": {"message": "Key limit exceeded"}})
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"temas": [item]})}}]})

        real_client = httpx.Client
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test"}), \
             mock.patch("httpx.Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
            out, adapter = adapt.adapt(topics, use_llm=True)
        self.assertEqual(adapter, f"openrouter ({adapt.OPENROUTER_MODELS[1]})")
        self.assertEqual(out[topics[0]["id"]]["angulo"], "y")


if __name__ == "__main__":
    unittest.main()
