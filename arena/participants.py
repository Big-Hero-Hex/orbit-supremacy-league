"""Official fixed rule-bot identities; this module loads no model or physics."""
import hashlib
import json
from pathlib import Path

BUILTINS={
    'rusher':('models/rusher_bot.py','models/sniper_bot.py'),
    'sniper':('models/sniper_bot.py',),
}

def builtin_identity(kind,hashes):
    if kind not in BUILTINS:raise ValueError('Unknown official rule bot')
    source={name:hashes[name] for name in BUILTINS[kind]}
    contract=dict(kind='official_rulebot',bot=kind,sources=source,adapter='original-raw84-box3-v1',adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    return hashlib.sha256(json.dumps(contract,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class OfficialRulePolicy:
    """Only adapt predict's interface; actions are the untouched official bot."""
    def __init__(self,kind):
        from models.rusher_bot import rusher_bot_action
        from models.sniper_bot import sniper_bot_action
        self.action={'rusher':rusher_bot_action,'sniper':sniper_bot_action}[kind]
    def predict(self,obs,deterministic=True):
        return self.action(obs),None
