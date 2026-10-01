"""Dashboard aggregation: an average day, never a total dressed up as one."""
from datetime import date, timedelta

import pandas as pd

from app.services.insights import generate_insights, whatsapp_summary
from app.services.metrics import (
    complete_days,
    daily_totals_by_weekday,
    heatmap_series,
    hourly_series,
    is_partial,
)


def frame(rows):
    return pd.DataFrame(rows, columns=["date", "hour", "footfall", "transactions", "sales"])


def day(date, hours, footfall=10, transactions=5, sales=500.0):
    return [(date, h, footfall, transactions, sales) for h in hours]


def by_hour(series):
    return {h["hour"]: h for h in series}


class TestHourlyAverages:
    def test_is_a_per_day_average_not_a_sum(self):
        df = frame(day("2026-09-14", [9], 10) + day("2026-09-15", [9], 20))
        h = by_hour(hourly_series(df))[9]
        assert h["footfall"] == 15  # not 30

    def test_conversion_comes_from_totals(self):
        # A quiet hour must not outweigh a busy one in the average.
        df = frame([("2026-09-14", 9, 2, 2, 100.0), ("2026-09-15", 9, 100, 10, 900.0)])
        assert by_hour(hourly_series(df))[9]["conversion"] == 12 / 102

    def test_an_unfinished_today_does_not_drag_the_evening_down(self):
        # 20:00 exists on the full day only, so it averages over one day.
        df = frame(
            day("2026-09-20", [9, 20], footfall=10) + day("2026-09-21", [9], footfall=10)
        )
        h = by_hour(hourly_series(df))
        assert h[20]["footfall"] == 10
        assert h[9]["footfall"] == 10

    def test_shops_are_added_before_averaging(self):
        df = frame([
            ("2026-09-14", 9, 10, 5, 500.0),  # shop A
            ("2026-09-14", 9, 30, 5, 500.0),  # shop B, same hour
            ("2026-09-15", 9, 20, 5, 500.0),
        ])
        assert by_hour(hourly_series(df))[9]["footfall"] == 30  # (40 + 20) / 2

    def test_closed_hours_are_zero(self):
        h = by_hour(hourly_series(frame(day("2026-09-14", [9]))))
        assert h[3]["footfall"] == 0 and h[3]["conversion"] == 0


class TestHeatmap:
    def test_weekday_averaged_over_its_own_occurrences(self):
        # Two Mondays and one Sunday: Monday must not look twice as busy.
        df = frame(
            day("2026-09-14", [9], 10)  # Mon
            + day("2026-09-21", [9], 10)  # Mon
            + day("2026-09-20", [9], 10)  # Sun
        )
        cells = {(c["dow"], c["hour"]): c["footfall"] for c in heatmap_series(df)}
        assert cells[(0, 9)] == cells[(6, 9)] == 10


class TestCompleteDays:
    week = sum((day(f"2026-09-{d:02d}", range(8, 22)) for d in range(14, 21)), [])

    def test_drops_a_final_day_that_stops_early(self):
        df = frame(self.week + day("2026-09-21", range(8, 15)))
        assert is_partial(df)
        assert "2026-09-21" not in set(complete_days(df)["date"])

    def test_keeps_a_final_day_that_ran_to_closing(self):
        df = frame(self.week + day("2026-09-21", range(8, 22)))
        assert not is_partial(df)

    def test_single_day_cannot_judge_itself_without_help(self):
        df = frame(day("2026-09-21", range(8, 15)))
        assert not is_partial(df)
        assert complete_days(df, partial_date="2026-09-21").empty

    def test_weekday_means_ignore_the_unfinished_day(self):
        df = frame(self.week + day("2026-09-21", range(8, 9)))  # Monday, one hour in
        means = daily_totals_by_weekday(df)
        assert means[0] == 14 * 10  # the full Monday, not averaged with 10


def texts(insights):
    return " ".join(i["text"] for i in insights)


def weeks(start_day, n_days, hours, footfall=10, transactions=5, sales=500.0):
    """n_days consecutive days from 2026-08-31 + start_day (a Monday)."""
    out = []
    for d in range(start_day, start_day + n_days):
        stamp = (date(2026, 8, 31) + timedelta(days=d)).isoformat()
        out += day(stamp, hours, footfall, transactions, sales)
    return out


class TestVersusBefore:
    def test_names_fewer_visitors_as_the_cause(self):
        before = frame(weeks(0, 7, range(8, 20), footfall=20, transactions=10))
        now = frame(weeks(7, 7, range(8, 20), footfall=15, transactions=7.5, sales=375.0))
        ins = generate_insights(now, previous=before, previous_label="the week before")
        first = ins[0]
        assert first["kind"] == "warning"
        assert first["text"].startswith("Takings are down 25% on the week before")
        assert "fewer people came in" in first["text"]
        assert "The rest barely moved" in first["text"] and "at the door" in first["text"]

    def test_names_a_smaller_share_buying_as_the_cause(self):
        before = frame(weeks(0, 7, range(8, 20), footfall=20, transactions=10))
        now = frame(weeks(7, 7, range(8, 20), footfall=20, transactions=7, sales=350.0))
        first = generate_insights(now, previous=before, previous_label="the week before")[0]
        assert "smaller share of visitors bought: 35% against 50%" in first["text"]
        assert "empty shelves" in first["text"]

    def test_a_good_period_is_a_win_without_advice(self):
        before = frame(weeks(0, 7, range(8, 20), footfall=20, transactions=10))
        now = frame(weeks(7, 7, range(8, 20), footfall=20, transactions=10, sales=650.0))
        first = generate_insights(now, previous=before, previous_label="the week before")[0]
        assert first["kind"] == "win" and "average bill" in first["text"]
        assert "check" not in first["text"].lower()

    def test_one_quiet_day_is_within_normal_ups_and_downs(self):
        # 30 bills a day: a 10% dip is well inside what chance alone gives.
        before = frame(day("2026-09-14", range(8, 14), footfall=10, transactions=5))
        now = frame(day("2026-09-21", range(8, 14), footfall=9, transactions=5, sales=450.0))
        first = generate_insights(now, previous=before, previous_label="last Monday")[0]
        assert first["kind"] == "observation"
        assert "about the same as last Monday" in first["text"]
        assert "ups and downs" in first["text"]

    def test_no_comparison_without_an_earlier_period(self):
        now = frame(weeks(0, 7, range(8, 20)))
        assert "Takings" not in texts(generate_insights(now))


class TestRush:
    def shop(self, rush_bills, calm_bills, n_days=14):
        rows = []
        for d in range(n_days):
            stamp = (date(2026, 8, 31) + timedelta(days=d)).isoformat()
            rows += day(stamp, [8, 9, 18, 19], footfall=40, transactions=rush_bills)
            rows += day(stamp, [11, 12, 13, 14, 15, 16], footfall=10, transactions=calm_bills)
        return frame(rows)

    def test_names_the_rush_hours(self):
        out = texts(generate_insights(self.shop(rush_bills=20, calm_bills=5)))
        assert "Your rushes are 8:00–10:00 and 18:00–20:00" in out
        assert "Restock and be at the counter before 8:00 and 18:00" in out

    def test_a_rush_that_loses_buyers_is_priced(self):
        ins = generate_insights(self.shop(rush_bills=12, calm_bills=6))  # 30% vs 60%
        card = next(i for i in ins if "rush" in i["text"])
        assert card["kind"] == "warning"
        assert "only 30% of them buy, against 60% in calmer hours" in card["text"]
        assert "a day" in card["text"] and "a week" in card["text"]

    def test_a_small_gap_chance_explains_is_not_priced(self):
        # Three days, few calm visitors: a few points' gap could be luck.
        ins = generate_insights(self.shop(rush_bills=19, calm_bills=5, n_days=3))
        assert "calmer hours" not in texts(ins)

    def test_one_day_is_too_short_to_call_a_rush(self):
        one = self.shop(rush_bills=20, calm_bills=5, n_days=1)
        assert "rush" not in texts(generate_insights(one))

    def test_one_day_borrows_the_usual_rush_from_recent_weeks(self):
        one = frame(day("2026-09-21", range(8, 12)))
        out = texts(generate_insights(one, history=self.shop(rush_bills=20, calm_bills=5)))
        assert "On a usual day, your rushes are 8:00–10:00 and 18:00–20:00" in out


class TestQuietWeekday:
    def shop(self, sunday_footfall, sunday_bills, n_weeks=2):
        rows = []
        for d in range(7 * n_weeks):
            stamp = (date(2026, 8, 31) + timedelta(days=d)).isoformat()
            sunday = d % 7 == 6
            bills = sunday_bills if sunday else 10
            rows += day(stamp, range(8, 20),
                        footfall=sunday_footfall if sunday else 20,
                        transactions=bills, sales=bills * 50.0)
        return frame(rows)

    def test_few_visitors_is_the_door_not_the_counter(self):
        card = next(i for i in generate_insights(self.shop(8, 4)) if "Sundays" in i["text"])
        assert card["kind"] == "observation"
        assert "fewer people come in" in card["text"] and "shorter hours" in card["text"]

    def test_visitors_who_do_not_buy_is_the_counter(self):
        card = next(i for i in generate_insights(self.shop(20, 4)) if "Sundays" in i["text"])
        assert card["kind"] == "warning"
        assert "only 20% buy against 50%" in card["text"]

    def test_needs_every_weekday_twice(self):
        assert "Sundays" not in texts(generate_insights(self.shop(8, 4, n_weeks=1)))


class TestBillByTime:
    def test_bigger_evening_bills_are_pointed_out(self):
        rows = weeks(0, 7, [8, 9, 10], footfall=10, transactions=5, sales=250.0)    # ₹50 bills
        rows += weeks(0, 7, [18, 19, 20], footfall=10, transactions=5, sales=600.0)  # ₹120 bills
        out = texts(generate_insights(frame(rows)))
        assert "Evening bills average ₹120" in out and "morning bills" in out

    def test_similar_bills_say_nothing(self):
        rows = weeks(0, 7, [8, 9, 10, 18, 19, 20])
        assert "bills average" not in texts(generate_insights(frame(rows)))


class TestInsightLimits:
    def test_at_most_four_cards(self):
        before = frame(weeks(0, 14, range(8, 20), footfall=30, transactions=15))
        rows = []
        for d in range(14, 28):
            stamp = (date(2026, 8, 31) + timedelta(days=d)).isoformat()
            sunday = d % 7 == 6
            rows += day(stamp, [8, 9], footfall=60 if not sunday else 10, transactions=12, sales=600.0)
            rows += day(stamp, [12, 13, 14, 15, 16], footfall=10, transactions=6, sales=1200.0)
            rows += day(stamp, [18, 19], footfall=60 if not sunday else 10, transactions=12, sales=2400.0)
        ins = generate_insights(frame(rows), previous=before, previous_label="the fortnight before")
        assert 1 <= len(ins) <= 4

    def test_nothing_from_nothing(self):
        assert generate_insights(frame(day("2026-09-21", [9], footfall=0, transactions=0, sales=0))) == []

    def test_whatsapp_uses_the_given_title(self):
        msg = whatsapp_summary(frame(day("2026-09-21", [9, 10])), "Summary for Mon 21 Sep so far")
        assert msg.splitlines()[0] == "📊 *Summary for Mon 21 Sep so far*"
        assert "Daily" not in msg

    def test_whatsapp_repeats_the_dashboard_cards(self):
        cards = [{"kind": "win", "text": "Takings are up."}]
        msg = whatsapp_summary(frame(day("2026-09-21", [9, 10])), "Summary", None, cards)
        assert msg.endswith("✅ Takings are up.")
