"""Criminal work flavour: which title and flash of text show based on
current infamy. Purely cosmetic content -- the payout math itself
lives in formulas.py (infamy_multiplier, roll_criminal_work), the same
split as jobs.py (yields) vs formulas.py (yield math).
"""

CRIME_TIERS = [
    (0, "Petty Thief", [
        "You slip a coin purse from an unwatched cart.",
        "You lift a loaf of bread and vanish into the crowd.",
        "You pick a drunk's pocket outside the tavern.",
        "You nick an apple from the fruit stall and run.",
    ]),
    (20, "Sticky-Fingered Rogue", [
        "You break into a merchant's storeroom after dark.",
        "You shake down a peddler for 'protection money'.",
        "You fence a bag of stolen goods in a back alley.",
        "You slip through a window left carelessly open.",
    ]),
    (50, "Known Troublemaker", [
        "You hold up a lone traveller on the forest road.",
        "You rob the till while the shopkeep's back is turned.",
        "You shake down the dockside warehouses.",
        "You strong-arm a rival gang out of their turf.",
    ]),
    (100, "Feared Outlaw", [
        "You rob a caravan under cover of night.",
        "You hold the jeweller at knifepoint for his finest stones.",
        "You raid a tax collector's strongbox.",
        "You ambush the guard escort and make off with the loot.",
    ]),
    (200, "Legendary Criminal", [
        "You rob the town's grandest estate blind.",
        "Whispers say you were behind last week's bank job.",
        "You shake down the guild masters themselves.",
        "You hold the whole market square to ransom.",
    ]),
]


def crime_tier(infamy: int) -> tuple[int, str, list[str]]:
    """Return (threshold, title, flavour_lines) for the highest tier at
    or below `infamy`."""
    result = CRIME_TIERS[0]
    for tier in CRIME_TIERS:
        if infamy >= tier[0]:
            result = tier
    return result
