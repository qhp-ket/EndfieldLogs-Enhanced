"""Registry of native modules and their fixed data requirements."""
from .damage import DamageModule
from .combo import ComboModule
from .uid import UidMaskModule

MODULES = {'damage': DamageModule, 'combo_skill': ComboModule, 'uid_mask': UidMaskModule}
