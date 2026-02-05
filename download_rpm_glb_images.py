import os
import re
import time
import argparse
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

RPM_3D_BASE = "https://api.readyplayer.me/v1/avatars/"
RPM_2D_BASE = "https://models.readyplayer.me"

ID_OR_GLB_RE = re.compile(r"^([a-fA-F0-9]+)(?:\.glb)?$")

POSES = ["power-stance", "relaxed", "standing", "thumbs-up"]
EXPRESSION = "happy"


def parse_id(line: str) -> str | None:
    s = line.strip().strip('"').strip("'")
    if not s:
        return None
    m = ID_OR_GLB_RE.match(s)
    return m.group(1) if m else None


def safe_mkdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def download_file(session: requests.Session, url: str, out_path: str, timeout: int) -> tuple[bool, str]:
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return True, "exists"

    tmp = out_path + ".part"
    try:
        with session.get(url, stream=True, timeout=timeout) as r:
            if r.status_code != 200:
                return False, f"http_{r.status_code}"
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1024 * 256):
                    if chunk:
                        f.write(chunk)
        os.replace(tmp, out_path)
        return True, "downloaded"
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        return False, f"error_{type(e).__name__}"


def render_url(avatar_id: str, params: dict) -> str:
    return f"{RPM_2D_BASE}/{avatar_id}.png?" + urlencode(params)


def process_avatar(avatar_id: str, out_root: str, base_params: dict, timeout: int) -> dict:
    session = requests.Session()
    session.headers.update({"User-Agent": "rpm-avatar-downloader/3.0"})

    result = {
        "avatar": avatar_id,
        "glb": None,
        "png_ok": 0,
        "png_fail": 0,
    }

    avatar_dir = os.path.join(out_root, avatar_id)
    safe_mkdir(avatar_dir)

    # GLB
    glb_path = os.path.join(avatar_dir, f"{avatar_id}.glb")
    glb_url = f"{RPM_3D_BASE}{avatar_id}.glb"

    ok, reason = download_file(session, glb_url, glb_path, timeout)
    if not ok:
        result["glb"] = f"FAILED ({reason})"
        return result

    result["glb"] = reason

    # 4 poses, expression=happy
    for pose in POSES:
        params = dict(base_params)
        params["pose"] = pose

        png_url = render_url(avatar_id, params)
        png_path = os.path.join(
            avatar_dir,
            f"{avatar_id}__pose-{pose}__expr-{EXPRESSION}.png"
        )

        ok, _ = download_file(session, png_url, png_path, timeout)
        if ok:
            result["png_ok"] += 1
        else:
            result["png_fail"] += 1

    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fast RPM downloader (GLB + 4 poses, happy expression, threaded)"
    )
    ap.add_argument("input_file")
    ap.add_argument("output_dir")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--camera", default="portrait", choices=["portrait", "fullbody", "fit"])
    ap.add_argument("--background", default="0,0,0")
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    safe_mkdir(args.output_dir)

    ids: list[str] = []
    bad = 0
    with open(args.input_file, "r", encoding="utf-8") as f:
        for line in f:
            i = parse_id(line)
            if i:
                ids.append(i)
            elif line.strip():
                bad += 1

    if not ids:
        print("No valid avatar IDs found.")
        return 1

    print(f"Avatars: {len(ids)} | Threads: {args.threads} | Bad lines: {bad}")

    base_params = {
        "size": str(max(1, min(1024, args.size))),
        "camera": args.camera,
        "background": args.background,
        "expression": EXPRESSION,
    }

    ok_glb = fail_glb = 0
    png_ok = png_fail = 0

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = [
            pool.submit(process_avatar, avatar_id, args.output_dir, base_params, args.timeout)
            for avatar_id in ids
        ]

        for f in as_completed(futures):
            r = f.result()
            if r["glb"].startswith("FAILED"):
                fail_glb += 1
                print(f"[{r['avatar']}] GLB {r['glb']}")
            else:
                ok_glb += 1
                print(f"[{r['avatar']}] GLB {r['glb']} | PNG ok={r['png_ok']} fail={r['png_fail']}")

            png_ok += r["png_ok"]
            png_fail += r["png_fail"]

    print("\n=== SUMMARY ===")
    print(f"GLB ok: {ok_glb} | GLB failed: {fail_glb}")
    print(f"PNG ok: {png_ok} | PNG failed: {png_fail}")

    return 0 if fail_glb == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
