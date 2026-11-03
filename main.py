"""Command-line interface for the Deauville Festival du Rire."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from festival import (
    DATA_PATH,
    artist_role,
    check_new_performance,
    end_of,
    festival_day,
    find_artist,
    load_festival,
    parse_festival_date,
    parse_performance_start,
    performance_id,
    save_festival,
    slugify,
    start_of,
    venue_name,
)


def show_summary(festival: dict[str, Any]) -> None:
    print(festival["name"])
    print(f"From {festival['first_day']} to {festival['last_day']}")
    print(
        f"{len(festival['venues'])} venues, "
        f"{len(festival['artists'])} artists, "
        f"{len(festival['performances'])} performances"
    )


def show_venues(festival: dict[str, Any]) -> None:
    total_seats = 0
    for venue in festival["venues"]:
        slug = slugify(venue["name"])
        print(f"{slug}: {venue['name']}, {venue['capacity']} seats")
        total_seats += venue["capacity"]
    print(f"Total: {total_seats} seats")


def show_programme(festival: dict[str, Any], day: str) -> None:
    selected_day = parse_festival_date(day)
    print(f"Programme for {selected_day:%A %d %B}:")
    performances = sorted(festival["performances"], key=start_of)
    for performance in performances:
        if festival_day(performance) == selected_day:
            place = venue_name(festival, performance["venue"])
            print(
                f"{start_of(performance):%H:%M}-{end_of(performance):%H:%M} "
                f"| {place} | {performance['title']} "
                f"({performance['kind']})"
            )


def show_artist(festival: dict[str, Any], artist_slug: str) -> None:
    artist = find_artist(festival, artist_slug)
    if artist is None:
        print(f"No artist '{artist_slug}'.")
        return

    print(artist["name"])
    for performance in sorted(festival["performances"], key=start_of):
        role = artist_role(performance, artist_slug)
        if role is not None:
            place = venue_name(festival, performance["venue"])
            print(
                f"{festival_day(performance):%a %d} "
                f"{start_of(performance):%H:%M}-{end_of(performance):%H:%M} "
                f"| {place} | "
                f"{performance['title']} ({role})"
            )


def show_now(festival: dict[str, Any], moment: str) -> None:
    try:
        at = datetime.fromisoformat(moment)
    except ValueError:
        raise ValueError(
            f"'{moment}' is not a moment, use YYYY-MM-DDTHH:MM."
        ) from None
    if at.strftime("%Y-%m-%dT%H:%M") != moment or at.tzinfo is not None:
        raise ValueError(f"'{moment}' is not a moment, use YYYY-MM-DDTHH:MM.")

    performances = sorted(festival["performances"], key=start_of)
    current = [
        performance
        for performance in performances
        if start_of(performance) <= at < end_of(performance)
    ]
    print(f"On stage at {at:%Y-%m-%d %H:%M}:")
    for performance in current:
        place = venue_name(festival, performance["venue"])
        print(
            f"- {performance['title']} at {place}, "
            f"until {end_of(performance):%H:%M}"
        )

    upcoming = [
        performance
        for performance in performances
        if start_of(performance) > at
    ][:3]
    print("Up next:")
    for performance in upcoming:
        place = venue_name(festival, performance["venue"])
        print(
            f"- {start_of(performance):%H:%M}-{end_of(performance):%H:%M} "
            f"| {place} | {performance['title']} "
            f"({performance['kind']})"
        )


def add_performance(
    festival: dict[str, Any], path: str | Path = DATA_PATH
) -> None:
    title = input("Title: ").strip()
    artist_slug = input("Artist (slug): ").strip()
    venue_slug = input("Venue (slug): ").strip()
    start_text = input("Start (YYYY-MM-DDTHH:MM): ").strip()
    duration_text = input("Duration (minutes): ").strip()
    try:
        duration_minutes = int(duration_text)
    except ValueError:
        raise ValueError(
            f"'{duration_text}' is not a number of minutes."
        ) from None

    performance = check_new_performance(
        festival,
        title,
        artist_slug,
        venue_slug,
        parse_performance_start(start_text),
        duration_minutes,
    )
    festival["performances"].append(performance)
    save_festival(festival, path)
    print(f"Added: {performance_id(performance)}")


def cancel_performance(
    festival: dict[str, Any],
    performance_id_to_cancel: str,
    path: str | Path = DATA_PATH,
) -> None:
    for index, performance in enumerate(festival["performances"]):
        if performance_id(performance) == performance_id_to_cancel:
            festival["performances"].pop(index)
            save_festival(festival, path)
            print(f"Cancelled: {performance['title']}")
            return
    raise ValueError(f"No performance '{performance_id_to_cancel}'.")


def show_usage() -> None:
    print(
        "Usage:\n"
        "  uv run main.py\n"
        "  uv run main.py venues\n"
        "  uv run main.py programme YYYY-MM-DD\n"
        "  uv run main.py artist SLUG\n"
        "  uv run main.py now YYYY-MM-DDTHH:MM\n"
        "  uv run main.py add\n"
        "  uv run main.py cancel ID"
    )


def main() -> None:
    arguments = sys.argv[1:]
    try:
        festival = load_festival()
        if not arguments:
            show_summary(festival)
        elif arguments == ["venues"]:
            show_venues(festival)
        elif len(arguments) == 2 and arguments[0] == "programme":
            show_programme(festival, arguments[1])
        elif len(arguments) == 2 and arguments[0] == "artist":
            show_artist(festival, arguments[1])
        elif len(arguments) == 2 and arguments[0] == "now":
            show_now(festival, arguments[1])
        elif arguments == ["add"]:
            add_performance(festival)
        elif len(arguments) == 2 and arguments[0] == "cancel":
            cancel_performance(festival, arguments[1])
        else:
            show_usage()
    except ValueError as error:
        print(f"Error: {error}")
        sys.exit(1)
    except EOFError:
        print("Error: Input ended before all answers were given.")
        sys.exit(1)


if __name__ == "__main__":
    main()
