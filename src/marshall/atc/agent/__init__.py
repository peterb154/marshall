"""The controller's brain: what we ASK a model, and in what words.

`agent` IS NOT A TOP-LEVEL PART, and this package is where that decision lands.
"The thing that calls Bedrock" is a mechanism, not a responsibility -- the
moment a second domain has a brain, a shared `agent/` holds an air traffic
controller and an enemy commander, which have nothing in common but an SDK.

So the MECHANISM is `core.llm` (tiers, structured output, retries) and what you
ask it belongs to the domain asking. This is ATC's half: its prompts, its
phraseology, its tools.

WHY THE PROMPTS MOVED HERE. They were in `director/prompts/`, which is a
deployable -- so "how does the controller talk" lived in a container's
directory, next to a Dockerfile, and could not be found by anybody reading the
ATC code. A pilot who has been directing this project for a month said so
plainly:

    "I don't know how/where that works today - I hope I can figure it out
     after this refactor."

That is a structural failure, not a documentation one. How a controller SAYS an
ILS clearance is part of knowing what an ILS is, and the words belong beside
the logic that decides them.

WHAT IS HERE, AND WHAT IS NOT. The three prompt parts are assembled in order:

    soul    who he is -- persona, and nothing procedural
    plate   THIS mission's facts, generated from route.py and pushed live by
            the radio bridge. Never hand-written; it is data wearing prose
    rules   field-agnostic behaviour: radar identification, formations,
            frequency changes, what he must not claim to know, clearance
            delivery, how he works

`rules` is 325 lines and growing, which is the next thing to break up: a
procedure's phraseology should ship WITH that procedure (`atc/procedure/ils.py`
carrying its own words) rather than accumulating in one file nothing owns. See
docs/STRUCTURE.md. This package existing is the precondition for that split.

The HTTP door -- endpoints, session locking, the tier swap -- stays in the
deployable. Serving is not deciding.
"""
