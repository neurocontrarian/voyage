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


OUT = Slice((leg("TP254", "YUL", "LIS", "2027-03-26T22:45", "2027-03-27T09:40", 415),))
RET = Slice((leg("TP253", "LIS", "YUL", "2027-04-02T18:25", "2027-04-02T21:10", 465),))
OUT_AC = Slice((leg("AC812", "YUL", "LIS", "2027-03-26T22:40", "2027-03-27T09:20", 400),))
RET_AC = Slice((leg("AC813", "LIS", "YUL", "2027-04-02T11:25", "2027-04-02T13:50", 445),))


def test_date_pairs_respect_nights_and_window():
    pairs = TRIP.date_pairs()
    assert pairs[0] == (date(2027, 3, 25), date(2027, 4, 1))
    assert pairs[-1] == (date(2027, 3, 27), date(2027, 4, 3))
    assert all((r - d).days - 1 >= TRIP.nuits_min for d, r in pairs)


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


def test_air_canada_exact_nonbasic_price_is_used():
    itin = Itinerary("aller-retour", OUT_AC, RET_AC, 4000, base_is_basic=True, nonbasic_price=4100)
    price_itinerary(itin, AIRLINES, 3, 2)
    assert itin.total == 4100  # moins cher que Basic + 4 valises (4 x 104 $)


def test_porter_uses_transat_rules():
    assert AIRLINES["PD"]["tarifs"] == AIRLINES["TS"]["tarifs"]


def test_connection_rules():
    via_lis = Slice((
        leg("TP254", "YUL", "LIS", "2027-03-26T22:45", "2027-03-27T09:40", 415),
        leg("TP1926", "LIS", "OPO", "2027-03-27T12:30", "2027-03-27T13:30", 60),
    ))
    assert slice_ok(via_lis, TRIP, "aller")
    long_wait = replace(via_lis, legs=(via_lis.legs[0], replace(
        via_lis.legs[1], dep=datetime(2027, 3, 27, 18, 0), arr=datetime(2027, 3, 27, 19, 0))))
    assert not slice_ok(long_wait, TRIP, "aller")
    detour = Slice((
        leg("AF345", "YUL", "CDG", "2027-03-26T20:05", "2027-03-27T08:35", 450),
        leg("AF1528", "CDG", "OPO", "2027-03-27T09:35", "2027-03-27T10:35", 120),
    ))
    assert not slice_ok(detour, TRIP, "aller")


def test_connection_kept_only_if_15_percent_cheaper():
    direct = Itinerary("aller-retour", OUT, RET, 0, total=3000)
    via = Slice((OUT.legs[0], leg("TP1926", "LIS", "OPO", "2027-03-27T12:30",
                                  "2027-03-27T13:30", 60)))
    cheap = Itinerary("aller-retour", via, RET, 0, total=2500)
    pricey = Itinerary("aller-retour", via, RET, 0, total=2700)
    kept = keep_worthwhile([direct, cheap, pricey], TRIP)
    assert cheap in kept and pricey not in kept and direct in kept


def test_minimum_nights():
    assert dates_ok(Itinerary("aller-retour", OUT, RET, 0), TRIP)
    early = Slice((leg("TP253", "LIS", "YUL", "2027-04-01T18:25", "2027-04-01T21:10", 465),))
    assert not dates_ok(Itinerary("aller-retour", OUT, early, 0), TRIP)
