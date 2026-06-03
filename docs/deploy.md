# Sentinel — Cloud Run deploy runbook

This is the minimum-viable path to put Sentinel on Cloud Run for the
hackathon demo URL. Two services: `sentinel-api` (FastAPI + SSE) and
`sentinel-web` (Next.js). Phoenix stays self-hosted; see the bottom of
this doc for options.

> **Cost note.** A single Cloud Run service idles at $0/hr with min
> instances = 0. Vertex AI Vector Search index endpoint is **not** free
> — it runs ~$0.45/hour while deployed. Set `SENTINEL_MEMORY_BACKEND=local`
> for the demo URL unless precedent recall on prod traffic is required.

---

## Prereqs (run once)

```bash
gcloud auth login
gcloud config set project <YOUR_PROJECT_ID>
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  aiplatform.googleapis.com

# Artifact Registry repo to host the two images
gcloud artifacts repositories create sentinel \
  --repository-format=docker \
  --location=us-central1 \
  --description="Sentinel agent images"
```

Set local shell variables that the rest of this doc reuses:

```bash
export PROJECT_ID="$(gcloud config get-value project)"
export REGION=us-central1
export REPO=sentinel
```

---

## 1. Deploy the API

```bash
# Build + push (Cloud Build, so no local docker daemon required)
gcloud builds submit \
  --tag "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/sentinel-api:latest" \
  --config /dev/null \
  --file Dockerfile.api \
  .

# Deploy
gcloud run deploy sentinel-api \
  --image "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/sentinel-api:latest" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600 \
  --concurrency 20 \
  --min-instances 0 \
  --max-instances 4 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
  --set-env-vars "GOOGLE_CLOUD_LOCATION=global" \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=true" \
  --set-env-vars "SENTINEL_MEMORY_BACKEND=local" \
  --set-env-vars "LOG_LEVEL=INFO"
```

Notes:
- `--timeout 3600` is required for the SSE streams (default 5 min would
  kill long incidents).
- `--allow-unauthenticated` because the demo URL must be reachable from
  the judge's browser. Add IAM auth later if needed.
- ADC works because Cloud Run injects a service-account identity by
  default. Grant it `roles/aiplatform.user`:

  ```bash
  PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role "roles/aiplatform.user"
  ```

Grab the URL Cloud Run printed (e.g.
`https://sentinel-api-xxx.run.app`) — the web service needs it.

```bash
export API_URL="$(gcloud run services describe sentinel-api --region "${REGION}" --format='value(status.url)')"
```

---

## 2. Deploy the web frontend

The Next.js build bakes `NEXT_PUBLIC_API_BASE_URL` in at compile time, so
it goes through a `--build-arg`:

```bash
gcloud builds submit \
  --tag "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/sentinel-web:latest" \
  --config /dev/null \
  --file web/Dockerfile \
  --substitutions=_API_URL="${API_URL}" \
  ./web
```

> If `gcloud builds submit` doesn't accept `--build-arg` in your version
> (it varies), use a one-line `cloudbuild.yaml` or just build locally:
>
> ```bash
> docker build -f web/Dockerfile \
>   --build-arg NEXT_PUBLIC_API_BASE_URL="${API_URL}" \
>   -t "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/sentinel-web:latest" \
>   ./web
> docker push "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/sentinel-web:latest"
> ```

Then:

```bash
gcloud run deploy sentinel-web \
  --image "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/sentinel-web:latest" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 4
```

Grab the URL and open it in a browser:

```bash
gcloud run services describe sentinel-web --region "${REGION}" --format='value(status.url)'
```

---

## 3. Phoenix (optional)

For the hackathon demo URL, the simplest path is to skip remote Phoenix
and let the API run without an OTLP exporter target — traces still
emit through OpenInference but go nowhere. The agents work end-to-end
without Phoenix being reachable.

If you want Phoenix in the cloud:

```bash
gcloud run deploy sentinel-phoenix \
  --image arizephoenix/phoenix:latest \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 1 \
  --port 6006 \
  --min-instances 1 \
  --max-instances 1

export PHOENIX_URL="$(gcloud run services describe sentinel-phoenix --region "${REGION}" --format='value(status.url)')"
```

Then redeploy the API with the OTLP endpoint pointed at it:

```bash
gcloud run services update sentinel-api \
  --region "${REGION}" \
  --update-env-vars "PHOENIX_COLLECTOR_ENDPOINT=${PHOENIX_URL}"
```

> Cloud Run's auto-scaling means Phoenix can lose in-memory state when
> idle scales it to zero. Pin `--min-instances 1` to keep traces. For a
> demo, a fresh trace history per cold-start is usually fine.

---

## 4. Tear down

```bash
gcloud run services delete sentinel-api    --region "${REGION}" --quiet
gcloud run services delete sentinel-web    --region "${REGION}" --quiet
gcloud run services delete sentinel-phoenix --region "${REGION}" --quiet
```

If Vector Search was provisioned (`scripts/setup_vector_search.py`),
undeploy the index endpoint separately — it bills hourly while up.
