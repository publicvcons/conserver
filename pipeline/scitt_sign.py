#!/usr/bin/env python3
"""Prototype lifecycle statement signer for PublicVCons.

This is the Phase 0 stand-in for the SCITT transparency service that will
run at scitt.publicvcons.org. It mints an ed25519-signed statement per
lifecycle stage over the vcon content hash and the lawful-basis hash, and
writes a receipt next to the vcon. The statement/receipt JSON is
deliberately SCITT-shaped (issuer, subject, stage, payload digest,
signature) so the Phase 1 swap to a real SCITT ledger is mechanical.

The signing key lives OUTSIDE any repo at ~/.publicvcons/scitt_ed25519.jwk
(0600). The public key is emitted so a verifier can check the chain.

Subcommands:
  keygen                       create the project signing key if absent
  sign  --vcon F --stage S ... append a signed statement + receipt
  verify --vcon F --receipts D verify every receipt against the key
"""
import argparse
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

KEY_PATH = Path.home() / ".publicvcons" / "scitt_ed25519.jwk"
ISSUER = "did:web:scitt.publicvcons.org"
REGISTRY = "https://scitt.publicvcons.org"
BACKFILL_STAGES = ["imported", "normalized", "transcribed", "analyzed",
                    "published"]
LIVE_STAGES = ["created", "transcribed", "analyzed", "published"]


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def load_key() -> Ed25519PrivateKey:
    j = json.loads(KEY_PATH.read_text())
    return Ed25519PrivateKey.from_private_bytes(b64u_dec(j["d"]))


def keygen() -> int:
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if KEY_PATH.exists():
        print(f"key already exists at {KEY_PATH}")
        return 0
    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key()
    raw_priv = sk.private_bytes_raw()
    raw_pub = pk.public_bytes_raw()
    KEY_PATH.write_text(json.dumps({
        "kty": "OKP", "crv": "Ed25519",
        "d": b64u(raw_priv), "x": b64u(raw_pub),
        "issuer": ISSUER,
    }))
    os.chmod(KEY_PATH, 0o600)
    print(f"wrote signing key -> {KEY_PATH}")
    print(f"public key (x): {b64u(raw_pub)}")
    return 0


def sign(vcon_path: str, lawful_basis_path: str, stage: str,
         receipts_dir: str, seq: int) -> int:
    sk = load_key()
    pub_x = b64u(sk.public_key().public_bytes_raw())
    vcon = json.loads(Path(vcon_path).read_text())

    payload = {
        "issuer": ISSUER,
        "subject": f"urn:vcon:{vcon['uuid']}",
        "stage": stage,
        "seq": seq,
        "vcon_sha256": sha256_file(vcon_path),
        "lawful_basis_sha256": sha256_file(lawful_basis_path),
        "registry": REGISTRY,
        "iat": int(time.time()),
        "alg": "Ed25519",
    }
    pb = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = sk.sign(pb)
    statement = {
        "protected": {"alg": "Ed25519", "kid": pub_x},
        "payload": json.loads(pb),
        "signature": b64u(sig),
    }
    Path(receipts_dir).mkdir(parents=True, exist_ok=True)
    out = Path(receipts_dir) / f"{seq:02d}_{stage}.scitt.json"
    out.write_text(json.dumps(statement, indent=2))
    print(f"signed stage '{stage}' (seq {seq}) -> {out}")
    return 0


def verify(receipts_dir: str) -> int:
    receipts = sorted(Path(receipts_dir).glob("*.scitt.json"))
    if not receipts:
        print("no receipts found", file=sys.stderr)
        return 1
    ok = True
    for r in receipts:
        st = json.loads(r.read_text())
        pub = Ed25519PublicKey.from_public_bytes(
            b64u_dec(st["protected"]["kid"]))
        pb = json.dumps(st["payload"], sort_keys=True,
                        separators=(",", ":")).encode()
        try:
            pub.verify(b64u_dec(st["signature"]), pb)
            print(f"OK  {r.name}  stage={st['payload']['stage']} "
                  f"vcon_sha256={st['payload']['vcon_sha256'][:16]}…")
        except Exception as e:
            ok = False
            print(f"BAD {r.name}: {e}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen")
    sp = sub.add_parser("sign")
    sp.add_argument("--vcon", required=True)
    sp.add_argument("--lawful-basis", required=True)
    sp.add_argument("--stage", required=True)
    sp.add_argument("--receipts", required=True)
    sp.add_argument("--seq", type=int, required=True)
    vp = sub.add_parser("verify")
    vp.add_argument("--receipts", required=True)
    a = ap.parse_args()

    if a.cmd == "keygen":
        return keygen()
    if a.cmd == "sign":
        return sign(a.vcon, a.lawful_basis, a.stage, a.receipts, a.seq)
    if a.cmd == "verify":
        return verify(a.receipts)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
