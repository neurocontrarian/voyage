from dataclasses import replace
from datetime import date, datetime

from voyage.config import load_airlines, load_trip
from voyage.gflights import Leg, Slice
from voyage.pricing import Itinerary, bag_cost, price_itinerary
from voyage.rules import fits, slice_ok

TRIP = load_trip()
FIXED, FLEX, FIXED_STOP, FLEX_STOP = TRIP.scenarios
AIRLINES = load_airlines()


def leg(code, origin, dest, dep, arr, minutes):
    return Leg(code[:2], code[2:], origin, dest, datetime.fromisoformat(dep),
               datetime.fromisoformat(arr), minutes)


OUT = Slice((leg("TP254", "YUL", "LIS", "2027-03-25T22:45", "2027-03-26T09:40", 415),))
RET = Slice((leg("TP253", "LIS", "YUL", "2027-04-02T18:25", "2027-04-02T21:10", 465),))
OUT_AC = Slice((leg("AC812", "YUL", "LIS", "2027-03-25T22:40", "2027-03-26T09:20", 400),))
RET_AC = Slice((leg("AC813", "LIS", "YUL", "2027-04-02T11:25", "2027-04-02T13:50", 445),))


def test_date_pairs_of_each_scenario():
    assert FIXED.date_pairs() == FIXED_STOP.date_pairs() == [(date(2027, 3, 25), date(2027, 4, 2))]
    assert FLEX.date_pairs() == FLEX_STOP.date_pairs() == [
        (date(2027, 3, 25), date(2027, 4, 1)), (date(2027, 3, 25), date(2027, 4, 2)),
        (date(2027, 3, 25), date(2027, 4, 3)), (date(2027, 3, 26), date(2027, 4, 2)),
        (date(2027, 3, 26), date(2027, 4, 3)), (date(2027, 3, 27), date(2027, 4, 3))]
    assert [s.escales_max for s in TRIP.scenarios] == [0, 0, 1, 1]


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


def test_trip_duration_and_excluded_airline():
    via_cdg = Slice((
        leg("AC870", "YUL", "CDG", "2027-03-25T19:00", "2027-03-26T07:50", 410),
        leg("AF1528", "CDG", "LIS", "2027-03-26T09:20", "2027-03-26T11:00", 160),
    ))
    assert via_cdg.total_minutes == 660 and not slice_ok(via_cdg, TRIP)  # 11 h : trop long
    quick = replace(via_cdg, legs=(via_cdg.legs[0], replace(
        via_cdg.legs[1], dep=datetime(2027, 3, 26, 8, 50), arr=datetime(2027, 3, 26, 10, 30),
        minutes=100)))
    assert quick.total_minutes == 570 and slice_ok(quick, TRIP)  # 9 h 30
    assert slice_ok(OUT_AC, TRIP) and not slice_ok(OUT, TRIP)  # TAP exclue
    tap_leg = replace(quick, legs=(quick.legs[0], replace(quick.legs[1], airline="TP")))
    assert not slice_ok(tap_leg, TRIP)  # exclue même pour un seul vol du trajet


def back(day):
    return Slice((leg("TP253", "LIS", "YUL", f"2027-{day}T18:25", f"2027-{day}T21:10", 465),))


def test_scenario_dates_and_nights():
    fixed = Itinerary("aller-retour", OUT, RET, 0)  # 25 mars -> 2 avril, 7 nuits
    assert all(fits(fixed, sc) for sc in TRIP.scenarios)
    one_less = Itinerary("aller-retour", OUT, back("04-01"), 0)  # 6 nuits
    assert fits(one_less, FLEX) and not fits(one_less, FIXED)
    assert not fits(Itinerary("aller-retour", OUT, back("03-31"), 0), FLEX)  # 5 nuits
    late = Slice((leg("TP254", "YUL", "LIS", "2027-03-27T22:45", "2027-03-28T09:40", 415),))
    assert fits(Itinerary("aller-retour", late, back("04-03"), 0), FLEX)  # 27 mars -> 3 avril
    assert not fits(Itinerary("aller-retour", late, back("04-03"), 0), FIXED)
    assert not fits(Itinerary("aller-retour", late, back("04-02"), 0), FLEX)  # 5 nuits
    assert not fits(Itinerary("aller-retour", OUT, back("04-04"), 0), FLEX)  # retour trop tard


def test_stops_allowed_only_in_scenarios_3_and_4():
    via = Slice((OUT.legs[0], leg("TP1926", "LIS", "OPO", "2027-03-26T12:30",
                                  "2027-03-26T13:30", 60)))
    itin = Itinerary("aller-retour", via, RET, 0)
    assert [fits(itin, sc) for sc in TRIP.scenarios] == [False, False, True, True]


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
    today = {"date": "2026-11-03 09:17", "total": 3000, "cle": "b", "fiche": "F", "resume": "LIGNE-JOUR"}

    def msg(*scenarios):
        return rappel.message({"scenarios": {str(n): {"nom": f"NOM{n}", **sc}
                                             for n, sc in enumerate(scenarios, 1)}}, now, "TENDANCES")

    text = msg({"record": record, "jour": today})
    assert "FICHE-RECORD" in text and "LIGNE-JOUR" in text and "TENDANCES" in text and "NOM1" in text
    same = msg({"record": record, "jour": {**today, "cle": "a", "total": 2900}})
    assert "aussi la meilleure offre du jour" in same and "LIGNE-JOUR" not in same
    cheaper_record = msg({"record": {**record, "total": 2800}, "jour": {**today, "cle": "a"}})
    assert "LIGNE-JOUR" in cheaper_record  # même vol, mais prix du jour différent du record
    stale = msg({"record": record, "jour": {**today, "date": "2026-11-02 09:17"}})
    assert "aucune recherche réussie" in stale
    shared = msg({"record": record}, {"record": record})  # même record : une seule fiche
    assert shared.count("FICHE-RECORD") == 1 and "la même qu'au scénario 1" in shared
    assert "Aucun vol trouvé jusqu'ici" in msg({"record": record}, {})


def test_report_and_alert_show_shared_best_once():
    from voyage.__main__ import alert_message, report
    from voyage.search import Outcome, ScenarioResult
    direct = Itinerary("aller-retour", OUT_AC, RET_AC, 2961)
    price_itinerary(direct, AIRLINES, 3, 2)
    results = [ScenarioResult(sc, [direct] if sc.escales_max == 0 or sc is FIXED_STOP else [])
               for sc in TRIP.scenarios]
    text = report(TRIP, Outcome(results), AIRLINES, datetime(2026, 11, 3, 9, 17))
    assert text.count("tout compris") == 1 and "le même qu'au scénario 1" in text
    assert "Aucun vol trouvé" in text and all(sc.titre in text for sc in TRIP.scenarios)
    alert = alert_message([(FIXED, direct, None), (FIXED_STOP, direct, None)], TRIP, AIRLINES)
    assert alert.count("tout compris") == 1 and "Le même voyage qu'au scénario 1" in alert


def test_record_reset_when_scenario_rules_change():
    from voyage.__main__ import rules_id
    assert rules_id(TRIP, FIXED) == rules_id(load_trip(), FIXED)
    assert rules_id(TRIP, FIXED) != rules_id(TRIP, FIXED_STOP)
    assert rules_id(TRIP, FIXED) != rules_id(replace(TRIP, compagnies_exclues=[]), FIXED)
    assert rules_id(TRIP, FIXED) != rules_id(replace(TRIP, duree_trajet_max_minutes=660), FIXED)
