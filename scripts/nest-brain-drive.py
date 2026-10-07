#!/usr/bin/env python3
"""Nest portable brains — Drive REST helper.

rclone moves the bytes; this helper does what rclone can't: creating the
version folder WITH Drive `appProperties` (entity, version, epoch,
sensitivity) so `files.list?q=appProperties has {...}` can find the latest
brain without path walking (see ssot.nest-brains.yml).

Token handling is identical to scripts/bench-gdrive.py: read the OAuth
token out of ~/.config/rclone/rclone.conf; when rclone uses its built-in
OAuth client (empty client_id) make a throwaway `rclone lsf` refresh the
token first, then reuse it.

Subcommands:
  ensure <entity> <version>         create nest/brains/<entity>/<version>
      --set entity=X version=Y ...  folder chain + set appProperties on the
                                    version dir. Prints the version dir id.
  props <entity> <version>          print appProperties of the version dir
  find <entity>                     list version dirs (name + appProperties)
                                    latest-first by name

Exit 0 on success, 3 on any failure — callers treat failure as
"fall back to plain rclone paths", never fatal to a pack.
"""
import json
import sys
import urllib.parse

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _nest_brain_common import Drive, log  # noqa: E402

FOLDER = "application/vnd.google-apps.folder"


def find_child(drv, parent_id, name):
    q = urllib.parse.quote(
        f"'{parent_id}' in parents and name='{name}' and trashed=false"
    )
    data = drv.req_json(
        "GET", f"/drive/v3/files?q={q}&fields=files(id,name,appProperties,mimeType)"
    )
    files = data.get("files", [])
    return files[0] if files else None


def mkdir(drv, parent_id, name):
    meta = {"name": name, "mimeType": FOLDER, "parents": [parent_id]}
    data = drv.req_json("POST", "/drive/v3/files", meta)
    return data["id"]


def ensure_folder(drv, parent_id, name):
    child = find_child(drv, parent_id, name)
    if child and child.get("mimeType") == FOLDER:
        return child["id"]
    if child:  # name exists but not a folder — don't stomp it
        raise RuntimeError(f"{name} exists under {parent_id} but is not a folder")
    return mkdir(drv, parent_id, name)


def ensure_chain(drv, entity, version):
    fid = "root"
    for part in ("nest", "brains", entity, version):
        fid = ensure_folder(drv, fid, part)
    return fid


def set_appprops(drv, file_id, props):
    drv.req_json(
        "PATCH",
        f"/drive/v3/files/{file_id}",
        {"appProperties": props},
    )


def main():
    args = []
    set_kv = {}
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--set" and i + 1 < len(sys.argv):
            for kv in sys.argv[i + 1].split(","):
                k, _, v = kv.partition("=")
                set_kv[k.strip()] = v.strip()
            i += 2
        else:
            args.append(sys.argv[i])
            i += 1

    drv = Drive()
    if not args:
        print(__doc__)
        return 3

    if args[0] == "ensure" and len(args) == 3:
        entity, version = args[1], args[2]
        vid = ensure_chain(drv, entity, version)
        if set_kv:
            set_appprops(drv, vid, set_kv)
        print(vid)
        return 0

    if args[0] == "props" and len(args) == 3:
        entity, version = args[1], args[2]
        fid = ensure_folder(drv, "root", "nest")
        fid = ensure_folder(drv, fid, "brains")
        fid = ensure_folder(drv, fid, entity)
        child = find_child(drv, fid, version)
        print(json.dumps(child.get("appProperties", {}) if child else {}))
        return 0

    if args[0] == "find" and len(args) == 2:
        entity = args[1]
        fid = "root"
        for part in ("nest", "brains", entity):
            child = find_child(drv, fid, part)
            if not child:
                print("[]")
                return 0
            fid = child["id"]
        q = urllib.parse.quote(
            f"'{fid}' in parents and mimeType='{FOLDER}' and trashed=false"
        )
        data = drv.req_json(
            "GET",
            f"/drive/v3/files?q={q}&fields=files(name,appProperties)&pageSize=200",
        )
        rows = sorted(
            (f["name"] for f in data.get("files", [])), reverse=True
        )
        print(json.dumps(rows))
        return 0

    print(__doc__)
    return 3


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"drive helper failed: {e}")
        sys.exit(3)
