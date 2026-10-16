"""Cache identity includes source, direction, domain context, glossary and model."""
import hashlib
import json

def cache_key(*,task_id,source_sha256,direction,context_sha256,glossary_version,glossary_domain,glossary_content_sha256,policy_version,translator_model_version):
    return hashlib.sha256(json.dumps(locals(),sort_keys=True,separators=(',',':')).encode()).hexdigest()
