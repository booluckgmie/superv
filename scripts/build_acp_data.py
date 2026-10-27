#!/usr/bin/env python3
"""Merge a fresh ACP activity export into acp_data.js.

Usage:  python3 scripts/build_acp_data.py EXPORT_FILE [--data acp_data.js]

EXPORT_FILE has one activity per line. Fields are separated by '||' or by tabs, in the
order of the source report:
  ID, Activity Title, Activity Status, Activity For (award stage), Activity Type,
  LOS Category (plan), BP L3 (department), [Activity Owner], Planned Completed Date
The owner column is optional and is never written to the output.

Merge rules
  * ids in the export: title / status / award stage / type / plan / dept / date come from
    the export; stage and scope are kept from the existing record when still consistent
    with the new status.
  * ids new to the dataset: BU comes from the department, scope from keyword matching,
    stage from the status (Ongoing -> 'In progress').
  * ids not in the export are kept unchanged and flagged "stale":1.
"""
import argparse, json, re, sys, datetime, collections

FIELDS = ['id', 'title', 'stage', 'stageStatus', 'awardStage', 'tenderType', 'plan', 'bu', 'dept', 'target', 'scope']
VALID_BU = {'D&GP', 'UP', 'CP&S', 'ECIS'}
PLANS = {'CAP 2026', 'Spillover 2025', 'Unplanned 2026'}
STATUSES = {'Ongoing', 'Yet to Initiate', 'On hold'}
# departments that do not occur in earlier data
EXTRA_BU = {'MPM Procurement': 'UP'}

# same keyword table as inferScope() in index.html; 'Other Services' -> 'General Operations'
SCOPE_RULES = [
    ('Rotating Equipment', ['ROTATING', 'COMPRESSOR', 'PUMP', 'TURBINE', 'MOTOR', 'GEARBOX', 'BEARING']),
    ('Electrical Systems', ['ELECTRICAL', 'SWITCHGEAR', 'TRANSFORMER', 'UPS ', 'MCC', 'SWITCHBOARD', 'RELAY']),
    ('Instrumentation & Control', ['INSTRUMENT', 'ANALYZER', 'GAS DETECT', 'CALIBRAT', 'METERING', 'DCS', 'PLC', 'SCADA', 'CONTROL SYSTEM', 'FLOW METER']),
    ('Civil & Infrastructure', ['CIVIL', 'BUILDING', 'INFRASTRUCTURE', 'ROAD ', 'STRUCTURAL', 'CONSTRUCTION']),
    ('HVAC & Utilities', ['HVAC', 'AIR CONDITIONING', 'VENTILATION']),
    ('Fire & Safety', ['FIRE ', 'SAFETY', 'EXTINGUISHER', 'SPRINKLER', ' ALARM']),
    ('Lifting Equipment', ['CRANE', 'LIFTING', 'HOIST']),
    ('EPCC / Capital Projects', ['EPCC', 'EPCIC', 'EPIC ', 'EPC ', 'ENGINEERING, PROCUREMENT, CONSTRUCTION']),
    ('Drilling & Wells', ['DRILLING', 'RIG ', 'WELLHEAD', 'COMPLETION', 'WORKOVER', 'ABANDONMENT', 'OCTG', 'CASING']),
    ('Chemicals Supply', ['CHEMICAL', 'ACID', 'ALKALI', 'INHIBITOR', 'CATALYST', 'SOLVENT', 'COAGULANT']),
    ('Mechanical Spares', ['GASKET', 'VALVE', 'FITTING', 'SEAL', 'FILTER', 'SPARE PART', 'HOSE', 'FASTENER', 'STUDBOLT']),
    ('Laboratory & Testing', ['LABORATOR', 'REAGENT', 'ANALYTICAL', 'ANALYSIS', 'TESTING']),
    ('IT & Digital', ['SOFTWARE', 'LICENSE', 'DIGITAL', 'IT ', 'ICT', ' SYSTEM', 'PLATFORM', 'APPLICATION', 'DATA ', 'NETWORK', 'CLOUD', 'CYBER']),
    ('Manpower & HR', ['MANPOWER', 'WORKFORCE', 'PERSONNEL', 'STAFFING', 'HUMAN RESOURCE', 'TRAINING']),
    ('Inspection & Integrity', ['INSPECTION', 'NDT', 'INTEGRITY', 'ASSESSMENT', 'MONITORING', 'AUDIT', 'SURVEY']),
    ('Environment & Waste', ['WASTE', 'SCHEDULED WASTE', 'DISPOSAL', 'ENVIRONMENTAL', 'EIA', 'EMISSION']),
    ('Facilities & Support', ['CATERING', 'FOOD', 'JANITORIAL', 'HOUSEKEEPING', 'CLEANING', 'LANDSCAPING', 'PEST CONTROL', 'CANTEEN']),
    ('Transportation & Logistics', ['TRANSPORT', 'VEHICLE', 'VESSEL', 'MARINE', 'HELICOPTER', 'AVIATION', 'SHUTTLE', 'CHARTER', 'BOAT']),
    ('Scaffolding & Coating', ['SCAFFOLDING', 'INSULATION', 'COATING', 'PAINTING', 'BLASTING']),
    ('Turnaround & Shutdown', ['TURNAROUND', 'SHUTDOWN', ' TA 20', 'TURNAROUND MAIN']),
    ('Security Services', ['SECURITY', 'GUARD ', 'SURVEILLANCE', 'CCTV']),
    ('Medical & Health', ['MEDICAL', 'HEALTH', 'CLINIC', 'PARAMEDIC', 'AMBULANCE']),
    ('Technical Consultancy', ['CONSULTANCY', 'ADVISORY', 'STUDY', 'ENGINEERING SERVICE', 'TECHNICAL SERVICE']),
    ('Decommissioning & Disposal', ['SCRAP', 'DECOMMISSION', 'DEMOLITION']),
    ('Lubricants & Oils', ['LUBRICAN', 'LUBE OIL', 'OIL ANALYSIS']),
    ('Subsea & Pipelines', ['SUBSEA', 'SURF ', 'PIPELINE', 'FLOWLINE', 'RISER', 'UMBILICAL']),
    ('Materials & Supplies', ['SUPPLY AND DELIVERY', 'PRICE AGREEMENT FOR SUPPLY']),
]


def infer_scope(title):
    t = title.upper()
    for scope, keys in SCOPE_RULES:
        if any(k in t for k in keys):
            return scope
    return 'General Operations'


def clean_title(t):
    t = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), t)  # literal "–" artefacts
    t = t.replace('\\"', '"').replace('\\n', ' ')
    t = t.strip().strip('"')
    return re.sub(r'\s+', ' ', t).strip()


def read_export(path):
    rows = []
    for n, line in enumerate(open(path, encoding='utf-8'), 1):
        line = line.rstrip('\n')
        if not line.strip():
            continue
        f = [x.strip() for x in (line.split('||') if '||' in line else line.split('\t'))]
        if len(f) == 9:
            del f[7]  # drop owner
        if len(f) != 8:
            sys.exit(f'{path}:{n}: expected 8 or 9 fields, got {len(f)}')
        rec = dict(zip(['id', 'title', 'status', 'awardStage', 'tenderType', 'plan', 'dept', 'target'], f))
        rec['title'] = clean_title(rec['title'])
        if not re.fullmatch(r'\d{4}-\d{4,6}', rec['id']):
            sys.exit(f'{path}:{n}: bad id {rec["id"]!r}')
        if rec['status'] not in STATUSES:
            sys.exit(f'{path}:{n}: unknown status {rec["status"]!r}')
        if rec['plan'] not in PLANS:
            sys.exit(f'{path}:{n}: unknown plan {rec["plan"]!r}')
        if rec['target']:
            datetime.datetime.strptime(rec['target'], '%d/%m/%Y')
        rows.append(rec)
    ids = [r['id'] for r in rows]
    dup = [k for k, c in collections.Counter(ids).items() if c > 1]
    if dup:
        sys.exit(f'duplicate ids in export: {dup[:10]}')
    return rows


def read_data(path):
    s = open(path, encoding='utf-8').read()
    i = s.index('const ACP_DATA = ') + len('const ACP_DATA = ')
    return json.loads(s[i:s.rindex(']') + 1])


def repair_shifted(x):
    """Rows whose quoted title swallowed a field separator are shifted one column to the right."""
    if x['stage'] != '\\"' and x['plan'] in PLANS and x['bu'] in VALID_BU:
        return x
    if x['stage'] == '\\"':  # 2026-0548 pattern: title fragment + '"' + fields shifted by one
        return dict(id=x['id'], title=x['title'], stage=x['stageStatus'], stageStatus=x['awardStage'],
                    awardStage=x['tenderType'], tenderType=x['plan'], plan=x['bu'], bu=x['dept'],
                    dept=x['target'], target='', scope=x['scope'])
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('export')
    ap.add_argument('--data', default='acp_data.js')
    a = ap.parse_args()

    new = read_export(a.export)
    old = [repair_shifted(x) for x in read_data(a.data)]
    O = {x['id']: x for x in old}
    dept_bu = {x['dept']: x['bu'] for x in old if x['bu'] in VALID_BU and x['dept'] not in VALID_BU}
    dept_bu.update(EXTRA_BU)

    out, stats = [], collections.Counter()
    seen = set()
    for n in new:
        seen.add(n['id'])
        o = O.get(n['id'])
        if n['dept'] not in dept_bu:
            sys.exit(f'no BU mapping for department {n["dept"]!r}')
        st = n['status']
        if o:
            keep = o['stage'] not in ('Yet to Initiate', 'On hold') and st == 'Ongoing'
            stage = o['stage'] if keep else ('In progress' if st == 'Ongoing' else st)
            if o['stage'] == 'In progress' and st != 'Ongoing':
                stage = st
            scope = o['scope']
            stats['updated'] += 1
        else:
            stage = 'In progress' if st == 'Ongoing' else st
            scope = infer_scope(n['title'])
            stats['added'] += 1
        out.append(dict(id=n['id'], title=n['title'], stage=stage, stageStatus=st, awardStage=n['awardStage'],
                        tenderType=n['tenderType'], plan=n['plan'], bu=dept_bu[n['dept']], dept=n['dept'],
                        target=n['target'], scope=scope))
    for x in old:
        if x['id'] not in seen:
            y = dict(x, title=clean_title(x['title']))
            y['stale'] = 1
            out.append(y)
            stats['stale'] += 1
    out.sort(key=lambda r: r['id'], reverse=True)

    head = ('// ACP 2026 — Annual Contract Plan activities\n'
            f'// {len(out)} activities ({stats["updated"] + stats["added"]} from the latest export, {stats["stale"]} carried over and flagged "stale")\n'
            '// Fields: id, title, stage, stageStatus, awardStage, tenderType, plan, bu, dept, target, scope[, stale]\n'
            '// Rebuild with: python3 scripts/build_acp_data.py <export file>\n\n')
    with open(a.data, 'w', encoding='utf-8') as f:
        f.write(head + 'const ACP_DATA = ' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n')
    print(dict(stats), 'total', len(out))


if __name__ == '__main__':
    main()
