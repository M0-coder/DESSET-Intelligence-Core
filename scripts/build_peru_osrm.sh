#!/usr/bin/env bash
# Offline/opt-in: builds an OSRM MLD graph from a predownloaded, checked Peru PBF.
# No network download, no production deployment and no public port is started.
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 /absolute/path/to/peru-YYMMDD.osm.pbf EXPECTED_SHA256 ghcr.io/project-osrm/osrm-backend@sha256:HEX" >&2
  exit 2
fi
PBF="$1"; EXPECTED="$2"; IMAGE="$3"
if [[ ! -f "$PBF" || ! "${PBF##*/}" =~ ^peru-[0-9]{6}\.osm\.pbf$ ]]; then
  echo "must provide an existing dated Peru PBF" >&2; exit 2
fi
if [[ ! "$EXPECTED" =~ ^[0-9a-f]{64}$ ]]; then
  echo "expected PBF SHA256 required" >&2; exit 2
fi
if [[ ! "$IMAGE" =~ ^ghcr.io/project-osrm/osrm-backend@sha256:[0-9a-f]{64}$ ]]; then
  echo "image MUST use verified immutable digest" >&2; exit 2
fi
for command in docker sha256sum python3 realpath; do
  command -v "$command" >/dev/null || { echo "missing prerequisite: $command" >&2; exit 2; }
done
PBF_REAL="$(realpath "$PBF")"
DIRECTORY="$(dirname "$PBF_REAL")"
NAME="$(basename "$PBF_REAL")"
ACTUAL="$(sha256sum "$PBF_REAL" | cut -d' ' -f1)"
if [[ "$EXPECTED" != "$ACTUAL" ]]; then
  echo "PBF SHA-256 mismatch" >&2; exit 2
fi
# Refuse any preexisting graph, even the bare .osrm file or a dangling symlink.
shopt -s nullglob
existing=("${PBF_REAL%.osm.pbf}.osrm" "${PBF_REAL%.osm.pbf}.osrm-build-manifest.json" "${PBF_REAL%.osm.pbf}.osrm."*)
for entry in "${existing[@]}"; do
  if [[ -e "$entry" || -L "$entry" ]]; then
    echo "existing OSRM graph files present: refusing overwrite" >&2; exit 2
  fi
done
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "pinned OSRM image not present locally (no automatic pull allowed)" >&2; exit 2
fi
# Build only in a new private staging directory; source PBF remains untouched.
# Keep partial staging directories on failure for review; no silent cleanup.
# Explicitly budget disk/memory before use (PBF is copied; graph can be large).
umask 077
BUILD_DIR="$(mktemp -d "$DIRECTORY/${NAME%.osm.pbf}.osrm-build.XXXXXXXX")"
cp -- "$PBF_REAL" "$BUILD_DIR/$NAME"
COPIED_SHA="$(sha256sum "$BUILD_DIR/$NAME" | cut -d' ' -f1)"
if [[ "$COPIED_SHA" != "$EXPECTED" ]]; then
  echo "staged PBF SHA-256 mismatch: refusing build" >&2; exit 2
fi
docker run --rm --pull never --network none --mount "type=bind,src=$BUILD_DIR,dst=/data" "$IMAGE" \
  osrm-extract -p /opt/car.lua "/data/$NAME"
BASE="/data/${NAME%.osm.pbf}.osrm"
docker run --rm --pull never --network none --mount "type=bind,src=$BUILD_DIR,dst=/data" "$IMAGE" osrm-partition "$BASE"
docker run --rm --pull never --network none --mount "type=bind,src=$BUILD_DIR,dst=/data" "$IMAGE" osrm-customize "$BASE"
python3 - "$BUILD_DIR/$NAME" "$IMAGE" "$ACTUAL" <<'PYJSON'
import datetime
import hashlib
import json
import pathlib
import sys

pbf = pathlib.Path(sys.argv[1]); image = sys.argv[2]
base = pbf.name.removesuffix(".osm.pbf")
artifacts = sorted(pbf.parent.glob(f"{base}.osrm.*"))
if (pbf.parent / f"{base}.osrm").is_file():
    artifacts.insert(0, pbf.parent / f"{base}.osrm")
if not artifacts:
    raise SystemExit("missing graph artifacts after preprocessing")
rows = []
for artifact in artifacts:
    checksum = hashlib.sha256()
    with artifact.open("rb") as src:
        for chunk in iter(lambda: src.read(1 << 20), b""):
            checksum.update(chunk)
    rows.append({"name": artifact.name, "bytes": artifact.stat().st_size,
                 "sha256": checksum.hexdigest()})
manifest = {
    "country_code": "PE", "pbf_name": pbf.name,
    "pbf_sha256": sys.argv[3],
    "image_reference": image, "osrm_algorithm": "MLD",
    "osrm_profile_declared": "/opt/car.lua",
    "preprocess_control_result": "PASS",
    "nationwide_coverage_control_result": "NOT_VERIFIED",
    "candidate_decision": "BLOCKED",
    "artifacts": rows,
    "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "limitations": "provenance declared; not a nationwide road or ETA validation",
}
out = pbf.parent / f"{base}.osrm-build-manifest.json"
with out.open("x", encoding="utf-8") as stream:
    json.dump(manifest, stream, indent=2, ensure_ascii=False)
print(f"Build manifest: {out}")
PYJSON
echo "MLD graph prepared in $BUILD_DIR; original PBF untouched. No daemon was started."
echo "To serve locally ONLY (separate decision):"
echo "docker run --rm -p 127.0.0.1:5000:5000 --mount type=bind,src=$BUILD_DIR,dst=/data,readonly $IMAGE osrm-routed --algorithm mld $BASE"
