"""Applies cross-source context to an analysis result: CDP/LLDP topology, then the signature library. Idempotent."""
from .devcheck import topology
from . import signatures


def apply(result, checks, cfg):
    if result is None:
        return result
    topology.annotate(result, (checks or {}).get("topology"))
    signatures.annotate(result, checks, cfg)
    return result
