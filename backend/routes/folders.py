"""
Folders: group sources under a name of the user's choosing.

A folder is stored as a name on each source inside it (a source is in at most one
folder), so a folder exists as long as it holds a source. Asking a question
"in" a folder searches every source in it (see routes/query.py).
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from security import AuthUser, get_current_user
from services import db_service

router = APIRouter(prefix="/api/folders", tags=["folders"])

MAX_FOLDER_CHARS = 60


def clean_folder_name(raw: str) -> str:
    """Collapse whitespace, drop control characters and slashes, and cap the length."""
    name = re.sub(r"[\x00-\x1f\x7f/\\]+", " ", raw)
    return " ".join(name.split())[:MAX_FOLDER_CHARS].strip()


def _existing_folders(user_id: str) -> dict[str, str]:
    """{lower-case name: name as first written} for the user's folders."""
    found: dict[str, str] = {}
    for doc in db_service.list_documents(user_id):
        name = doc.get("folder")
        if name:
            found.setdefault(name.lower(), name)
    return found


class AssignBody(BaseModel):
    filenames: list[str] = Field(min_length=1, max_length=200)
    # None / empty takes the sources out of their folder.
    folder: str | None = Field(default=None, max_length=200)


@router.put("/assign")
def assign_folder(body: AssignBody, user: AuthUser = Depends(get_current_user)):
    """Move sources into a folder (created on the spot), or out of any folder."""
    names = list(dict.fromkeys(body.filenames))
    known = {d["filename"] for d in db_service.list_documents(user.id)}
    missing = [n for n in names if n not in known]
    if missing:
        raise HTTPException(status_code=404, detail=f"Document not found: {missing[0]}")

    folder: str | None = None
    if body.folder and body.folder.strip():
        folder = clean_folder_name(body.folder)
        if not folder:
            raise HTTPException(status_code=400, detail="The folder name can't be empty.")
        folder = _existing_folders(user.id).get(folder.lower(), folder)  # "contracts" joins "Contracts"

    moved = db_service.set_documents_folder(user.id, names, folder)
    return {"status": "success", "folder": folder, "moved": moved}


class RenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    new_name: str = Field(min_length=1, max_length=200)


@router.patch("")
def rename_folder(body: RenameBody, user: AuthUser = Depends(get_current_user)):
    existing = _existing_folders(user.id)
    current = existing.get(body.name.strip().lower())
    if current is None:
        raise HTTPException(status_code=404, detail="Folder not found.")
    new_name = clean_folder_name(body.new_name)
    if not new_name:
        raise HTTPException(status_code=400, detail="The folder name can't be empty.")
    clash = existing.get(new_name.lower())
    if clash is not None and clash.lower() != current.lower():
        raise HTTPException(status_code=409, detail=f"A folder named \"{clash}\" already exists.")
    db_service.rename_folder(user.id, current, new_name)
    return {"status": "success", "folder": new_name}


@router.delete("")
def delete_folder(name: str = Query(min_length=1, max_length=200), user: AuthUser = Depends(get_current_user)):
    """Remove a folder. Its sources are kept; they just stop being grouped."""
    current = _existing_folders(user.id).get(name.strip().lower())
    if current is None:
        raise HTTPException(status_code=404, detail="Folder not found.")
    members = [d["filename"] for d in db_service.list_documents(user.id) if d.get("folder") == current]
    db_service.set_documents_folder(user.id, members, None)
    return {"status": "success", "ungrouped": len(members)}
