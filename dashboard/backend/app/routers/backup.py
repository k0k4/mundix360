"""Backup & restore API — appliance configuration + SIEM snapshots."""
from __future__ import annotations

import os

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..services import backup

router = APIRouter(prefix="/api/backup", tags=["backup"])


class ScheduleRequest(BaseModel):
    enabled: bool
    interval_hours: int
    retention: int
    include_clickhouse: bool


@router.get("/overview")
def overview():
    return backup.overview()


@router.post("/run")
def run():
    try:
        return backup.run_backup()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@router.post("/import")
def import_(file: UploadFile = File(...)):
    try:
        return backup.import_backup(file.filename, file.file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/verify/{name}")
def verify(name: str):
    try:
        return backup.verify_backup(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError:
        raise HTTPException(status_code=404, detail="backup não encontrado")


@router.post("/extract/{name}")
def extract(name: str):
    try:
        return backup.extract_to_staging(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError:
        raise HTTPException(status_code=404, detail="backup não encontrado")


@router.get("/download/{name}")
def download(name: str):
    try:
        path = backup.backup_path(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="backup não encontrado")
    return FileResponse(path, media_type="application/gzip", filename=name)


@router.delete("/{name}")
def delete(name: str):
    try:
        return backup.delete_backup(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/schedule")
def schedule(req: ScheduleRequest):
    return backup.set_schedule(req.enabled, req.interval_hours,
                               req.retention, req.include_clickhouse)
