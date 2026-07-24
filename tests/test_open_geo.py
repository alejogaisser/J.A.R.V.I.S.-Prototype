from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from actions.open_geo import OpenGeoClient, OpenGeoError, open_geo


def response(data):
    item = Mock(ok=True)
    item.json.return_value = data
    return item


class OpenGeoTests(unittest.TestCase):
    @patch("actions.open_geo.requests.get")
    def test_resolves_place_without_key(self, get):
        get.return_value = response({"results": [{
            "id": 1, "name": "Buenos Aires", "latitude": -34.6,
            "longitude": -58.38, "country": "Argentina", "admin1": "Buenos Aires",
        }]})
        place = OpenGeoClient().resolve_place("Buenos Aires")
        self.assertEqual(place["name"], "Buenos Aires")
        self.assertNotIn("apikey", get.call_args.kwargs["params"])
        self.assertIn("JARVIS-Mark-L", get.call_args.kwargs["headers"]["User-Agent"])

    @patch("actions.open_geo.requests.get")
    def test_prefers_argentine_city_over_same_named_foreign_place(self, get):
        get.return_value = response({"results": [
            {
                "id": 1, "name": "Pilar", "latitude": 8.0, "longitude": -80.0,
                "country": "Panama", "country_code": "PA", "feature_code": "PPL",
                "population": 12000,
            },
            {
                "id": 2, "name": "Pilar", "latitude": -34.46, "longitude": -58.91,
                "country": "Argentina", "country_code": "AR", "admin1": "Buenos Aires",
                "feature_code": "PPLA2", "population": 81000,
            },
        ]})
        place = OpenGeoClient().resolve_place("Pilar", place_type="city")
        self.assertEqual(place["id"], "2")
        self.assertEqual(place["place_type"], "city")
        self.assertEqual(place["country_code"], "AR")

    @patch("actions.open_geo.requests.get")
    def test_qualifier_and_type_distinguish_city_from_province(self, get):
        get.return_value = response({"results": [
            {
                "id": 3, "name": "Bella Vista", "latitude": -1, "longitude": -1,
                "country": "Argentina", "country_code": "AR",
                "feature_code": "ADM1", "admin1": "Bella Vista",
            },
            {
                "id": 4, "name": "Bella Vista", "latitude": -34.56, "longitude": -58.69,
                "country": "Argentina", "country_code": "AR",
                "feature_code": "PPL", "admin1": "Buenos Aires",
            },
        ]})
        place = OpenGeoClient().resolve_place(
            "Bella Vista, Buenos Aires", place_type="ciudad", country_code="AR"
        )
        self.assertEqual(place["id"], "4")
        self.assertEqual(place["address"], "Bella Vista, Buenos Aires, Argentina")

    @patch("actions.open_geo.requests.get")
    def test_route_returns_geojson_path(self, get):
        place_a = {"results": [{"name": "Alpha", "latitude": 1, "longitude": 2}]}
        place_b = {"results": [{"name": "Beta", "latitude": 3, "longitude": 4}]}
        route = {"code": "Ok", "routes": [{
            "duration": 3660, "distance": 1200,
            "geometry": {"coordinates": [[2, 1], [4, 3]]},
        }]}
        get.side_effect = [response(place_a), response(place_b), response(route)]
        result = OpenGeoClient().route("Alpha", "Beta")
        self.assertEqual(result["path"], [{"lat": 1.0, "lng": 2.0}, {"lat": 3.0, "lng": 4.0}])
        self.assertEqual(result["duration"], "1 h 01 min")

    def test_status_explicitly_has_no_billing_or_keys(self):
        status = open_geo({"action": "status"})
        self.assertFalse(status["billing"])
        self.assertFalse(status["api_keys"])

    @patch("actions.open_geo.requests.get")
    def test_does_not_misrepresent_unsupported_travel_mode(self, get):
        get.side_effect = [
            response({"results": [{"name": "Alpha", "latitude": 1, "longitude": 2}]}),
            response({"results": [{"name": "Beta", "latitude": 3, "longitude": 4}]}),
        ]
        with self.assertRaises(OpenGeoError):
            OpenGeoClient().route("Alpha", "Beta", "WALK")


if __name__ == "__main__":
    unittest.main()
