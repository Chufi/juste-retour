import sys
from pathlib import Path

# Le repo n'est pas installé en package : on ajoute sa racine au path pour
# importer core/, verticals/ et backend/ depuis les tests.
RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))
