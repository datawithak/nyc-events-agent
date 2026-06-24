"""Source registry. Import each module so its Source subclass registers itself.

Note: NYC.gov, NYC Parks, NYPL, and Eventbrite all sit behind anti-bot WAFs
(Imperva/Incapsula) that return challenge pages instead of feed data when
scraped from a server. Adapters for them are kept in this directory as
templates but are NOT auto-registered. Wire them in once you have a workable
access path (residential proxy, official partner feed, or LibCal calendar ID
for the libraries) by uncommenting their import below.
"""
from sources.base import Source, registry  # noqa: F401
from sources import (  # noqa: F401
    ticketmaster,
    seatgeek,
    nyc_open_data,
    resident_advisor,
    city_parks_foundation,
    yelp_events,
    secret_nyc,
)

# Disabled by default — endpoints are bot-blocked or require a calendar ID.
# Uncomment once you've replaced the placeholder URL in the module with
# a working one.
# from sources import nyc_parks, nypl, bpl, qpl, eventbrite_rss  # noqa: F401


def all_sources() -> list[Source]:
    return [cls() for cls in registry]
