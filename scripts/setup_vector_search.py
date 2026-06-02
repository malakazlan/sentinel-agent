"""One-time Vertex AI Vector Search provisioning for Sentinel memory.

Creates a Matching Engine Index + Endpoint + deploys the index, then writes
the resource names to ``data/memory/vector_search_config.json`` for the
runtime to consume.

USAGE (one-time, takes ~30–60 minutes total wall-clock):

    .\\.venv\\Scripts\\python.exe scripts\\setup_vector_search.py

Required env (read from .env):

    GOOGLE_CLOUD_PROJECT       — your GCP project ID (e.g. alphalens-478615)
    GOOGLE_CLOUD_LOCATION      — region for the index; ``us-central1`` works
                                 (Vector Search regional endpoints are
                                 separate from Gemini's ``global`` endpoint)

Optional:

    SENTINEL_VECTOR_INDEX_NAME — display name for the index (default:
                                 ``sentinel-incident-memory``)

Costs (as of 2026-06):

    - Index storage: ~$1/GB/month. Our index is tiny (KB).
    - Endpoint runtime: ~$0.45/hour while deployed. ~$10/day if left running.
      DEPLOY ONLY WHEN ACTIVELY DEMOING. Use the cleanup script to undeploy.

This script is idempotent: if the index/endpoint already exist (matched by
display name), it reuses them rather than creating duplicates.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _require(env: str) -> str:
    val = os.environ.get(env)
    if not val:
        print(f"FATAL: env var {env} is required (set in .env)", file=sys.stderr)
        sys.exit(1)
    return val


def main() -> None:
    project = _require("GOOGLE_CLOUD_PROJECT")
    # Vector Search endpoints are regional, NOT global. Default to
    # us-central1 if the user has GOOGLE_CLOUD_LOCATION=global (which is
    # what Gemini 3 uses) — the two products use different region pools.
    raw_loc = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    location = "us-central1" if raw_loc == "global" else raw_loc
    if raw_loc == "global":
        print(
            "NOTE: GOOGLE_CLOUD_LOCATION=global is Gemini-only; using "
            "us-central1 for Vector Search (regional product).\n"
        )

    display_name = os.environ.get("SENTINEL_VECTOR_INDEX_NAME", "sentinel-incident-memory")
    endpoint_display_name = f"{display_name}-endpoint"

    print(f"Provisioning Vertex AI Vector Search in {project}/{location}...")
    print(f"  Index display name:    {display_name}")
    print(f"  Endpoint display name: {endpoint_display_name}")
    print()

    from google.cloud import aiplatform

    aiplatform.init(project=project, location=location)

    # ── 1. Index ──────────────────────────────────────────────────────────
    existing_indexes = aiplatform.MatchingEngineIndex.list(
        filter=f'display_name="{display_name}"'
    )
    if existing_indexes:
        index = existing_indexes[0]
        print(f"[reuse] Index already exists: {index.resource_name}")
    else:
        print("[create] Creating index (this can take 20–40 minutes)...")
        index = aiplatform.MatchingEngineIndex.create_tree_ah_index(
            display_name=display_name,
            description="Sentinel persistent incident memory (Phase 7 / ADR-013).",
            dimensions=768,  # text-embedding-004 default
            approximate_neighbors_count=10,
            distance_measure_type="COSINE_DISTANCE",
            leaf_node_embedding_count=500,
            leaf_nodes_to_search_percent=10,
            index_update_method="STREAM_UPDATE",
        )
        print(f"[ok] Created index: {index.resource_name}")

    # ── 2. Endpoint ───────────────────────────────────────────────────────
    existing_endpoints = aiplatform.MatchingEngineIndexEndpoint.list(
        filter=f'display_name="{endpoint_display_name}"'
    )
    if existing_endpoints:
        endpoint = existing_endpoints[0]
        print(f"[reuse] Endpoint already exists: {endpoint.resource_name}")
    else:
        print("[create] Creating index endpoint (public access)...")
        endpoint = aiplatform.MatchingEngineIndexEndpoint.create(
            display_name=endpoint_display_name,
            description="Sentinel Vector Search query endpoint.",
            public_endpoint_enabled=True,
        )
        print(f"[ok] Created endpoint: {endpoint.resource_name}")

    # ── 3. Deploy index to endpoint ───────────────────────────────────────
    deployed_index_id_safe = display_name.replace("-", "_")
    already_deployed = any(
        d.id == deployed_index_id_safe for d in (endpoint.deployed_indexes or [])
    )
    if already_deployed:
        print(f"[reuse] Index already deployed as {deployed_index_id_safe}")
    else:
        print(
            f"[deploy] Deploying index to endpoint (this can take 10–30 minutes)..."
        )
        endpoint = endpoint.deploy_index(
            index=index,
            deployed_index_id=deployed_index_id_safe,
            display_name=f"{display_name}-deployment",
            min_replica_count=1,
            max_replica_count=1,
        )
        print(f"[ok] Deployed index as {deployed_index_id_safe}")

    # ── 4. Write runtime config ───────────────────────────────────────────
    config_path = Path("data/memory/vector_search_config.json")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "project": project,
        "location": location,
        "index_resource_name": index.resource_name,
        "endpoint_resource_name": endpoint.resource_name,
        "deployed_index_id": deployed_index_id_safe,
        "dimensions": 768,
        "distance_measure": "COSINE_DISTANCE",
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print()
    print(f"[ok] Wrote runtime config to {config_path}")
    print()
    print("Set SENTINEL_MEMORY_BACKEND=vector_search in .env to use the new")
    print("backend. Local JSONL fallback remains available via")
    print("SENTINEL_MEMORY_BACKEND=local (or unset).")
    print()
    print(
        "REMINDER: the endpoint costs ~$0.45/hour while deployed. "
        "Undeploy when not actively demoing."
    )


if __name__ == "__main__":
    main()
