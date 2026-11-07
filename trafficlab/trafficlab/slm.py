"""OPTIONAL local-model explainer. The model is a CLIENT-SIDE helper that phrases evidence the deterministic engine already produced.
It never sees raw samples, never detects anything, and its output is validated:
  * the evidence pack holds only aggregates, ids, raw timestamp strings, rule claims (no sample arrays)
  * every 'possible cause' must cite an evidence id that exists in the pack, else it is STRIPPED and listed
  * ids that do not exist, and numbers that appear nowhere in the pack, are FLAGGED
  * the UI always shows: 'AI-generated explanation. Verify against evidence.'
Transport: HTTP POST to an OpenAI-compatible /v1/chat/completions endpoint (llama.cpp server, Ollama, LM Studio and others offer one: verify yours).
Stdlib only; loopback-only unless explicitly allowed. NOT tested against a real model by the author."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

BANNER = "AI-generated explanation. Verify against evidence."
SECTIONS = ["Summary", "Ranked possible causes", "Evidence cited", "Unknowns", "Suggested checks"]
UNKNOWN = "Unknown - insufficient evidence"
ID_RX = re.compile(r"\b(?:[FCD]-[0-9a-f]{10}|KB:[A-Za-z0-9_-]+|R\d_[a-z_]+|DC\d{2}|X\d{2}|C[A-Z0-9_-]{2,20}|CR[-A-Za-z0-9_]*)\b")
SYSTEM = ("You write plain-language explanations of network findings from an EVIDENCE PACK produced by a deterministic engine. "
          "Use ONLY the pack. Never invent numbers, commands, device behaviour or ids. Output exactly these five sections, each starting with its heading on its own line: "
          + "; ".join(SECTIONS) + ". Under 'Ranked possible causes' write a numbered list; EVERY item must cite at least one evidence id from the pack in square brackets, e.g. [F-0123456789]. "
          f"If the pack does not support a cause, write exactly: {UNKNOWN}. 'Evidence cited' lists the ids you used. Keep it short.")


class SLMError(ValueError):
    pass


def check_endpoint(cfg):
    sl = cfg["slm"]
    if not sl["enabled"]:
        raise SLMError("the local model explainer is disabled (config.slm.enabled = false). The tool works fully without it.")
    u = urllib.parse.urlparse(sl["endpoint"])
    if u.scheme not in ("http", "https") or not u.hostname:
        raise SLMError("slm.endpoint must be an http(s) URL")
    if u.hostname not in ("127.0.0.1", "localhost", "::1") and not sl["allow_non_loopback"]:
        raise SLMError(f"slm.endpoint host '{u.hostname}' is not this machine; refused (offline tool). Set slm.allow_non_loopback only if you accept sending the evidence pack off-machine.")
    return sl


def build_pack(result, checks, finding_id, max_chars=6000):
    """-> (pack dict, allowed_ids set, truncated bool). Aggregates and ids only."""
    f = next((x for x in result["findings"] if x["id"] == finding_id), None)
    if f is None:
        raise SLMError("unknown finding id")
    w = f["window"]
    pack = {"finding": {"id": f["id"], "kind": f["kind"], "device": f["device"], "interface": f["interface"], "metric": f["metric"], "zone": f["zone"], "severity": f["severity"], "direction": f.get("direction"),
                        "window_ts_raw": [w["start_raw"], w["end_raw"]], "numbers": f["numbers"], "confidence": f["confidence"]},
            "interpretation": [{"rule": i.get("rule"), "claim": i["claim"], "evidence": i.get("evidence", []), "checks": i.get("checks", [])} for i in f["interpretation"]],
            "cr_candidates": [{"id": c["cr_id"], "title": c["title"], "relation": c["relation"], "label": c["label"]} for c in f.get("cr_candidates", [])]}
    cl = next((c for c in result["clusters"] if f["id"] in c["members"]), None)
    if cl:
        pack["cluster"] = {"id": cl["id"], "devices": cl["devices"], "zones": cl["zones"], "mean_pearson_r": cl["mean_pearson_r"], "label": cl["label"], "label_topology": cl.get("label_topology")}
    if f.get("topology"):
        pack["topology"] = f["topology"]
    dev = [d for d in (checks or {}).get("findings", []) if f["device"].lower() in d["device"].lower().split(",") and not d.get("waived")]
    pack["device_checks"] = [{"id": d["id"], "rule": d["rule"], "severity": d["severity"], "title": d["title"], "detail": d["detail"][:160]} for d in dev[:8]]
    pack["data_quality_note"] = "numbers are aggregates computed by the engine; no raw samples are included"

    def size():
        return len(json.dumps(pack, default=str))
    trunc = False
    for key, keep in (("device_checks", 3), ("device_checks", 0)):                # drop lowest-priority context first
        if size() > max_chars and key in pack:
            pack[key] = pack[key][:keep]
            trunc = True
    if size() > max_chars:
        for i in pack["interpretation"]:
            i["checks"] = i["checks"][:1]
        pack.pop("topology", None)
        trunc = True
    if size() > max_chars:
        raise SLMError(f"evidence pack is {size():,} characters after trimming, above slm.max_pack_chars={max_chars:,}; raise the limit or use a model with a larger context")
    allowed = set(ID_RX.findall(json.dumps(pack, default=str))) | {f["id"]}
    allowed |= {i["rule"] for i in pack["interpretation"] if i.get("rule")}
    return pack, allowed, trunc


def _split_sections(text):
    heads = "|".join(re.escape(h) for h in SECTIONS)
    parts = re.split(rf"(?im)^[\s#*_>-]*({heads})[\s*_:]*$", text)
    out = {}
    for k in range(1, len(parts) - 1, 2):
        out[next(h for h in SECTIONS if h.lower() == parts[k].lower())] = parts[k + 1].strip()
    return out


def validate(text, allowed, pack_text):
    secs = _split_sections(text)
    missing = [h for h in SECTIONS if h not in secs]
    stripped, kept = [], []
    for line in secs.get("Ranked possible causes", "").splitlines():
        if not line.strip():
            continue
        ids = ID_RX.findall(line)
        good = [i for i in ids if i in allowed]
        if UNKNOWN.lower() in line.lower() and not good:
            kept.append(line)
        elif good:
            kept.append(line)
        else:
            stripped.append({"line": line.strip(), "reason": "no citation of an evidence id from the pack" if not ids else f"cites ids not in the pack: {ids}"})
    bad_ids = sorted({i for i in ID_RX.findall(text) if i not in allowed})
    nums = sorted({n for n in re.findall(r"\d[\d,]*\.?\d*", text) if len(re.sub(r"\D", "", n)) >= 2 and n.strip(",") not in pack_text and n.replace(",", "") not in pack_text})
    clean = dict(secs)
    clean["Ranked possible causes"] = "\n".join(kept) if kept else UNKNOWN
    return {"banner": BANNER, "sections": clean, "missing_sections": missing, "stripped_causes": stripped, "invalid_ids": bad_ids, "unverified_numbers": nums,
            "accepted_causes": len([k for k in kept if UNKNOWN.lower() not in k.lower()]), "raw": text}


def explain(result, checks, finding_id, cfg):
    sl = check_endpoint(cfg)
    pack, allowed, trunc = build_pack(result, checks, finding_id, sl["max_pack_chars"])
    pack_text = json.dumps(pack, default=str)
    body = {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "EVIDENCE PACK (JSON):\n" + pack_text}], "temperature": sl["temperature"], "stream": False}
    if sl["model"]:
        body["model"] = sl["model"]
    req = urllib.request.Request(sl["endpoint"], data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=sl["timeout_s"]) as r:
            raw = json.loads(r.read())
        text = raw["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise SLMError(f"model server returned HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SLMError(f"cannot reach the model server at {sl['endpoint']}: {getattr(e, 'reason', e)}. Start your local model server first.")
    except (KeyError, IndexError, ValueError, TypeError):
        raise SLMError("the model server's reply is not an OpenAI-style chat completion (expected choices[0].message.content)")
    out = validate(text, allowed, pack_text)
    out.update(pack_chars=len(pack_text), pack_truncated=trunc, allowed_ids=sorted(allowed), finding_id=finding_id)
    return out
