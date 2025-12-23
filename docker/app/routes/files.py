"""File operations API routes.

Provides file system operations for the web UI.
"""

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import get_settings, Settings


router = APIRouter()


class FileWrite(BaseModel):
    """Request model for writing a file."""
    path: str
    content: str


class FileNode(BaseModel):
    """File/directory node for tree view."""
    name: str
    path: str
    type: str  # 'file' or 'directory'
    size: Optional[int] = None
    children: Optional[list["FileNode"]] = None


def is_safe_path(base_path: str, target_path: str) -> bool:
    """Check if target_path is safely within base_path."""
    base = Path(base_path).resolve()
    target = Path(target_path).resolve()
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def get_allowed_base_paths(settings: Settings) -> list[Path]:
    """Get list of allowed base paths for file operations."""
    return [
        settings.projects_dir,
        settings.data_dir,
        Path("/tmp"),
    ]


def validate_path(path: str, settings: Settings) -> Path:
    """Validate path is within allowed directories."""
    resolved = Path(path).resolve()
    allowed = get_allowed_base_paths(settings)

    for base in allowed:
        try:
            resolved.relative_to(base.resolve())
            return resolved
        except ValueError:
            continue

    raise HTTPException(
        status_code=403,
        detail=f"Access denied: path must be within {[str(p) for p in allowed]}"
    )


@router.get("/read")
async def read_file(
    path: str = Query(..., description="File path to read"),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Read file contents."""
    file_path = validate_path(path, settings)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if not file_path.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    # Check file size (limit to 10MB)
    if file_path.stat().st_size > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    try:
        content = file_path.read_text(encoding="utf-8")
        return {"content": content, "path": str(file_path)}
    except UnicodeDecodeError:
        # Try reading as binary and return base64
        import base64
        content = base64.b64encode(file_path.read_bytes()).decode("ascii")
        return {"content": content, "path": str(file_path), "binary": True}


@router.post("/write")
async def write_file(
    data: FileWrite,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Write file contents."""
    file_path = validate_path(data.path, settings)

    # Create parent directories if needed
    file_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        file_path.write_text(data.content, encoding="utf-8")
        return {"success": True, "path": str(file_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_directory(
    path: str = Query(..., description="Directory path to list"),
    settings: Settings = Depends(get_settings),
) -> list[str]:
    """List directory contents."""
    dir_path = validate_path(path, settings)

    if not dir_path.exists():
        raise HTTPException(status_code=404, detail="Directory not found")

    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    try:
        entries = []
        for entry in dir_path.iterdir():
            entries.append(entry.name)
        return sorted(entries)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")


@router.get("/exists")
async def file_exists(
    path: str = Query(..., description="Path to check"),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Check if file/directory exists."""
    file_path = validate_path(path, settings)
    return {"exists": file_path.exists(), "is_file": file_path.is_file() if file_path.exists() else False}


@router.get("/tree")
async def get_file_tree(
    path: str = Query(..., description="Root path for tree"),
    depth: int = Query(3, description="Maximum depth"),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Get file tree structure."""
    root_path = validate_path(path, settings)

    if not root_path.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    def build_tree(current_path: Path, current_depth: int) -> dict:
        node = {
            "name": current_path.name or str(current_path),
            "path": str(current_path),
            "type": "directory" if current_path.is_dir() else "file",
        }

        if current_path.is_file():
            try:
                node["size"] = current_path.stat().st_size
            except OSError:
                pass

        if current_path.is_dir() and current_depth < depth:
            children = []
            try:
                entries = sorted(current_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                for entry in entries:
                    # Skip hidden files and common ignored directories
                    # Allow: .auto-claude (specs/config), .git (repo), .worktrees (Claude's work branches)
                    if entry.name.startswith('.') and entry.name not in ['.auto-claude', '.git', '.worktrees']:
                        continue
                    if entry.name in ['node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build']:
                        continue
                    children.append(build_tree(entry, current_depth + 1))
            except PermissionError:
                pass
            node["children"] = children

        return node

    return build_tree(root_path, 0)


@router.delete("/delete")
async def delete_file(
    path: str = Query(..., description="Path to delete"),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Delete a file or empty directory."""
    file_path = validate_path(path, settings)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    try:
        if file_path.is_file():
            file_path.unlink()
        elif file_path.is_dir():
            file_path.rmdir()  # Only works for empty directories
        return {"success": True}
    except OSError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/mkdir")
async def create_directory(
    path: str = Query(..., description="Directory path to create"),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Create a directory."""
    dir_path = validate_path(path, settings)

    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        return {"success": True, "path": str(dir_path)}
    except OSError as e:
        raise HTTPException(status_code=400, detail=str(e))
