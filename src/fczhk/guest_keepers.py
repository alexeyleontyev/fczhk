"""One public card for unnamed keepers, with distinct historical appearances.

The two keepers on 26 June played against each other. Their storage identities
must stay separate: merging them would corrupt result participants and statistics.
"""

GUEST_KEEPER_ALIAS = "Приглашённый вратарь"
LEGACY_KEEPER_ALIASES = frozenset(
    {
        "Вратарь (смены полевых, 11.09.2026)",
        "Вратарь (смены, 03.07.2026, белые)",
        "Вратарь (смены, 26.06.2026, белые)",
        "Вратарь (смены, 26.06.2026, чёрные)",
    }
)
SHARED_KEEPER_ALIASES = LEGACY_KEEPER_ALIASES | {GUEST_KEEPER_ALIAS}
