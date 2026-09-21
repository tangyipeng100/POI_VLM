import json
import unittest

from inference_bridge import (
    build_payload,
    endpoint_from_base,
    parse_decision,
    response_text,
)


class InferenceBridgeTest(unittest.TestCase):
    def test_endpoint_normalization(self):
        self.assertEqual(
            endpoint_from_base("http://localhost:8000/v1", "chat"),
            "http://localhost:8000/v1/chat/completions",
        )
        self.assertEqual(
            endpoint_from_base("https://example.test/v1/responses", "responses"),
            "https://example.test/v1/responses",
        )

    def test_payload_contains_text_and_image(self):
        payload = build_payload(["data:image/png;base64,abc", "data:image/jpeg;base64,def"], "choose", "demo", "chat", 80)
        content = payload["messages"][0]["content"]
        self.assertEqual([item["type"] for item in content], ["text", "image_url", "image_url"])
        self.assertEqual(payload["model"], "demo")

    def test_response_parsing_tolerates_fence_and_string_poi(self):
        decision = parse_decision('```json\n{"action":"go_to_poi","poi_number":"3","reason":"left edge"}\n```')
        self.assertEqual(decision, {"action": "go_to_poi", "poi_number": 3, "reason": "left edge"})

    def test_response_parsing_keeps_rotation_fields(self):
        decision = parse_decision('{"action":"rotate","poi_number":null,"rotate_direction":"right","rotate_angle_deg":30,"reason":"turn"}')
        self.assertEqual(decision["action"], "rotate")
        self.assertEqual(decision["rotate_direction"], "right")
        self.assertEqual(decision["rotate_angle_deg"], 30)

    def test_unparsed_response_is_bounded(self):
        decision = parse_decision("x" * 900)
        self.assertEqual(decision["action"], "unparsed")
        self.assertLessEqual(len(decision["reason"]), 500)

    def test_chat_and_responses_text_extraction(self):
        chat = {"choices": [{"message": {"content": '{"action":"skip"}'}}]}
        responses = {"output": [{"content": [{"type": "output_text", "text": '{"action":"rotate"}'}]}]}
        self.assertEqual(json.loads(response_text(chat, "chat"))["action"], "skip")
        self.assertEqual(json.loads(response_text(responses, "responses"))["action"], "rotate")


if __name__ == "__main__":
    unittest.main()
