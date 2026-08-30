# Correct the documented granularities on GET /api/analytics/revenue

## What is wrong

`api/analytics/routes/revenue.py` accepts four granularity values:

    _VALID_GRANULARITIES = {"hour", "day", "week", "month"}

Both places that document the parameter say three. The query parameter is
declared as

    granularity: str = Query("day", description="day, week, or month"),

and `get_revenue`'s docstring does not mention the accepted values at all.

`hour` is genuinely supported: `analytics/services/analytics_engine.py`
carries a helper documented as "Generate hourly revenue data for a single day
— used when granularity=hour", and the route passes `granularity` straight
through to `revenue_report`. So the code is right and the documentation is
stale.

The description string is what a caller reads in the generated OpenAPI docs,
so today the API tells its users that a value it accepts is invalid.

## What done means

1. The `granularity` query parameter's `description` names all four accepted
   values: hour, day, week, month.
2. `get_revenue`'s docstring states the accepted granularities as well. Keep
   the existing "Defaults to last 30 days if start/end not provided." line.
3. Nothing else changes.

## What must not change

`_VALID_GRANULARITIES` itself. The accepted set is correct; narrowing it to
match the stale documentation would be a behaviour change wearing the same
diff, and it would break `granularity=hour` for anyone using it.

Do not touch any other file. Do not reformat the module, reorder imports, or
remove the unused `List` and `get_tenant_from_header` imports -- they are
real, they are pre-existing, and cleaning them up here would make a one-line
documentation fix arrive as a diff nobody scoped.

## How it is checked

    api/analytics/routes/revenue.py still compiles
    ruff --select E9 is clean on it
    the accepted set is untouched, and both the docstring and the parameter
    description name all four values

The third check reads the file with `ast` and lives outside this repository.
