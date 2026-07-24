"""Zero-key geospatial services for the personal JARVIS desktop app."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import requests

USER_AGENT = "JARVIS-Mark-L/1.0 (personal desktop assistant)"
TIMEOUT = 15


class OpenGeoError(RuntimeError):
    pass


class OpenGeoClient:
    """Open-Meteo geocoding/weather plus the public OSRM demo router."""

    def _get(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=TIMEOUT,
        )
        if not response.ok:
            raise OpenGeoError(f"Open geo service error {response.status_code}: {response.text[:220]}")
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            raise OpenGeoError(str(data.get("reason") or "Open geo service rejected the request."))
        return data

    @staticmethod
    def _normalized(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").casefold())
        ascii_text = text.encode("ascii", "ignore").decode()
        return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text).split())

    @classmethod
    def _place_kind(cls, place: dict[str, Any]) -> str:
        code = str(place.get("feature_code") or place.get("featureCode") or "").upper()
        feature_class = str(place.get("feature_class") or place.get("featureClass") or "").upper()
        raw_type = cls._normalized(place.get("type") or place.get("addresstype"))
        if code.startswith("PPL") or feature_class == "P" or raw_type in {
            "city", "town", "village", "municipality", "suburb",
        }:
            return "city"
        if code.startswith("ADM1") or raw_type in {"state", "province", "region"}:
            return "province"
        if code == "PCLI" or raw_type == "country":
            return "country"
        if code.startswith("ADM") or raw_type in {"county", "department", "administrative"}:
            return "administrative"
        return "place"

    @classmethod
    def _candidate_score(
        cls,
        place: dict[str, Any],
        *,
        name: str,
        qualifiers: list[str],
        requested_type: str,
        country_code: str,
    ) -> float:
        candidate_name = cls._normalized(place.get("name") or place.get("display_name"))
        score = 100.0 if candidate_name == name else (35.0 if name in candidate_name else 0.0)
        searchable = cls._normalized(" ".join(str(place.get(field) or "") for field in (
            "name", "admin1", "admin2", "admin3", "country", "country_code", "display_name",
        )))
        score += 30.0 * sum(qualifier in searchable for qualifier in qualifiers)
        kind = cls._place_kind(place)
        if requested_type:
            score += 55.0 if kind == requested_type else -12.0
        elif kind == "city":
            # Spoken place requests normally target a populated place rather
            # than an identically named administrative boundary.
            score += 18.0
        code = str(place.get("country_code") or place.get("countryCode") or "").upper()
        if country_code:
            score += 45.0 if code == country_code else -25.0
        elif code == "AR":
            # This installation uses Buenos Aires as its local clock/location.
            # The small bias disambiguates Pilar and Bella Vista naturally.
            score += 10.0
        population = float(place.get("population") or 0)
        score += min(12.0, population / 100000.0)
        return score

    def _open_meteo_candidates(self, name: str) -> list[dict[str, Any]]:
        data = self._get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": name, "count": 20, "language": "es", "format": "json"},
        )
        return list(data.get("results") or [])

    def _nominatim_candidates(self, query: str) -> list[dict[str, Any]]:
        data = self._get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": query, "format": "jsonv2", "addressdetails": 1,
                "limit": 10, "accept-language": "es",
            },
        )
        if not isinstance(data, list):
            return []
        candidates: list[dict[str, Any]] = []
        for item in data:
            address = item.get("address") or {}
            candidates.append({
                **item,
                "name": (
                    item.get("name") or address.get("city") or address.get("town")
                    or address.get("village") or str(item.get("display_name", "")).split(",", 1)[0]
                ),
                "latitude": item.get("lat"),
                "longitude": item.get("lon"),
                "country": address.get("country", ""),
                "country_code": str(address.get("country_code", "")).upper(),
                "admin1": address.get("state") or address.get("province") or "",
                "admin2": address.get("county") or address.get("state_district") or "",
            })
        return candidates

    def resolve_place(
        self,
        query: str,
        *,
        place_type: str = "",
        country_code: str = "",
    ) -> dict[str, Any]:
        query = str(query or "").strip()
        if len(query) < 2:
            raise OpenGeoError("Enter a city, place name, or postal code.")
        type_aliases = {
            "ciudad": "city", "city": "city", "localidad": "city",
            "provincia": "province", "province": "province", "estado": "province",
            "pais": "country", "country": "country",
        }
        requested_type = type_aliases.get(self._normalized(place_type), "")
        country_code = str(country_code or "").strip().upper()
        pieces = [piece.strip() for piece in query.split(",") if piece.strip()]
        primary_query = pieces[0] if pieces else query
        primary = self._normalized(primary_query)
        qualifiers = [self._normalized(piece) for piece in pieces[1:]]

        matches = self._open_meteo_candidates(primary_query)
        provider = "Open-Meteo / GeoNames"
        if not matches:
            matches = self._nominatim_candidates(query)
            provider = "Nominatim / OpenStreetMap"
        if not matches:
            raise OpenGeoError(f"No location found for: {query}")
        place = max(
            matches,
            key=lambda candidate: self._candidate_score(
                candidate,
                name=primary,
                qualifiers=qualifiers,
                requested_type=requested_type,
                country_code=country_code,
            ),
        )
        region = place.get("admin1") or place.get("admin2") or place.get("country") or ""
        country = str(place.get("country") or "")
        return {
            "id": str(place.get("id") or place.get("place_id") or ""),
            "name": str(place.get("name") or query),
            "address": ", ".join(dict.fromkeys(
                str(part) for part in (place.get("name"), region, country) if part
            )),
            "latitude": float(place["latitude"]),
            "longitude": float(place["longitude"]),
            "country": country,
            "country_code": str(
                place.get("country_code") or place.get("countryCode") or ""
            ).upper(),
            "admin1": str(place.get("admin1") or ""),
            "admin2": str(place.get("admin2") or ""),
            "place_type": self._place_kind(place),
            "timezone": str(place.get("timezone") or "auto"),
            "provider": provider,
        }

    def route(self, origin: str, destination: str, travel_mode: str = "DRIVE") -> dict[str, Any]:
        start = self.resolve_place(origin)
        end = self.resolve_place(destination)
        requested_mode = str(travel_mode or "DRIVE").upper()
        if requested_mode not in {"DRIVE", "DRIVING", "CAR"}:
            raise OpenGeoError(
                "The current zero-key router supports driving routes only; "
                "walking and cycling need another open routing backend."
            )
        coordinates = (
            f"{start['longitude']},{start['latitude']};"
            f"{end['longitude']},{end['latitude']}"
        )
        data = self._get(
            f"https://router.project-osrm.org/route/v1/driving/{coordinates}",
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
        )
        if data.get("code") != "Ok" or not data.get("routes"):
            raise OpenGeoError(str(data.get("message") or "No route found."))
        route = data["routes"][0]
        coords = (route.get("geometry") or {}).get("coordinates") or []
        return {
            "origin": start,
            "destination": end,
            "travel_mode": "DRIVE",
            "requested_mode": requested_mode,
            "duration_seconds": float(route.get("duration", 0)),
            "duration": _format_duration(float(route.get("duration", 0))),
            "distance_meters": float(route.get("distance", 0)),
            "path": [{"lat": float(lat), "lng": float(lon)} for lon, lat in coords],
            "provider": "OSRM / OpenStreetMap",
        }

    def weather(self, location: str) -> dict[str, Any]:
        place = self.resolve_place(location)
        data = self._get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": (
                    "temperature_2m,apparent_temperature,relative_humidity_2m,"
                    "precipitation,weather_code,wind_speed_10m"
                ),
                "timezone": "auto",
                "forecast_days": 1,
            },
        )
        return {
            "place": place,
            "current": data.get("current") or {},
            "units": data.get("current_units") or {},
            "provider": "Open-Meteo",
        }


def _format_duration(seconds: float) -> str:
    minutes = max(0, round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def open_geo(parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    args = dict(parameters or {})
    action = str(args.get("action", "status")).lower()
    if action == "status":
        return {
            "configured": True,
            "billing": False,
            "api_keys": False,
            "map": "MapLibre + OpenFreeMap + OpenStreetMap",
            "geocoding": "Open-Meteo / GeoNames",
            "routes": "OSRM / OpenStreetMap",
            "weather": "Open-Meteo",
        }
    client = OpenGeoClient()
    if action in {"place", "focus"}:
        return client.resolve_place(
            str(args.get("query") or args.get("location") or ""),
            place_type=str(args.get("place_type") or ""),
            country_code=str(args.get("country_code") or ""),
        )
    if action == "route":
        return client.route(
            str(args.get("origin", "")), str(args.get("destination", "")),
            str(args.get("travel_mode", "DRIVE")),
        )
    if action == "weather":
        return client.weather(str(args.get("location", "")))
    raise OpenGeoError(f"Unknown geo action: {action}")
