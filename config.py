"""Load a small, non-executable .env file; process environment has priority."""
import os
from pathlib import Path

def load():
    file=Path(__file__).resolve().with_name('.env')
    if not file.exists(): return
    allowed={'ANTHROPIC_API_KEY','ANTHROPIC_MODEL','META_ORIGIN','META_SECURE_COOKIE','META_DB','META_TRUSTED_PROXIES','META_DATABASE_URL'}
    for line in file.read_text(encoding="utf-8").splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        key,value=line.split('=',1);key=key.strip();value=value.strip()
        if key not in allowed: continue
        if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):value=value[1:-1]
        if value:os.environ.setdefault(key,value)
