"""FastAPI routes for the Deauville festival."""

from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from festival import (
    ConflictError,
    Festival,
    FestivalError,
    InvalidValueError,
    NotFoundError,
    PerformanceNotFoundError,
    find_artist,
    find_venue,
    load_festival,
    parse_performance_start,
    save_festival,
)

app = FastAPI(title="Deauville Festival du Rire")


STATUS = {
    NotFoundError: 404,
    ConflictError: 409,
    InvalidValueError: 422,
}


class PerformanceIn(BaseModel):
    title: str
    artist: str
    venue: str
    start: str
    duration_minutes: int


class PerformancePatch(BaseModel):
    title: str | None = None
    artist: str | None = None
    venue: str | None = None
    start: str | None = None
    duration_minutes: int | None = None


class ArtistIn(BaseModel):
    name: str


class ParticipantIn(BaseModel):
    name: str


@app.exception_handler(FestivalError)
def festival_error(request: Request, error: FestivalError) -> JSONResponse:
    status_code = STATUS.get(type(error), 400)
    return JSONResponse(status_code=status_code, content={"detail": str(error)})


festival_data = load_festival()
festival = Festival(festival_data)


@app.get("/api/festival")
def get_festival() -> dict[str, object]:
    return {
        "name": festival.name,
        "first_day": festival.first_day,
        "last_day": festival.last_day,
        "days": festival.days,
    }


@app.get("/api/venues")
def list_venues() -> list[dict[str, object]]:
    return [
        {
            "slug": venue.slug,
            "name": venue.name,
            "capacity": venue.capacity,
            "address": venue.address,
        }
        for venue in festival.venues
    ]


@app.get("/api/artists")
def list_artists() -> list[dict[str, object]]:
    artists = [
        {
            "slug": artist.slug,
            "name": artist.name,
            "bio": artist.bio,
            "photo_url": artist.photo_url,
        }
        for artist in festival.artists
    ]
    return sorted(artists, key=lambda item: item["slug"])


@app.get("/api/programme")
def get_programme(
    day: date | None = None,
    venue: str | None = Query(default=None),
) -> list[dict[str, object]]:
    if venue is not None and find_venue(festival_data, venue) is None:
        raise HTTPException(status_code=404, detail=f"No venue '{venue}'.")
    performances = festival.programme(
        day.isoformat() if day is not None else None,
        venue,
    )
    return [performance.to_view() for performance in performances]


@app.get("/api/performances/{performance_id}")
def get_performance(performance_id: str) -> dict[str, object]:
    performance = festival.find_performance(performance_id)
    if performance is None:
        raise HTTPException(
            status_code=404,
            detail=f"No performance '{performance_id}'.",
        )
    return performance.to_view()


@app.get("/api/artists/{artist_slug}")
def get_artist(artist_slug: str) -> dict[str, object]:
    artist = find_artist(festival_data, artist_slug)
    if artist is None:
        raise HTTPException(status_code=404, detail=f"No artist '{artist_slug}'.")
    performances = [
        performance.to_view()
        for performance in festival.artist_performances(artist_slug)
    ]
    return {
        "slug": artist_slug,
        "name": artist["name"],
        "bio": artist.get("bio", ""),
        "photo_url": artist.get("photo_url", ""),
        "performances": performances,
    }


@app.get("/api/now")
def get_now(at: str | None = None) -> dict[str, object]:
    import datetime as dt

    if at is None:
        moment = dt.datetime.now()
    else:
        try:
            moment = dt.datetime.fromisoformat(at)
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail=f"'{at}' is not a moment, use YYYY-MM-DDTHH:MM.",
            ) from error
    current, upcoming = festival.now(moment)
    return {
        "now_playing": [performance.to_view() for performance in current],
        "up_next": [performance.to_view() for performance in upcoming],
    }


@app.post("/api/admin/performances", status_code=201)
def create_performance(body: PerformanceIn) -> dict[str, object]:
    performance = festival.add_performance(
        body.title,
        body.artist,
        body.venue,
        parse_performance_start(body.start),
        body.duration_minutes,
    )
    save_festival(festival.to_dict())
    return performance.to_view()


@app.put("/api/admin/performances/{performance_id}")
def update_performance(
    performance_id: str,
    body: PerformancePatch,
) -> dict[str, object]:
    performance = festival.find_performance(performance_id)
    if performance is None:
        raise PerformanceNotFoundError(f"No performance '{performance_id}'.")

    data = dict(performance.data)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if key == "start":
            data["start"] = parse_performance_start(value).isoformat(
                timespec="minutes"
            )
        else:
            data[key] = value

    festival._validate_performance_data(data, ignore_id=performance_id)
    performance.data.update(data)
    save_festival(festival.to_dict())
    return performance.to_view()


@app.delete("/api/admin/performances/{performance_id}", status_code=204)
def delete_performance(performance_id: str) -> Response:
    festival.remove_performance(performance_id)
    save_festival(festival.to_dict())
    return Response(status_code=204)


@app.post("/api/admin/artists", status_code=201)
def create_artist(body: ArtistIn) -> dict[str, object]:
    artist = festival.add_artist(body.name)
    save_festival(festival.to_dict())
    return artist.to_dict()


@app.post("/api/admin/performances/{performance_id}/participants", status_code=201)
def add_participant(
    performance_id: str,
    body: ParticipantIn,
) -> dict[str, object]:
    name = festival.register_participant(performance_id, body.name)
    save_festival(festival.to_dict())
    return {"performance_id": performance_id, "name": name}


public_dir = Path(__file__).parent / "web" / "public"
admin_dir = Path(__file__).parent / "web" / "admin"
if admin_dir.exists():
    app.mount("/admin/", StaticFiles(directory=str(admin_dir), html=True))
if public_dir.exists():
    app.mount("/", StaticFiles(directory=str(public_dir), html=True))
