"""License-key check for Understand This Video Plugin (Freemius or Lemon Squeezy license APIs).

First use: key is activated online (one activation per machine) and cached in
~/.video-context/license.json. Afterwards it works offline; it re-validates
quietly every REVALIDATE_DAYS when online and keeps working offline for up to
OFFLINE_GRACE_DAYS since the last successful check.
"""
import hashlib
import hmac
import json
import os
import re
import platform
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

# ---- Seller settings ----------------------------------------------------------------
# PROVIDER: "freemius" (works for sellers in Uganda) or "lemonsqueezy".
PROVIDER = os.environ.get("VC_LICENSE_PROVIDER", "freemius")
FS_PRODUCT_ID = os.environ.get("VC_FS_PRODUCT_ID", "41518")     # Freemius product id
FS_API = os.environ.get("VC_FS_API", "https://api.freemius.com/v1")
STORE_ID = int(os.environ.get("VC_LS_STORE_ID", "0"))      # Settings > Stores
PRODUCT_ID = int(os.environ.get("VC_LS_PRODUCT_ID", "0"))  # Products > (id in URL)
# -------------------------------------------------------------------------------------
API = os.environ.get("VC_LICENSE_API", "https://api.lemonsqueezy.com/v1/licenses")
BUY_URL = os.environ.get("VC_BUY_URL", "https://checkout.freemius.com/app/41518/plan/72061/licenses/3/")
FS_STORE_ID = 21020
FS_PUBLIC_KEY = "pk_97f08b294dea7237bb3aa9b24edb6"
FS_PLAN_ID = 72061
FS_PRICING_ID = 99382
REVALIDATE_DAYS = 14
OFFLINE_GRACE_DAYS = 14
CACHE = Path(os.environ.get("VC_LICENSE_DIR", str(Path.home() / ".video-context"))) / "license.json"


def space_sentences(text):
    """Blank line between sentences, so a dialog or Claude is easy to read."""
    text = (text or "").strip()
    if "\n\n" in text:
        return text
    return re.sub(r"(?<=[.?!])[ \t]+(?=[A-Z])", "\n\n", text)


class LicenseError(Exception):
    def __init__(self, msg=""):
        super().__init__(space_sentences(msg))


def _machine_id():
    raw = "%s|%s|%s" % (uuid.getnode(), platform.node(), platform.system())
    return hashlib.sha256(raw.encode()).hexdigest()


def _sign(d):
    body = json.dumps({k: d[k] for k in sorted(d) if k != "sig"}, sort_keys=True)
    return hmac.new(_machine_id().encode(), body.encode(), hashlib.sha256).hexdigest()


def _post(endpoint, data):
    req = urllib.request.Request(
        "%s/%s" % (API, endpoint), data=urllib.parse.urlencode(data).encode(),
        headers={"Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:  # LS returns 400/404 with a JSON body
        try:
            return json.loads(e.read().decode())
        except Exception:
            raise LicenseError("license server error %s" % e.code)


def _check_product(resp):
    meta = resp.get("meta") or {}
    if STORE_ID and meta.get("store_id") != STORE_ID:
        raise LicenseError("this key is not for Understand This Video")
    if PRODUCT_ID and meta.get("product_id") != PRODUCT_ID:
        raise LicenseError("this key is not for Understand This Video")


def _load():
    try:
        d = json.loads(CACHE.read_text())
        if hmac.compare_digest(d.get("sig", ""), _sign(d)):
            return d
    except Exception:
        pass
    return None


def _save(d):
    d = dict(d)
    d["sig"] = _sign(d)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(d, indent=2))
    try:
        os.chmod(str(CACHE), 0o600)
    except OSError:
        pass


def _fs(method, path, body=None, query=None):
    url = "%s/products/%s/%s" % (FS_API, FS_PRODUCT_ID, path)
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Accept": "application/json",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
        except Exception:
            err = {}
        msg = (err.get("error") or {}).get("message") if isinstance(err.get("error"), dict) else err.get("error")
        raise LicenseError(msg or "license server error %s" % e.code)


def _uid():
    return _machine_id()[:32]


def activate(key):
    if PROVIDER == "freemius":
        return _fs_activate(key.strip())
    return _ls_activate(key.strip())


def _fs_activate(key):
    if not FS_PRODUCT_ID:
        raise LicenseError("seller config missing (FS_PRODUCT_ID)")
    try:
        r = _fs("POST", "licenses/activate.json",
                {"uid": _uid(), "license_key": key,
                 "title": "%s (%s)" % (socket.gethostname(), platform.system())})
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise LicenseError("can't reach the license server to activate (internet needed once): %s" % e)
    if not r.get("install_id"):
        raise LicenseError("activation failed")
    if r.get("license_plan_id") and str(r["license_plan_id"]) != str(FS_PLAN_ID):
        raise LicenseError("this key is not for Understand This Video")
    _save({"key": key, "instance_id": str(r["install_id"]), "checked": time.time(),
           "customer": ""})
    return {"meta": {}}


def _fs_validate(d):
    """Returns True if valid; raises network errors; raises LicenseError if invalid."""
    r = _fs("GET", "installs/%s/license.json" % d["instance_id"],
            query={"uid": _uid(), "license_key": d["key"]})
    if r.get("is_cancelled"):
        return False
    exp = r.get("expiration")
    if exp and time.mktime(time.strptime(exp, "%Y-%m-%d %H:%M:%S")) < time.time():
        return False
    return True


def _ls_activate(key):
    try:
        r = _post("activate", {"license_key": key,
                               "instance_name": "%s (%s)" % (socket.gethostname(), platform.system())})
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise LicenseError("can't reach the license server to activate (internet needed once): %s" % e)
    if not r.get("activated"):
        raise LicenseError(r.get("error") or "activation failed")
    _check_product(r)
    _save({"key": key, "instance_id": r["instance"]["id"], "checked": time.time(),
           "customer": (r.get("meta") or {}).get("customer_email", "")})
    return r


def deactivate():
    d = _load()
    if not d:
        return False
    try:
        if PROVIDER == "freemius":
            _fs("POST", "licenses/deactivate.json",
                {"uid": _uid(), "install_id": d["instance_id"], "license_key": d["key"]})
        else:
            _post("deactivate", {"license_key": d["key"], "instance_id": d["instance_id"]})
    except Exception:
        pass
    CACHE.unlink()
    return True


def require_license():
    """Return normally if licensed; raise LicenseError otherwise."""
    env_key = os.environ.get("VIDEO_CONTEXT_LICENSE_KEY", "").strip()
    d = _load()
    if d is None or (env_key and env_key != d.get("key")):
        if not env_key:
            raise LicenseError(
                "Understand This Video isn't activated yet.\n\n"
                "Paste this line into Terminal (Mac) to add your license key:\n\n"
                "curl -fsSL https://understandvideo.shipmonthly.com/install.sh | bash\n\n"
                "On Windows, run the installer again.\n\n"
                "Your key is in your purchase email.\n\n"
                "No key yet? Get one at https://understandvideo.shipmonthly.com"
            )
        activate(env_key)
        return
    age_days = (time.time() - d["checked"]) / 86400.0
    if age_days < REVALIDATE_DAYS:
        return
    if PROVIDER == "freemius":
        try:
            ok = _fs_validate(d)
        except (urllib.error.URLError, socket.timeout, OSError):
            if age_days <= OFFLINE_GRACE_DAYS:
                return
            raise LicenseError("please connect to the internet once to re-check your license")
        except LicenseError:
            ok = False
        if not ok:
            CACHE.unlink()
            raise LicenseError("license is no longer valid (cancelled/refunded). Contact support.")
        d["checked"] = time.time()
        _save(d)
        return
    try:
        r = _post("validate", {"license_key": d["key"], "instance_id": d["instance_id"]})
    except (urllib.error.URLError, socket.timeout, OSError, LicenseError):
        if age_days <= OFFLINE_GRACE_DAYS:
            return
        raise LicenseError("please connect to the internet once to re-check your license")
    status = (r.get("license_key") or {}).get("status")
    if not r.get("valid") or status in ("disabled", "expired"):
        CACHE.unlink()
        raise LicenseError("license is no longer valid (%s). Contact support." % (r.get("error") or status))
    _check_product(r)
    d["checked"] = time.time()
    _save(d)


def cli(argv):
    """Handle `understand-this-video activate KEY | deactivate | license-status`. Returns True if handled."""
    if not argv:
        return False
    cmd = argv[0]
    try:
        if cmd == "activate" and len(argv) == 2:
            r = activate(argv[1])
            print("Activated. Thank you!")
        elif cmd == "deactivate":
            print("Deactivated this machine." if deactivate() else "No license on this machine.")
        elif cmd == "license-status":
            d = _load()
            print("Licensed (%s), last checked %s" % (d["key"][:8] + "...",
                  time.strftime("%Y-%m-%d", time.localtime(d["checked"]))) if d else "Not activated.")
        else:
            return False
    except LicenseError as e:
        sys.stderr.write("License error: %s\n" % e)
        sys.exit(5)
    return True
