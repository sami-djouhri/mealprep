# mealprep

![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)
![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)

Recipes, a weekly plan, and the shopping list that falls out of the two. Part of
the [Saganta Suite](https://github.com/sami-djouhri/saganta-suite), usable on
its own. All user-facing text is German.

## The point of it inside the suite

A shopping list is only useful if it knows what you already have. This service
asks the pantry (`lager`) what is in stock and subtracts it, and it asks the
calendar what kind of day each one is, because a working day and a day off do
not get the same plan.

Both connections are optional. Without them you get a plain weekly planner with
a complete shopping list instead of a reduced one, which is a smaller feature
rather than an error.

## Configuration

Everything is passed in through the environment. This service has **no**
`env_file`, so every value has to be listed in the compose file explicitly. That
is worth saying out loud: a value written into a `.env` next to it looks set,
and never reaches the container.

## Tests

```bash
./run-tests.sh
```

## License

AGPL-3.0.

## About this snapshot

The recipe, not the data. The secrets vault and the home-network compose overlay
are not in here.

The development history stays private; the public one starts at the first
release and grows with each one.
