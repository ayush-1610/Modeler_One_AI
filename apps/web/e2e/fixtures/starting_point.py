"""A project starting point's content (its CPF and studies) for the e2e specs, as JSON on stdout.

    uv run python apps/web/e2e/fixtures/starting_point.py dapagliflozin-osp

The specs build their scripted projects from it (create, CPF, studies) through the write API. It reads the platform's
own registry (`modeler_api.reference_models.starting_point`): the published OSP model is imported from its snapshot,
the illustrative set is labelled as such. The `/templates` routes that served it are retired (the console redesign's
slice 9). Software test data for the illustrative one; nothing here runs a simulation.
"""

from __future__ import annotations

import json
import sys

from modeler_api.config import get_settings
from modeler_api.reference_models import starting_point

if __name__ == "__main__":
    print(json.dumps(starting_point(sys.argv[1], get_settings())))
