# Design Document: World Cup Data — Switch to Football-Data.org API

**Based on:** `implementation_plan.md`  
**Target File:** `scripts/update_sports.py`  
**No changes to:** `index.html`

---

## 1. Overview

The current `get_worldcup_data(serper_key, gemini_key)` relies on a two-step pipeline:
1. Google Search via Serper API (subject to quota exhaustion and region-dependent results)
2. Gemini LLM to parse unstructured search snippets into JSON (subject to hallucination and format errors)

Both steps have proven unreliable in the GitHub Actions environment. Since `FOOTBALL_DATA_API_KEY` is already in use for EPL data and Football-Data.org supports a `WC` competition code on the same v4 API, the correct fix is to replace the entire search pipeline with a single deterministic API call.

**Goal:** Rewrite `get_worldcup_data` to call `https://api.football-data.org/v4/competitions/WC/matches`, filter results to today and tomorrow in KST, and return the same output schema that `sports.json["worldcup"]` already expects.

---

## 2. API Reference — Football-Data.org v4 `WC` Endpoint

### Request

```
GET https://api.football-data.org/v4/competitions/WC/matches
Headers:
    X-Auth-Token: {football_key}
Query Parameters:
    dateFrom  YYYY-MM-DD   (UTC date, lower bound, inclusive)
    dateTo    YYYY-MM-DD   (UTC date, upper bound, inclusive)
```

The `dateFrom` / `dateTo` parameters filter by the UTC calendar date of the match. Because KST is UTC+9, a match played at 23:00 UTC on June 14 appears as 08:00 KST on June 15. To ensure no KST-today matches are dropped, the request must widen the UTC window by ±1 day relative to KST; the KST-based filter is then applied locally (see Section 4).

### Response Structure

```json
{
  "competition": {
    "id": 2000,
    "name": "FIFA World Cup",
    "code": "WC"
  },
  "season": {
    "currentMatchday": 3
  },
  "matches": [
    {
      "id": 123456,
      "utcDate": "2026-06-15T14:00:00Z",
      "status": "SCHEDULED",
      "stage": "GROUP_STAGE",
      "group": "GROUP_A",
      "matchday": 1,
      "homeTeam": {
        "id": 770,
        "name": "Mexico",
        "shortName": "Mexico",
        "tla": "MEX"
      },
      "awayTeam": {
        "id": 771,
        "name": "United States",
        "shortName": "USA",
        "tla": "USA"
      },
      "score": {
        "winner": null,
        "duration": "REGULAR",
        "fullTime": { "home": null, "away": null },
        "halfTime": { "home": null, "away": null }
      }
    }
  ]
}
```

**Key fields used by the new function:**

| API field | Used for |
|---|---|
| `matches[i].utcDate` | KST conversion and date filtering |
| `matches[i].status` | Status mapping (see Section 5) |
| `matches[i].stage` | Phase label derivation (see Section 6) |
| `matches[i].group` | Group label normalization (see Section 7) |
| `matches[i].homeTeam.name` | `home` field in output |
| `matches[i].awayTeam.name` | `away` field in output |
| `matches[i].score.fullTime.home` | Score numerator (LIVE / FINISHED only) |
| `matches[i].score.fullTime.away` | Score denominator (LIVE / FINISHED only) |

---

## 3. Function Interface Design

### Signature

```python
def get_worldcup_data(football_key: str) -> dict:
```

**Replaces:** `def get_worldcup_data(serper_key, gemini_key)`

### Input

| Parameter | Type | Description |
|---|---|---|
| `football_key` | `str \| None` | Value of `FOOTBALL_DATA_API_KEY` environment variable. If `None` or empty, the function returns the empty default immediately. |

### Return Value Schema

```python
{
    "phase": str,     # Human-readable tournament phase label (see Section 6)
    "matches": list   # List of match dicts (see below). Empty list if no matches today/tomorrow.
}
```

Each element of `"matches"`:

```python
{
    "home":     str,  # Home team full name, e.g. "Mexico"
    "away":     str,  # Away team full name, e.g. "United States"
    "kst_date": str,  # "MM.DD" format, e.g. "06.15"
    "kst_time": str,  # "HH:MM" 24-hour format (KST), e.g. "23:00"
    "score":    str,  # "H-A" if LIVE or FINISHED and scores are available, else ""
    "status":   str,  # One of: "LIVE", "FINISHED", "SCHEDULED"
    "group":    str   # Human-readable group/stage label, e.g. "Group A", or "" if not available
}
```

**On any failure** (missing key, HTTP error, parsing error), the function returns:
```python
{"phase": "Group Stage", "matches": []}
```

---

## 4. KST Date-Filtering Pseudocode

```
FUNCTION get_worldcup_data(football_key):

    IF football_key is None OR football_key is empty:
        log("⚠️ FOOTBALL_DATA_API_KEY 없음 → World Cup 수집 불가")
        RETURN {"phase": "Group Stage", "matches": []}

    kst_now        ← get_kst_now()
    today_kst_str  ← kst_now.strftime("%m.%d")               # e.g. "06.15"
    tomorrow_kst_str ← (kst_now + 1 day).strftime("%m.%d")   # e.g. "06.16"

    # Widen the UTC window by ±1 day to capture KST timezone shift (UTC+9)
    date_from ← (kst_now.date() - 1 day).strftime("%Y-%m-%d")  # e.g. "2026-06-14"
    date_to   ← (kst_now.date() + 1 day).strftime("%Y-%m-%d")  # e.g. "2026-06-16"

    url     ← f"{FOOTBALL_DATA_API_URL}/competitions/WC/matches"
    headers ← {"X-Auth-Token": football_key}
    params  ← {"dateFrom": date_from, "dateTo": date_to}

    TRY:
        response ← requests.get(url, headers=headers, params=params, timeout=10)

        IF response.status_code != 200:
            log(f"⚠️ Football-Data WC API error: status={response.status_code}, body={response.text[:300]}")
            RETURN {"phase": "Group Stage", "matches": []}

        all_matches ← response.json().get("matches", [])
        log(f"[WorldCup] API 응답: {len(all_matches)}경기 (UTC {date_from} ~ {date_to})")

    EXCEPT Exception as e:
        log(f"⚠️ Football-Data WC API exception: {e}")
        RETURN {"phase": "Group Stage", "matches": []}

    phase          ← "Group Stage"   # default; updated as matches are processed
    output_matches ← []

    FOR match IN all_matches:

        utc_date  ← match.get("utcDate", "")
        time_info ← convert_utc_to_kst(utc_date)   # returns dict or None

        IF time_info is None:
            CONTINUE

        kst_date ← time_info["kst_date"]            # "MM.DD"

        # ── KST date filter: keep only today and tomorrow ──
        IF kst_date NOT IN {today_kst_str, tomorrow_kst_str}:
            CONTINUE

        # ── Status mapping (Section 5) ──
        raw_status ← match.get("status", "")
        status     ← map_status(raw_status)

        # ── Score extraction (Section 5) ──
        score ← extract_score(match, status)

        # ── Phase update (Section 6) ──
        stage       ← match.get("stage", "")
        phase_label ← map_stage_to_phase(stage)
        IF phase_label is not None:
            phase ← phase_label

        # ── Group label (Section 7) ──
        group_raw ← match.get("group") or ""
        group     ← normalize_group(group_raw, stage)

        # ── Team names ──
        home ← match.get("homeTeam", {}).get("name", "").strip()
        away ← match.get("awayTeam", {}).get("name", "").strip()

        IF home is empty OR away is empty:
            CONTINUE

        output_matches.APPEND({
            "home":     home,
            "away":     away,
            "kst_date": time_info["kst_date"],
            "kst_time": time_info["kst_time"],
            "score":    score,
            "status":   status,
            "group":    group
        })

    log(f"✅ World Cup 데이터: {len(output_matches)}경기 ({phase})")
    FOR m IN output_matches:
        icon ← "🔴" if LIVE, "✅" if FINISHED, else "📅"
        log(f"   {icon} {m.kst_date} {m.kst_time} KST | {m.home} vs {m.away} [{m.status}] {m.score} {m.group}")

    RETURN {"phase": phase, "matches": output_matches}
```

---

## 5. Status Mapping and Score Extraction Rules

### Status Mapping

| Football-Data.org `status` value | Output `status` |
|---|---|
| `"IN_PLAY"` | `"LIVE"` |
| `"PAUSED"` | `"LIVE"` |
| `"FINISHED"` | `"FINISHED"` |
| `"AWARDED"` | `"FINISHED"` |
| `"SCHEDULED"` | `"SCHEDULED"` |
| `"TIMED"` | `"SCHEDULED"` |
| `"POSTPONED"` | `"SCHEDULED"` |
| `"SUSPENDED"` | `"SCHEDULED"` |
| `"CANCELLED"` | `"SCHEDULED"` |
| Any other / empty | `"SCHEDULED"` |

```
FUNCTION map_status(raw_status):
    IF raw_status IN ("IN_PLAY", "PAUSED"):
        RETURN "LIVE"
    ELIF raw_status IN ("FINISHED", "AWARDED"):
        RETURN "FINISHED"
    ELSE:
        RETURN "SCHEDULED"
```

### Score Extraction

```
FUNCTION extract_score(match, status):
    IF status NOT IN ("LIVE", "FINISHED"):
        RETURN ""
    full_time  ← match.get("score", {}).get("fullTime", {})
    home_score ← full_time.get("home")
    away_score ← full_time.get("away")
    IF home_score is not None AND away_score is not None:
        RETURN f"{home_score}-{away_score}"
    RETURN ""
```

---

## 6. Phase Label Derivation

### Stage → Phase Mapping Table

| Football-Data.org `stage` value | Output `phase` |
|---|---|
| `"GROUP_STAGE"` | `"Group Stage"` |
| `"LAST_16"` | `"Round of 16"` |
| `"ROUND_OF_16"` | `"Round of 16"` |
| `"QUARTER_FINALS"` | `"Quarter-Finals"` |
| `"SEMI_FINALS"` | `"Semi-Finals"` |
| `"THIRD_PLACE"` | `"Third Place"` |
| `"FINAL"` | `"Final"` |
| Empty / unknown | `None` (phase unchanged; default `"Group Stage"` preserved) |

---

## 7. Group Label Normalization

```
FUNCTION normalize_group(group_raw, stage):
    IF group_raw is None OR group_raw is empty:
        RETURN ""
    IF group_raw.startswith("GROUP_"):
        RETURN "Group " + group_raw[6:]   # "GROUP_A" → "Group A"
    RETURN group_raw.replace("_", " ").title()
```

---

## 8. Changes to `update_sports_data()` — Parameter Flow

### Step 5a call site (approximately lines 2376–2382)

**Current:**
```python
    # STEP 5a: 2026 FIFA World Cup (Serper + Gemini)
    log("\n🏆 [Step 5a] 2026 FIFA World Cup (Serper + Gemini)...")
    worldcup_data = get_worldcup_data(serper_api_key, gemini_api_key)
    log(f"   ✅ Phase: {worldcup_data['phase']} | Matches: {len(worldcup_data['matches'])}경기")
```

**Replace with:**
```python
    # STEP 5a: 2026 FIFA World Cup (Football-Data.org API)
    log("\n🏆 [Step 5a] 2026 FIFA World Cup (Football-Data.org API)...")
    worldcup_data = get_worldcup_data(football_api_key)
    log(f"   ✅ Phase: {worldcup_data['phase']} | Matches: {len(worldcup_data['matches'])}경기")
```

---

## 9. Complete Replacement — `get_worldcup_data` Function

Find the existing `get_worldcup_data` function and **replace it entirely** with:

```python
# =============================================================================
# World Cup 함수 (Football-Data.org API — competition code: WC)
# =============================================================================
def get_worldcup_data(football_key):
    """
    2026 FIFA World Cup 오늘/내일 경기 수집 (Football-Data.org API v4)
    Endpoint: /v4/competitions/WC/matches

    Returns:
        dict: {"phase": str, "matches": list}
    """
    if not football_key:
        log("   ⚠️ FOOTBALL_DATA_API_KEY 없음 → World Cup 데이터 수집 불가")
        return {"phase": "Group Stage", "matches": []}

    kst_now = get_kst_now()
    today_kst_str    = kst_now.strftime("%m.%d")
    tomorrow_kst_str = (kst_now + timedelta(days=1)).strftime("%m.%d")

    date_from = (kst_now.date() - timedelta(days=1)).strftime("%Y-%m-%d")
    date_to   = (kst_now.date() + timedelta(days=1)).strftime("%Y-%m-%d")

    url     = f"{FOOTBALL_DATA_API_URL}/competitions/WC/matches"
    headers = {"X-Auth-Token": football_key}
    params  = {"dateFrom": date_from, "dateTo": date_to}

    STAGE_TO_PHASE = {
        "GROUP_STAGE":    "Group Stage",
        "LAST_16":        "Round of 16",
        "ROUND_OF_16":    "Round of 16",
        "QUARTER_FINALS": "Quarter-Finals",
        "SEMI_FINALS":    "Semi-Finals",
        "THIRD_PLACE":    "Third Place",
        "FINAL":          "Final",
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code != 200:
            log(f"   ⚠️ Football-Data WC API error: status={response.status_code}, body={response.text[:300]}")
            return {"phase": "Group Stage", "matches": []}
        all_matches = response.json().get("matches", [])
        log(f"   [WorldCup] API 응답: {len(all_matches)}경기 (UTC {date_from}~{date_to})")
    except Exception as e:
        log(f"   ⚠️ Football-Data WC API exception: {e}")
        return {"phase": "Group Stage", "matches": []}

    phase = "Group Stage"
    output_matches = []

    for match in all_matches:
        utc_date  = match.get("utcDate", "")
        time_info = convert_utc_to_kst(utc_date)
        if not time_info:
            continue

        kst_date = time_info["kst_date"]
        if kst_date not in (today_kst_str, tomorrow_kst_str):
            continue

        raw_status = match.get("status", "")
        if raw_status in ("IN_PLAY", "PAUSED"):
            status = "LIVE"
        elif raw_status in ("FINISHED", "AWARDED"):
            status = "FINISHED"
        else:
            status = "SCHEDULED"

        if status in ("LIVE", "FINISHED"):
            ft = match.get("score", {}).get("fullTime", {})
            h, a = ft.get("home"), ft.get("away")
            score = f"{h}-{a}" if h is not None and a is not None else ""
        else:
            score = ""

        stage = match.get("stage", "")
        phase_label = STAGE_TO_PHASE.get(stage)
        if phase_label:
            phase = phase_label

        group_raw = match.get("group") or ""
        if group_raw.startswith("GROUP_"):
            group = "Group " + group_raw[6:]
        elif group_raw:
            group = group_raw.replace("_", " ").title()
        else:
            group = ""

        home = match.get("homeTeam", {}).get("name", "").strip()
        away = match.get("awayTeam", {}).get("name", "").strip()
        if not home or not away:
            continue

        output_matches.append({
            "home":     home,
            "away":     away,
            "kst_date": time_info["kst_date"],
            "kst_time": time_info["kst_time"],
            "score":    score,
            "status":   status,
            "group":    group
        })

    log(f"   ✅ World Cup 데이터: {len(output_matches)}경기 ({phase})")
    for m in output_matches:
        icon = "🔴" if m["status"] == "LIVE" else ("✅" if m["status"] == "FINISHED" else "📅")
        log(f"      {icon} {m['kst_date']} {m['kst_time']} KST | {m['home']} vs {m['away']} [{m['status']}] {m['score']} {m['group']}")

    return {"phase": phase, "matches": output_matches}
```

---

## 10. Scope and Constraints

- **Single file change.** Only `scripts/update_sports.py` is modified. `index.html` and all other files are untouched.
- **No new imports.** `requests`, `timedelta`, `FOOTBALL_DATA_API_URL`, `convert_utc_to_kst`, `get_kst_now`, and `log` are all already available.
- **No new environment variables.** `FOOTBALL_DATA_API_KEY` (already in GitHub Secrets) is reused. `SERPER_API_KEY` and `GEMINI_API_KEY` are no longer consumed by this function.
- **Output schema unchanged.** `sports.json["worldcup"]` structure is identical, so `index.html` needs no changes.
- **`debug.logs` integration automatic.** All `log()` calls inside the new function feed into `LOG_MESSAGES` and appear in `debug.logs`.

---

## 11. Verification Checklist

### Local
1. Run `python scripts/update_sports.py`.
2. Console shows `[Step 5a] 2026 FIFA World Cup (Football-Data.org API)`.
3. No `"⚠️ Football-Data WC API error"` appears.
4. `sports.json` has non-empty `worldcup.matches` with correct KST dates.

### GitHub Actions
1. Push to `main` and manually trigger `Update Sports Data`.
2. Pull and inspect `sports.json`:
   - `worldcup.matches` non-empty → fix confirmed.
   - `debug.logs` shows `"status=403"` → free tier does not include WC; plan upgrade needed.
   - `debug.logs` shows `"status=404"` → `WC` competition code not yet active on the API.
   - `debug.logs` shows `"API 응답: 0경기"` with no error → verify the ±1 day UTC window logic.
