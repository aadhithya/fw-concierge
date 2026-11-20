"""Seed the fictional providers and top up their availability for the next 14 days. Safe to run on every start."""

from datetime import UTC, datetime, time, timedelta

import psycopg

# id, name, neighbourhood, tags, description, price_band, languages, accessible, home_visits, evenings, weekends
PROVIDERS = [
    ("p01", "Harbourside Physio", "Harbourside", ["back pain", "neck pain", "posture"], "Friendly clinic by the ferry, strong on desk-related back and neck problems.", 2, ["English"], True, False, True, False),
    ("p02", "Old Mill Movement Clinic", "Old Mill", ["knee", "sports injury", "running"], "Sports-focused clinic with a running gait lab.", 3, ["English", "Spanish"], True, False, False, True),
    ("p03", "Kestrel Heights Rehab", "Kestrel Heights", ["post-surgery", "hip", "knee"], "Post-operative rehabilitation led by former hospital physios.", 3, ["English"], True, True, False, False),
    ("p04", "Lantern Quay Family Physio", "Lantern Quay", ["paediatric", "back pain", "shoulder"], "Family practice that welcomes children and teenagers.", 2, ["English", "French"], True, False, True, True),
    ("p05", "Fernwick Home Physio", "Fernwick", ["back pain", "elderly", "balance"], "Mobile physiotherapists who visit you at home.", 2, ["English"], False, True, True, False),
    ("p06", "Tideway Sports Therapy", "Harbourside", ["sports injury", "shoulder", "knee"], "Treats amateur athletes and weekend players; late appointments.", 2, ["English"], False, False, True, True),
    ("p07", "Millrace Spine Centre", "Old Mill", ["back pain", "sciatica", "neck pain"], "Specialist spine care, exercise-based programmes.", 3, ["English", "Polish"], True, False, False, False),
    ("p08", "Gull Street Physio", "Lantern Quay", ["shoulder", "neck pain", "posture"], "Small, affordable clinic near the quay.", 1, ["English"], False, False, False, True),
    ("p09", "Heather Hill Wellbeing", "Kestrel Heights", ["pregnancy", "pelvic", "back pain"], "Women's health physiotherapy, including pregnancy-related back pain.", 2, ["English"], True, False, False, False),
    ("p10", "Fernwick Active Recovery", "Fernwick", ["sports injury", "ankle", "running"], "Rehab gym and physio under one roof.", 2, ["English"], True, False, True, False),
    ("p11", "Saltmarsh Physiotherapy", "Harbourside", ["back pain", "knee", "elderly"], "Long-established clinic, calm and unhurried appointments.", 1, ["English", "Welsh"], True, True, False, False),
    ("p12", "Quayside Express Physio", "Lantern Quay", ["neck pain", "back pain", "posture"], "Short, focused sessions for busy people; early and late slots.", 1, ["English"], True, False, True, True),
]

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
