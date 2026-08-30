"""Home Maintenance Tracker Home Assistant app."""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import qrcode
import qrcode.image.svg
from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from database import (
    ATTACHMENT_DIR,
    DATA_DIR,
    DB_PATH,
    STANDARD_FIELDS,
    connect,
    delete_sample_data,
    get_setting,
    initialize_database,
    new_id,
    row_to_dict,
    seed_sample_data,
    set_setting,
    transaction,
    utcnow,
)
from scheduling import enrich_task, parse_date, reminder_days


APP_VERSION = "0.2.0"
STATIC_DIR = Path(__file__).parent / "static"
VALID_ATTACHMENT_CATEGORIES = {"manual", "receipt", "warranty", "diagram", "photograph", "video", "service_record", "other"}
VALID_REMARK_CATEGORIES = {"preventive", "corrective", "observation", "lifecycle"}
VALID_SCHEDULE_TYPES = {"one_time", "calendar", "meter", "combined", "seasonal", "pattern", "condition"}
METER_UNITS = {
    "mileage": ["miles", "kilometers", "nautical miles"],
    "runtime": ["hours", "minutes"],
    "cycles": ["cycles", "starts", "uses", "loads", "operations"],
    "volume": ["US gallons", "Imperial gallons", "liters", "cubic feet", "cubic meters"],
    "energy": ["kWh", "MWh", "therms", "BTU", "megajoules"],
    "mass": ["pounds", "kilograms"],
}

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("HMT_MAX_UPLOAD_MB", "250")) * 1024 * 1024


def payload() -> dict:
    return request.get_json(silent=True) or {}


def require_fields(data: dict, *fields: str) -> None:
    missing = [field for field in fields if data.get(field) in (None, "")]
    if missing:
        abort(400, description=f"Missing required field(s): {', '.join(missing)}")


def validate_meter_definition(kind: str, unit: str) -> tuple[str, str]:
    kind = (kind or "").strip()
    unit = (unit or "").strip()
    if kind not in METER_UNITS:
        abort(400, description="Choose a standard meter type.")
    if unit not in METER_UNITS[kind]:
        abort(400, description="Choose a standard unit for the selected meter type.")
    return kind, unit


def db_row(db, sql: str, values=(), *, required=True):
    row = db.execute(sql, values).fetchone()
    if required and not row:
        abort(404, description="Record not found")
    return row


def json_attributes(data: dict) -> str:
    allowed = {field["key"] for field in STANDARD_FIELDS}
    attrs = data.get("attributes") or {}
    cleaned = {key: str(value).strip() for key, value in attrs.items() if key in allowed and str(value).strip()}
    return json.dumps(cleaned)


def creates_cycle(db, asset_id: str, parent_id: str | None) -> bool:
    cursor = parent_id
    while cursor:
        if cursor == asset_id:
            return True
        row = db.execute("SELECT parent_id FROM assets WHERE id=?", (cursor,)).fetchone()
        cursor = row["parent_id"] if row else None
    return False


def descendants(db, asset_id: str) -> list[str]:
    rows = db.execute(
        "WITH RECURSIVE tree(id) AS (SELECT id FROM assets WHERE parent_id=? UNION ALL "
        "SELECT a.id FROM assets a JOIN tree t ON a.parent_id=t.id) SELECT id FROM tree",
        (asset_id,),
    ).fetchall()
    return [row["id"] for row in rows]


def task_dict(db, row) -> dict:
    task = row_to_dict(row)
    if task.get("asset_id"):
        asset = db.execute("SELECT name FROM assets WHERE id=?", (task["asset_id"],)).fetchone()
        task["asset_name"] = asset["name"] if asset else "Archived or deleted item"
    else:
        task["asset_name"] = "General / unassigned"
    if task.get("meter_id"):
        meter = db.execute("SELECT name,unit,kind FROM meters WHERE id=?", (task["meter_id"],)).fetchone()
        task["meter_definition"] = dict(meter) if meter else None
    return enrich_task(db, task)


def validate_running_total(db, meter_id: str, reading: float, recorded_at: str) -> None:
    previous = db.execute(
        "SELECT reading FROM meter_readings WHERE meter_id=? AND recorded_at<=? ORDER BY recorded_at DESC LIMIT 1",
        (meter_id, recorded_at),
    ).fetchone()
    following = db.execute(
        "SELECT reading FROM meter_readings WHERE meter_id=? AND recorded_at>? ORDER BY recorded_at ASC LIMIT 1",
        (meter_id, recorded_at),
    ).fetchone()
    if previous and reading < float(previous["reading"]):
        abort(400, description="The reading is lower than an earlier running-total reading.")
    if following and reading > float(following["reading"]):
        abort(400, description="The reading is higher than a later running-total reading.")


@app.errorhandler(Exception)
def handle_error(error):
    if isinstance(error, HTTPException):
        return jsonify({"error": error.description}), error.code
    app.logger.exception("Unhandled application error")
    return jsonify({"error": "An unexpected application error occurred."}), 500


@app.get("/")
@app.get("/<path:path>")
def index(path=""):
    if path.startswith("api/"):
        abort(404)
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok", "version": APP_VERSION})


@app.get("/api/bootstrap")
def bootstrap():
    with connect() as db:
        settings = {row["key"]: json.loads(row["value"]) for row in db.execute("SELECT key,value FROM settings")}
        assets = [row_to_dict(row) for row in db.execute("SELECT * FROM assets ORDER BY archived,name")]
        task_rows = db.execute("SELECT * FROM maintenance_tasks WHERE active=1").fetchall()
        tasks = [task_dict(db, row) for row in task_rows]
        window = int(settings.get("dashboard_window_days", 30))
        cutoff = (date.today() + timedelta(days=window)).isoformat()
        due = [task for task in tasks if task["state"] in ("red", "overdue") or (task.get("calendar_due") and task["calendar_due"] <= cutoff) or (task.get("meter_forecast", {}).get("estimated_date") if task.get("meter_forecast") else None) and task["meter_forecast"]["estimated_date"] <= cutoff]
        recent = [row_to_dict(row) for row in db.execute(
            "SELECT mc.*,mt.title,a.name AS asset_name FROM maintenance_completions mc "
            "JOIN maintenance_tasks mt ON mt.id=mc.task_id LEFT JOIN assets a ON a.id=mt.asset_id "
            "ORDER BY mc.completion_date DESC,mc.created_at DESC LIMIT 12"
        )]
        warranties = []
        for asset in assets:
            expiration = asset.get("attributes", {}).get("warranty_expiration")
            if expiration and not asset["archived"]:
                warranties.append({"asset_id": asset["id"], "name": asset["name"], "expiration": expiration})
        warranties.sort(key=lambda item: item["expiration"])
        return jsonify({
            "version": APP_VERSION,
            "meter_units": METER_UNITS,
            "settings": settings,
            "standard_fields": STANDARD_FIELDS,
            "assets": assets,
            "tasks": tasks,
            "dashboard": {
                "overdue": sum(task["state"] in ("red", "overdue") for task in tasks),
                "red": sum(task["state"] == "red" for task in tasks),
                "upcoming": len(due),
                "active_assets": sum(not asset["archived"] for asset in assets),
                "due_tasks": sorted(due, key=lambda item: (0 if item["state"] == "red" else 1 if item["state"] == "overdue" else 2, item.get("calendar_due") or "9999-12-31")),
                "recent": recent,
                "warranties": warranties[:12],
            },
        })


# Assets ---------------------------------------------------------------------

@app.get("/api/assets")
def list_assets():
    include_archived = request.args.get("archived") == "1"
    with connect() as db:
        sql = "SELECT * FROM assets" + ("" if include_archived else " WHERE archived=0") + " ORDER BY name"
        return jsonify([row_to_dict(row) for row in db.execute(sql)])


@app.post("/api/assets")
def create_asset():
    data = payload()
    require_fields(data, "name")
    asset_id = new_id("asset")
    now = utcnow()
    with transaction() as db:
        parent_id = data.get("parent_id") or None
        if parent_id:
            parent = db_row(db, "SELECT archived FROM assets WHERE id=?", (parent_id,))
            if parent["archived"]:
                abort(400, description="An active item cannot be placed under an archived parent.")
        db.execute(
            "INSERT INTO assets(id,parent_id,name,attributes_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (asset_id, parent_id, data["name"].strip(), json_attributes(data), now, now),
        )
        return jsonify(row_to_dict(db_row(db, "SELECT * FROM assets WHERE id=?", (asset_id,)))), 201


@app.get("/api/assets/<asset_id>")
def get_asset(asset_id):
    with connect() as db:
        asset = row_to_dict(db_row(db, "SELECT * FROM assets WHERE id=?", (asset_id,)))
        asset["children"] = [row_to_dict(row) for row in db.execute("SELECT * FROM assets WHERE parent_id=? ORDER BY name", (asset_id,))]
        asset["remarks"] = [row_to_dict(row) for row in db.execute("SELECT * FROM remarks WHERE asset_id=? ORDER BY work_date DESC,entry_timestamp DESC", (asset_id,))]
        for remark in asset["remarks"]:
            remark["attachments"] = [row_to_dict(row) for row in db.execute(
                "SELECT * FROM attachments WHERE owner_type='remark' AND owner_id=? ORDER BY uploaded_at DESC", (remark["id"],)
            )]
        asset["attachments"] = [row_to_dict(row) for row in db.execute("SELECT * FROM attachments WHERE owner_type='asset' AND owner_id=? ORDER BY uploaded_at DESC", (asset_id,))]
        asset["meters"] = []
        for row in db.execute("SELECT * FROM meters WHERE asset_id=? ORDER BY name", (asset_id,)):
            meter = row_to_dict(row)
            meter["readings"] = [row_to_dict(reading) for reading in db.execute("SELECT * FROM meter_readings WHERE meter_id=? ORDER BY recorded_at DESC LIMIT 20", (row["id"],))]
            meter["active_task_count"] = db.execute("SELECT COUNT(*) n FROM maintenance_tasks WHERE meter_id=? AND active=1", (row["id"],)).fetchone()["n"]
            asset["meters"].append(meter)
        asset["tasks"] = [task_dict(db, row) for row in db.execute("SELECT * FROM maintenance_tasks WHERE asset_id=? ORDER BY active DESC,title", (asset_id,))]
        if asset.get("replaced_by_id"):
            linked = db.execute("SELECT id,name FROM assets WHERE id=?", (asset["replaced_by_id"],)).fetchone()
            asset["replaced_by"] = dict(linked) if linked else None
        if asset.get("replaced_from_id"):
            linked = db.execute("SELECT id,name FROM assets WHERE id=?", (asset["replaced_from_id"],)).fetchone()
            asset["replaced_from"] = dict(linked) if linked else None
        return jsonify(asset)


@app.put("/api/assets/<asset_id>")
def update_asset(asset_id):
    data = payload()
    require_fields(data, "name")
    with transaction() as db:
        db_row(db, "SELECT id FROM assets WHERE id=?", (asset_id,))
        db.execute(
            "UPDATE assets SET name=?,attributes_json=?,updated_at=? WHERE id=?",
            (data["name"].strip(), json_attributes(data), utcnow(), asset_id),
        )
        return jsonify(row_to_dict(db_row(db, "SELECT * FROM assets WHERE id=?", (asset_id,))))


@app.post("/api/assets/<asset_id>/move")
def move_asset(asset_id):
    parent_id = payload().get("parent_id") or None
    with transaction() as db:
        row = db_row(db, "SELECT archived,parent_id FROM assets WHERE id=?", (asset_id,))
        if parent_id:
            parent = db_row(db, "SELECT archived FROM assets WHERE id=?", (parent_id,))
            if parent["archived"] and not row["archived"]:
                abort(400, description="An active item cannot be moved under an archived parent.")
        if creates_cycle(db, asset_id, parent_id):
            abort(400, description="That move would place an item inside itself.")
        old_parent = row["parent_id"]
        db.execute("UPDATE assets SET parent_id=?,updated_at=? WHERE id=?", (parent_id, utcnow(), asset_id))
        db.execute(
            "INSERT INTO remarks VALUES (?,?,?,?,?,?,?,?,0)",
            (new_id("remark"), asset_id, "lifecycle", date.today().isoformat(), utcnow(), "Item moved to a different parent in the material hierarchy.", "system", old_parent),
        )
        return jsonify({"ok": True})


def archive_subtree(db, root_id: str) -> None:
    ids = [root_id] + descendants(db, root_id)
    now = utcnow()
    for item_id in ids:
        db.execute("UPDATE assets SET archived=1,archived_at=?,updated_at=? WHERE id=?", (now, now, item_id))


@app.post("/api/assets/<asset_id>/archive")
def archive_asset(asset_id):
    data = payload()
    decisions = data.get("children") or {}
    reason = (data.get("reason") or "Item archived.").strip()
    with transaction() as db:
        db_row(db, "SELECT id FROM assets WHERE id=?", (asset_id,))
        children = db.execute("SELECT id FROM assets WHERE parent_id=? AND archived=0", (asset_id,)).fetchall()
        for child in children:
            decision = decisions.get(child["id"])
            if not decision or decision.get("action") not in ("archive", "move"):
                abort(400, description="Every active child must be archived or moved before continuing.")
            if decision["action"] == "move":
                new_parent = decision.get("parent_id") or None
                if new_parent == asset_id or creates_cycle(db, child["id"], new_parent):
                    abort(400, description="A child has an invalid destination.")
                if new_parent:
                    parent = db_row(db, "SELECT archived FROM assets WHERE id=?", (new_parent,))
                    if parent["archived"]:
                        abort(400, description="A child cannot be moved under an archived parent.")
                db.execute("UPDATE assets SET parent_id=?,updated_at=? WHERE id=?", (new_parent, utcnow(), child["id"]))
            else:
                archive_subtree(db, child["id"])
        archive_subtree(db, asset_id)
        db.execute(
            "INSERT INTO remarks VALUES (?,?,?,?,?,?,?,?,0)",
            (new_id("remark"), asset_id, "lifecycle", date.today().isoformat(), utcnow(), reason, "system", None),
        )
        return jsonify({"ok": True})


@app.post("/api/assets/<asset_id>/restore")
def restore_asset(asset_id):
    with transaction() as db:
        asset = db_row(db, "SELECT parent_id FROM assets WHERE id=?", (asset_id,))
        if asset["parent_id"]:
            parent = db_row(db, "SELECT archived FROM assets WHERE id=?", (asset["parent_id"],))
            if parent["archived"]:
                abort(400, description="Restore or move the parent before restoring this item.")
        db.execute("UPDATE assets SET archived=0,archived_at=NULL,updated_at=? WHERE id=?", (utcnow(), asset_id))
        return jsonify({"ok": True})


@app.delete("/api/assets/<asset_id>")
def delete_asset(asset_id):
    if request.args.get("confirm") != "permanent":
        abort(400, description="Permanent deletion requires explicit confirmation.")
    with transaction() as db:
        db_row(db, "SELECT id FROM assets WHERE id=?", (asset_id,))
        asset_ids = [asset_id] + descendants(db, asset_id)
        placeholders = ",".join("?" for _ in asset_ids)
        remark_ids = [row["id"] for row in db.execute(f"SELECT id FROM remarks WHERE asset_id IN ({placeholders})", asset_ids)]
        task_ids = [row["id"] for row in db.execute(f"SELECT id FROM maintenance_tasks WHERE asset_id IN ({placeholders})", asset_ids)]
        completion_ids = []
        if task_ids:
            task_marks = ",".join("?" for _ in task_ids)
            completion_ids = [row["id"] for row in db.execute(f"SELECT id FROM maintenance_completions WHERE task_id IN ({task_marks})", task_ids)]
        owners = [("asset", item) for item in asset_ids] + [("remark", item) for item in remark_ids] + [("task", item) for item in task_ids] + [("completion", item) for item in completion_ids]
        for owner_type, owner_id in owners:
            for attachment in db.execute("SELECT id,stored_name FROM attachments WHERE owner_type=? AND owner_id=?", (owner_type, owner_id)):
                path = ATTACHMENT_DIR / attachment["stored_name"]
                if path.exists():
                    path.unlink()
                db.execute("DELETE FROM attachments WHERE id=?", (attachment["id"],))
        if task_ids:
            db.execute(f"DELETE FROM maintenance_tasks WHERE id IN ({','.join('?' for _ in task_ids)})", task_ids)
        # Delete leaves before parents to satisfy the one-parent foreign key.
        for item_id in reversed(asset_ids):
            db.execute("DELETE FROM assets WHERE id=?", (item_id,))
        return jsonify({"ok": True})


@app.post("/api/assets/<asset_id>/replace")
def replace_asset(asset_id):
    data = payload()
    require_fields(data, "name")
    new_asset_id = new_id("asset")
    now = utcnow()
    with transaction() as db:
        old = db_row(db, "SELECT * FROM assets WHERE id=?", (asset_id,))
        db.execute(
            "INSERT INTO assets(id,parent_id,name,attributes_json,replaced_from_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (new_asset_id, old["parent_id"], data["name"].strip(), json_attributes(data), asset_id, now, now),
        )
        for child_id in data.get("move_child_ids", []):
            child = db_row(db, "SELECT parent_id FROM assets WHERE id=?", (child_id,))
            if child["parent_id"] != asset_id:
                abort(400, description="Only direct children can be transferred during replacement.")
            db.execute("UPDATE assets SET parent_id=?,updated_at=? WHERE id=?", (new_asset_id, now, child_id))
        for task_id in data.get("copy_task_ids", []):
            task = db_row(db, "SELECT * FROM maintenance_tasks WHERE id=? AND asset_id=?", (task_id, asset_id))
            columns = [key for key in task.keys() if key not in {"id", "asset_id", "last_completed_date", "last_completed_reading", "snoozed_until", "created_at", "updated_at", "is_sample"}]
            values = [task[key] for key in columns]
            sql = f"INSERT INTO maintenance_tasks(id,asset_id,{','.join(columns)},created_at,updated_at) VALUES ({','.join('?' for _ in range(len(columns)+4))})"
            db.execute(sql, [new_id("task"), new_asset_id, *values, now, now])
        archive_subtree(db, asset_id)
        db.execute("UPDATE assets SET replaced_by_id=? WHERE id=?", (new_asset_id, asset_id))
        reason = (data.get("reason") or "Item replaced.").strip()
        db.execute("INSERT INTO remarks VALUES (?,?,?,?,?,?,?,?,0)", (new_id("remark"), asset_id, "lifecycle", date.today().isoformat(), now, f"{reason} Replaced by {data['name'].strip()}.", "replacement", new_asset_id))
        db.execute("INSERT INTO remarks VALUES (?,?,?,?,?,?,?,?,0)", (new_id("remark"), new_asset_id, "lifecycle", date.today().isoformat(), now, f"Installed as replacement for {old['name']}.", "replacement", asset_id))
        return jsonify({"id": new_asset_id}), 201


@app.get("/api/assets/<asset_id>/qr")
def asset_qr(asset_id):
    target_url = request.args.get("url")
    if not target_url:
        abort(400, description="A target URL is required.")
    with connect() as db:
        db_row(db, "SELECT id FROM assets WHERE id=?", (asset_id,))
    image = qrcode.make(target_url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=3)
    output = io.BytesIO()
    image.save(output)
    return Response(output.getvalue(), mimetype="image/svg+xml")


# Remarks and attachments -----------------------------------------------------

@app.post("/api/assets/<asset_id>/remarks")
def create_remark(asset_id):
    data = payload()
    require_fields(data, "category", "work_date", "text")
    if data["category"] not in VALID_REMARK_CATEGORIES - {"lifecycle"}:
        abort(400, description="Invalid remark category.")
    with transaction() as db:
        db_row(db, "SELECT id FROM assets WHERE id=?", (asset_id,))
        remark_id = new_id("remark")
        db.execute(
            "INSERT INTO remarks VALUES (?,?,?,?,?,?,?,?,0)",
            (remark_id, asset_id, data["category"], data["work_date"], utcnow(), data["text"].strip(), "manual", None),
        )
        return jsonify(row_to_dict(db_row(db, "SELECT * FROM remarks WHERE id=?", (remark_id,)))), 201


@app.put("/api/remarks/<remark_id>")
def update_remark(remark_id):
    data = payload()
    require_fields(data, "category", "work_date", "text")
    if data["category"] not in VALID_REMARK_CATEGORIES:
        abort(400, description="Invalid remark category.")
    with transaction() as db:
        db_row(db, "SELECT id FROM remarks WHERE id=?", (remark_id,))
        db.execute("UPDATE remarks SET category=?,work_date=?,text=? WHERE id=?", (data["category"], data["work_date"], data["text"].strip(), remark_id))
        return jsonify(row_to_dict(db_row(db, "SELECT * FROM remarks WHERE id=?", (remark_id,))))


@app.delete("/api/remarks/<remark_id>")
def delete_remark(remark_id):
    with transaction() as db:
        db.execute("DELETE FROM attachments WHERE owner_type='remark' AND owner_id=?", (remark_id,))
        result = db.execute("DELETE FROM remarks WHERE id=?", (remark_id,))
        if not result.rowcount:
            abort(404, description="Remark not found.")
        return jsonify({"ok": True})


def owner_exists(db, owner_type: str, owner_id: str) -> bool:
    table = {"asset": "assets", "remark": "remarks", "task": "maintenance_tasks", "completion": "maintenance_completions"}.get(owner_type)
    if not table:
        return False
    return bool(db.execute(f"SELECT 1 FROM {table} WHERE id=?", (owner_id,)).fetchone())


@app.post("/api/attachments")
def upload_attachment():
    uploaded = request.files.get("file")
    owner_type = request.form.get("owner_type", "")
    owner_id = request.form.get("owner_id", "")
    category = request.form.get("category", "other")
    if not uploaded or not uploaded.filename:
        abort(400, description="Choose a file to upload.")
    if category not in VALID_ATTACHMENT_CATEGORIES:
        abort(400, description="Invalid attachment category.")
    with transaction() as db:
        if not owner_exists(db, owner_type, owner_id):
            abort(400, description="Invalid attachment owner.")
        attachment_id = new_id("attachment")
        safe_name = secure_filename(uploaded.filename) or "attachment"
        stored_name = f"{attachment_id}_{safe_name}"
        target = ATTACHMENT_DIR / stored_name
        uploaded.save(target)
        size = target.stat().st_size
        db.execute(
            "INSERT INTO attachments VALUES (?,?,?,?,?,?,?,?,?,0)",
            (attachment_id, owner_type, owner_id, category, uploaded.filename, stored_name, uploaded.mimetype, size, utcnow()),
        )
        return jsonify(row_to_dict(db_row(db, "SELECT * FROM attachments WHERE id=?", (attachment_id,)))), 201


@app.get("/api/attachments/<attachment_id>")
def download_attachment(attachment_id):
    with connect() as db:
        row = db_row(db, "SELECT * FROM attachments WHERE id=?", (attachment_id,))
        path = ATTACHMENT_DIR / row["stored_name"]
        if not path.exists():
            abort(404, description="Attachment file is missing.")
        return send_file(path, as_attachment=request.args.get("download") == "1", download_name=row["original_name"], mimetype=row["content_type"])


@app.delete("/api/attachments/<attachment_id>")
def delete_attachment(attachment_id):
    with transaction() as db:
        row = db_row(db, "SELECT stored_name FROM attachments WHERE id=?", (attachment_id,))
        path = ATTACHMENT_DIR / row["stored_name"]
        db.execute("DELETE FROM attachments WHERE id=?", (attachment_id,))
        if path.exists():
            path.unlink()
        return jsonify({"ok": True})


# Meters ---------------------------------------------------------------------

@app.get("/api/meters")
def list_meters():
    with connect() as db:
        include_archived = request.args.get("include_archived") == "1"
        rows = db.execute(
            "SELECT m.*,a.name AS asset_name FROM meters m JOIN assets a ON a.id=m.asset_id "
            "WHERE a.archived=0 AND (?=1 OR m.archived=0) ORDER BY m.archived,a.name,m.name",
            (1 if include_archived else 0,),
        ).fetchall()
        result = []
        for row in rows:
            meter = row_to_dict(row)
            latest = db.execute("SELECT * FROM meter_readings WHERE meter_id=? ORDER BY recorded_at DESC LIMIT 1", (row["id"],)).fetchone()
            meter["latest"] = row_to_dict(latest)
            meter["reading_count"] = db.execute("SELECT COUNT(*) n FROM meter_readings WHERE meter_id=?", (row["id"],)).fetchone()["n"]
            meter["task_count"] = db.execute("SELECT COUNT(*) n FROM maintenance_tasks WHERE meter_id=?", (row["id"],)).fetchone()["n"]
            meter["active_task_count"] = db.execute("SELECT COUNT(*) n FROM maintenance_tasks WHERE meter_id=? AND active=1", (row["id"],)).fetchone()["n"]
            result.append(meter)
        return jsonify(result)


@app.post("/api/meters")
def create_meter():
    data = payload()
    require_fields(data, "asset_id", "name", "kind", "unit")
    kind, unit = validate_meter_definition(data["kind"], data["unit"])
    meter_id = new_id("meter")
    with transaction() as db:
        db_row(db, "SELECT id FROM assets WHERE id=?", (data["asset_id"],))
        db.execute(
            "INSERT INTO meters(id,asset_id,name,kind,unit,archived,archived_at,is_sample,created_at) VALUES (?,?,?,?,?,0,NULL,0,?)",
            (meter_id, data["asset_id"], data["name"].strip(), kind, unit, utcnow()),
        )
        if data.get("initial_reading") not in (None, ""):
            reading = float(data["initial_reading"])
            if reading < 0:
                abort(400, description="A running-total reading cannot be negative.")
            recorded_at = data.get("initial_recorded_at") or utcnow()
            db.execute(
                "INSERT INTO meter_readings VALUES (?,?,?,?,?,0,?)",
                (new_id("reading"), meter_id, reading, recorded_at, "Initial reading", utcnow()),
            )
        return jsonify(row_to_dict(db_row(db, "SELECT * FROM meters WHERE id=?", (meter_id,)))), 201


@app.put("/api/meters/<meter_id>")
def update_meter(meter_id):
    data = payload()
    require_fields(data, "name", "kind", "unit")
    kind, unit = validate_meter_definition(data["kind"], data["unit"])
    with transaction() as db:
        db_row(db, "SELECT id FROM meters WHERE id=?", (meter_id,))
        db.execute("UPDATE meters SET name=?,kind=?,unit=? WHERE id=?", (data["name"].strip(), kind, unit, meter_id))
        return jsonify(row_to_dict(db_row(db, "SELECT * FROM meters WHERE id=?", (meter_id,))))


@app.post("/api/meters/<meter_id>/archive")
def archive_meter(meter_id):
    with transaction() as db:
        meter = db_row(db, "SELECT * FROM meters WHERE id=?", (meter_id,))
        active_tasks = db.execute("SELECT COUNT(*) n FROM maintenance_tasks WHERE meter_id=? AND active=1", (meter_id,)).fetchone()["n"]
        if active_tasks:
            abort(409, description="This meter is used by active maintenance tasks. Reassign, change, or cancel those tasks first.")
        db.execute("UPDATE meters SET archived=1,archived_at=? WHERE id=?", (utcnow(), meter_id))
        return jsonify({"ok": True, "meter_id": meter["id"]})


@app.post("/api/meters/<meter_id>/restore")
def restore_meter(meter_id):
    with transaction() as db:
        db_row(db, "SELECT id FROM meters WHERE id=?", (meter_id,))
        db.execute("UPDATE meters SET archived=0,archived_at=NULL WHERE id=?", (meter_id,))
        return jsonify({"ok": True})


@app.delete("/api/meters/<meter_id>")
def delete_meter(meter_id):
    with transaction() as db:
        db_row(db, "SELECT id FROM meters WHERE id=?", (meter_id,))
        readings = db.execute("SELECT COUNT(*) n FROM meter_readings WHERE meter_id=?", (meter_id,)).fetchone()["n"]
        tasks = db.execute("SELECT COUNT(*) n FROM maintenance_tasks WHERE meter_id=?", (meter_id,)).fetchone()["n"]
        if readings or tasks:
            abort(409, description="Meters with readings or linked maintenance tasks must be archived instead of deleted.")
        db.execute("DELETE FROM meters WHERE id=?", (meter_id,))
        return jsonify({"ok": True})


@app.get("/api/meters/<meter_id>/qr")
def meter_qr(meter_id):
    target_url = request.args.get("url")
    if not target_url:
        abort(400, description="A target URL is required.")
    with connect() as db:
        db_row(db, "SELECT id FROM meters WHERE id=?", (meter_id,))
    image = qrcode.make(target_url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=3)
    output = io.BytesIO()
    image.save(output)
    return Response(output.getvalue(), mimetype="image/svg+xml")


@app.post("/api/meters/readings")
def add_meter_readings():
    data = payload()
    readings = data.get("readings") or []
    if not readings:
        abort(400, description="At least one reading is required.")
    created = []
    with transaction() as db:
        for item in readings:
            require_fields(item, "meter_id", "reading", "recorded_at")
            meter = db_row(db, "SELECT id,archived FROM meters WHERE id=?", (item["meter_id"],))
            if meter["archived"]:
                abort(400, description="Archived meters cannot receive new readings.")
            reading = float(item["reading"])
            validate_running_total(db, item["meter_id"], reading, item["recorded_at"])
            reading_id = new_id("reading")
            db.execute("INSERT INTO meter_readings VALUES (?,?,?,?,?,0,?)", (reading_id, item["meter_id"], reading, item["recorded_at"], (item.get("note") or "").strip(), utcnow()))
            created.append(reading_id)
        return jsonify({"created": created}), 201


# Maintenance ----------------------------------------------------------------

def task_values(data: dict) -> dict:
    require_fields(data, "title", "schedule_type")
    if data["schedule_type"] not in VALID_SCHEDULE_TYPES:
        abort(400, description="Invalid schedule type.")
    result = {
        "asset_id": data.get("asset_id") or None,
        "title": data["title"].strip(),
        "description": (data.get("description") or "").strip(),
        "schedule_type": data["schedule_type"],
        "calendar_value": float(data["calendar_value"]) if data.get("calendar_value") not in (None, "") else None,
        "calendar_unit": data.get("calendar_unit") or None,
        "meter_id": data.get("meter_id") or None,
        "meter_interval": float(data["meter_interval"]) if data.get("meter_interval") not in (None, "") else None,
        "combination_rule": data.get("combination_rule") or None,
        "start_date": data.get("start_date") or date.today().isoformat(),
        "fixed_month": int(data["fixed_month"]) if data.get("fixed_month") else None,
        "fixed_day": int(data["fixed_day"]) if data.get("fixed_day") else None,
        "estimated_minutes": int(data["estimated_minutes"]) if data.get("estimated_minutes") else None,
        "planned_cost": float(data["planned_cost"]) if data.get("planned_cost") else None,
    }
    stype = result["schedule_type"]
    if stype in {"calendar", "seasonal", "pattern", "combined"} and not (result["calendar_value"] and result["calendar_unit"]):
        abort(400, description="This schedule requires a calendar interval.")
    if stype in {"meter", "combined"} and not (result["meter_id"] and result["meter_interval"]):
        abort(400, description="This schedule requires a meter and interval.")
    if stype == "combined" and result["combination_rule"] not in {"first", "last"}:
        abort(400, description="Combined schedules require a first/last rule.")
    return result


@app.get("/api/tasks")
def list_tasks():
    with connect() as db:
        sql = "SELECT * FROM maintenance_tasks" + ("" if request.args.get("all") == "1" else " WHERE active=1") + " ORDER BY title"
        return jsonify([task_dict(db, row) for row in db.execute(sql)])


@app.get("/api/tasks/<task_id>")
def get_task(task_id):
    with connect() as db:
        task = task_dict(db, db_row(db, "SELECT * FROM maintenance_tasks WHERE id=?", (task_id,)))
        task["attachments"] = [row_to_dict(row) for row in db.execute(
            "SELECT * FROM attachments WHERE owner_type='task' AND owner_id=? ORDER BY uploaded_at DESC", (task_id,)
        )]
        task["completions"] = [row_to_dict(row) for row in db.execute(
            "SELECT * FROM maintenance_completions WHERE task_id=? ORDER BY completion_date DESC,created_at DESC", (task_id,)
        )]
        return jsonify(task)


@app.post("/api/tasks")
def create_task():
    values = task_values(payload())
    task_id = new_id("task")
    now = utcnow()
    with transaction() as db:
        if values["asset_id"]:
            db_row(db, "SELECT id FROM assets WHERE id=?", (values["asset_id"],))
        if values["meter_id"]:
            meter = db_row(db, "SELECT asset_id,archived FROM meters WHERE id=?", (values["meter_id"],))
            if meter["archived"]:
                abort(400, description="Archived meters cannot be assigned to active maintenance tasks.")
            if values["asset_id"] and meter["asset_id"] != values["asset_id"]:
                abort(400, description="The selected meter belongs to a different item.")
        columns = list(values)
        db.execute(
            f"INSERT INTO maintenance_tasks(id,{','.join(columns)},active,is_sample,created_at,updated_at) VALUES ({','.join('?' for _ in range(len(columns)+5))})",
            [task_id, *[values[key] for key in columns], 1, 0, now, now],
        )
        return jsonify(task_dict(db, db_row(db, "SELECT * FROM maintenance_tasks WHERE id=?", (task_id,)))), 201


@app.put("/api/tasks/<task_id>")
def update_task(task_id):
    values = task_values(payload())
    with transaction() as db:
        db_row(db, "SELECT id FROM maintenance_tasks WHERE id=?", (task_id,))
        if values["asset_id"]:
            db_row(db, "SELECT id FROM assets WHERE id=?", (values["asset_id"],))
        if values["meter_id"]:
            meter = db_row(db, "SELECT asset_id,archived FROM meters WHERE id=?", (values["meter_id"],))
            if meter["archived"]:
                abort(400, description="Archived meters cannot be assigned to active maintenance tasks.")
            if values["asset_id"] and meter["asset_id"] != values["asset_id"]:
                abort(400, description="The selected meter belongs to a different item.")
        assignments = ",".join(f"{key}=?" for key in values)
        db.execute(f"UPDATE maintenance_tasks SET {assignments},updated_at=? WHERE id=?", [*[values[key] for key in values], utcnow(), task_id])
        return jsonify(task_dict(db, db_row(db, "SELECT * FROM maintenance_tasks WHERE id=?", (task_id,))))


@app.post("/api/tasks/<task_id>/snooze")
def snooze_task(task_id):
    until = payload().get("until")
    if not until:
        abort(400, description="Choose a snooze date.")
    with transaction() as db:
        db_row(db, "SELECT id FROM maintenance_tasks WHERE id=?", (task_id,))
        db.execute("UPDATE maintenance_tasks SET snoozed_until=?,updated_at=? WHERE id=?", (until, utcnow(), task_id))
        return jsonify({"ok": True})


@app.post("/api/tasks/<task_id>/cancel")
def cancel_task(task_id):
    reason = (payload().get("reason") or "Maintenance task canceled.").strip()
    with transaction() as db:
        task = db_row(db, "SELECT * FROM maintenance_tasks WHERE id=?", (task_id,))
        db.execute("UPDATE maintenance_tasks SET active=0,snoozed_until=NULL,updated_at=? WHERE id=?", (utcnow(), task_id))
        if task["asset_id"]:
            db.execute("INSERT INTO remarks VALUES (?,?,?,?,?,?,?,?,0)", (
                new_id("remark"), task["asset_id"], "lifecycle", date.today().isoformat(), utcnow(), reason, "system", task_id,
            ))
        return jsonify({"ok": True})


@app.post("/api/tasks/<task_id>/complete")
def complete_task(task_id):
    data = payload()
    require_fields(data, "completion_date", "outcome", "remark_text")
    if data["outcome"] not in {"completed", "skipped", "higher_authority"}:
        abort(400, description="Invalid completion outcome.")
    if data["outcome"] == "higher_authority" and not data.get("replacement_asset_id"):
        abort(400, description="Higher-authority completion must link the replacement or corrective item.")
    completion_id = new_id("completion")
    now = utcnow()
    with transaction() as db:
        task = db_row(db, "SELECT * FROM maintenance_tasks WHERE id=?", (task_id,))
        reading = float(data["meter_reading"]) if data.get("meter_reading") not in (None, "") else None
        if reading is not None and task["meter_id"]:
            reading_time = data["completion_date"] + "T12:00:00+00:00"
            validate_running_total(db, task["meter_id"], reading, reading_time)
            db.execute("INSERT INTO meter_readings VALUES (?,?,?,?,?,0,?)", (new_id("reading"), task["meter_id"], reading, reading_time, f"Maintenance completion {completion_id}", now))
        advance = bool(data.get("advance_schedule", True))
        db.execute(
            "INSERT INTO maintenance_completions VALUES (?,?,?,?,?,?,?,?,?,?,?,1,0,?,?)",
            (completion_id, task_id, data["completion_date"], reading, data["outcome"], data["remark_text"].strip(),
             int(data["labor_minutes"]) if data.get("labor_minutes") else None,
             float(data["total_cost"]) if data.get("total_cost") else None,
             json.dumps(data.get("materials") or []), data.get("replacement_asset_id") or None, int(advance), now, now),
        )
        # Completed-by-higher-authority explicitly resets ordinary periodicity.
        resets = data["outcome"] in {"completed", "higher_authority"} or (data["outcome"] == "skipped" and advance)
        if resets:
            scheduled_due = task_dict(db, task).get("calendar_due") if task["schedule_type"] in {"pattern", "seasonal"} else None
            db.execute(
                "UPDATE maintenance_tasks SET last_completed_date=?,last_completed_reading=COALESCE(?,last_completed_reading),"
                "last_scheduled_due=COALESCE(?,last_scheduled_due),snoozed_until=NULL,active=?,updated_at=? WHERE id=?",
                (data["completion_date"], reading, scheduled_due, 0 if task["schedule_type"] == "one_time" else 1, now, task_id),
            )
        if task["asset_id"]:
            category = "corrective" if data["outcome"] == "higher_authority" else "preventive"
            db.execute(
                "INSERT INTO remarks VALUES (?,?,?,?,?,?,?,?,0)",
                (new_id("remark"), task["asset_id"], category, data["completion_date"], now, data["remark_text"].strip(), "maintenance", completion_id),
            )
        return jsonify({"id": completion_id, "reset_periodicity": resets}), 201


@app.put("/api/completions/<completion_id>")
def update_completion(completion_id):
    data = payload()
    require_fields(data, "completion_date", "outcome", "remark_text")
    with transaction() as db:
        completion = db_row(db, "SELECT * FROM maintenance_completions WHERE id=?", (completion_id,))
        task = db_row(db, "SELECT * FROM maintenance_tasks WHERE id=?", (completion["task_id"],))
        outcome = data["outcome"]
        if outcome not in {"completed", "skipped", "higher_authority"}:
            abort(400, description="Invalid completion outcome.")
        if outcome == "higher_authority" and not data.get("replacement_asset_id"):
            abort(400, description="Higher-authority completion must link the replacement or corrective item.")
        reading = float(data["meter_reading"]) if data.get("meter_reading") not in (None, "") else completion["meter_reading"]
        if task["meter_id"]:
            linked = db.execute("SELECT id FROM meter_readings WHERE note=?", (f"Maintenance completion {completion_id}",)).fetchone()
            if linked:
                db.execute("DELETE FROM meter_readings WHERE id=?", (linked["id"],))
            if reading is not None:
                reading_time = data["completion_date"] + "T12:00:00+00:00"
                validate_running_total(db, task["meter_id"], reading, reading_time)
                db.execute("INSERT INTO meter_readings VALUES (?,?,?,?,?,0,?)", (
                    linked["id"] if linked else new_id("reading"), task["meter_id"], reading, reading_time,
                    f"Maintenance completion {completion_id}", utcnow(),
                ))
        advance = bool(data.get("advance_schedule", completion["advance_schedule"]))
        db.execute(
            "UPDATE maintenance_completions SET completion_date=?,meter_reading=?,outcome=?,remark_text=?,labor_minutes=?,total_cost=?,"
            "materials_json=?,replacement_asset_id=?,advance_schedule=?,updated_at=? WHERE id=?",
            (data["completion_date"], reading, outcome, data["remark_text"].strip(), data.get("labor_minutes") or None,
             data.get("total_cost") or None, json.dumps(data.get("materials") or []), data.get("replacement_asset_id") or None,
             int(advance), utcnow(), completion_id),
        )
        db.execute("UPDATE remarks SET work_date=?,text=?,category=? WHERE source='maintenance' AND source_id=?", (data["completion_date"], data["remark_text"].strip(), "corrective" if outcome == "higher_authority" else "preventive", completion_id))
        latest = db.execute(
            "SELECT completion_date,meter_reading FROM maintenance_completions WHERE task_id=? AND approved=1 "
            "AND (outcome IN ('completed','higher_authority') OR (outcome='skipped' AND advance_schedule=1)) "
            "ORDER BY completion_date DESC,created_at DESC LIMIT 1", (task["id"],)
        ).fetchone()
        db.execute(
            "UPDATE maintenance_tasks SET last_completed_date=?,last_completed_reading=?,active=?,updated_at=? WHERE id=?",
            (latest["completion_date"] if latest else None, latest["meter_reading"] if latest else None,
             0 if latest and task["schedule_type"] == "one_time" else 1, utcnow(), task["id"]),
        )
        return jsonify({"ok": True})


# Reports, settings, Home Assistant, and data portability --------------------

@app.get("/api/reports/<report_name>")
def report(report_name):
    with connect() as db:
        if report_name in {"upcoming", "overdue"}:
            tasks = [task_dict(db, row) for row in db.execute("SELECT * FROM maintenance_tasks WHERE active=1")]
            if report_name == "overdue":
                tasks = [task for task in tasks if task["state"] in ("overdue", "red")]
            else:
                cutoff = (date.today() + timedelta(days=int(request.args.get("days", 30)))).isoformat()
                tasks = [task for task in tasks if task["state"] in ("overdue", "red") or task.get("calendar_due") and task["calendar_due"] <= cutoff]
            return jsonify(tasks)
        if report_name == "history":
            rows = db.execute(
                "SELECT mc.*,mt.title,a.name AS asset_name FROM maintenance_completions mc JOIN maintenance_tasks mt ON mt.id=mc.task_id "
                "LEFT JOIN assets a ON a.id=mt.asset_id ORDER BY mc.completion_date DESC"
            ).fetchall()
            return jsonify([row_to_dict(row) for row in rows])
        if report_name == "costs":
            rows = db.execute(
                "SELECT a.name AS asset_name,mt.title,mc.completion_date,mc.total_cost,mc.labor_minutes,mc.materials_json "
                "FROM maintenance_completions mc JOIN maintenance_tasks mt ON mt.id=mc.task_id LEFT JOIN assets a ON a.id=mt.asset_id "
                "WHERE mc.completion_date BETWEEN ? AND ? ORDER BY mc.completion_date DESC",
                (request.args.get("from", "0001-01-01"), request.args.get("to", "9999-12-31")),
            ).fetchall()
            return jsonify([row_to_dict(row) for row in rows])
        if report_name == "parts":
            rows = db.execute(
                "SELECT mc.completion_date,mc.materials_json,mt.title,a.name AS asset_name "
                "FROM maintenance_completions mc JOIN maintenance_tasks mt ON mt.id=mc.task_id "
                "LEFT JOIN assets a ON a.id=mt.asset_id ORDER BY mc.completion_date DESC"
            ).fetchall()
            materials = []
            for row in rows:
                try:
                    entries = json.loads(row["materials_json"] or "[]")
                except json.JSONDecodeError:
                    entries = []
                for entry in entries:
                    materials.append({
                        "completion_date": row["completion_date"], "title": row["title"],
                        "asset_name": row["asset_name"] or "General / unassigned",
                        "description": entry.get("description", ""), "quantity": entry.get("quantity"), "cost": entry.get("cost"),
                    })
            return jsonify(materials)
        if report_name == "meters":
            rows = db.execute(
                "SELECT mr.recorded_at,mr.reading,mr.note,m.name AS meter_name,m.unit,a.name AS asset_name "
                "FROM meter_readings mr JOIN meters m ON m.id=mr.meter_id JOIN assets a ON a.id=m.asset_id "
                "ORDER BY mr.recorded_at DESC"
            ).fetchall()
            return jsonify([dict(row) for row in rows])
        if report_name == "archived":
            return jsonify([row_to_dict(row) for row in db.execute("SELECT * FROM assets WHERE archived=1 ORDER BY archived_at DESC")])
        if report_name == "warranties":
            data = []
            for row in db.execute("SELECT * FROM assets WHERE archived=0"):
                asset = row_to_dict(row)
                if asset.get("attributes", {}).get("warranty_expiration"):
                    data.append(asset)
            return jsonify(sorted(data, key=lambda item: item["attributes"]["warranty_expiration"]))
        abort(404, description="Unknown report.")


@app.get("/api/settings")
def get_settings():
    with connect() as db:
        return jsonify({row["key"]: json.loads(row["value"]) for row in db.execute("SELECT key,value FROM settings")})


@app.put("/api/settings")
def update_settings():
    allowed = {"dashboard_window_days", "theme", "notification_services", "notification_check_hour", "setup_complete"}
    data = payload()
    with transaction() as db:
        for key, value in data.items():
            if key in allowed:
                set_setting(db, key, value)
        return jsonify({"ok": True})


def fetch_ha_services():
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return []
    req = urllib.request.Request(
        "http://supervisor/core/api/services",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


@app.get("/api/ha/app-info")
def ha_app_info():
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return jsonify({"connected": False, "slug": None, "panel_path": None})
    try:
        req = urllib.request.Request(
            "http://supervisor/addons/self/info",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.load(response)
        info = result.get("data", result)
        slug = info.get("slug")
        return jsonify({"connected": True, "slug": slug, "panel_path": f"/hassio/ingress/{slug}" if slug else None})
    except Exception as error:
        app.logger.warning("Could not read app identity from Supervisor: %s", error)
        return jsonify({"connected": False, "slug": None, "panel_path": None})


@app.get("/api/ha/notify-services")
def ha_notify_services():
    try:
        domains = fetch_ha_services()
        services = []
        for domain in domains:
            if domain.get("domain") != "notify":
                continue
            for name in domain.get("services", {}):
                if name.startswith("mobile_app_"):
                    services.append({"service": name, "label": name.removeprefix("mobile_app_").replace("_", " ").title()})
        return jsonify({"connected": True, "services": sorted(services, key=lambda item: item["label"])})
    except Exception as error:
        app.logger.warning("Could not read Home Assistant notify services: %s", error)
        return jsonify({"connected": False, "services": [], "message": "Home Assistant services are unavailable while running outside the app environment."})


def send_ha_notification(service: str, title: str, message: str, data=None) -> bool:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return False
    body = json.dumps({"title": title, "message": message, "data": data or {}}).encode()
    req = urllib.request.Request(
        f"http://supervisor/core/api/services/notify/{service}",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError):
        return False


@app.post("/api/ha/test-notification")
def test_notification():
    targets = payload().get("services") or []
    results = {target: send_ha_notification(target, "Home Maintenance Tracker", "Notifications are connected successfully.") for target in targets}
    return jsonify(results)


def run_notification_check() -> None:
    with transaction() as db:
        targets = get_setting(db, "notification_services", [])
        if not targets:
            return
        for row in db.execute("SELECT * FROM maintenance_tasks WHERE active=1"):
            task = task_dict(db, row)
            if task["state"] not in {"overdue", "red"}:
                continue
            cadence = reminder_days(task)
            latest = db.execute("SELECT sent_at FROM notification_log WHERE task_id=? ORDER BY sent_at DESC LIMIT 1", (task["id"],)).fetchone()
            if latest and datetime.fromisoformat(latest["sent_at"]) > datetime.now(timezone.utc) - timedelta(days=cadence):
                continue
            title = "Maintenance escalation" if task["state"] == "red" else "Maintenance overdue"
            message = f"{task['title']} — {task['asset_name']}"
            successful = [target for target in targets if send_ha_notification(target, title, message, {"tag": f"hmt-{task['id']}"})]
            if successful:
                db.execute("INSERT INTO notification_log VALUES (?,?,?,?,?)", (new_id("notification"), task["id"], utcnow(), task["state"], json.dumps(successful)))


def notification_worker() -> None:
    last_date = None
    while True:
        try:
            now = datetime.now()
            with connect() as db:
                hour = int(get_setting(db, "notification_check_hour", 9))
            if now.hour == hour and last_date != now.date():
                run_notification_check()
                last_date = now.date()
        except Exception:
            app.logger.exception("Notification check failed")
        time.sleep(300)


@app.post("/api/sample-data/remove")
def remove_sample_data():
    with transaction() as db:
        delete_sample_data(db)
    return jsonify({"ok": True})


@app.post("/api/sample-data/restore")
def restore_sample_data():
    with transaction() as db:
        existing = db.execute("SELECT COUNT(*) n FROM assets WHERE is_sample=1").fetchone()["n"]
        if existing:
            abort(400, description="Sample data is already installed.")
        seed_sample_data(db)
    return jsonify({"ok": True})


@app.get("/api/export")
def export_data():
    file_handle, raw_archive_path = tempfile.mkstemp(prefix="hmt-export-", suffix=".zip", dir=DATA_DIR)
    os.close(file_handle)
    archive_path = Path(raw_archive_path)
    snapshot = DATA_DIR / f"hmt-snapshot-{uuid.uuid4().hex}.sqlite3"
    source = connect()
    target = sqlite3.connect(snapshot)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, "database/home_maintenance.sqlite3")
            archive.writestr("manifest.json", json.dumps({"application": "Home Maintenance Tracker", "version": APP_VERSION, "exported_at": utcnow()}, indent=2))
            for path in ATTACHMENT_DIR.iterdir():
                if path.is_file():
                    archive.write(path, f"attachments/{path.name}")
    finally:
        snapshot.unlink(missing_ok=True)
    response = send_file(archive_path, as_attachment=True, download_name=f"home-maintenance-export-{date.today().isoformat()}.zip", mimetype="application/zip")
    response.call_on_close(lambda: archive_path.unlink(missing_ok=True))
    return response


@app.post("/api/import")
def import_data():
    uploaded = request.files.get("file")
    if not uploaded:
        abort(400, description="Choose an export ZIP file.")
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        archive_path = temp / "import.zip"
        uploaded.save(archive_path)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                if "manifest.json" not in names or "database/home_maintenance.sqlite3" not in names:
                    abort(400, description="This is not a valid Home Maintenance Tracker export.")
                if any(name.startswith("/") or ".." in Path(name).parts for name in names):
                    abort(400, description="The import archive contains an unsafe path.")
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("application") != "Home Maintenance Tracker":
                    abort(400, description="The export manifest is invalid.")
                extracted_db = temp / "imported.sqlite3"
                extracted_db.write_bytes(archive.read("database/home_maintenance.sqlite3"))
                check = sqlite3.connect(extracted_db)
                try:
                    required = {"assets", "maintenance_tasks", "attachments", "settings"}
                    tables = {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if not required.issubset(tables):
                        abort(400, description="The exported database is incomplete.")
                finally:
                    check.close()
                new_attachments = temp / "attachments"
                new_attachments.mkdir()
                for name in names:
                    if name.startswith("attachments/") and not name.endswith("/"):
                        target = new_attachments / Path(name).name
                        target.write_bytes(archive.read(name))
        except zipfile.BadZipFile:
            abort(400, description="The selected file is not a valid ZIP archive.")

        backup_path = DATA_DIR / "pre-import.sqlite3"
        backup_path.unlink(missing_ok=True)
        live_source = connect()
        backup_target = sqlite3.connect(backup_path)
        try:
            live_source.backup(backup_target)
        finally:
            backup_target.close()
            live_source.close()
        old_attachments = DATA_DIR / "attachments.pre-import"
        if old_attachments.exists():
            shutil.rmtree(old_attachments)
        ATTACHMENT_DIR.rename(old_attachments)
        try:
            imported_source = sqlite3.connect(extracted_db)
            live_target = sqlite3.connect(DB_PATH)
            try:
                imported_source.backup(live_target)
            finally:
                live_target.close()
                imported_source.close()
            shutil.copytree(new_attachments, ATTACHMENT_DIR)
            initialize_database()
        except Exception:
            rollback_source = sqlite3.connect(backup_path)
            rollback_target = sqlite3.connect(DB_PATH)
            try:
                rollback_source.backup(rollback_target)
            finally:
                rollback_target.close()
                rollback_source.close()
            if ATTACHMENT_DIR.exists():
                shutil.rmtree(ATTACHMENT_DIR)
            old_attachments.rename(ATTACHMENT_DIR)
            raise
        else:
            backup_path.unlink(missing_ok=True)
            shutil.rmtree(old_attachments, ignore_errors=True)
    return jsonify({"ok": True, "message": "Import completed. Reloading the application is recommended."})


initialize_database()

if os.environ.get("HMT_DISABLE_NOTIFICATION_THREAD") != "1":
    threading.Thread(target=notification_worker, name="hmt-notifications", daemon=True).start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8099")), debug=os.environ.get("FLASK_DEBUG") == "1")
