"""Tag events with audience labels (kids, singles, family, etc.) and infer age bounds.

These are intentionally simple keyword heuristics — they're cheap, transparent,
and good enough for filtering. Swap in a classifier later if precision matters."""
from __future__ import annotations

import re
from typing import Optional

# Audience -> list of patterns (lowercased substrings or regexes).
AUDIENCE_PATTERNS: dict[str, list[str]] = {
    "kids": [
        r"\bkids?\b", r"\bchildren\b", r"\btoddler", r"\bstoryt(?:ime|elling)\b",
        r"\bstory hour\b", r"\bfamily\b", r"\bplaygroup\b", r"\bpreschool\b",
    ],
    "family": [
        r"\bfamily\b", r"\ball ages\b", r"\bfamily[- ]friendly\b",
    ],
    "teens": [
        r"\bteen", r"\bya\b", r"\byoung adult\b", r"\bhigh school\b",
    ],
    "singles": [
        r"\bsingles?\b", r"\bspeed dating\b", r"\bdating\b", r"\bmingle\b",
        r"\bmixer\b", r"\bsingle and ", r"\bmeet[- ]?cute\b",
    ],
    "girls": [
        r"\bgirls?[' ]? ?night\b", r"\bladies night\b", r"\bgalentine",
        r"\bwomen only\b", r"\bfor women\b",
    ],
    "boys": [
        r"\bguys?[' ]? ?night\b", r"\bmen only\b", r"\bfor men\b",
        r"\bbros?[' ]? night\b",
    ],
    "parents": [
        r"\bparents?\b", r"\bmoms?\b", r"\bdads?\b", r"\bmommy\b", r"\bdaddy\b",
        r"\bnew parent", r"\bstroller\b",
    ],
    "seniors": [
        r"\bseniors?\b", r"\b55\+\b", r"\b60\+\b", r"\b65\+\b", r"\bolder adults?\b",
    ],
    "lgbtq": [
        r"\blgbt", r"\bqueer\b", r"\bpride\b", r"\bdrag\b", r"\bgay\b",
        r"\blesbian\b", r"\btrans\b", r"\bnonbinary\b",
    ],
    "21+": [r"\b21\+\b", r"\b21 and over\b", r"\b21 and up\b"],
    "18+": [r"\b18\+\b", r"\b18 and over\b", r"\b18 and up\b"],
    "adults": [r"\badults?\b", r"\badult only\b", r"\bgrown-?ups?\b"],
}

# Category -> patterns for broader bucketing.
CATEGORY_PATTERNS: dict[str, list[str]] = {
    "music": [r"\bconcert\b", r"\blive music\b", r"\bdj\b", r"\bband\b", r"\bopera\b"],
    "comedy": [r"\bcomedy\b", r"\bstand[- ]?up\b", r"\bimprov\b"],
    "theater": [r"\btheat(?:er|re)\b", r"\bbroadway\b", r"\bplay\b", r"\bmusical\b"],
    "food_drink": [r"\bfood\b", r"\btasting\b", r"\bbrunch\b", r"\bdinner\b", r"\bcocktail\b", r"\bwine\b", r"\bbeer\b"],
    "sports": [r"\bgame\b", r"\bsports?\b", r"\bbasketball\b", r"\bbaseball\b", r"\bsoccer\b", r"\byankees\b", r"\bmets\b", r"\bknicks\b", r"\bnets\b"],
    "fitness": [r"\byoga\b", r"\brun(?:ning)?\b", r"\bfitness\b", r"\bworkout\b", r"\bbootcamp\b"],
    "arts": [r"\bart\b", r"\bgallery\b", r"\bexhibit", r"\bmuseum\b", r"\bpainting\b"],
    "film": [r"\bfilm\b", r"\bmovie\b", r"\bscreening\b", r"\bcinema\b"],
    "tech": [r"\btech\b", r"\bhackathon\b", r"\bcoding\b", r"\bdeveloper\b", r"\bai\b"],
    "outdoors": [r"\bpark\b", r"\bhike\b", r"\bnature\b", r"\bbeach\b", r"\boutdoor\b"],
    "education": [r"\bworkshop\b", r"\bclass\b", r"\bseminar\b", r"\blecture\b", r"\btalk\b"],
    "nightlife": [
        r"\bnight\s*club\b",
        r"\bnightlife\b",
        r"\bafter[- ]?party\b",
        r"\brave\b",
        r"\bopen\s+bar\b",
        r"\bdance\s+floor\b",
        r"\bclub\s+night\b",
        r"\bbottle\s+service\b",
        r"\bvip\s+(?:table|booth|entry|access)\b",
        r"\bnight(?:cap|out)\b",
        r"\bpool\s+party\b",
        r"\brooftop\s+party\b",
    ],
    "festival": [r"\bfestival\b", r"\bfair\b", r"\bparade\b", r"\bblock party\b"],
}


def _find_matches(text: str, patterns: dict[str, list[str]]) -> list[str]:
    matches = []
    for label, pats in patterns.items():
        for p in pats:
            if re.search(p, text):
                matches.append(label)
                break
    return matches


def categorize(title: str, description: str = "") -> tuple[list[str], list[str]]:
    """Returns (categories, audiences)."""
    text = f"{title or ''}\n{description or ''}".lower()
    return _find_matches(text, CATEGORY_PATTERNS), _find_matches(text, AUDIENCE_PATTERNS)


def infer_age_bounds(title: str, description: str = "") -> tuple[Optional[int], Optional[int]]:
    text = f"{title or ''}\n{description or ''}".lower()
    age_min = age_max = None

    # "21+", "18+", "65+"
    m = re.search(r"\b(\d{1,2})\+\b", text)
    if m:
        age_min = int(m.group(1))

    # "ages 5-12", "ages 3 to 7"
    m = re.search(r"\bages?\s+(\d{1,2})\s*(?:-|to|–)\s*(\d{1,2})\b", text)
    if m:
        age_min = int(m.group(1))
        age_max = int(m.group(2))

    # "all ages"
    if re.search(r"\ball ages\b", text):
        age_min = 0

    return age_min, age_max


def looks_free(title: str, description: str = "") -> Optional[bool]:
    """Best-effort price hint when the source doesn't give one."""
    text = f"{title or ''}\n{description or ''}".lower()
    if re.search(r"\bfree\b", text) and not re.search(r"\bnot free\b", text):
        return True
    if re.search(r"\$\d", text):
        return False
    return None
