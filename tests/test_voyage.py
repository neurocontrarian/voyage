from dataclasses import replace
from datetime import date, datetime

from voyage.config import load_airlines, load_trip
from voyage.gflights import Leg, Slice
from voyage.pricing import Itinerary, bag_cost, price_itinerary
from voyage.rules import dates_ok, keep_worthwhile, slice_ok

TRIP = load_trip()
AIRLINES = load_airlines()


def leg(code, origin, dest, dep, arr, minutes):
    return Leg(code[:2], code[2:], origin, dest, datetime.fromisoformat(dep),
               datetime.fromisoformat(arr), minutes)


OUT = Slice((leg("TP254", "YUL", "LIS", "2027-03-25T22:45", "2027-03-26T09:40", 415),))
RET = Slice((leg("TP253", "LIS", "YUL", "2027-04-02T18:25", "2027-04-02T21:10", 465),))
OUT_AC = Slice((leg("AC812", "YUL", "LIS", "2027-03-25T22:40", "2027-03-26T09:20", 400),))
RET_AC = Slice((leg("AC813", "LIS", "YUL", "2027-04-02T11:25", "2027-04-02T13:50", 445),))


def test_date_pairs_fixed_departure_and_one_night_less():
    assert TRIP.date_pairs() == [(date(2027, 3, 25), date(2027, 4, 2)),
                                 (date(2027, 3, 25), date(2027, 4, 1))]


def test_bag_cost_first_bags_then_second_bags():
    no_bag = {"bagages_inclus": 0, "frais_bagage": [100, 150]}
    one_bag = {"bagages_inclus": 1, "frais_bagage": [100, 150]}
    assert bag_cost(no_bag, 3, 2) == 200  # deux passagers paient leur 1re valise
    assert bag_cost(no_bag, 1, 2) == 250  # un seul passager : 1re + 2e valise
    assert bag_cost(one_bag, 3, 2) == 0
    assert bag_cost(one_bag, 1, 2) == 150


def test_tap_discount_compared_with_upgrade():
    itin = Itinerary("aller-retour", OUT, RET, 2469)
    price_itinerary(itin, AIRLINES, 3, 2)
    discount_bags = 2 * 2 * 115
    basic_upgrade = 2 * 3 * 60
    assert itin.total == 2469 + min(discount_bags, basic_upgrade)


def test_air_canada_standard_when_google_confirms_not_basic():
    itin = Itinerary("aller-retour", OUT_AC, RET_AC, 4548, base_is_basic=False)
    price_itinerary(itin, AIRLINES, 3, 2)
    assert itin.total == 4548  # Standard : 1 valise par passager, rien à ajouter


def test_air_canada_unknown_fare_is_assumed_basic_with_bags_to_pay():
    # Sur le transatlantique, Google ignore le filtre : un prix inchangé ne prouve rien.
    itin = Itinerary("aller-retour", OUT_AC, RET_AC, 2961)
    price_itinerary(itin, AIRLINES, 3, 2)
    assert itin.total == 2961 + 2 * 2 * 104 and itin.extras == 416 and itin.fares == ("Économie Basic",) * 2


def test_air_canada_exact_nonbasic_price_is_used():
    itin = Itinerary("aller-retour", OUT_AC, RET_AC, 4000, base_is_basic=True, nonbasic_price=4100)
    price_itinerary(itin, AIRLINES, 3, 2)
    assert itin.total == 4100  # moins cher que Basic + 4 valises (4 x 104 $)


def test_tap_quality_preference_affects_ranking_not_price():
    tap = Itinerary("aller-retour", OUT, RET, 2469)
    mixed = Itinerary("aller-retour", OUT_AC, RET, 2469, base_is_basic=False)
    for itin in (tap, mixed):
        price_itinerary(itin, AIRLINES, 3, 2)
    assert tap.score == tap.total * 1.10
    assert mixed.score == mixed.total * 1.05  # TAP seulement au retour


def test_porter_uses_transat_rules():
    assert AIRLINES["PD"]["tarifs"] == AIRLINES["TS"]["tarifs"]


def test_connection_rules():
    via_lis = Slice((
        leg("TP254", "YUL", "LIS", "2027-03-25T22:45", "2027-03-26T09:40", 415),
        leg("TP1926", "LIS", "OPO", "2027-03-26T12:30", "2027-03-26T13:30", 60),
    ))
    assert slice_ok(via_lis, TRIP, "aller")
    long_wait = replace(via_lis, legs=(via_lis.legs[0], replace(
        via_lis.legs[1], dep=datetime(2027, 3, 26, 18, 0), arr=datetime(2027, 3, 26, 19, 0))))
    assert not slice_ok(long_wait, TRIP, "aller")
    detour = Slice((
        leg("AF345", "YUL", "CDG", "2027-03-25T20:05", "2027-03-26T08:35", 450),
        leg("AF1528", "CDG", "OPO", "2027-03-26T09:35", "2027-03-26T10:35", 120),
    ))
    assert not slice_ok(detour, TRIP, "aller")


def test_connection_kept_only_if_15_percent_cheaper():
    direct = Itinerary("aller-retour", OUT, RET, 0, total=3000)
    via = Slice((OUT.legs[0], leg("TP1926", "LIS", "OPO", "2027-03-26T12:30",
                                  "2027-03-26T13:30", 60)))
    cheap = Itinerary("aller-retour", via, RET, 0, total=2500)
    pricey = Itinerary("aller-retour", via, RET, 0, total=2700)
    kept = keep_worthwhile([direct, cheap, pricey], TRIP)
    assert cheap in kept and pricey not in kept and direct in kept


def test_nights_and_departure_date():
    assert dates_ok(Itinerary("aller-retour", OUT, RET, 0), TRIP)  # 7 nuits
    one_less = Slice((leg("TP253", "LIS", "YUL", "2027-04-01T18:25", "2027-04-01T21:10", 465),))
    two_less = Slice((leg("TP253", "LIS", "YUL", "2027-03-31T18:25", "2027-03-31T21:10", 465),))
    assert dates_ok(Itinerary("aller-retour", OUT, one_less, 0), TRIP)  # 6 nuits
    assert not dates_ok(Itinerary("aller-retour", OUT, two_less, 0), TRIP)
    next_day = Slice((leg("TP254", "YUL", "LIS", "2027-03-26T22:45", "2027-03-27T09:40", 415),))
    assert not dates_ok(Itinerary("aller-retour", next_day, RET, 0), TRIP)  # départ le 26 : refusé


def test_one_night_less_kept_only_if_15_percent_cheaper():
    one_less = Slice((leg("TP253", "LIS", "YUL", "2027-04-01T18:25", "2027-04-01T21:10", 465),))
    full = Itinerary("aller-retour", OUT, RET, 0, total=3000)
    short_cheap = Itinerary("aller-retour", OUT, one_less, 0, total=2550)
    short_close = Itinerary("aller-retour", OUT, one_less, 0, total=2600)
    kept = keep_worthwhile([full, short_cheap, short_close], TRIP)
    assert full in kept and short_cheap in kept and short_close not in kept


def test_trends_hour_and_weekday_effects():
    from voyage import tendances
    rows = []
    for d in range(1, 22):  # 3 semaines pleines, prix qui dérive de +1 $ par jour
        for hour in range(8, 20):
            base = 1000 + d + (-20 if hour == 3 + 8 else 0) + (-30 if d % 7 == 3 else 0)
            rows.append((datetime(2026, 11, d, hour, 17), float(base)))
    hours, n_days = tendances.by_hour(rows)
    assert n_days == 21 and min(hours, key=hours.get) == 11
    weekdays, n_weeks = tendances.by_weekday(rows)
    assert n_weeks == 3 and min(weekdays, key=weekdays.get) == datetime(2026, 11, 3).weekday()
    assert "vers 11 h" in tendances.analyse(rows)[0]
    assert "pas encore calculables" in tendances.analyse(rows[:5])[0]


def test_daily_reminder_message():
    from voyage import rappel
    now = datetime(2026, 11, 3, 17, 0)
    record = {"total": 2900, "cle": "a", "date": "2026-11-01 10:17", "fiche": "FICHE-RECORD"}
    today = {"date": "2026-11-03 09:17", "total": 3000, "cle": "b", "fiche": "FICHE-JOUR"}
    both = rappel.message({"record": record, "jour": today}, now, "TENDANCES")
    assert "FICHE-RECORD" in both and "FICHE-JOUR" in both and "TENDANCES" in both
    same = rappel.message({"record": record, "jour": {**today, "cle": "a", "total": 2900}}, now, "T")
    assert same.count("FICHE-RECORD") == 1 and "FICHE-JOUR" not in same
    cheaper_record = rappel.message({"record": {**record, "total": 2800}, "jour": {**today, "cle": "a"}}, now, "T")
    assert "FICHE-JOUR" in cheaper_record  # même vol, mais prix du jour différent du record
    stale = rappel.message({"record": record, "jour": {**today, "date": "2026-11-02 09:17"}}, now, "T")
    assert "Aucune recherche réussie aujourd'hui" in stale
