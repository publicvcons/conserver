#!/usr/bin/env python3
"""PublicVCons acceptance runner — executes TEST_PLAN.md T1-T13.

Run with the tools venv:
    ~/venvs/tools/bin/python seed/conserver/tests/run_testplan.py

Paths are derived from this file's location (conserver/tests ->
conserver -> seed -> workspace root) so the runner is relocatable.
Overrides via env:
  PVCONS_WS      workspace root (default: derived)
  PVCONS_SRCMP4  source mp4 (default: the local publicvcons drive path)
  PVCONS_SITE    served viewer base for T10 (default http://localhost:8096/)
T7/T10 also have manual parts (audio spot-check, visual render) that
this runner explicitly cannot cover and reports as such.
"""
import json, hashlib, subprocess, urllib.request, warnings, sys, base64, os
from pathlib import Path
warnings.filterwarnings("ignore")

_REL = "2010/05/25/ia_gov_house/4c724522-adfa-4275-9633-a66ec3157c5e"
WS = Path(os.environ.get("PVCONS_WS",
          Path(__file__).resolve().parents[3]))
VDIR = WS/"seed/vcons"/_REL
PUBK = WS/"seed/vcons/.well-known/scitt-pubkey.json"
SCITT = WS/"seed/conserver/pipeline/scitt_sign.py"
SRCMP4 = Path(os.environ.get("PVCONS_SRCMP4",
          "/Volumes/publicvcons/media/ia_gov_house/2010/05/25/gov.house.20100525.mp4"))
SITE = os.environ.get("PVCONS_SITE", "http://localhost:8096/")
RAW = ("https://raw.githubusercontent.com/publicvcons/vcons/main/"+_REL)
EXP_SHA = "922b7af4c64e337f0db7dd301c2de1aa56358bb7a09c3326c15f3cdc61b79c61"
STAGES = ["imported","normalized","transcribed","analyzed","published"]

results = {}
def rec(name, ok, detail=""):
    results[name] = ok
    print(f"{name}: {'PASS' if ok else 'FAIL'}" + (f"  — {detail}" if detail else ""))

def sha256(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()

vcon = json.loads((VDIR/"vcon.json").read_text())
lbside = json.loads((VDIR/"lawful_basis.json").read_text())
lb_att = next((a for a in vcon["attachments"] if a.get("purpose")=="lawful_basis"), None)
lbb = lb_att["body"] if lb_att else {}

# ---- T1 ----
miss=[]
for f in ["README.md","vcon.json","lawful_basis.json","source_media.sha256"]:
    if not (VDIR/f).is_file(): miss.append(f)
sc = sorted(p.name for p in (VDIR/"scitt").glob("*.scitt.json"))
exp_sc = [f"{i+1:02d}_{s}.scitt.json" for i,s in enumerate(STAGES)]
if sc != exp_sc: miss.append(f"scitt set {sc} != {exp_sc}")
if not PUBK.is_file(): miss.append(".well-known/scitt-pubkey.json")
rec("T1", not miss, "all files + 5 receipts + pubkey present" if not miss else str(miss))

# ---- T2 ----
errs=[]
if vcon.get("vcon")!="0.4.0": errs.append(f"vcon={vcon.get('vcon')}")
if vcon.get("uuid")!="4c724522-adfa-4275-9633-a66ec3157c5e": errs.append("uuid")
if not str(vcon.get("created_at","")).startswith("2010-05-25"): errs.append("created_at")
if not vcon.get("subject"): errs.append("subject")
if vcon.get("extensions")!=["lawful_basis"]: errs.append(f"extensions={vcon.get('extensions')}")
if len(vcon.get("parties",[]))!=4: errs.append("parties!=4")
if len(vcon.get("dialog",[]))!=1: errs.append("dialog!=1")
atypes=[a["type"] for a in vcon.get("analysis",[])]
if sorted(atypes)!=["summary","transcript"]: errs.append(f"analysis={atypes}")
if lb_att is None or "type" in lb_att: errs.append("attachment must use purpose not type")
segs=next(a for a in vcon["analysis"] if a["type"]=="transcript")["body"]["segments"]
if len(segs)!=697: errs.append(f"segments={len(segs)}")
if not all(all(k in s for k in ("start","end","speaker","text")) for s in segs):
    errs.append("segment keys")
try:
    from vcon import Vcon
    v=Vcon.load_from_file(str(VDIR/"vcon.json")); valid,verr=v.is_valid()
    if not valid: errs.append(f"is_valid={verr}")
    libok=f"library is_valid={valid}"
except Exception as e:
    errs.append(f"lib load {e}"); libok=""
rec("T2", not errs, f"spec 0.4.0, extensions, 697 segs, {libok}" if not errs else str(errs))

# ---- T3 ----
e=[]
if lbb.get("lawful_basis")!="public_task": e.append("basis")
pg=lbb.get("purpose_grants",[])
if not (isinstance(pg,list) and pg and all(isinstance(g,dict) for g in pg)):
    e.append("purpose_grants not objects")
purposes={g.get("purpose") for g in pg if isinstance(g,dict)}
if not {"public_transparency","research","journalism"} <= purposes:
    e.append(f"purposes={purposes}")
if not all(g.get("granted") is True and g.get("granted_at") for g in pg):
    e.append("grant fields")
if lbb.get("expiration") is not None: e.append("expiration!=null")
if lbb.get("terms_of_service")!="https://policy.publicvcons.org/terms": e.append("terms")
reg=lbb.get("registry")
if not (isinstance(reg,dict) and reg.get("type")=="scitt"
        and reg.get("url")=="https://scitt.publicvcons.org"): e.append(f"registry={reg}")
pm=lbb.get("proof_mechanisms",[])
hit=any(isinstance(m,dict) and m.get("proof_type")=="cryptographic_signature"
        and m.get("proof_data",{}).get("mechanism")=="scitt_statement_chain"
        and m["proof_data"].get("stages")==STAGES for m in pm)
if not hit: e.append("proof_mechanisms")
md=lbb.get("metadata",{})
if not md.get("justification"): e.append("justification")
cit=" ".join(md.get("citations",[]))
if "17/105" not in cit or "creativecommons.org/publicdomain/zero" not in cit:
    e.append("citations")
src=md.get("source",{})
if src.get("archive_identifier")!="gov.house.20100525" or not src.get("source_media_sha256"):
    e.append("source block")
if lbside!=lbb: e.append("sidecar != inlined")
rec("T3", not e, "IETF lawful-basis shape correct; sidecar==inlined" if not e else str(e))

# ---- T4 ----
e=[]
disk = sha256(SRCMP4) if SRCMP4.is_file() else "NO_FILE"
filehash = (VDIR/"source_media.sha256").read_text().split()[0]
dch = vcon["dialog"][0].get("content_hash","")
mss = lbb.get("metadata",{}).get("source",{}).get("source_media_sha256","")
for label,val in [("disk",disk),("source_media.sha256",filehash),
                  ("dialog.content_hash",dch.replace("sha256-","")),
                  ("metadata.source.sha256",mss)]:
    if val!=EXP_SHA: e.append(f"{label}={val[:16]}")
rec("T4", not e, f"all 4 == {EXP_SHA[:16]}…" if not e else str(e))

# ---- T5 ----
r=subprocess.run([str(Path.home()/ "venvs/tools/bin/python"),str(SCITT),
                  "verify","--receipts",str(VDIR/"scitt")],
                 capture_output=True,text=True)
oks=r.stdout.count("OK "); bads=r.stdout.count("BAD")
rec("T5", r.returncode==0 and oks==5 and bads==0,
    f"{oks} OK, {bads} BAD, exit {r.returncode}")

# ---- T6 ----
e=[]
pub_x=json.loads(PUBK.read_text())["x"]
vhash=sha256(VDIR/"vcon.json")
for i,s in enumerate(STAGES):
    st=json.loads((VDIR/"scitt"/f"{i+1:02d}_{s}.scitt.json").read_text())
    p=st["payload"]
    if p.get("subject")!="urn:vcon:4c724522-adfa-4275-9633-a66ec3157c5e": e.append(f"{s}.subject")
    if p.get("stage")!=s: e.append(f"{s}.stage")
    if p.get("seq")!=i+1: e.append(f"{s}.seq")
    if p.get("registry")!="https://scitt.publicvcons.org": e.append(f"{s}.registry")
    if p.get("vcon_sha256")!=vhash: e.append(f"{s}.vcon_sha256")
    if not p.get("lawful_basis_sha256"): e.append(f"{s}.lb_sha")
    if st["protected"]["kid"]!=pub_x: e.append(f"{s}.kid")
# negative check: tamper a copy
import tempfile, shutil
tmp=Path(tempfile.mkdtemp())
shutil.copytree(VDIR/"scitt", tmp/"scitt")
victim=tmp/"scitt"/"03_transcribed.scitt.json"
d=json.loads(victim.read_text())
sigb=bytearray(base64.urlsafe_b64decode(d["signature"]+"=="*((-len(d["signature"]))%4 and 1)))
sig=d["signature"]; sig=("A" if sig[0]!="A" else "B")+sig[1:]
d["signature"]=sig; victim.write_text(json.dumps(d))
rn=subprocess.run([str(Path.home()/ "venvs/tools/bin/python"),str(SCITT),
                   "verify","--receipts",str(tmp/"scitt")],
                  capture_output=True,text=True)
neg_caught = "BAD" in rn.stdout or rn.returncode!=0
if not neg_caught: e.append("tamper not detected")
shutil.rmtree(tmp)
rec("T6", not e, "payloads bind right hashes/kid; tamper detected" if not e else str(e))

# ---- T7 (automatable part) ----
seg120=[s for s in segs if 118<=s["start"]<=150]
joined=" ".join(s["text"] for s in seg120).lower()
hits=[w for w in ["lundgren","administration","attorney general","california"] if w in joined]
rec("T7", len(hits)>=3,
    f"@~120s contains {hits} (manual audio spot-check still required)")

# ---- T8 ----
e=[]
req=WS/"seed/conserver/requirements"
for f in ["README.md","tools.lock.txt","pvcons.lock.txt"]:
    if not (req/f).is_file() or not (req/f).read_text().strip(): e.append(f)
tl=(req/"tools.lock.txt").read_text()
if "vcon==" not in tl: e.append("vcon not pinned")
rdme=(req/"README.md").read_text()
if "3.13" not in rdme or "torch" not in rdme: e.append("README missing pin rationale")
rec("T8", not e, "lockfiles present, vcon pinned, README explains pins" if not e else str(e))

# ---- T9 ----
e=[]
import glob
try:
    import yaml
except ImportError:
    yaml=None
srcdir=WS/"seed/conserver/sources"
profs={}
for fp in glob.glob(str(srcdir/"*.yaml")):
    txt=Path(fp).read_text()
    name=Path(fp).stem
    if yaml:
        profs[name]=yaml.safe_load(txt)
    else:
        profs[name]=txt
def field(p,k):
    return p.get(k) if isinstance(p,dict) else (k+":" in p)
if "house_clerk_youtube" not in profs: e.append("house_clerk_youtube missing")
else:
    p=profs["house_clerk_youtube"]
    if yaml and (p.get("kind")!="live" or p.get("status")!="active"
                 or p.get("lawful_basis",{}).get("basis")!="public_task"):
        e.append("house_clerk_youtube fields")
if "cspan_house_floor" not in profs: e.append("cspan missing")
else:
    p=profs["cspan_house_floor"]
    if yaml and p.get("status")!="paused": e.append("cspan not paused")
if "ia_gov_house" not in profs: e.append("ia_gov_house missing")
else:
    p=profs["ia_gov_house"]
    if yaml and (p.get("kind")!="backfill" or "sourced_from" not in p):
        e.append("ia_gov_house fields")
rec("T9", not e, f"{sorted(profs)} valid" if not e else str(e))

# ---- T10 (automatable part) ----
e=[]
try:
    site=urllib.request.urlopen(SITE,timeout=5).read().decode()
except Exception:
    site=None
gh_ok=False
try:
    gv=json.loads(urllib.request.urlopen(RAW+"/vcon.json",timeout=15).read())
    gh_ok = gv["vcon"]=="0.4.0" and any(a.get("purpose")=="lawful_basis" for a in gv["attachments"])
except Exception as ex:
    e.append(f"github raw {ex}")
# static contract: viewer reads purpose, structured grants, registry.url, metadata.source
idx=(WS/"seed/site/index.html").read_text()
for token in ['purpose==="lawful_basis"','lbb.metadata','registry.url','lbSource']:
    if token not in idx: e.append(f"viewer missing {token}")
if not gh_ok: e.append("github vcon shape")
rec("T10", not e,
    "GitHub corpus serves 0.4.0; viewer code matches new shape "
    "(visual/seek render = manual)" if not e else str(e))

# ---- T11  SCITT transparency receipts ----
e=[]
scitt_cli = WS/"seed/scitt/cli/pvcons_scitt.py"
recs = sorted((VDIR/"scitt").glob("*.scitt-receipt.json"))
exp_rec = [f"{i+1:02d}_{s}.scitt-receipt.json"
           for i,s in enumerate(STAGES)]
if [r.name for r in recs] != exp_rec:
    e.append(f"receipts {[r.name for r in recs]} != {exp_rec}")
# published service public key present
cfg = WS/"seed/vcons/.well-known/scitt-transparency-configuration.json"
svc_x = None
if not cfg.is_file():
    e.append("missing scitt-transparency-configuration.json")
else:
    svc_x = json.loads(cfg.read_text())["service_public_key"]["x"]
# every receipt countersigned by that published service key
for r in recs:
    if svc_x and json.loads(r.read_text()).get("service_kid") != svc_x:
        e.append(f"{r.name} service_kid != published key")
# offline verify: countersig + inclusion proof + leaf + issuer sig
if scitt_cli.is_file():
    rv = subprocess.run(
        [str(Path.home()/ "venvs/tools/bin/python"), str(scitt_cli),
         "verify", "--receipts", str(VDIR/"scitt")],
        capture_output=True, text=True)
    if not (rv.returncode == 0 and rv.stdout.count("OK ") == 5
            and "BAD" not in rv.stdout):
        e.append(f"offline verify: {rv.stdout.strip()} {rv.stderr[:120]}")
    # negative control: tamper a statement and a receipt root
    import tempfile as _tf, shutil as _sh
    tdir = Path(_tf.mkdtemp())
    _sh.copytree(VDIR/"scitt", tdir/"scitt")
    sp = tdir/"scitt"/"03_transcribed.scitt.json"
    d = json.loads(sp.read_text()); d["payload"]["stage"] = "HACKED"
    sp.write_text(json.dumps(d))
    rp = tdir/"scitt"/"05_published.scitt-receipt.json"
    d = json.loads(rp.read_text())
    d["receipt"]["root"] = "AAAA" + d["receipt"]["root"][4:]
    rp.write_text(json.dumps(d))
    rn = subprocess.run(
        [str(Path.home()/ "venvs/tools/bin/python"), str(scitt_cli),
         "verify", "--receipts", str(tdir/"scitt")],
        capture_output=True, text=True)
    if not (rn.returncode != 0 and rn.stdout.count("BAD") >= 2):
        e.append(f"tamper not caught: {rn.stdout.strip()}")
    _sh.rmtree(tdir)
else:
    e.append("scitt/cli/pvcons_scitt.py missing")
rec("T11", not e,
    "5 receipts verify offline (countersig+proof+leaf+issuer); "
    "published service key matches; tamper detected"
    if not e else str(e))

# ---- T12  MCP server ----
e=[]
mcp_test = WS/"seed/mcp/test_server.py"
if not mcp_test.is_file():
    e.append("seed/mcp/test_server.py missing")
else:
    mt = subprocess.run(
        [str(Path.home()/ "venvs/tools/bin/python"), str(mcp_test)],
        capture_output=True, text=True,
        env={**os.environ, "PVCONS_CORPUS": str(WS/"seed/vcons")})
    if mt.returncode != 0 or "PASS" not in mt.stdout:
        tail = (mt.stdout + mt.stderr).strip().splitlines()[-3:]
        e.append("smoke test failed: " + " | ".join(tail))
rec("T12", not e,
    "MCP stdio: all tools + resources + verify_vcon + error path OK"
    if not e else str(e))

# ---- T13  viewer home feed + in-browser SCITT verifier ----
e=[]
idxf = WS/"seed/vcons/index.json"
if not idxf.is_file():
    e.append("seed/vcons/index.json missing")
else:
    ix = json.loads(idxf.read_text())
    if ix.get("count",0) < 1 or not ix.get("vcons"):
        e.append("index.json empty")
    if "by_source" not in ix.get("collections",{}):
        e.append("index.json missing collections.by_source")
idx_html = (WS/"seed/site/index.html").read_text()
for tok in ['import { verifyChain }', 'function home(',
            'function detail(', 'index.json', 'vbtn']:
    if tok not in idx_html: e.append(f"viewer missing {tok}")
import shutil as _sh2
node = _sh2.which("node")
ptest = WS/"seed/site/test_scitt_verify.mjs"
if node and ptest.is_file():
    pr = subprocess.run([node, str(ptest)],
                        capture_output=True, text=True)
    if pr.returncode != 0 or "PARITY TEST: PASS" not in pr.stdout:
        e.append("verifier parity: " +
                 (pr.stdout+pr.stderr).strip().splitlines()[-1])
elif not node:
    e.append("node not found (cannot run verifier parity test)")
else:
    e.append("test_scitt_verify.mjs missing")
rec("T13", not e,
    "index.json + collections; viewer home/detail/verify wired; "
    "in-browser verifier has Python parity (clean + tamper)"
    if not e else str(e))

print("\n==== SUMMARY ====")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
fails=[k for k,v in results.items() if not v]
print(("ALL AUTOMATABLE CHECKS PASS" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
