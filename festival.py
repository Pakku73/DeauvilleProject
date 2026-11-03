import json
import unicodedata
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

FESTIVAL_DAY_START = timedelta(hours=6)
PERFORMANCE_GAP = timedelta(minutes=30)
DATA_PATH = Path("data/festival.json")


class FestivalError(ValueError):
    """Base class for festival-level validation and lookup errors."""


class NotFoundError(FestivalError):
    pass


class ArtistNotFoundError(NotFoundError):
    pass


class VenueNotFoundError(NotFoundError):
    pass


class PerformanceNotFoundError(NotFoundError):
    pass


class ConflictError(FestivalError):
    pass


class InvalidValueError(FestivalError):
    pass


class DuplicateArtistError(ConflictError):
    pass


class DuplicateParticipantError(ConflictError):
    pass


def load_festival(path: str | Path = DATA_PATH) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        raise ValueError(f"Festival data file '{path}' was not found.") from None
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Festival data file '{path}' is damaged (line {error.lineno})."
        ) from None
    except UnicodeDecodeError:
        raise ValueError(f"Festival data file '{path}' is not valid UTF-8.") from None


def save_festival(festival: dict[str, Any], path: str | Path = DATA_PATH) -> None:
    try:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(festival, file, ensure_ascii=False, indent=2)
            file.write("\n")
    except OSError as error:
        raise ValueError(f"Could not save festival data to '{path}': {error}") from None


def slugify(name: str) -> str:
    plain_name = (
        unicodedata.normalize("NFKD", name)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    slug = ""
    for character in plain_name:
        if character.isalnum():
            slug += character
        elif slug and not slug.endswith("-"):
            slug += "-"
    return slug.strip("-")


def find_venue(festival: dict[str, Any], slug: str) -> dict[str, Any] | None:
    for venue in festival["venues"]:
        if slugify(venue["name"]) == slug:
            return venue
    return None


def find_artist(festival: dict[str, Any], slug: str) -> dict[str, Any] | None:
    for artist in festival["artists"]:
        if slugify(artist["name"]) == slug:
            return artist
    return None


class Venue:
    def __init__(self, data: dict[str, Any]):
        self.name = data["name"]
        self.capacity = data["capacity"]
        self.address = data["address"]

    @property
    def slug(self) -> str:
        return slugify(self.name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "capacity": self.capacity,
            "address": self.address,
        }


class Artist:
    def __init__(self, data: dict[str, Any]):
        self.name = data["name"]
        self.bio = data.get("bio", "")
        self.photo_url = data.get("photo_url", "")

    @property
    def slug(self) -> str:
        return slugify(self.name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "bio": self.bio,
            "photo_url": self.photo_url,
        }


class Performance(ABC):
    kind = ""

    def __init__(self, data: dict[str, Any]):
        self.data = data

    @property
    def id(self) -> str:
        return performance_id(self.data)

    @property
    def venue_name(self) -> str:
        return venue_name_from_slug(self.data["venue"])

    @property
    def venue_capacity(self) -> int:
        venue = find_venue(load_festival(), self.data["venue"])
        if venue is None:
            return 0
        return venue["capacity"]

    @property
    def festival_day_value(self) -> date:
        return festival_day(self.data)

    @property
    def artists(self) -> list[dict[str, str]]:
        return [
            {"slug": slug, "name": artist_name(slug)}
            for slug in self.artist_slugs()
        ]

    @abstractmethod
    def artist_slugs(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def summary(self) -> str:
        raise NotImplementedError

    def to_view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.data["kind"],
            "title": self.data["title"],
            "venue": self.data["venue"],
            "venue_name": self.venue_name,
            "start": self.data["start"],
            "end": end_of(self.data).isoformat(timespec="minutes"),
            "duration_minutes": self.data["duration_minutes"],
            "festival_day": self.festival_day_value.isoformat(),
            "description": self.data.get("description", ""),
            "summary": self.summary(),
            "capacity": self.venue_capacity,
            "artists": self.artists,
        }

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Performance):
            return NotImplemented
        return start_of(self.data) < start_of(other.data)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Performance):
            return NotImplemented
        return self.id == other.id

    def __str__(self) -> str:
        return self.data["title"]


class SoloShow(Performance):
    kind = "solo"

    def artist_slugs(self) -> list[str]:
        return [self.data["artist"]]

    def summary(self) -> str:
        return artist_name(self.data["artist"])

    def to_view(self) -> dict[str, Any]:
        view = super().to_view()
        view["artist"] = self.data["artist"]
        view["min_age"] = self.data.get("min_age", 0)
        return view


class Lineup(Performance):
    kind = "lineup"

    def artist_slugs(self) -> list[str]:
        return [self.data["host"], *self.data["acts"]]

    def summary(self) -> str:
        people = [artist_name(slug) for slug in self.artist_slugs()]
        return f"hosted by {people[0]}, with {', '.join(people[1:])}"

    def to_view(self) -> dict[str, Any]:
        view = super().to_view()
        view["host"] = self.data.get("host")
        view["acts"] = self.data.get("acts", [])
        return view


class Workshop(Performance):
    kind = "workshop"

    def __init__(self, data: dict[str, Any]):
        super().__init__(data)
        max_participants = self.data.get("max_participants")
        if max_participants is None:
            self.data["max_participants"] = 0
        if self.data["max_participants"] < 1:
            raise ValueError("A workshop must accept at least one participant.")
        venue = find_venue(load_festival(), self.data["venue"])
        if venue is not None and self.data["max_participants"] > venue["capacity"]:
            self.data["max_participants"] = venue["capacity"]

    def artist_slugs(self) -> list[str]:
        return [self.data["teacher"]]

    def summary(self) -> str:
        teacher = artist_name(self.data["teacher"])
        taken = len(self.data.get("participants", []))
        max_participants = self.data.get("max_participants", 0)
        return f"with {teacher}, {taken}/{max_participants} places taken"

    def to_view(self) -> dict[str, Any]:
        view = super().to_view()
        view["teacher"] = self.data.get("teacher")
        view["max_participants"] = self.data.get("max_participants")
        view["participants"] = self.data.get("participants", [])
        if self.data.get("max_participants") is not None:
            view["places_left"] = self.data["max_participants"] - len(
                self.data.get("participants", [])
            )
        return view


def performance_from_dict(data: dict[str, Any]) -> Performance:
    kinds: dict[str, type[Performance]] = {
        "solo": SoloShow,
        "lineup": Lineup,
        "workshop": Workshop,
    }
    performance_class = kinds.get(data["kind"])
    if performance_class is None:
        raise ValueError(f"Unknown performance kind: {data['kind']!r}.")
    return performance_class(data)


class Festival:
    def __init__(self, data: dict[str, Any]):
        self.name = data["name"]
        self.first_day = data["first_day"]
        self.last_day = data["last_day"]
        self._venues = [Venue(item) for item in data["venues"]]
        self._artists = [Artist(item) for item in data["artists"]]
        self._performances = [
            performance_from_dict(item) for item in data["performances"]
        ]

    @property
    def venues(self) -> list[Venue]:
        return list(self._venues)

    @property
    def artists(self) -> list[Artist]:
        return list(self._artists)

    @property
    def performances(self) -> list[Performance]:
        return list(self._performances)

    @property
    def days(self) -> list[str]:
        day = date.fromisoformat(self.first_day)
        last = date.fromisoformat(self.last_day)
        values: list[str] = []
        while day <= last:
            values.append(day.isoformat())
            day += timedelta(days=1)
        return values

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "first_day": self.first_day,
            "last_day": self.last_day,
            "venues": [venue.to_dict() for venue in self._venues],
            "artists": [artist.to_dict() for artist in self._artists],
            "performances": [performance.data for performance in self._performances],
        }

    def find_venue(self, slug: str) -> Venue | None:
        for venue in self._venues:
            if venue.slug == slug:
                return venue
        return None

    def find_artist(self, slug: str) -> Artist | None:
        for artist in self._artists:
            if artist.slug == slug:
                return artist
        return None

    def find_performance(self, performance_id_value: str) -> Performance | None:
        for performance in self._performances:
            if performance.id == performance_id_value:
                return performance
        return None

    def add_artist(self, name: str) -> Artist:
        cleaned = name.strip()
        if not cleaned:
            raise InvalidValueError("The artist name cannot be empty.")
        if any(artist.slug == slugify(cleaned) for artist in self._artists):
            raise DuplicateArtistError(f"Artist '{cleaned}' already exists.")
        artist = Artist({"name": cleaned, "bio": "", "photo_url": ""})
        self._artists.append(artist)
        return artist

    def add_performance(
        self,
        title: str,
        artist_slug: str,
        venue_slug: str,
        start: datetime,
        duration_minutes: int,
    ) -> Performance:
        cleaned_title = title.strip()
        if not cleaned_title:
            raise InvalidValueError("The performance title cannot be empty.")
        artist = self.find_artist(artist_slug)
        if artist is None:
            raise ArtistNotFoundError(f"No artist '{artist_slug}'.")
        venue = self.find_venue(venue_slug)
        if venue is None:
            raise VenueNotFoundError(f"No venue '{venue_slug}'.")
        if not 1 <= duration_minutes <= 360:
            raise InvalidValueError("Duration must be between 1 and 360 minutes.")

        data = {
            "kind": "solo",
            "title": cleaned_title,
            "venue": venue_slug,
            "start": start.isoformat(timespec="minutes"),
            "duration_minutes": duration_minutes,
            "description": "",
            "artist": artist_slug,
            "min_age": 0,
        }
        self._validate_performance_data(data)
        performance = performance_from_dict(data)
        self._performances.append(performance)
        return performance

    def move_performance(
        self,
        performance_id_value: str,
        *,
        start: datetime | None = None,
        venue_slug: str | None = None,
        duration_minutes: int | None = None,
    ) -> Performance:
        performance = self.find_performance(performance_id_value)
        if performance is None:
            raise PerformanceNotFoundError(f"No performance '{performance_id_value}'.")

        data = dict(performance.data)
        if start is not None:
            data["start"] = start.isoformat(timespec="minutes")
        if venue_slug is not None:
            data["venue"] = venue_slug
        if duration_minutes is not None:
            data["duration_minutes"] = duration_minutes

        self._validate_performance_data(data, ignore_id=performance_id_value)
        performance.data.update(data)
        return performance

    def remove_performance(self, performance_id_value: str) -> Performance:
        for index, performance in enumerate(self._performances):
            if performance.id == performance_id_value:
                return self._performances.pop(index)
        raise PerformanceNotFoundError(f"No performance '{performance_id_value}'.")

    def register_participant(self, performance_id_value: str, name: str) -> str:
        performance = self.find_performance(performance_id_value)
        if performance is None:
            raise PerformanceNotFoundError(f"No performance '{performance_id_value}'.")
        if performance.data["kind"] != "workshop":
            raise InvalidValueError(f"'{performance_id_value}' is not a workshop.")

        cleaned = name.strip()
        if not cleaned:
            raise InvalidValueError("The participant name cannot be empty.")
        participants = performance.data.get("participants", [])
        if any(p.strip().lower() == cleaned.lower() for p in participants):
            raise DuplicateParticipantError(f"'{cleaned}' is already registered.")

        max_participants = performance.data.get("max_participants", 0)
        if len(participants) >= max_participants:
            raise ConflictError(
                f"{performance.data['title']} is already full."
            )

        participants.append(cleaned)
        performance.data["participants"] = participants
        return cleaned

    def _validate_performance_data(
        self,
        data: dict[str, Any],
        *,
        ignore_id: str | None = None,
    ) -> None:
        if data["kind"] not in {"solo", "lineup", "workshop"}:
            raise InvalidValueError(f"Unknown performance kind: {data['kind']!r}.")

        if "title" not in data or not str(data["title"]).strip():
            raise InvalidValueError("The performance title cannot be empty.")

        artist_slug = data.get("artist") or data.get("host") or data.get("teacher")
        if artist_slug is not None:
            if self.find_artist(artist_slug) is None:
                raise ArtistNotFoundError(f"No artist '{artist_slug}'.")

        venue_slug = data.get("venue")
        if venue_slug is not None:
            if self.find_venue(venue_slug) is None:
                raise VenueNotFoundError(f"No venue '{venue_slug}'.")

        if "duration_minutes" in data and not 1 <= data["duration_minutes"] <= 360:
            raise InvalidValueError("Duration must be between 1 and 360 minutes.")

        day = festival_day(data)
        first_day = date.fromisoformat(self.first_day)
        last_day = date.fromisoformat(self.last_day)
        if not first_day <= day <= last_day:
            raise InvalidValueError(f"{day.isoformat()} is not a day of the festival.")

        new_end = end_of(data)
        for existing in self._performances:
            if ignore_id is not None and existing.id == ignore_id:
                continue
            existing_data = existing.data
            existing_start = start_of(existing_data)
            existing_end = end_of(existing_data)
            too_close = (
                start_of(data) < existing_end + PERFORMANCE_GAP
                and existing_start < new_end + PERFORMANCE_GAP
            )
            if not too_close:
                continue
            if existing_data["venue"] == data["venue"]:
                raise ConflictError(
                    f"{self.find_venue(data['venue']).name} is busy with "
                    f"{existing_data['title']} ({existing_start:%Y-%m-%d %H:%M}-"
                    f"{existing_end:%H:%M})."
                )
            if (
                data.get("artist") is not None
                and data["artist"] in performance_artists(existing_data)
            ):
                raise ConflictError(
                    f"{artist_name(data['artist'])} is on stage in "
                    f"{existing_data['title']}."
                )
            if (
                data.get("host") is not None
                and data["host"] in performance_artists(existing_data)
            ):
                raise ConflictError(
                    f"{artist_name(data['host'])} is on stage in "
                    f"{existing_data['title']}."
                )
            if (
                data.get("teacher") is not None
                and data["teacher"] in performance_artists(existing_data)
            ):
                raise ConflictError(
                    f"{artist_name(data['teacher'])} is on stage in "
                    f"{existing_data['title']}."
                )

    def programme(
        self,
        day: str | None = None,
        venue: str | None = None,
    ) -> list[Performance]:
        performances = list(self._performances)
        if day is not None:
            performances = [
                performance
                for performance in performances
                if performance.festival_day_value.isoformat() == day
            ]
        if venue is not None:
            performances = [
                performance
                for performance in performances
                if performance.data["venue"] == venue
            ]
        return sorted(performances, key=lambda item: start_of(item.data))

    def artist_performances(self, artist_slug: str) -> list[Performance]:
        return [
            performance
            for performance in self._performances
            if artist_slug in performance.artist_slugs()
        ]

    def now(self, at: datetime) -> tuple[list[Performance], list[Performance]]:
        current = [
            performance
            for performance in self.programme()
            if start_of(performance.data) <= at < end_of(performance.data)
        ]
        upcoming = [
            performance
            for performance in self.programme()
            if start_of(performance.data) > at
        ][:3]
        return current, upcoming


def artist_name(slug: str) -> str:
    festival = load_festival()
    artist = find_artist(festival, slug)
    if artist is None:
        raise ValueError(f"No artist '{slug}'.")
    return artist["name"]


def venue_name_from_slug(slug: str) -> str:
    festival = load_festival()
    venue = find_venue(festival, slug)
    if venue is None:
        raise ValueError(f"No venue '{slug}'.")
    return venue["name"]


def venue_name(festival: dict[str, Any], slug: str) -> str:
    venue = find_venue(festival, slug)
    if venue is None:
        raise ValueError(f"No venue '{slug}'.")
    return venue["name"]


def start_of(performance: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(performance["start"])


def end_of(performance: dict[str, Any]) -> datetime:
    return start_of(performance) + timedelta(
        minutes=performance["duration_minutes"]
    )


def festival_day(performance: dict[str, Any]) -> date:
    return (start_of(performance) - FESTIVAL_DAY_START).date()


def parse_festival_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"'{value}' is not a day, use YYYY-MM-DD.") from None
    if parsed.isoformat() != value:
        raise ValueError(f"'{value}' is not a day, use YYYY-MM-DD.")
    return parsed


def parse_performance_start(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"'{value}' is not a start, use YYYY-MM-DDTHH:MM."
        ) from None
    if parsed.strftime("%Y-%m-%dT%H:%M") != value or parsed.tzinfo is not None:
        raise ValueError(f"'{value}' is not a start, use YYYY-MM-DDTHH:MM.")
    return parsed


def performance_artists(performance: dict[str, Any]) -> list[str]:
    return performance_from_dict(performance).artist_slugs()


def artist_role(performance: dict[str, Any], artist_slug: str) -> str | None:
    performance_object = performance_from_dict(performance)
    if performance_object.kind == "solo":
        if performance["artist"] == artist_slug:
            return "solo"
    elif performance_object.kind == "lineup":
        if performance["host"] == artist_slug:
            return "host"
        if artist_slug in performance["acts"]:
            return "act"
    elif performance_object.kind == "workshop":
        if performance["teacher"] == artist_slug:
            return "teacher"
    return None


def check_new_performance(
    festival: dict[str, Any],
    title: str,
    artist_slug: str,
    venue_slug: str,
    start: datetime,
    duration_minutes: int,
) -> dict[str, Any]:
    title = title.strip()
    if not title:
        raise ValueError("The performance title cannot be empty.")

    artist = find_artist(festival, artist_slug)
    if artist is None:
        raise ValueError(f"No artist '{artist_slug}'.")
    venue = find_venue(festival, venue_slug)
    if venue is None:
        raise ValueError(f"No venue '{venue_slug}'.")
    if not 1 <= duration_minutes <= 360:
        raise ValueError("Duration must be between 1 and 360 minutes.")

    new_performance: dict[str, Any] = {
        "kind": "solo",
        "title": title,
        "venue": venue_slug,
        "start": start.isoformat(timespec="minutes"),
        "duration_minutes": duration_minutes,
        "description": "",
        "artist": artist_slug,
        "min_age": 0,
    }
    day = festival_day(new_performance)
    first_day = date.fromisoformat(festival["first_day"])
    last_day = date.fromisoformat(festival["last_day"])
    if not first_day <= day <= last_day:
        raise ValueError(f"{day.isoformat()} is not a day of the festival.")

    new_end = end_of(new_performance)
    for existing in festival["performances"]:
        existing_start = start_of(existing)
        existing_end = end_of(existing)
        too_close = (
            start < existing_end + PERFORMANCE_GAP
            and existing_start < new_end + PERFORMANCE_GAP
        )
        if not too_close:
            continue
        if existing["venue"] == venue_slug:
            raise ValueError(
                f"{venue['name']} is busy with {existing['title']} "
                f"({existing_start:%Y-%m-%d %H:%M}-"
                f"{existing_end:%H:%M})."
            )
        if artist_slug in performance_artists(existing):
            raise ValueError(
                f"{artist['name']} is on stage in {existing['title']}."
            )

    return new_performance


def performance_id(performance: dict[str, Any]) -> str:
    return (
        f"{performance['venue']}-"
        f"{start_of(performance):%Y-%m-%d-%H%M}"
    )
