"""Git operations API routes.

Provides git repository operations for the web UI.
"""

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import get_settings, Settings


router = APIRouter()


class GitInit(BaseModel):
    """Request model for initializing a git repo."""
    path: str


async def run_git_command(cwd: str, *args: str) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stdout.decode().strip(), stderr.decode().strip()


@router.get("/branches")
async def get_branches(
    path: str = Query(..., description="Repository path"),
    settings: Settings = Depends(get_settings),
) -> list[str]:
    """Get list of branches."""
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="Path not found")

    returncode, stdout, stderr = await run_git_command(path, "branch", "-a", "--format=%(refname:short)")

    if returncode != 0:
        raise HTTPException(status_code=400, detail=stderr or "Failed to get branches")

    branches = [b.strip() for b in stdout.split("\n") if b.strip()]
    return branches


@router.get("/current-branch")
async def get_current_branch(
    path: str = Query(..., description="Repository path"),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Get current branch name."""
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="Path not found")

    returncode, stdout, stderr = await run_git_command(path, "rev-parse", "--abbrev-ref", "HEAD")

    if returncode != 0:
        return {"branch": None}

    return {"branch": stdout.strip()}


@router.get("/main-branch")
async def detect_main_branch(
    path: str = Query(..., description="Repository path"),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Detect the main branch (main, master, etc.)."""
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="Path not found")

    # Check for common main branch names
    for branch in ["main", "master", "develop"]:
        returncode, _, _ = await run_git_command(
            path, "rev-parse", "--verify", f"refs/heads/{branch}"
        )
        if returncode == 0:
            return {"branch": branch}

    return {"branch": None}


@router.get("/status")
async def get_git_status(
    path: str = Query(..., description="Repository path"),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Get git status."""
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="Path not found")

    # Check if it's a git repo
    returncode, _, _ = await run_git_command(path, "rev-parse", "--is-inside-work-tree")
    if returncode != 0:
        return {"isRepo": False, "clean": False, "branch": None, "files": []}

    # Get current branch
    _, branch, _ = await run_git_command(path, "rev-parse", "--abbrev-ref", "HEAD")

    # Get status
    returncode, stdout, _ = await run_git_command(path, "status", "--porcelain")

    files = []
    if stdout:
        for line in stdout.split("\n"):
            if line:
                status = line[:2]
                file_path = line[3:]
                files.append({"status": status.strip(), "path": file_path})

    return {
        "isRepo": True,
        "clean": len(files) == 0,
        "branch": branch,
        "files": files,
    }


@router.post("/init")
async def init_repo(
    data: GitInit,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Initialize a git repository."""
    if not Path(data.path).exists():
        raise HTTPException(status_code=404, detail="Path not found")

    returncode, stdout, stderr = await run_git_command(data.path, "init")

    if returncode != 0:
        raise HTTPException(status_code=400, detail=stderr or "Failed to initialize repository")

    return {"success": True, "message": stdout or "Initialized empty Git repository"}


@router.get("/log")
async def get_git_log(
    path: str = Query(..., description="Repository path"),
    limit: int = Query(10, description="Number of commits"),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    """Get recent commits."""
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="Path not found")

    returncode, stdout, stderr = await run_git_command(
        path,
        "log",
        f"-{limit}",
        "--format=%H|%s|%an|%ae|%aI",
    )

    if returncode != 0:
        return []

    commits = []
    for line in stdout.split("\n"):
        if line:
            parts = line.split("|", 4)
            if len(parts) == 5:
                commits.append({
                    "hash": parts[0],
                    "message": parts[1],
                    "author": parts[2],
                    "email": parts[3],
                    "date": parts[4],
                })

    return commits


@router.get("/diff")
async def get_git_diff(
    path: str = Query(..., description="Repository path"),
    staged: bool = Query(False, description="Show staged changes"),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Get git diff."""
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="Path not found")

    args = ["diff"]
    if staged:
        args.append("--cached")

    returncode, stdout, stderr = await run_git_command(path, *args)

    return {"diff": stdout}


@router.get("/remote")
async def get_git_remote(
    path: str = Query(..., description="Repository path"),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    """Get git remotes."""
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="Path not found")

    returncode, stdout, _ = await run_git_command(path, "remote", "-v")

    if returncode != 0:
        return []

    remotes = {}
    for line in stdout.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0]
                url = parts[1]
                if name not in remotes:
                    remotes[name] = {"name": name, "url": url}

    return list(remotes.values())


@router.post("/fetch")
async def git_fetch(
    path: str = Query(..., description="Repository path"),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Fetch from remote."""
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="Path not found")

    returncode, stdout, stderr = await run_git_command(path, "fetch", "--all")

    if returncode != 0:
        raise HTTPException(status_code=400, detail=stderr or "Failed to fetch")

    return {"success": True, "message": stdout or stderr or "Fetch complete"}


@router.post("/pull")
async def git_pull(
    path: str = Query(..., description="Repository path"),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Pull from remote."""
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="Path not found")

    returncode, stdout, stderr = await run_git_command(path, "pull")

    if returncode != 0:
        raise HTTPException(status_code=400, detail=stderr or "Failed to pull")

    return {"success": True, "message": stdout or stderr or "Pull complete"}
