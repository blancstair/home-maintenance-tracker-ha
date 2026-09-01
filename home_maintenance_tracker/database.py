"""SQLite persistence and fictional demonstration data."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


DATA_DIR = Path(os.environ.get("HMT_DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "home_maintenance.sqlite3"
ATTACHMENT_DIR = DATA_DIR / "attachments"

STANDARD_FIELDS = [
    {"key": "category", "label": "Category / type"},
    {"key": "manufacturer", "label": "Manufacturer"},
    {"key": "model", "label": "Model number"},
    {"key": "serial", "label": "Serial number"},
    {"key": "part_number", "label": "Part number"},
    {"key": "lot_number", "label": "Lot number"},
    {"key": "asset_tag", "label": "Asset / tag number"},
    {"key": "physical_location", "label": "Physical location"},
    {"key": "purchase_date", "label": "Purchase date"},
    {"key": "in_service_date", "label": "Installation / in-service date"},
    {"key": "vendor_installer", "label": "Vendor / installer"},
    {"key": "warranty_expiration", "label": "Warranty expiration"},
]


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    ensure_directories()
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextmanager
def transaction():
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES assets(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    archived INTEGER NOT NULL DEFAULT 0,
    archived_at TEXT,
    replaced_by_id TEXT REFERENCES assets(id) ON DELETE SET NULL,
    replaced_from_id TEXT REFERENCES assets(id) ON DELETE SET NULL,
    is_sample INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_parent ON assets(parent_id);
CREATE INDEX IF NOT EXISTS idx_assets_archived ON assets(archived);

CREATE TABLE IF NOT EXISTS remarks (
    id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    category TEXT NOT NULL CHECK(category IN ('preventive','corrective','observation','lifecycle')),
    work_date TEXT NOT NULL,
    entry_timestamp TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    source_id TEXT,
    is_sample INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_remarks_asset ON remarks(asset_id, work_date DESC);

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    owner_type TEXT NOT NULL CHECK(owner_type IN ('asset','remark','task','completion')),
    owner_id TEXT NOT NULL,
    category TEXT NOT NULL,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE,
    content_type TEXT,
    size_bytes INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL,
    is_sample INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_attachments_owner ON attachments(owner_type, owner_id);

CREATE TABLE IF NOT EXISTS meters (
    id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    unit TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    archived_at TEXT,
    is_sample INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meter_readings (
    id TEXT PRIMARY KEY,
    meter_id TEXT NOT NULL REFERENCES meters(id) ON DELETE CASCADE,
    reading REAL NOT NULL,
    recorded_at TEXT NOT NULL,
    note TEXT,
    is_sample INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meter_readings_meter ON meter_readings(meter_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS maintenance_tasks (
    id TEXT PRIMARY KEY,
    asset_id TEXT REFERENCES assets(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    schedule_type TEXT NOT NULL,
    calendar_value REAL,
    calendar_unit TEXT,
    meter_id TEXT REFERENCES meters(id) ON DELETE SET NULL,
    meter_interval REAL,
    combination_rule TEXT CHECK(combination_rule IN ('first','last') OR combination_rule IS NULL),
    start_date TEXT,
    fixed_month INTEGER,
    fixed_day INTEGER,
    estimated_minutes INTEGER,
    planned_cost REAL,
    last_completed_date TEXT,
    last_completed_reading REAL,
    last_scheduled_due TEXT,
    snoozed_until TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    is_sample INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_asset ON maintenance_tasks(asset_id);

CREATE TABLE IF NOT EXISTS maintenance_completions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES maintenance_tasks(id) ON DELETE CASCADE,
    completion_date TEXT NOT NULL,
    meter_reading REAL,
    outcome TEXT NOT NULL CHECK(outcome IN ('completed','skipped','higher_authority')),
    remark_text TEXT NOT NULL,
    labor_minutes INTEGER,
    total_cost REAL,
    materials_json TEXT NOT NULL DEFAULT '[]',
    replacement_asset_id TEXT REFERENCES assets(id) ON DELETE SET NULL,
    advance_schedule INTEGER NOT NULL DEFAULT 1,
    approved INTEGER NOT NULL DEFAULT 1,
    is_sample INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_completions_task ON maintenance_completions(task_id, completion_date DESC);

CREATE TABLE IF NOT EXISTS notification_log (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES maintenance_tasks(id) ON DELETE CASCADE,
    sent_at TEXT NOT NULL,
    severity TEXT NOT NULL,
    targets_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS qr_tags (
    tag_id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL CHECK(target_type IN ('asset','meter')),
    target_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(target_type, target_id)
);
CREATE INDEX IF NOT EXISTS idx_qr_tags_target ON qr_tags(target_type, target_id);
"""


DEFAULT_SETTINGS = {
    "sample_data_installed": True,
    "dashboard_window_days": 30,
    "theme": "system",
    "notification_services": [],
    "notification_check_hour": 9,
    "qr_android_service": None,
    "setup_complete": False,
}


def initialize_database() -> None:
    ensure_directories()
    with transaction() as db:
        db.executescript(SCHEMA)
        task_columns = {row["name"] for row in db.execute("PRAGMA table_info(maintenance_tasks)")}
        if "last_scheduled_due" not in task_columns:
            db.execute("ALTER TABLE maintenance_tasks ADD COLUMN last_scheduled_due TEXT")
        meter_columns = {row["name"] for row in db.execute("PRAGMA table_info(meters)")}
        if "archived" not in meter_columns:
            db.execute("ALTER TABLE meters ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        if "archived_at" not in meter_columns:
            db.execute("ALTER TABLE meters ADD COLUMN archived_at TEXT")
        db.execute("UPDATE meters SET kind='volume',unit='US gallons' WHERE is_sample=1 AND kind='quantity' AND unit='gallons'")
        for key, value in DEFAULT_SETTINGS.items():
            db.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )
        count = db.execute("SELECT COUNT(*) AS n FROM assets").fetchone()["n"]
        if count == 0 and get_setting(db, "sample_data_installed", True):
            seed_sample_data(db)


def get_setting(db: sqlite3.Connection, key: str, default=None):
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return default


def set_setting(db: sqlite3.Connection, key: str, value) -> None:
    db.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )


def row_to_dict(row: sqlite3.Row | None):
    if row is None:
        return None
    result = dict(row)
    for key in ("attributes_json", "materials_json", "targets_json"):
        if key in result:
            try:
                result[key[:-5] if key.endswith("_json") else key] = json.loads(result.pop(key) or "{}")
            except json.JSONDecodeError:
                result[key[:-5]] = {} if key == "attributes_json" else []
    for key in ("archived", "active", "approved", "advance_schedule", "is_sample"):
        if key in result:
            result[key] = bool(result[key])
    return result


def seed_sample_data(db: sqlite3.Connection) -> None:
    """Insert a large, generic dataset containing no personal identifiers."""
    now = utcnow()
    today = date.today()
    asset_ids: dict[str, str] = {}

    def asset(key: str, name: str, parent: str | None, **attrs) -> str:
        asset_id = f"sample_asset_{key}"
        parent_id = asset_ids.get(parent) if parent else None
        db.execute(
            "INSERT INTO assets(id,parent_id,name,attributes_json,is_sample,created_at,updated_at) "
            "VALUES (?,?,?,?,1,?,?)",
            (asset_id, parent_id, name, json.dumps(attrs), now, now),
        )
        asset_ids[key] = asset_id
        return asset_id

    asset("property", "Sample Property", None, category="Property", in_service_date="2018-06-15")
    for area in ("Kitchen", "Laundry Room", "Mechanical Room", "Garage", "Exterior", "Living Area", "Electrical System", "Plumbing System"):
        asset(area.lower().replace(" ", "_"), area, "property", category="Area")

    asset("dishwasher", "Dishwasher", "kitchen", category="Appliance", manufacturer="Northstar", model="DW-4200", serial="DEMO-DW-000184", in_service_date="2022-04-10", warranty_expiration="2027-04-10")
    for key, name, part in (("dw_pump", "Circulation Pump", "P-420"), ("dw_heater", "Heating Element", "H-88"), ("dw_filter", "Filter Assembly", "F-12"), ("dw_rack", "Upper Rack", "R-420")):
        asset(key, name, "dishwasher", category="Component", manufacturer="Northstar Parts", part_number=part)

    asset("refrigerator", "Refrigerator", "kitchen", category="Appliance", manufacturer="Polar Home", model="RF-28M", serial="DEMO-RF-003211", in_service_date="2021-08-22")
    for key, name in (("fridge_filter", "Water Filter"), ("fridge_ice", "Ice Maker"), ("fridge_comp", "Compressor"), ("fridge_coil", "Condenser Coil")):
        asset(key, name, "refrigerator", category="Component")

    asset("range", "Induction Range", "kitchen", category="Appliance", manufacturer="Hearthline", model="IR-510", serial="DEMO-IR-000751")
    asset("range_filter", "Vent Filter", "range", category="Consumable component", part_number="VF-510")
    asset("microwave", "Microwave", "kitchen", category="Appliance", manufacturer="Hearthline", model="MW-210")

    asset("washer", "Clothes Washer", "laundry_room", category="Appliance", manufacturer="CleanWorks", model="CW-900", serial="DEMO-CW-009310")
    asset("washer_hoses", "Supply Hoses", "washer", category="Component", lot_number="DEMO-LOT-24A")
    asset("washer_filter", "Drain Pump Filter", "washer", category="Component")
    asset("dryer", "Electric Dryer", "laundry_room", category="Appliance", manufacturer="CleanWorks", model="ED-900", serial="DEMO-ED-009188")
    asset("dryer_vent", "Dryer Vent", "dryer", category="Ducting", physical_location="Rear wall")

    asset("water_heater", "Heat Pump Water Heater", "mechanical_room", category="Water heater", manufacturer="AquaTherm", model="HPWH-80", serial="DEMO-WH-004010", in_service_date="2023-02-18", warranty_expiration="2033-02-18")
    for key, name in (("wh_anode", "Anode Rod"), ("wh_filter", "Air Filter"), ("wh_tpr", "Temperature and Pressure Relief Valve"), ("wh_drain", "Drain Valve")):
        asset(key, name, "water_heater", category="Component")

    asset("hvac", "Central HVAC System", "mechanical_room", category="HVAC system", manufacturer="ClimateCraft", model="CC-48H", serial="DEMO-HVAC-11028", in_service_date="2020-09-01")
    asset("air_handler", "Air Handler", "hvac", category="HVAC component", model="AH-48")
    asset("hvac_filter", "Return Air Filter", "air_handler", category="Replaceable filter", part_number="20X25X4")
    asset("outdoor_unit", "Outdoor Heat Pump", "hvac", category="HVAC component", model="HP-48")
    asset("compressor", "Compressor", "outdoor_unit", category="Sealed component", serial="DEMO-COMP-8831")
    asset("condensate", "Condensate Drain", "air_handler", category="Drain component")

    asset("generator", "Standby Generator", "exterior", category="Generator", manufacturer="EverReady Power", model="SG-22", serial="DEMO-GEN-002214", in_service_date="2020-10-11")
    asset("gen_engine", "Generator Engine", "generator", category="Engine", model="V2-999")
    asset("gen_battery", "Starting Battery", "generator", category="Battery", lot_number="DEMO-BAT-26")
    asset("gen_filter", "Oil Filter", "gen_engine", category="Filter", part_number="OF-22")
    asset("gen_air", "Air Filter", "gen_engine", category="Filter", part_number="AF-22")

    asset("garage_vehicle", "Sample Utility Vehicle", "garage", category="Vehicle", manufacturer="Example Motors", model="Trail 2500", serial="DEMO-VIN-00000000001", in_service_date="2021-05-04")
    asset("engine", "Engine", "garage_vehicle", category="Engine", model="V8-Demo")
    asset("engine_oil", "Engine Oil", "engine", category="Fluid", part_number="5W-30")
    asset("transmission", "Transmission", "garage_vehicle", category="Transmission", model="AT-10")
    asset("front_axle", "Front Axle", "garage_vehicle", category="Driveline")
    asset("rear_axle", "Rear Axle", "garage_vehicle", category="Driveline")
    asset("left_headlight", "Left Headlight", "garage_vehicle", category="Lighting")
    asset("left_bulb", "Left Headlight Bulb", "left_headlight", category="Bulb", part_number="LED-9005")
    asset("right_headlight", "Right Headlight", "garage_vehicle", category="Lighting")
    asset("right_bulb", "Right Headlight Bulb", "right_headlight", category="Bulb", part_number="LED-9005")
    asset("vehicle_battery", "Vehicle Battery", "garage_vehicle", category="Battery", lot_number="DEMO-24Q4")
    asset("tires", "Tire Set", "garage_vehicle", category="Tires", lot_number="DEMO-TIRE-26")

    asset("main_panel", "Main Electrical Panel", "electrical_system", category="Electrical distribution", manufacturer="SafeCircuit", model="SC-200", serial="DEMO-PNL-0044")
    for n in range(1, 7):
        asset(f"circuit_{n}", f"Circuit {n:02d}", "main_panel", category="Branch circuit", physical_location=f"Panel position {n}")
    asset("smoke_group", "Smoke and CO Alarm Group", "electrical_system", category="Life safety")
    for n in range(1, 6):
        asset(f"alarm_{n}", f"Alarm {n}", "smoke_group", category="Smoke/CO alarm", model="SC-A10", lot_number="DEMO-ALARM-26")

    asset("main_shutoff", "Main Water Shutoff", "plumbing_system", category="Valve", physical_location="Utility entry")
    asset("pressure_reducer", "Pressure Reducing Valve", "plumbing_system", category="Valve", model="PRV-34")
    asset("sump_pump", "Sump Pump", "plumbing_system", category="Pump", manufacturer="DryHome", model="SP-150", serial="DEMO-SP-331")
    asset("backflow", "Irrigation Backflow Preventer", "plumbing_system", category="Backflow device", model="BF-100")

    asset("television", "Living Area Television", "living_area", category="Television", manufacturer="VisionWorks", model="V-65OLED", serial="DEMO-TV-0019", in_service_date="2024-11-22")
    asset("receiver", "Audio Receiver", "living_area", category="Audio equipment", manufacturer="SoundField", model="AVR-710")
    asset("network", "Home Network", "living_area", category="Network system")
    asset("router", "Gateway Router", "network", category="Network equipment", manufacturer="NetCore", model="GW-10")
    asset("switch", "Main Network Switch", "network", category="Network equipment", manufacturer="NetCore", model="SW-24P")

    # Meters and realistic reading history.
    meters: dict[str, str] = {}

    def meter(key: str, asset_key: str, name: str, kind: str, unit: str, start: float, daily: float):
        meter_id = f"sample_meter_{key}"
        meters[key] = meter_id
        db.execute(
            "INSERT INTO meters(id,asset_id,name,kind,unit,archived,archived_at,is_sample,created_at) VALUES (?,?,?,?,?,0,NULL,1,?)",
            (meter_id, asset_ids[asset_key], name, kind, unit, now),
        )
        for days_ago in (180, 120, 60, 30, 7, 0):
            value = round(start + (180 - days_ago) * daily, 1)
            recorded = datetime.now(timezone.utc) - timedelta(days=days_ago)
            db.execute(
                "INSERT INTO meter_readings VALUES (?,?,?,?,?,1,?)",
                (f"sample_reading_{key}_{days_ago}", meter_id, value, recorded.replace(microsecond=0).isoformat(), "Sample reading", now),
            )

    meter("vehicle_miles", "garage_vehicle", "Odometer", "mileage", "miles", 38250, 24.2)
    meter("generator_hours", "generator", "Engine Hours", "runtime", "hours", 121.0, 0.16)
    meter("generator_starts", "generator", "Generator Starts", "cycles", "starts", 88, 0.08)
    meter("dishwasher_cycles", "dishwasher", "Wash Cycles", "cycles", "cycles", 710, 0.8)
    meter("water_gallons", "water_heater", "Hot Water Throughput", "volume", "US gallons", 91000, 64)

    def task(key: str, asset_key: str | None, title: str, *, schedule_type="calendar", calendar_value=None, calendar_unit=None, meter_key=None, meter_interval=None, combination_rule=None, days_since=0, start_offset=0, minutes=None, cost=None):
        task_id = f"sample_task_{key}"
        last_date = today - timedelta(days=days_since) if days_since else None
        last_reading = None
        if meter_key and days_since:
            row = db.execute("SELECT reading FROM meter_readings WHERE meter_id=? ORDER BY recorded_at DESC LIMIT 1", (meters[meter_key],)).fetchone()
            last_reading = max(0, row["reading"] - (meter_interval or 0) * 0.65)
        db.execute(
            """INSERT INTO maintenance_tasks(
                id,asset_id,title,description,schedule_type,calendar_value,calendar_unit,meter_id,meter_interval,
                combination_rule,start_date,estimated_minutes,planned_cost,last_completed_date,last_completed_reading,
                active,is_sample,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
            (task_id, asset_ids.get(asset_key) if asset_key else None, title, "Fictional demonstration task.", schedule_type,
             calendar_value, calendar_unit, meters.get(meter_key), meter_interval, combination_rule,
             (today + timedelta(days=start_offset)).isoformat(), minutes, cost, last_date.isoformat() if last_date else None,
             last_reading, 1, now, now),
        )
        return task_id

    task("hvac_filter", "hvac_filter", "Replace return air filter", calendar_value=3, calendar_unit="months", days_since=78, minutes=10, cost=24)
    task("hvac_service", "hvac", "Seasonal HVAC inspection", schedule_type="seasonal", calendar_value=6, calendar_unit="months", days_since=170, minutes=90)
    task("condensate", "condensate", "Flush condensate drain", calendar_value=6, calendar_unit="months", days_since=198, minutes=30)
    task("generator_exercise", "generator", "Verify generator exercise cycle", calendar_value=1, calendar_unit="weeks", days_since=8, minutes=15)
    task("generator_oil", "gen_engine", "Change generator oil and filter", schedule_type="combined", calendar_value=1, calendar_unit="years", meter_key="generator_hours", meter_interval=100, combination_rule="first", days_since=310, minutes=75, cost=48)
    task("generator_air", "gen_air", "Inspect generator air filter", schedule_type="meter", meter_key="generator_hours", meter_interval=50, days_since=110, minutes=15)
    task("vehicle_oil", "engine", "Change engine oil and filter", schedule_type="combined", calendar_value=12, calendar_unit="months", meter_key="vehicle_miles", meter_interval=7500, combination_rule="first", days_since=215, minutes=60, cost=70)
    task("tires", "tires", "Rotate tires", schedule_type="meter", meter_key="vehicle_miles", meter_interval=7500, days_since=195, minutes=45)
    task("vehicle_battery", "vehicle_battery", "Test battery condition", calendar_value=1, calendar_unit="years", days_since=330, minutes=15)
    task("dishwasher_filter", "dw_filter", "Clean dishwasher filter", calendar_value=1, calendar_unit="months", days_since=37, minutes=10)
    task("dishwasher_deep", "dishwasher", "Run dishwasher cleaning cycle", schedule_type="combined", calendar_value=3, calendar_unit="months", meter_key="dishwasher_cycles", meter_interval=100, combination_rule="first", days_since=70, minutes=10, cost=8)
    task("washer_hoses", "washer_hoses", "Inspect washer supply hoses", calendar_value=6, calendar_unit="months", days_since=120, minutes=10)
    task("dryer_vent", "dryer_vent", "Clean dryer vent", calendar_value=6, calendar_unit="months", days_since=190, minutes=45)
    task("water_heater", "water_heater", "Inspect water heater and relief valve", calendar_value=1, calendar_unit="years", days_since=280, minutes=45)
    task("wh_anode", "wh_anode", "Inspect anode rod", calendar_value=2, calendar_unit="years", days_since=610, minutes=60)
    task("smoke_test", "smoke_group", "Test smoke and CO alarms", calendar_value=1, calendar_unit="months", days_since=26, minutes=20)
    task("alarm_battery", "smoke_group", "Replace alarm batteries", schedule_type="pattern", calendar_value=1, calendar_unit="years", days_since=300, start_offset=35, minutes=25, cost=30)
    task("sump", "sump_pump", "Test sump pump", calendar_value=3, calendar_unit="months", days_since=101, minutes=20)
    task("backflow", "backflow", "Backflow prevention inspection", calendar_value=1, calendar_unit="years", days_since=340, minutes=60)
    task("fridge_coils", "fridge_coil", "Vacuum refrigerator condenser area", calendar_value=6, calendar_unit="months", days_since=142, minutes=30)
    task("range_filter", "range_filter", "Clean range vent filter", calendar_value=1, calendar_unit="months", days_since=18, minutes=15)
    task("main_shutoff", "main_shutoff", "Exercise main water shutoff", calendar_value=6, calendar_unit="months", days_since=179, minutes=10)
    task("warranty", "television", "Review television warranty coverage", schedule_type="one_time", start_offset=21, minutes=10)
    task("general", None, "Review household emergency supplies", calendar_value=6, calendar_unit="months", days_since=155, minutes=45)

    # History gives the reports and item cards meaningful density.
    task_rows = db.execute("SELECT id,asset_id,title,last_completed_date,last_completed_reading FROM maintenance_tasks WHERE is_sample=1 AND last_completed_date IS NOT NULL").fetchall()
    for index, row in enumerate(task_rows):
        completion_id = f"sample_completion_{index}"
        text = f"Completed {row['title'].lower()}. No discrepancies noted in this fictional sample record."
        db.execute(
            "INSERT INTO maintenance_completions VALUES (?,?,?,?,?,?,?,?,?,?,1,1,1,?,?)",
            (completion_id, row["id"], row["last_completed_date"], row["last_completed_reading"], "completed", text,
             15 + (index % 4) * 15, round(8.5 + index * 2.25, 2), json.dumps([]), None, now, now),
        )
        if row["asset_id"]:
            db.execute(
                "INSERT INTO remarks VALUES (?,?,?,?,?,?,?,?,1)",
                (f"sample_remark_task_{index}", row["asset_id"], "preventive", row["last_completed_date"], now, text, "maintenance", completion_id),
            )

    observation_assets = ["dishwasher", "hvac", "generator", "garage_vehicle", "water_heater", "main_panel", "sump_pump", "television"]
    for index, key in enumerate(observation_assets):
        work_date = (today - timedelta(days=14 + index * 17)).isoformat()
        db.execute(
            "INSERT INTO remarks VALUES (?,?,?,?,?,?,?,?,1)",
            (f"sample_observation_{index}", asset_ids[key], "observation", work_date, now,
             "Routine observation entered for demonstration. Equipment appearance and operation were normal.", "manual", None),
        )

    set_setting(db, "sample_data_installed", True)


def delete_sample_data(db: sqlite3.Connection) -> None:
    # Sample root cascades to sample assets, remarks, meters, readings, and linked history.
    db.execute("DELETE FROM notification_log WHERE task_id IN (SELECT id FROM maintenance_tasks WHERE is_sample=1)")
    db.execute("DELETE FROM attachments WHERE is_sample=1")
    db.execute("DELETE FROM maintenance_tasks WHERE is_sample=1")
    # Break the self-referencing hierarchy before the bulk delete. All affected
    # records are sample records, so no user-created relationship is changed.
    db.execute("UPDATE assets SET parent_id=NULL WHERE is_sample=1")
    db.execute("DELETE FROM assets WHERE is_sample=1")
    set_setting(db, "sample_data_installed", False)
