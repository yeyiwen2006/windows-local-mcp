"""Remove inherited tunnel credentials before loading file and desktop tools."""
import os

for _name in ("CONTROL_PLANE_API_KEY", "OPENAI_API_KEY", "OPENAI_ADMIN_KEY"):
    os.environ.pop(_name, None)

from .server import main

main()
