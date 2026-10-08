"""Response models of the API's pages and results (phase 6, rule B2: typed contracts at every process edge).

They describe the answers exactly as the handlers build them: every key declared (`extra="forbid"`, so an undeclared
key fails loudly instead of being dropped), numbers typed `int | float` so nothing is coerced, timestamps as the
ISO strings the handlers send. Stored artifact content stays `dict[str, Any]` until its owner module gives it a model.
"""
