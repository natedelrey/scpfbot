# scpfbot

## Ranking configuration

Members with either Discord role `1233139781840670746` or
`1233139781840670749` can configure ranking through:

- `/rank_setup show`: download the current ranks and Discord role limits.
- `/rank_setup set_rank name:<Roblox role name> value:<1–255>`: add or update a rank.
- `/rank_setup remove_rank name:<rank name>`: remove an assignable rank.
- `/rank_setup set_limit role:<Discord role> maximum:<0–255>`: set that role's ranking ceiling; zero disables ranking.

Rank values are Roblox's numeric rank values, not Roblox role IDs. Names must
match the group role names (spacing, punctuation and case are normalized).
To rename a configured rank, remove the old entry and add the new one.
`/rank` suggestions update immediately; deployment or command synchronization
is not needed after setup edits. Manually entered ranks are still validated.

The default ranks are Class - D [1], Class - E [3], Level - 1 [4],
Level - 2 [5], Level - 3 [6], Level - 4 [7], O5 Council [9], O5 Head [10],
and The Administrator [11]. Existing Discord permission ceilings remain numeric
and unchanged; use `set_limit` to adjust them to the new hierarchy.

With `DATABASE_URL` configured, setup is stored in the `bot_rank_config` PostgreSQL
table and restored on connection. The database user needs permission to create
that table. Failed saves leave the active configuration unchanged. Without
`DATABASE_URL`, configuration is written atomically to `rank_config.json`.
On Railway, use PostgreSQL for persistence across deployments, or set
`RANK_CONFIG_FILE` to a path on a persistent volume. Configuration applies to
this bot instance, across its servers.

Deploy the updated code and restart the bot once to register `/rank_setup` and
replace `/rank`'s old fixed choices with autocomplete. Setup changes edit the
bot's mapping; they do not create or rename roles in Roblox itself.

## Tests

Install `requirements.txt`, then run `python -m unittest discover -s tests -v`.
Tests use isolated configuration and mock database access; they do not contact
Discord, Roblox or a live database.
