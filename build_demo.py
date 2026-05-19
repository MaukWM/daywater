#!/usr/bin/env python3
"""Build a self-contained static demo site from daywater session data.

Copies the exact production index.html, style.css, mask-painter.js and injects
a fetch-interceptor that serves pre-baked JSON + base64 images. The result is
visually identical to the real app but fully static (no backend needed).

Usage:
    python build_demo.py [--out demo-site] [--sessions ./sessions]
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "src" / "web" / "static"


# ── Helpers ──────────────────────────────────────────────────────────────── #


def b64_img(path: Path) -> str:
    """Return a data-URI for a PNG, or empty string if missing."""
    if not path.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _read_disc_contents(proj_dir: Path, cfg: dict) -> dict:
    """Read ISO filesystem at build time, matching the real /api/disc-contents response."""
    import struct
    import sys

    analyzed_binaries = cfg.get("analyzed_binaries", {})
    empty = {"files": [], "total_files": 0, "total_size": 0, "analyzed_binaries": analyzed_binaries}

    # Resolve the ISO: the session symlink points to /app/cache/isos/<sha>.iso
    # but locally we have cache/isos/<sha>.iso relative to the project root.
    iso_sha = cfg.get("iso_sha1", "")
    if not iso_sha:
        return empty

    # Try local cache path
    cache_iso = proj_dir.parent.parent / "cache" / "isos" / f"{iso_sha}.iso"
    if not cache_iso.exists():
        # Try the symlink itself
        iso_link = proj_dir / "iso.iso"
        if iso_link.exists() and iso_link.is_file():
            cache_iso = iso_link
        else:
            print(f"    warn: ISO not found for {cfg.get('game_id', '?')}, skipping disc contents")
            return empty

    try:
        # Add src/ to path so we can import the ISO reader
        src_dir = str(proj_dir.parent.parent)
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)
        from src.ghidra.iso import list_iso_files, read_header

        files = list_iso_files(cache_iso)
        hdr = read_header(cache_iso)

        # Compute boot.dol size from DOL header segments
        dol_size = 0
        try:
            with cache_iso.open("rb") as f:
                f.seek(hdr.dol_offset)
                dol_hdr = f.read(0x100)
                if len(dol_hdr) >= 0x100:
                    max_end = 0
                    for i in range(18):
                        off = struct.unpack(">I", dol_hdr[i * 4 : i * 4 + 4])[0]
                        sz = struct.unpack(">I", dol_hdr[0x90 + i * 4 : 0x94 + i * 4])[0]
                        if off and sz:
                            max_end = max(max_end, off + sz)
                    dol_size = max_end
        except Exception:
            pass

        file_list = [{"path": "boot.dol", "size": dol_size, "is_directory": False}]
        file_list.extend({"path": f.path, "size": f.size, "is_directory": False} for f in files)

        total_size = sum(f.size for f in files)
        print(f"    disc: {len(file_list)} files, {total_size / 1e6:.1f} MB")

        return {
            "files": file_list,
            "analyzed_binaries": analyzed_binaries,
            "total_files": len(file_list),
            "total_size": total_size,
        }
    except Exception as e:
        print(f"    warn: failed to read ISO: {e}")
        return empty


# ── Data collection ──────────────────────────────────────────────────────── #


def collect_project(proj_dir: Path) -> dict | None:
    cfg = read_json(proj_dir / "config.json")
    if not cfg:
        return None

    pid = cfg["project_id"]

    # Project-level API response: GET /api/projects/{id}
    project_detail = {**cfg}
    project_detail["task_count"] = 0

    # Savestates
    savestates: list[dict] = []
    savestates_screenshots: dict[str, str] = {}  # ssid -> data-uri
    savestate_details: dict[str, dict] = {}  # ssid -> detail for GET /savestates/{id}
    savestate_findings: dict[str, list] = {}  # ssid -> findings list
    ss_dir = proj_dir / "savestates"
    if ss_dir.exists():
        for sd in sorted(ss_dir.iterdir()):
            ss_cfg = read_json(sd / "config.json")
            if not ss_cfg:
                continue
            ssid = ss_cfg["savestate_id"]
            has_screenshot = (sd / "screenshot.png").exists()

            # Parse savestate-level findings (FindingsStore format: list under "findings")
            ss_findings_data = read_json(sd / "findings.json")
            ss_findings_list: list[dict] = []
            for f in ss_findings_data.get("findings", []):
                ss_findings_list.append({
                    "id": f.get("id", ""),
                    "kind": f.get("kind", ""),
                    "address": f.get("address", ""),
                    "label": f.get("label", ""),
                    "detail": f.get("detail", ""),
                })

            # Build list-view response (matches real API)
            savestates.append({
                "savestate_id": ssid,
                "name": ss_cfg.get("name", ""),
                "notes": ss_cfg.get("notes", ""),
                "created_at": ss_cfg.get("created_at", 0),
                "has_screenshot": has_screenshot,
                "findings_count": len(ss_findings_list),
            })

            # Build detail-view response
            savestate_details[ssid] = {
                "savestate_id": ssid,
                "name": ss_cfg.get("name", ""),
                "notes": ss_cfg.get("notes", ""),
                "created_at": ss_cfg.get("created_at", 0),
                "has_file": (sd / "savestate.sav").exists(),
                "has_screenshot": has_screenshot,
            }
            savestate_findings[ssid] = ss_findings_list

            if has_screenshot:
                savestates_screenshots[ssid] = b64_img(sd / "screenshot.png")

    # Tasks
    tasks: list[dict] = []
    task_details: dict[str, dict] = {}  # tid -> full detail
    task_files: dict[str, dict[str, str]] = {}  # tid -> {filename: data-uri}
    task_results: dict[str, dict] = {}  # tid -> result object
    tasks_dir = proj_dir / "tasks"
    if tasks_dir.exists():
        for td in sorted(tasks_dir.iterdir()):
            t_cfg = read_json(td / "config.json")
            if not t_cfg:
                continue
            tid = t_cfg["task_id"]

            # List item (GET /api/projects/{pid}/tasks)
            spec = t_cfg.get("job_spec", {})
            tasks.append({
                "task_id": tid,
                "name": t_cfg.get("name", ""),
                "state": t_cfg.get("state", ""),
                "created_at": t_cfg.get("created_at", 0),
                "preset": spec.get("_preset", ""),
                "goal_type": spec.get("goal_type", ""),
            })

            # Detail (GET /api/projects/{pid}/tasks/{tid})
            detail = {**t_cfg}
            detail["has_savestate"] = bool(t_cfg.get("savestate_id"))
            detail["has_reference"] = (td / "reference.png").exists()
            detail["has_mask"] = (td / "mask.png").exists()
            detail["survey_complete"] = cfg.get("survey_complete", True)
            task_details[tid] = detail

            # Files
            files: dict[str, str] = {}
            for fname in ["reference.png", "mask.png", "result_frame.png"]:
                fp = td / fname
                if fp.exists():
                    files[fname] = b64_img(fp)
            task_files[tid] = files

            # Result
            gecko_text = ""
            gecko_path = td / "result.gecko"
            if gecko_path.exists():
                gecko_text = gecko_path.read_text()
            task_results[tid] = {
                "verdict": t_cfg.get("result_verdict", ""),
                "gecko": t_cfg.get("result_gecko", "") or gecko_text,
                "hud_mean": t_cfg.get("result_hud_mean", 0),
                "preserve_mean": t_cfg.get("result_preserve_mean", 0),
                "has_frame": (td / "result_frame.png").exists(),
            }

    project_detail["task_count"] = len(tasks)

    # Research docs
    research_list: list[dict] = []
    research_content: dict[str, str] = {}  # filename -> content
    research_dir = proj_dir / "research"
    if research_dir.exists():
        for md in sorted(research_dir.glob("*.md")):
            research_list.append({"filename": md.name, "summary": "", "task_id": "", "created_at": 0})
            research_content[md.name] = md.read_text()

    # Research index (combine all docs into a summary)
    research_index = "\n".join(f"- {d['filename']}" for d in research_list)

    # Gecko codes
    gecko_codes_list: list[dict] = []
    gecko_codes_content: dict[str, dict] = {}  # filename -> {content, description}
    gecko_dir = proj_dir / "gecko_codes"
    if gecko_dir.exists():
        for gc in sorted(gecko_dir.glob("*.gecko")):
            content = gc.read_text()
            lines = content.strip().splitlines()
            name = gc.stem
            # Parse first line for $Name
            desc = ""
            if lines and lines[0].startswith("$"):
                name = lines[0][1:].strip()
            gecko_codes_list.append({
                "filename": gc.name,
                "name": name,
                "lines": len(lines),
                "description": desc,
                "task_id": "",
            })
            gecko_codes_content[gc.name] = {"content": content, "description": desc}

    # Knowledge/findings (FindingsStore format: list under "findings" key)
    findings_data = read_json(proj_dir / "findings.json")
    knowledge: dict[str, list] = {
        "findings": [],
        "renames": [],
        "notes": [],
    }
    for f in findings_data.get("findings", []):
        knowledge["findings"].append({
            "id": f.get("id", ""),
            "kind": f.get("kind", ""),
            "address": f.get("address", ""),
            "label": f.get("label", ""),
            "detail": f.get("detail", ""),
        })

    # Renames/notes from Ghidra binary cache (cache/binaries/<sha1>/notes.json)
    # Only include binaries that belong to this project
    cache_root = proj_dir.parent.parent / "cache" / "binaries"
    project_shas = {v["sha1"] for v in cfg.get("analyzed_binaries", {}).values()}
    if cache_root.exists():
        for sha_dir in sorted(cache_root.iterdir()):
            if sha_dir.name not in project_shas:
                continue
            notes_data = read_json(sha_dir / "notes.json")
            for addr, entry in notes_data.get("renames", {}).items():
                knowledge["renames"].append({
                    "address": addr,
                    "name": entry.get("value", "") if isinstance(entry, dict) else str(entry),
                    "binary": sha_dir.name[:8],
                    "task_id": entry.get("task_id", "") if isinstance(entry, dict) else "",
                })
            for addr, entry in notes_data.get("notes", {}).items():
                knowledge["notes"].append({
                    "address": addr,
                    "text": entry.get("value", "") if isinstance(entry, dict) else str(entry),
                    "binary": sha_dir.name[:8],
                    "task_id": entry.get("task_id", "") if isinstance(entry, dict) else "",
                })

    # Disc contents — read from ISO if available
    disc_contents = _read_disc_contents(proj_dir, cfg)

    # Controller mapping
    ctrl_mapping = read_json(proj_dir / "controller_mapping.json")
    if not ctrl_mapping:
        ctrl_mapping = {"buttons": {}, "sticks": {}}

    return {
        "project_id": pid,
        "config": cfg,
        "detail": project_detail,
        "savestates": savestates,
        "savestates_screenshots": savestates_screenshots,
        "savestate_details": savestate_details,
        "savestate_findings": savestate_findings,
        "tasks": tasks,
        "task_details": task_details,
        "task_files": task_files,
        "task_results": task_results,
        "research_list": research_list,
        "research_index": research_index,
        "research_content": research_content,
        "gecko_codes_list": gecko_codes_list,
        "gecko_codes_content": gecko_codes_content,
        "knowledge": knowledge,
        "disc_contents": disc_contents,
        "ctrl_mapping": ctrl_mapping,
    }


# ── Build the fetch interceptor ──────────────────────────────────────────── #


def build_interceptor_js(projects: list[dict]) -> str:
    """Build a JS snippet that intercepts fetch() and returns static data."""

    # Build the route table
    routes: dict[str, object] = {}

    # GET /api/projects
    project_list = []
    for p in projects:
        project_list.append(p["config"])
    routes["GET /api/projects"] = project_list

    # GET /api/settings
    routes["GET /api/settings"] = {"openai_api_key_set": True, "openai_api_key_preview": "sk-...demo", "model": "openai/gpt-5.5", "setup_complete": True}

    # GET /api/presets (empty in demo)
    routes["GET /api/presets"] = []

    for p in projects:
        pid = p["project_id"]

        # GET /api/projects/{pid}
        routes[f"GET /api/projects/{pid}"] = p["detail"]

        # GET /api/projects/{pid}/savestates
        routes[f"GET /api/projects/{pid}/savestates"] = p["savestates"]

        # GET /api/projects/{pid}/tasks
        routes[f"GET /api/projects/{pid}/tasks"] = p["tasks"]

        # GET /api/projects/{pid}/knowledge
        routes[f"GET /api/projects/{pid}/knowledge"] = p["knowledge"]

        # GET /api/projects/{pid}/research
        routes[f"GET /api/projects/{pid}/research"] = {"docs": p["research_list"], "index": p["research_index"]}

        # GET /api/projects/{pid}/gecko-codes
        routes[f"GET /api/projects/{pid}/gecko-codes"] = {"codes": p["gecko_codes_list"]}

        # GET /api/projects/{pid}/disc-contents
        routes[f"GET /api/projects/{pid}/disc-contents"] = p["disc_contents"]

        # GET /api/projects/{pid}/controller-mapping
        routes[f"GET /api/projects/{pid}/controller-mapping"] = p["ctrl_mapping"]

        # Per-savestate detail
        for ssid, ss_detail in p["savestate_details"].items():
            routes[f"GET /api/projects/{pid}/savestates/{ssid}"] = ss_detail
            routes[f"GET /api/projects/{pid}/savestates/{ssid}/findings"] = p["savestate_findings"].get(ssid, [])

        # Per-task detail + files + results
        for tid, detail in p["task_details"].items():
            routes[f"GET /api/projects/{pid}/tasks/{tid}"] = detail

            result = p["task_results"].get(tid, {})
            routes[f"GET /api/projects/{pid}/tasks/{tid}/result"] = result

        # Per-research doc content
        for filename, content in p["research_content"].items():
            routes[f"GET /api/projects/{pid}/research/{filename}"] = {"content": content}

        # Per-gecko code content
        for filename, data in p["gecko_codes_content"].items():
            routes[f"GET /api/projects/{pid}/gecko-codes/{filename}"] = data

    # Build image route table separately (data URIs are large)
    img_routes: dict[str, str] = {}
    for p in projects:
        pid = p["project_id"]
        for ssid, data_uri in p["savestates_screenshots"].items():
            img_routes[f"/api/projects/{pid}/savestates/{ssid}/screenshot"] = data_uri
        for tid, files in p["task_files"].items():
            for fname, data_uri in files.items():
                img_routes[f"/api/projects/{pid}/tasks/{tid}/files/{fname}"] = data_uri

    routes_json = json.dumps(routes, separators=(",", ":"))
    img_routes_json = json.dumps(img_routes, separators=(",", ":"))

    return f"""
// ── DEMO MODE: Static fetch interceptor ─────────────────────────────── //
(function() {{
  const _routes = {routes_json};
  const _imgRoutes = {img_routes_json};
  const _realFetch = window.fetch;

  window.fetch = function(url, opts) {{
    const method = (opts && opts.method) || 'GET';
    // Strip query params for matching
    const cleanUrl = String(url).split('?')[0];
    const key = method.toUpperCase() + ' ' + cleanUrl;

    // Check JSON routes
    if (_routes[key] !== undefined) {{
      return Promise.resolve(new Response(JSON.stringify(_routes[key]), {{
        status: 200,
        headers: {{'Content-Type': 'application/json'}},
      }}));
    }}

    // Check image routes
    if (_imgRoutes[cleanUrl]) {{
      // Convert data URI to blob response
      const dataUri = _imgRoutes[cleanUrl];
      const parts = dataUri.split(',');
      const byteString = atob(parts[1]);
      const ab = new ArrayBuffer(byteString.length);
      const ia = new Uint8Array(ab);
      for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
      return Promise.resolve(new Response(new Blob([ab], {{type: 'image/png'}}), {{status: 200}}));
    }}

    // Demo: block all mutating API calls silently
    if (method !== 'GET') {{
      return Promise.resolve(new Response(JSON.stringify({{detail: 'Demo mode: read-only'}}), {{
        status: 403,
        headers: {{'Content-Type': 'application/json'}},
      }}));
    }}

    // Unmatched GET — return 404
    console.warn('[demo] unmatched route:', key);
    return Promise.resolve(new Response(JSON.stringify({{detail: 'Not found in demo snapshot'}}), {{
      status: 404,
      headers: {{'Content-Type': 'application/json'}},
    }}));
  }};

  // Stub EventSource (no SSE in static mode)
  window.EventSource = function() {{
    this.close = function() {{}};
    this.onmessage = null;
    this.onerror = null;
  }};

  // ── Intercept <img> src for /api/ image paths ─────────────────────── //
  // img.src and innerHTML-based <img src="..."> don't go through fetch(),
  // so we monkey-patch the src setter to resolve data URIs.
  const _origSrcDesc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
  Object.defineProperty(HTMLImageElement.prototype, 'src', {{
    get: function() {{ return _origSrcDesc.get.call(this); }},
    set: function(val) {{
      const clean = String(val).split('?')[0];
      if (_imgRoutes[clean]) {{
        _origSrcDesc.set.call(this, _imgRoutes[clean]);
      }} else {{
        _origSrcDesc.set.call(this, val);
      }}
    }},
    enumerable: true,
    configurable: true,
  }});

  // Also intercept setAttribute('src', ...) for innerHTML-created images
  const _origSetAttr = HTMLImageElement.prototype.setAttribute;
  HTMLImageElement.prototype.setAttribute = function(name, value) {{
    if (name === 'src') {{
      const clean = String(value).split('?')[0];
      if (_imgRoutes[clean]) {{
        return _origSetAttr.call(this, name, _imgRoutes[clean]);
      }}
    }}
    return _origSetAttr.call(this, name, value);
  }};

  // For images created via innerHTML, the browser parses and sets src
  // before our JS runs. Use a MutationObserver to catch those.
  const _imgObserver = new MutationObserver(function(mutations) {{
    for (const m of mutations) {{
      for (const node of m.addedNodes) {{
        if (node.nodeType !== 1) continue;
        const imgs = node.tagName === 'IMG' ? [node] : node.querySelectorAll ? node.querySelectorAll('img') : [];
        for (const img of imgs) {{
          const src = img.getAttribute('src') || '';
          const clean = src.split('?')[0];
          if (_imgRoutes[clean]) {{
            img.src = _imgRoutes[clean];
          }}
        }}
      }}
    }}
  }});
  _imgObserver.observe(document.documentElement, {{ childList: true, subtree: true }});
}})();
"""


# ── HTML patching ────────────────────────────────────────────────────────── #


def patch_html(html: str, interceptor_js: str) -> str:
    """Patch index.html for demo mode."""

    # 1. Inject the interceptor BEFORE the existing <script> tag
    #    so it's available when the app code runs.
    html = html.replace(
        '<script src="/mask-painter.js"></script>',
        '<script src="mask-painter.js"></script>',
    )
    html = html.replace(
        '<link rel="stylesheet" href="/style.css">',
        '<link rel="stylesheet" href="style.css">',
    )

    # Inject interceptor + demo banner right before the main <script>
    demo_banner = ""

    inject_point = '<script src="mask-painter.js"></script>\n  <script>'
    html = html.replace(
        inject_point,
        f'<script src="mask-painter.js"></script>\n{demo_banner}\n  <script>\n{interceptor_js}\n',
    )

    # 2. Top banner + hide interactive elements via CSS
    demo_css = """
<style>
  /* Demo mode: top banner */
  #demo-top-banner {
    position: fixed;
    top: 0; left: 0; right: 0;
    z-index: 9999;
    background: var(--surface);
    border-bottom: 1px solid var(--green-dim);
    padding: 0.45rem 1.5rem;
    font-size: 0.75rem;
    color: var(--green);
    text-align: center;
    letter-spacing: 0.03em;
  }
  /* Push everything down to make room for the banner */
  body { padding-top: 2rem; }
  header { margin-top: 0; }
  /* Fixed views (project, task, knowledge) need top offset too */
  .proj-page, .task-page, #view-knowledge { top: 2rem !important; }
  #global-toolbar { top: 2.75rem !important; }

  /* Demo mode: hide interactive-only elements */
  .upload-form { display: none !important; }
  .ss-upload { display: none !important; }
  .delete-btn { display: none !important; }
  #global-toolbar { display: none !important; }
  #kb-reset-btn { display: none !important; }
  .proj-panel-header button { display: none !important; }
  #run-btn { display: none !important; }
  #inspect-link-inline { display: none !important; }
  #submit-mask-btn { display: none !important; }
  #capture-btn { display: none !important; }
  #savestate-select-btn { display: none !important; }
  #ss-screenshot-btn { display: none !important; }
  .danger { display: none !important; }
</style>
"""
    html = html.replace('</head>', f'{demo_css}\n</head>')

    # 3. Inject top banner right after <body>
    top_banner = '<div id="demo-top-banner">This is a read-only demo of the Daywater research platform. All data shown is from real AI agent reverse-engineering runs.</div>'
    html = html.replace('<body>', f'<body>\n  {top_banner}')

    # 4. Change subtitle
    html = html.replace(
        'gamecube reverse engineering platform',
        'gamecube reverse engineering platform — research demo',
    )

    return html


# ── Main ─────────────────────────────────────────────────────────────────── #


def main() -> None:
    parser = argparse.ArgumentParser(description="Build daywater static demo site")
    parser.add_argument("--out", default="demo-site", help="Output directory")
    parser.add_argument("--sessions", default="./sessions", help="Sessions directory")
    args = parser.parse_args()

    out = Path(args.out)
    sessions = Path(args.sessions)

    print(f"Building demo site -> {out}")

    # Collect projects
    projects: list[dict] = []
    if sessions.exists():
        for proj_dir in sorted(sessions.iterdir()):
            if not (proj_dir / "config.json").exists():
                continue
            print(f"  Collecting project: {proj_dir.name}")
            p = collect_project(proj_dir)
            if p:
                projects.append(p)
    print(f"  {len(projects)} projects collected")

    # Build output
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # Build the fetch interceptor
    print("  Building fetch interceptor...")
    interceptor_js = build_interceptor_js(projects)

    # Read and patch the real index.html
    html = (STATIC_DIR / "index.html").read_text()
    html = patch_html(html, interceptor_js)
    (out / "index.html").write_text(html)

    # Copy static assets
    shutil.copy2(STATIC_DIR / "style.css", out / "style.css")
    shutil.copy2(STATIC_DIR / "mask-painter.js", out / "mask-painter.js")

    total_size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"\nDone! Output: {out}/")
    print(f"  Files: {sum(1 for _ in out.rglob('*') if _.is_file())}")
    print(f"  Total size: {total_size / 1024 / 1024:.1f} MB")
    print(f"\nServe with: python -m http.server -d {out} 8090")


if __name__ == "__main__":
    main()
