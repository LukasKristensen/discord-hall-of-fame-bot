"""Tests for the two bot listing sites the server count is reported to.

Both are fire-and-forget calls made from the daily task, and both sites answer with HTML rather than
JSON when something is wrong on their side. The bot must survive that, because a listing site having
a bad day is not a reason for the daily task to fail.
"""

import unittest
from unittest import mock

import requests

from api_services import discordbotlist_api, topgg_api


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_fails=False):
        self.status_code = status_code
        self.payload = payload if payload is not None else {}
        self.json_fails = json_fails

    def json(self):
        if self.json_fails:
            raise requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)
        return self.payload


class TopGgPostBotStatsTests(unittest.TestCase):
    def post(self, response, server_count=140, api_key="secret"):
        with mock.patch.object(requests, "post", return_value=response) as request:
            result = topgg_api.post_bot_stats(server_count, api_key)
        return result, request.call_args

    def test_reports_the_server_count(self):
        _, call = self.post(FakeResponse())

        self.assertEqual({"server_count": 140}, call.kwargs["json"])

    def test_authorises_with_the_key_it_was_given(self):
        _, call = self.post(FakeResponse(), api_key="a-real-key")

        self.assertEqual("a-real-key", call.kwargs["headers"]["Authorization"])

    def test_posts_to_the_stats_endpoint(self):
        _, call = self.post(FakeResponse())

        self.assertEqual("https://top.gg/api/bots/1177041673352663070/stats", call.args[0])

    def test_returns_the_status_and_the_answer(self):
        result, _ = self.post(FakeResponse(status_code=200, payload={"ok": True}))

        self.assertEqual((200, {"ok": True}), result)

    def test_survives_an_answer_that_is_not_json(self):
        """The site answers with an HTML error page often enough to matter."""
        result, _ = self.post(FakeResponse(status_code=502, json_fails=True))

        self.assertEqual(502, result[0])
        self.assertIn("error", result[1])

    def test_leaves_out_the_shard_fields_until_the_bot_is_sharded(self):
        _, call = self.post(FakeResponse())

        self.assertNotIn("shard_count", call.kwargs["json"])

    def test_reports_the_shards_once_there_are_some(self):
        with mock.patch.object(requests, "post", return_value=FakeResponse()) as request:
            topgg_api.post_bot_stats(140, "secret", shards=[10, 12], shard_id=0, shard_count=2)

        self.assertEqual({"server_count": 140, "shards": [10, 12], "shard_id": 0, "shard_count": 2},
                         request.call_args.kwargs["json"])


class DiscordBotListPostBotStatsTests(unittest.TestCase):
    def post(self, response, server_count=140):
        with mock.patch.object(requests, "post", return_value=response) as request:
            result = discordbotlist_api.post_bot_stats(server_count)
        return result, request.call_args

    def test_reports_the_server_count_under_the_name_the_site_expects(self):
        _, call = self.post(FakeResponse())

        self.assertEqual({"guilds": 140}, call.kwargs["json"])

    def test_posts_to_the_stats_endpoint(self):
        _, call = self.post(FakeResponse())

        self.assertEqual("https://discordbotlist.com/api/v1/bots/1177041673352663070/stats", call.args[0])

    def test_returns_the_status_and_the_answer(self):
        result, _ = self.post(FakeResponse(status_code=200, payload={"success": True}))

        self.assertEqual((200, {"success": True}), result)

    def test_survives_an_answer_that_is_not_json(self):
        result, _ = self.post(FakeResponse(status_code=500, json_fails=True))

        self.assertEqual(500, result[0])
        self.assertIn("error", result[1])


class DiscordBotListCommandListTests(unittest.TestCase):
    def post(self, response=None):
        with mock.patch.object(requests, "post", return_value=response or FakeResponse()) as request:
            result = discordbotlist_api.post_command_list()
        return result, request.call_args

    def test_describes_every_command_it_publishes(self):
        _, call = self.post()

        for command in call.kwargs["json"]:
            with self.subTest(command=command["name"]):
                self.assertTrue(command["description"])
                self.assertEqual(1, command["type"])

    def test_publishes_the_commands_members_can_use(self):
        _, call = self.post()

        names = {command["name"] for command in call.kwargs["json"]}
        self.assertIn("leaderboard", names)
        self.assertIn("user_profile", names)
        self.assertIn("help", names)

    def test_survives_an_answer_that_is_not_json(self):
        result, _ = self.post(FakeResponse(status_code=503, json_fails=True))

        self.assertEqual(503, result[0])
        self.assertIn("error", result[1])


if __name__ == "__main__":
    unittest.main()
