"""`python -m fluidvoice.gtkui` — same as `fluidvoice app`."""
import sys

from .application import run

sys.exit(run(sys.argv[1:]))
