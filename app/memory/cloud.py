"""Optional Supabase REST snapshot persistence for Render/free-tier deployments.

SQLite remains the primary local store. When cloud memory is enabled, each session's
messages/state are mirrored to one JSONB row in Supabase so history survives instance
restarts/redeploys. This is intentionally optional and never blocks a local request
when the remote store is unavailable.
"""
from __future__ import annotations
import json
import logging
import time
from typing import Any
import httpx

log = logging.getLogger('astra.cloud_memory')

class SupabaseMemory:
    def __init__(self, url: str, key: str, table: str='astra_memory'):
        self.url=url.rstrip('/')
        self.key=key
        self.table=table
        self.endpoint=f"{self.url}/rest/v1/{table}"
        self.headers={"apikey":key,"Authorization":f"Bearer {key}","Content-Type":"application/json"}
    def enabled(self)->bool:
        return bool(self.url and self.key)
    def _client(self):
        return httpx.Client(timeout=5.0,headers=self.headers)
    def upsert(self, snapshot:dict[str,Any])->bool:
        body={"session_id":snapshot["session_id"],"payload":snapshot,"updated_at":"now()"}
        try:
            with self._client() as c:
                r=c.post(self.endpoint,params={"on_conflict":"session_id"},headers={**self.headers,"Prefer":"resolution=merge-duplicates,return=minimal"},json=body)
                if r.status_code>=400:
                    log.warning('Supabase upsert failed: %s %s',r.status_code,r.text[:250]); return False
            return True
        except httpx.HTTPError as e:
            log.warning('Supabase unavailable: %s',e); return False
    def delete(self,sid:str)->bool:
        try:
            with self._client() as c:
                r=c.delete(self.endpoint,params={"session_id":f"eq.{sid}"})
                return r.status_code<400
        except httpx.HTTPError:return False
    def all(self)->list[dict[str,Any]]:
        try:
            with self._client() as c:
                r=c.get(self.endpoint,params={"select":"payload","order":"updated_at.desc","limit":"200"})
                if r.status_code>=400:
                    log.warning('Supabase read failed: %s %s',r.status_code,r.text[:250]);return []
                rows=r.json() or []
                return [x.get('payload') or {} for x in rows]
        except (httpx.HTTPError,ValueError) as e:
            log.warning('Supabase read unavailable: %s',e);return []
