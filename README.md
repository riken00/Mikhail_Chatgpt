# 📊 Weekly Stats API

This API provides **day-wise weekly statistics** for background processing scripts such as:

* `crawler2`
* `news_tagger`
* `llm_calls`

It aggregates data from the database and returns:

* Processed count
* Success / Failure
* Success rate
* Average processing time
* Weekly summary

---

## 🚀 Endpoint

```
GET /api/stats/weekly/
```

---

## 🔧 Query Parameters

| Parameter | Type   | Required | Description                              |
| --------- | ------ | -------- | ---------------------------------------- |
| `file`    | string | ❌        | Name of the script (default: `crawler2`) |
| `date`    | string | ❌        | Reference date in format `DD/MM/YYYY`    |

---

## 📌 Behavior

* If `date` is **not provided** → returns stats for **current week**
* If `date` is provided → returns stats for the **week containing that date**
* Week starts on **Monday** and ends on **Sunday**
* Missing days are automatically filled with `0` values

---

## 🧪 Examples

### ✅ 1. Get current week stats (default: crawler2)

```bash
curl -X GET "http://localhost:8000/api/stats/weekly/"
```

---

### ✅ 2. Get stats for a specific script

```bash
curl -X GET "http://localhost:8000/api/stats/weekly/?file=news_tagger"
```

---

### ✅ 3. Get stats for a specific date

```bash
curl -X GET "http://localhost:8000/api/stats/weekly/?file=crawler2&date=31/12/2025"
```

---

## 📊 Response Format

```json
{
  "file_name": "crawler2",
  "week_range": {
    "from": "30-12-2025",
    "to": "05-01-2026"
  },
  "summary": {
    "processed": 1200,
    "success": 1100,
    "failed": 100,
    "success_rate": 91.67,
    "avg_time": 0.82
  },
  "daily": [
    {
      "date": "30-12-2025",
      "day": "Monday",
      "processed": 200,
      "success": 180,
      "failed": 20,
      "success_rate": 90.0,
      "avg_time": 0.8
    }
  ]
}
```

---

## ⚠️ Error Handling

### Invalid date format

```bash
curl -X GET "http://localhost:8000/api/stats/weekly/?date=2025-12-31"
```

Response:

```json
{
  "error": "Invalid date format. Use DD/MM/YYYY"
}
```

---

## 💡 Notes

* No authentication required
* Optimized for frontend dashboards
* Supports multiple processing pipelines via `file` parameter
* Data is aggregated from daily stats table

---

## 🛠️ Typical Use Cases

* Monitoring crawler performance
* Tracking LLM success rate
* Debugging failure spikes
* Building dashboards (React, Grafana, etc.)

---
