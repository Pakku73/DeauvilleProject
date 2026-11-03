import os
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from festival import (
    check_new_performance,
    end_of,
    festival_day,
    load_festival,
    slugify,
    start_of,
)

TRACK = Path(__file__).parent.parent


def run_command(
    *arguments: str,
    cwd: Path = TRACK,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, str(TRACK / "main.py"), *arguments],
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=20,
    )


def run_main(*arguments: str) -> str:
    result = run_command(*arguments)
    assert result.returncode == 0, result.stderr
    return result.stdout


def copy_festival_data(folder: Path) -> Path:
    data_folder = folder / "data"
    data_folder.mkdir()
    data_path = data_folder / "festival.json"
    shutil.copyfile(TRACK / "data" / "festival.json", data_path)
    return data_path


def test_slugify_removes_accents_and_collapses_separators():
    assert slugify("Théâtre des Planches") == "theatre-des-planches"
    assert slugify("Élodie  Marchal !") == "elodie-marchal"


def test_default_command_prints_summary():
    assert run_main() == (
        "Deauville Festival du Rire 2027\n"
        "From 2027-06-10 to 2027-06-13\n"
        "4 venues, 12 artists, 23 performances\n"
    )


def test_venues_command_prints_slugs_and_total():
    assert run_main("venues") == (
        "grand-casino: Grand Casino, 650 seats\n"
        "theatre-des-planches: Théâtre des Planches, 320 seats\n"
        "le-kiosque: Le Kiosque, 120 seats\n"
        "la-cabane: La Cabane, 40 seats\n"
        "Total: 1130 seats\n"
    )


def test_programme_command_prints_selected_day():
    assert run_main("programme", "2027-06-11") == (
        "Programme for Friday 11 June:\n"
        "10:30-12:30 | La Cabane | Improv for Beginners (workshop)\n"
        "15:00-16:30 | Le Kiosque | Writing a Punchline (workshop)\n"
        "18:00-19:15 | Théâtre des Planches | Nothing Serious (solo)\n"
        "20:30-21:50 | Grand Casino | Tall Tales (solo)\n"
        "21:30-22:40 | Théâtre des Planches | Straight Face (solo)\n"
        "23:30-00:30 | Le Kiosque | Late Laughs (solo)\n"
        "01:00-02:00 | Le Kiosque | After Hours (lineup)\n"
    )


def test_programme_command_moves_after_midnight_to_previous_festival_day():
    assert "After Hours" not in run_main("programme", "2027-06-12")
    assert "01:00-02:00 | Le Kiosque | After Hours (lineup)\n" in run_main(
        "programme", "2027-06-11"
    )


def test_artist_command_prints_performances_and_roles():
    assert run_main("artist", "max-pellerin") == (
        "Max Pellerin\n"
        "Thu 10 20:30-22:30 | Grand Casino | Opening Gala (act)\n"
        "Fri 11 23:30-00:30 | Le Kiosque | Late Laughs (solo)\n"
        "Sat 12 21:00-22:40 | Théâtre des Planches | "
        "Deauville Comedy Club (host)\n"
        "Sun 13 20:30-22:40 | Grand Casino | Closing Gala (act)\n"
    )


def test_artist_command_finds_accents_and_teacher_role():
    output = run_main("artist", "ines-moreau")

    assert output.startswith("Inès Moreau\n")
    assert "Fri 11 10:30-12:30 | La Cabane | Improv for Beginners (teacher)\n" in output


def test_artist_command_reports_unknown_slug():
    assert run_main("artist", "nobody") == "No artist 'nobody'.\n"


def test_unknown_command_prints_usage():
    assert run_main("unknown") == (
        "Usage:\n"
        "  uv run main.py\n"
        "  uv run main.py venues\n"
        "  uv run main.py programme YYYY-MM-DD\n"
        "  uv run main.py artist SLUG\n"
        "  uv run main.py now YYYY-MM-DDTHH:MM\n"
        "  uv run main.py add\n"
        "  uv run main.py cancel ID\n"
    )


def test_performance_datetimes_and_festival_day():
    festival = load_festival()
    after_hours = next(
        performance
        for performance in festival["performances"]
        if performance["title"] == "After Hours"
    )

    assert start_of(after_hours) == datetime(2027, 6, 12, 1)
    assert end_of(after_hours) == datetime(2027, 6, 12, 2)
    assert festival_day(after_hours) == date(2027, 6, 11)


def test_now_command_shows_current_performance_and_next_three():
    assert run_main("now", "2027-06-11T21:00") == (
        "On stage at 2027-06-11 21:00:\n"
        "- Tall Tales at Grand Casino, until 21:50\n"
        "Up next:\n"
        "- 21:30-22:40 | Théâtre des Planches | Straight Face (solo)\n"
        "- 23:30-00:30 | Le Kiosque | Late Laughs (solo)\n"
        "- 01:00-02:00 | Le Kiosque | After Hours (lineup)\n"
    )


def test_now_command_handles_moment_after_midnight():
    assert run_main("now", "2027-06-12T01:30") == (
        "On stage at 2027-06-12 01:30:\n"
        "- After Hours at Le Kiosque, until 02:00\n"
        "Up next:\n"
        "- 10:30-12:30 | La Cabane | Stand-up Lab (workshop)\n"
        "- 11:00-12:00 | Théâtre des Planches | Brunch & Punchlines (solo)\n"
        "- 15:00-16:30 | Le Kiosque | New Faces (lineup)\n"
    )


def test_add_command_saves_new_performance_and_cancel_removes_it(tmp_path):
    copy_festival_data(tmp_path)

    added = run_command(
        "add",
        cwd=tmp_path,
        input_text=(
            "Morning Coffee\n"
            "karim-benali\n"
            "la-cabane\n"
            "2027-06-13T08:00\n"
            "30\n"
        ),
    )
    assert added.returncode == 0, added.stderr
    assert "Added: la-cabane-2027-06-13-0800\n" in added.stdout

    programme = run_command("programme", "2027-06-13", cwd=tmp_path)
    assert programme.returncode == 0, programme.stderr
    assert programme.stdout.splitlines()[1] == (
        "08:00-08:30 | La Cabane | Morning Coffee (solo)"
    )

    cancelled = run_command(
        "cancel", "la-cabane-2027-06-13-0800", cwd=tmp_path
    )
    assert cancelled.returncode == 0, cancelled.stderr
    assert cancelled.stdout == "Cancelled: Morning Coffee\n"
    after_cancel = run_command("programme", "2027-06-13", cwd=tmp_path)
    assert "Morning Coffee" not in after_cancel.stdout


@pytest.mark.parametrize(
    ("answers", "expected_error"),
    [
        (
            "Too Late\nkarim-benali\nle-kiosque\n2027-06-12T02:15\n30\n",
            "Le Kiosque is busy with After Hours (2027-06-12 01:00-02:00).",
        ),
        (
            "Too Close\nmax-pellerin\nla-cabane\n2027-06-11T23:00\n30\n",
            "Max Pellerin is on stage in Late Laughs.",
        ),
        (
            "Out of Festival\nkarim-benali\nla-cabane\n2027-06-14T08:00\n30\n",
            "2027-06-14 is not a day of the festival.",
        ),
        (
            "Bad Duration\nkarim-benali\nla-cabane\n2027-06-13T08:00\nhalf an hour\n",
            "'half an hour' is not a number of minutes.",
        ),
    ],
)
def test_add_command_rejects_invalid_schedules(
    tmp_path, answers: str, expected_error: str
):
    copy_festival_data(tmp_path)

    result = run_command("add", cwd=tmp_path, input_text=answers)

    assert result.returncode == 1
    assert result.stdout.rstrip().endswith(f"Error: {expected_error}")
    assert "Traceback" not in result.stderr


def test_invalid_programme_day_exits_with_a_clear_error():
    result = run_command("programme", "June-11")

    assert result.returncode == 1
    assert result.stdout == "Error: 'June-11' is not a day, use YYYY-MM-DD.\n"
    assert "Traceback" not in result.stderr


def test_cancel_unknown_id_exits_with_a_clear_error():
    result = run_command("cancel", "unknown-id")

    assert result.returncode == 1
    assert result.stdout == "Error: No performance 'unknown-id'.\n"


def test_damaged_data_file_exits_with_a_clear_error(tmp_path):
    data_path = copy_festival_data(tmp_path)
    data_path.write_text("[{", encoding="utf-8")

    result = run_command(cwd=tmp_path)

    assert result.returncode == 1
    assert (
        "Error: Festival data file 'data\\festival.json' is damaged (line 1)."
        in result.stdout
    )
    assert "Traceback" not in result.stderr


def test_check_new_performance_rejects_unknown_artist_and_venue():
    festival = load_festival()
    start = datetime(2027, 6, 13, 8)

    with pytest.raises(ValueError, match="No artist 'nobody'"):
        check_new_performance(
            festival, "Morning Coffee", "nobody", "la-cabane", start, 30
        )
    with pytest.raises(ValueError, match="No venue 'unknown-venue'"):
        check_new_performance(
            festival, "Morning Coffee", "karim-benali", "unknown-venue", start, 30
        )


@pytest.mark.parametrize(
    "artist_slug",
    ["tom-vasseur", "hugo-lemaire", "elodie-marchal", "maya-choukri"],
)
def test_check_new_performance_checks_every_lineup_role(artist_slug):
    festival = load_festival()

    with pytest.raises(ValueError, match="is on stage in Open Mic Night"):
        check_new_performance(
            festival,
            "Another Show",
            artist_slug,
            "la-cabane",
            datetime(2027, 6, 10, 22),
            30,
        )


def test_check_new_performance_checks_workshop_teacher():
    festival = load_festival()

    with pytest.raises(ValueError, match="is on stage in Improv for Beginners"):
        check_new_performance(
            festival,
            "Another Workshop",
            "ines-moreau",
            "le-kiosque",
            datetime(2027, 6, 11, 10),
            30,
        )


@pytest.mark.parametrize("duration", [0, 361])
def test_check_new_performance_rejects_duration_outside_allowed_range(duration):
    festival = load_festival()

    with pytest.raises(ValueError, match="between 1 and 360 minutes"):
        check_new_performance(
            festival,
            "Morning Coffee",
            "karim-benali",
            "la-cabane",
            datetime(2027, 6, 13, 8),
            duration,
        )


def test_check_new_performance_allows_exactly_thirty_minutes_between_shows():
    festival = load_festival()

    performance = check_new_performance(
        festival,
        "Morning Coffee",
        "karim-benali",
        "le-kiosque",
        datetime(2027, 6, 12, 2, 30),
        30,
    )

    assert performance["title"] == "Morning Coffee"


def test_programme_rejects_invalid_date_with_exit_code_one():
    result = run_command("programme", "2027-02-30")

    assert result.returncode == 1
    assert result.stdout == "Error: '2027-02-30' is not a day, use YYYY-MM-DD.\n"
