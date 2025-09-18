import os
import redis as redis_mod

_memory_store = {}

import os
import redis as redis_mod

def _make_redis():
    try:
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            print(f"Conectando ao Redis via URL: {redis_url}")
            # Desabilitar verificação SSL para evitar erro de certificado autoassinado
            return redis_mod.from_url(redis_url, decode_responses=True, ssl_cert_reqs=None)

        # fallback local
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", 6379))
        db = int(os.getenv("REDIS_DB", 0))
        print(f"Conectando ao Redis local: {host}:{port}, db={db}")
        return redis_mod.StrictRedis(host=host, port=port, db=db, decode_responses=True)
    except Exception as e:
        print(f"Erro ao conectar ao Redis: {e}")
        return None

_redis = _make_redis()

_redis = _make_redis()

def redis_get(key):
    if _redis:
        try:
            value = _redis.get(key)
            print(f"Redis GET: {key} => {value}")
            return value
        except Exception as e:
            print(f"Erro no redis_get: {e}")
    value = _memory_store.get(key)
    print(f"Memory GET: {key} => {value}")
    return value

def redis_set(key, value):
    if _redis:
        try:
            result = _redis.set(key, value)
            print(f"Redis SET: {key} => {value}, resultado: {result}")
            return result
        except Exception as e:
            print(f"Erro no redis_set: {e}")
    _memory_store[key] = value
    print(f"Memory SET: {key} => {value}")
    return True
