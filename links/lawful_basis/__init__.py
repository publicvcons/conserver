"""Link: enforce the lawful-basis hard rule.

PublicVCons hard rule: no vCon proceeds without a populated
lawful_basis attachment. The orchestrator adds it at ingress from the
source profile; this link is the chain-level gate. If the attachment is
missing or incomplete it returns None, which tells vcon-server to drop
the vCon from the chain rather than publish it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _base import init_logger, get_store  # noqa: E402

logger = init_logger("pvcons.lawful_basis")

default_options = {
    "required": ["lawful_basis", "purpose_grants", "terms_of_service",
                 "registry", "proof_mechanisms"],
}


def run(vcon_uuid, link_name, opts=default_options):
    o = {**default_options, **(opts or {})}
    store = get_store()
    v = store.get_vcon(vcon_uuid)

    atts = [a for a in v.vcon_dict.get("attachments", [])
            if a.get("purpose") == "lawful_basis"
            or a.get("type") == "lawful_basis"]
    if not atts:
        logger.error("HARD RULE: no lawful_basis attachment on %s — "
                     "halting chain", vcon_uuid)
        return None

    body = atts[0].get("body") or {}
    missing = [k for k in o["required"] if not body.get(k)]
    if missing:
        logger.error("HARD RULE: lawful_basis missing %s on %s — "
                     "halting chain", missing, vcon_uuid)
        return None

    logger.info("lawful_basis OK: %s", body.get("lawful_basis"))
    return vcon_uuid
