"""The language deployable's own plumbing. The ATC left; what is here is serving.

This package used to hold twelve modules of ATC domain reasoning -- approaches,
clearance, flights, identify, plans, frequencies, capability, filing, hooks,
context, ops -- inside a container's directory, findable only by somebody who
already knew to look in a deployable. That is the prompts problem one layer
down: `ebea93a` moved the controller's WORDS into `marshall.atc.agent` for
exactly this reason and stopped there. **[ARCH-26] #147**, item 3.

Ten of the twelve are now `marshall.atc.*` and nothing redirects: an importer
that still says `tools.plans` gets an ImportError rather than a working name
that lies about where the code is. `tests/test_the_atc_is_not_in_a_container.py`
is the grep that keeps it that way.

WHAT IS LEFT IS SERVING, NOT DECIDING, which is the line
`marshall/atc/agent/__init__.py` already draws for the prompts:

    busy.py   one non-blocking lock per agent identity, because strands raises
              ConcurrencyException when a second call arrives while the first
              is in flight. The docstring argues at length about SEATS, and
              that argument is about what the KEY must be; the code is a table
              of locks with no aviation in it, reached only by the HTTP door.
    ops.py    `escalate` -- how the agent raises its hand to the operator. A
              log line with a greppable marker. No aerodrome, no procedure,
              and nothing a second domain's agent would want differently.

Both are properties of running an agent behind HTTP, not of controlling
aeroplanes, and both would move again the day this deployable is entered
through `marshall-atc` rather than through a directory.
"""
