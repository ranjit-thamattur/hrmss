"""Re-pin requirements.txt to the installed versions (run inside a container after pip install)."""
import importlib.metadata as md
import re
import sys

path = sys.argv[1]
names = [line.split("==")[0].strip() for line in open(path) if line.strip()]
pins = [f"{n}=={md.version(re.sub(r'\[.*\]', '', n))}" for n in names]
open(path, "w").write("\n".join(pins) + "\n")
print("\n".join(pins))
