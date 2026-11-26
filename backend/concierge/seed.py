"""Seed the fictional providers and top up their availability for the next 14 days. Safe to run on every start:
every insert is `ON CONFLICT DO NOTHING` and slot ids are derived from provider and time."""

from datetime import UTC, datetime, time, timedelta

import psycopg

# All providers are FICTIONAL, in real Munich neighbourhoods. Slot times are UTC, read as Munich local time.
# Columns: id, name, neighbourhood, tags (conditions treated), description, price_band (1 low .. 3 high), languages,
#          accessible, home_visits, evenings, weekends
# fmt: off  (one provider per row, so the table stays readable)
PROVIDERS = [
    (
        "p01",
        "Isarblick Physiotherapie",
        "Haidhausen",
        ["back pain", "neck pain", "posture"],
        "Bright clinic near the Isar, strong on desk-related back and neck problems.",
        2,
        ["German", "English"],
        True,
        False,
        True,
        False,
    ),
    (
        "p02",
        "Englischer Garten Sportphysio",
        "Schwabing",
        ["knee", "sports injury", "running"],
        "Sports-focused clinic with a running gait lab.",
        3,
        ["German", "English", "Spanish"],
        True,
        False,
        False,
        True,
    ),
    (
        "p03",
        "Reha Zentrum Maxvorstadt",
        "Maxvorstadt",
        ["post-surgery", "hip", "knee"],
        "Post-operative rehabilitation led by former hospital physiotherapists.",
        3,
        ["German", "English"],
        True,
        True,
        False,
        False,
    ),
    (
        "p04",
        "Familienpraxis Neuhausen",
        "Neuhausen",
        ["paediatric", "back pain", "shoulder"],
        "Family practice that welcomes children and teenagers.",
        2,
        ["German", "English", "French"],
        True,
        False,
        True,
        True,
    ),
    (
        "p05",
        "Hausbesuch Physio Giesing",
        "Giesing",
        ["back pain", "elderly", "balance"],
        "Mobile physiotherapists who visit you at home.",
        2,
        ["German", "Turkish"],
        False,
        True,
        True,
        False,
    ),
    (
        "p06",
        "Schwabinger Sport & Therapie",
        "Schwabing",
        ["sports injury", "shoulder", "knee"],
        "Treats amateur athletes and weekend players; late appointments.",
        2,
        ["German", "English"],
        False,
        False,
        True,
        True,
    ),
    (
        "p07",
        "Wirbelsäulenzentrum Sendling",
        "Sendling",
        ["back pain", "sciatica", "neck pain"],
        "Specialist spine care with exercise-based programmes.",
        3,
        ["German", "English", "Polish"],
        True,
        False,
        False,
        False,
    ),
    (
        "p08",
        "Nymphenburger Physio",
        "Neuhausen",
        ["shoulder", "neck pain", "posture"],
        "Small, affordable clinic near Nymphenburg.",
        1,
        ["German"],
        False,
        False,
        False,
        True,
    ),
    (
        "p09",
        "Frauengesundheit Haidhausen",
        "Haidhausen",
        ["pregnancy", "pelvic", "back pain"],
        "Women's health physiotherapy, including pregnancy-related back pain.",
        2,
        ["German", "English"],
        True,
        False,
        False,
        False,
    ),
    (
        "p10",
        "Giesinger Aktiv Reha",
        "Giesing",
        ["sports injury", "ankle", "running"],
        "Rehab gym and physiotherapy under one roof.",
        2,
        ["German", "English"],
        True,
        False,
        True,
        False,
    ),
    (
        "p11",
        "Praxis am Königsplatz",
        "Maxvorstadt",
        ["back pain", "knee", "elderly"],
        "Long-established practice, calm and unhurried appointments.",
        1,
        ["German", "English"],
        True,
        True,
        False,
        False,
    ),
    (
        "p12",
        "Schnelle Physio Sendling",
        "Sendling",
        ["neck pain", "back pain", "posture"],
        "Short, focused sessions for busy people; early and late slots.",
        1,
        ["German", "English"],
        True,
        False,
        True,
        True,
    ),
]
# fmt: on

WEEKDAY_HOURS = [9, 10, 11, 14, 15, 16]
EVENING_HOURS = [18, 19]
WEEKEND_HOURS = [10, 11]
DAYS_AHEAD = 14


def _slots_for(provider, today):
    _, *_, evenings, weekends = provider
    for offset in range(1, DAYS_AHEAD + 1):
        day = today + timedelta(days=offset)
        weekend = day.weekday() >= 5
        if weekend and not weekends:
            continue
        hours = WEEKEND_HOURS if weekend else WEEKDAY_HOURS + (EVENING_HOURS if evenings else [])
        for i, hour in enumerate(hours):
            if (offset + int(provider[0][1:]) + i) % 3 == 0:  # a deterministic, uneven spread: not everything is free
                continue
            yield f"{provider[0]}-{day:%Y%m%d}-{hour:02d}00", datetime.combine(day, time(hour), tzinfo=UTC)


async def seed(conn: psycopg.AsyncConnection) -> None:
    for p in PROVIDERS:
        await conn.execute(
            "INSERT INTO app.providers (id, name, neighbourhood, tags, description, price_band, languages, accessible, home_visits, evenings, weekends) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            p,
        )
    today = datetime.now(UTC).date()
    for p in PROVIDERS:
        for slot_id, starts_at in _slots_for(p, today):
            await conn.execute(
                "INSERT INTO app.availability_slots (id, provider_id, starts_at) VALUES (%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                (slot_id, p[0], starts_at),
            )
