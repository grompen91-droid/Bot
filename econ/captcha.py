"""Anti-bot checks: the town guard.

Every work has a small chance to trigger a letter challenge. Until the
player types the letters back in chat, all commands and buttons stay
locked and just repeat the challenge. State is in memory; a restart
clears outstanding checks, which is fine.
"""

import random
import time

CHALLENGE_CHANCE = 1 / 20   # odds per work
CODE_LENGTH = 5
GRACE_SECONDS = 600         # no re-check within 10 min of passing one
# No I/L/O/0/1 lookalikes.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ"

_pending: dict[tuple[int, int], str] = {}
_last_passed: dict[tuple[int, int], float] = {}


def has_pending(guild_id: int, user_id: int) -> bool:
    return (guild_id, user_id) in _pending


def pending_code(guild_id: int, user_id: int) -> str | None:
    return _pending.get((guild_id, user_id))


def maybe_challenge(guild_id: int, user_id: int) -> str | None:
    """Roll the dice on a work. Returns the active code if one is (now)
    pending, else None."""
    key = (guild_id, user_id)
    if key in _pending:
        return _pending[key]
    if time.time() - _last_passed.get(key, 0) < GRACE_SECONDS:
        return None
    if random.random() < CHALLENGE_CHANCE:
        code = "".join(random.choices(ALPHABET, k=CODE_LENGTH))
        _pending[key] = code
        return code
    return None


def try_solve(guild_id: int, user_id: int, answer: str) -> bool:
    key = (guild_id, user_id)
    code = _pending.get(key)
    if code is None:
        return False
    if answer.strip().upper().replace(" ", "") == code:
        del _pending[key]
        _last_passed[key] = time.time()
        return True
    return False
