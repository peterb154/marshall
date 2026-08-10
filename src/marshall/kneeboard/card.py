"""What a kneeboard page is allowed to know.

    "1) Ww2 is a feature, not the purpose. 2) There are aspects of the kneeboard
     eventually that will be pilot specific... 3) we're going to need a dynamic
     kb system eventually. So that after planning a flight there is a dashboard
     that can be loaded with pertinent details."

THE PROBLEM, MEASURED. Seven of the nine pages take a `profile` argument and
then read the theatre out of module constants anyway -- `R.STATIONS`,
`R.ARRIVAL_FIELD`, `R.WIND_FROM_DEG`. The parameter is decoration. `navlog.py`
reaches ten of them and takes no profile at all. So a page cannot be pointed at
another field: it has to be rewritten, which is why twenty-four of the
twenty-nine surviving Caucasus references in this system are kneeboard prose.

A PAGE IS A FUNCTION OF A CARD. Everything it may read arrives here, and nothing
it may read is a module constant. That is the whole idea and the rest is
consequence:

    a second theatre       needs no page edited, only a different Card
    a pilot-specific page  is a Card with a pilot on it
    a planned-flight       is a Card with the assigned plan on it
      dashboard

The last two are the deferred half and they are DECLARED here rather than left
to be discovered later, because the shape of the thing decides whether they are
cheap or another rewrite. `pilot` and `plan` are empty today and every page that
wants them will find them in the same place.

WW2 IS A FEATURE, NOT THE FRAME. Some pages genuinely ARE the 1944 sortie -- the
beacon letdown plate, the strike route map, the squadron brief -- and those stay
pointed at the Caucasus on purpose and say so. What must not happen is a page
that means to be general and is accidentally specific, which is every other page
today.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Card:
    """One sortie's worth of facts, as a page may read them.

    Frozen, because a page renders a card and must not change it. Two pages
    disagreeing about the wind because one of them normalised it is the same
    class of bug as two controllers disagreeing about the runway.
    """

    # WHERE. The whole theatre, so a page can name the other field without
    # importing a map.
    theatre: str
    fields: tuple = ()
    departure: str = ""
    arrival: str = ""
    stations: tuple = ()

    # WHAT HE IS FLYING. The approach at the arrival end, which carries its own
    # minima, courses and station list.
    profile: object = None

    # THE WEATHER, as one number each rather than a module constant, so a page
    # that prints the wind and a controller who reads it come from one place.
    wind_from_deg: float = 0.0
    wind_mph: float = 0.0

    # --- the deferred half, declared so it has somewhere to go ---------------
    #
    # A FILED PLAN, once there is a dashboard to render it on. `flight_state`
    # already joins label, route, cruise level and whether it was read back --
    # see `assembly.flight_strip`, which reads exactly this.
    plan: dict = field(default_factory=dict)
    # AND WHOSE CARD IT IS. Empty means the generic set, which is every card
    # today. A per-pilot page is this being filled in, not a new mechanism.
    pilot: str = ""

    @property
    def arrival_field(self):
        return self.field_named(self.arrival)

    @property
    def departure_field(self):
        return self.field_named(self.departure)

    # A `stations_at(field)` helper was here and is deliberately gone. It read
    # well, nothing called it, and `tools/unwired.py` said so on the same
    # afternoon it was written -- which is the whole point of that check and the
    # second time it has caught this author in one session. A convenience nobody
    # uses is the beginning of every unwired system in this repo.
    def field_named(self, name: str):
        return next((f for f in self.fields
                     if f.name.lower() == (name or "").lower()), None)


def for_caucasus() -> Card:
    """The 362nd's sortie. Kobuleti to Batumi, radar recovery."""
    from marshall.core import route as R
    return Card(theatre="Caucasus", fields=tuple(R.FIELDS),
                departure=R.DEPARTURE_FIELD, arrival=R.ARRIVAL_FIELD,
                stations=tuple(R.STATIONS), profile=R.BATUMI_ASR,
                wind_from_deg=R.WIND_FROM_DEG, wind_mph=R.WIND_MPH)


def for_nevada() -> Card:
    """Nellis to Tonopah, ILS at both ends."""
    from marshall.core import nevada as N
    return Card(theatre="Nevada", fields=tuple(N.NEVADA_FIELDS),
                departure="Nellis", arrival="Tonopah",
                stations=tuple(N.NEVADA_STATIONS), profile=N.TONOPAH_ILS,
                wind_from_deg=210.0, wind_mph=9.2)


THEATRES = {"caucasus": for_caucasus, "nevada": for_nevada}


def current() -> Card:
    """The card this kneeboard is serving.

    ONE ENVIRONMENT VARIABLE, and it is deliberately not cleverer than that.
    Deriving the theatre from whatever mission happens to be loaded sounds
    better and is worse: the kneeboard container generates its pages at start,
    so it would be reading the sim at exactly the moment nobody has told the sim
    anything yet, and a page that guesses wrong is a chart that disagrees with
    the aeroplane -- which is the failure this whole project is about.
    """
    import os
    want = os.environ.get("MARSHALL_THEATRE", "caucasus").strip().lower()
    return THEATRES.get(want, for_caucasus)()
