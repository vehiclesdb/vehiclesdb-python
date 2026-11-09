#!/bin/bash
# Cross-language parity: run the same resolve()/modelMatch() cases through the
# JS SDK and the Python SDK over the same dataset bytes, and fail on any
# difference in ids, methods, confidences, trails, ambiguity or candidates.
#
# Neither SDK's own test suite can catch a divergence, because each only ever
# interrogates its own implementation. This script is identical in
# vehiclesdb/vehiclesdb-js and vehiclesdb/vehiclesdb-python; run it from
# either, with the other checked out next to it:
#
#   bash tools/parity_check.sh                         # against fixtures/
#   bash tools/parity_check.sh ../vehiclesdb           # against a dataset checkout
#   VDB_DATA=path/to/vehicles.json bash tools/parity_check.sh
#
# Override the sibling locations with JS_SDK=... / PY_SDK=...
set -eu
HERE="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$HERE/package.json" ]; then
  JS_SDK="${JS_SDK:-$HERE}"; PY_SDK="${PY_SDK:-$HERE/../vehiclesdb-python}"
else
  PY_SDK="${PY_SDK:-$HERE}"; JS_SDK="${JS_SDK:-$HERE/../vehiclesdb-js}"
fi
JS_SDK="$(cd "$JS_SDK" && pwd)"; PY_SDK="$(cd "$PY_SDK" && pwd)"
ROOT="${VDB_DATA:-${1:-$HERE/fixtures}}"
ROOT="$(cd "$(dirname "$ROOT")" && pwd)/$(basename "$ROOT")"
export ROOT JS_SDK PY_SDK
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
PY=${PYTHON:-python}
export CASES="$OUT/cases.json" JS_OUT="$OUT/js.json" PY_OUT="$OUT/py.json"
cat > "$CASES" <<'JSON'
[
  {
    "input": "car/volkswagen/golf"
  },
  {
    "input": "car/alfa-romeo/1750gtv"
  },
  {
    "input": "VW Golf"
  },
  {
    "input": "VW Golf 1.9 TDI"
  },
  {
    "input": "Rabbit"
  },
  {
    "input": "Renault Duster"
  },
  {
    "input": "mercedes c class"
  },
  {
    "input": "golf"
  },
  {
    "input": "Landcruiser"
  },
  {
    "input": "toyota hilux",
    "kind": "car"
  },
  {
    "input": "MERCEDES-BENZ | SPRINTER",
    "kind": "van"
  },
  {
    "input": "BMW Serie 3"
  },
  {
    "input": "Peugeot 2008 Allure"
  },
  {
    "input": "Citroën Nuevo Citroën C3 Aircr"
  },
  {
    "input": "丰田 カローラ"
  },
  {
    "make": "VW",
    "model": "Golf"
  },
  {
    "make": "Volkswagon",
    "model": "Golf"
  },
  {
    "make": "VW",
    "model": "Gollf"
  },
  {
    "make": "Volkswagon",
    "model": "Gollf"
  },
  {
    "make": "VW",
    "model": "Nuevo Volkswagen Golf",
    "kind": "car"
  },
  {
    "make": "VW",
    "model": "Volkswagen"
  },
  {
    "make": "VW",
    "model": "Toureg"
  },
  {
    "make": "Opel",
    "model": "Insigna"
  },
  {
    "make": "Peugeot",
    "model": "2008 Allure"
  },
  {
    "make": "Toyota",
    "model": "2008 Allure"
  },
  {
    "make": "Kia",
    "model": "XCeed"
  },
  {
    "make": "BMW",
    "model": "Serie 3"
  },
  {
    "make": "Mercedes",
    "model": "C Class"
  },
  {
    "make": "Marcedes",
    "model": "C Class"
  },
  {
    "make": "marcedes-benz",
    "model": "C Class"
  },
  {
    "make": "Marcedes-Benz",
    "model": "C Class"
  },
  {
    "make": "Peugeot",
    "model": "2088"
  },
  {
    "make": "Toyota",
    "model": "Land Cruiser",
    "kind": "bus"
  },
  {
    "make": "VW",
    "model": "new-gollf"
  },
  {
    "input": "nope nope"
  },
  {
    "input": "vw golf"
  },
  {
    "input": "Volkswagen Golf"
  },
  {
    "input": "vw rabbit"
  },
  {
    "input": "alfa romeo 1750gtv"
  },
  {
    "input": "Citroën C3"
  },
  {
    "input": "citroen c3"
  },
  {
    "input": "citroen c3 aircross 1.2"
  },
  {
    "input": "citroen c3 1.2 puretech"
  },
  {
    "input": "ford mustang mach-e gt"
  },
  {
    "input": "ford mustang 5.0 v8"
  },
  {
    "input": "mercedes benz c-class 220d"
  },
  {
    "input": "merc c class"
  },
  {
    "input": "seat leon"
  },
  {
    "input": "dacia sandero stepway 0.9 tce"
  },
  {
    "input": "volkswagen"
  },
  {
    "input": "delorean dmc-12"
  },
  {
    "input": "malaga"
  },
  {
    "input": "Málaga"
  },
  {
    "input": "seat malaga"
  },
  {
    "input": "mercedes benz sprinter"
  },
  {
    "input": "aixam mega"
  },
  {
    "input": "toyota land cruiser prado 150"
  },
  {
    "input": "toyota land cruiser 300 gr sport"
  },
  {
    "input": "landrover defender"
  },
  {
    "input": "range rover defender"
  },
  {
    "input": "Tin Lizzie"
  },
  {
    "input": "car/volkswagen/golf",
    "kind": "van"
  },
  {
    "make": "Delorean",
    "model": "Dmc-12"
  },
  {
    "make": "Acra",
    "model": "Alpha"
  },
  {
    "input": "marcedes-benz gla"
  },
  {
    "input": "MARCEDES-BENZ gla"
  },
  {
    "input": "Marcedes-Benz gla"
  },
  {
    "input": "VW gollf-plus"
  },
  {
    "input": "VW Golf-Plus"
  },
  {
    "make": "Chevrolet",
    "model": "v ette",
    "kind": "car"
  },
  {
    "make": "Landrover",
    "model": "Discovery",
    "kind": "car"
  }
]
JSON
node <<'JS'
const fs = require('fs'), path = require('path')
const { VehiclesDB } = require(path.join(process.env.JS_SDK, 'index.cjs'))
const p = fs.statSync(process.env.ROOT).isDirectory() ? path.join(process.env.ROOT, 'dist/vehicles.json') : process.env.ROOT
const db = new VehiclesDB({fetch: async url => { if (!url.endsWith('/dist/vehicles.json')) throw Error(url); return new Response(fs.readFileSync(p)) }})
;(async () => {
 const results = []
 for (const c of JSON.parse(fs.readFileSync(process.env.CASES))) {
   const r = c.make ? await db.modelMatch(c.make, c.model, {kind:c.kind}) : await db.resolve(c.input, {kind:c.kind})
   results.push([c, r ? {id:r.id, method:r.method, confidence:r.confidence, via:r.via, ambiguous:r.ambiguous, candidates:r.candidates.map(m=>m.id).sort()} : null])
 }
 fs.writeFileSync(process.env.JS_OUT, JSON.stringify(results))
})().catch(e=>{console.error(e);process.exit(1)})
JS
"$PY" <<'PY'
import os, sys, json
sys.path.insert(0, os.path.join(os.environ['PY_SDK'], 'src'))
from vehiclesdb import VehiclesDB
p = os.environ['ROOT']
if os.path.isdir(p): p = os.path.join(p, 'dist/vehicles.json')
with open(p, 'rb') as f: data = f.read()
def transport(url, headers):
    assert url.endswith('/dist/vehicles.json'), url
    return 200, data
db = VehiclesDB(transport=transport)
results = []
with open(os.environ['CASES']) as f: cases = json.load(f)
for c in cases:
    r = db.model_match(c['make'], c['model'], kind=c.get('kind')) if 'make' in c else db.resolve(c['input'], kind=c.get('kind'))
    results.append([c, dict(id=r.id, method=r.method, confidence=r.confidence, via=r.via, ambiguous=r.ambiguous, candidates=sorted(m.id for m in r.candidates)) if r else None])
with open(os.environ['PY_OUT'], 'w') as f: json.dump(results, f)
with open(os.environ['JS_OUT']) as f: js = json.load(f)
for a, b in zip(js, results):
    if a != b:
        print('PARITY FAILED', a, b)
        sys.exit(1)
assert len(js) == len(results)
print('PARITY OK — %d cases (%d pair, %d text), identical ids, methods, confidences, trails and ambiguity' % (len(cases), sum('make' in c for c in cases), sum('input' in c for c in cases)))
for c, r in results:
    print('%s\t%s' % (c.get('input') or c['make'] + ' | ' + c['model'], '%s|%s|%s' % (r['id'] or 'ambiguous', r['method'], r['confidence']) if r else 'null'))
PY
