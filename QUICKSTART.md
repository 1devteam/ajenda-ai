# Omnipath v5.0 - Quick Start Guide

**For Obex Blackvault** - Get up and running in 5 minutes

---

## Step 1: Pull the Code (30 seconds)

```bash
cd /home/inmoa/projects/omnipath_v2
git checkout v5.0-rewrite
git pull origin v5.0-rewrite
```

---

## Step 2: Start Everything (2 minutes)

```bash
# Stop old containers
docker-compose -f docker-compose.v3.yml down

# Rebuild with new code
docker-compose -f docker-compose.v3.yml build --no-cache backend

# Start all services
docker-compose -f docker-compose.v3.yml up -d

# Wait for services to be healthy (about 30 seconds)
sleep 30
```

---

## Step 3: Verify It Works (1 minute)

```bash
# Check all containers are running
docker-compose -f docker-compose.v3.yml ps

# Test backend
curl http://localhost:8000/health

# Should return:
# {"status":"ok","service":"Omnipath","version":"5.0.0","environment":"development"}

# Check metrics are working
curl http://localhost:8000/metrics | head -20
```

---

## Step 4: Open the Interfaces (1 minute)

**Open these URLs in your browser:**

1. **API Documentation**
   - http://localhost:8000/docs
   - Interactive API explorer

2. **Grafana Dashboards**
   - http://localhost:3000
   - Login: `admin` / `admin`
   - Go to Dashboards → See 3 dashboards

3. **Prometheus**
   - http://localhost:9090
   - Query: `omnipath_http_requests_total`

4. **Jaeger Tracing**
   - http://localhost:16686
   - Select "omnipath" service

---

## Step 5: Try the CLI (30 seconds)

```bash
cd cli
pip install -r requirements.txt
./omnipath.py status
./omnipath.py --help
```

---

## 🎉 You're Done!

**What you have now:**

✅ Omnipath v5.0 backend running  
✅ Real-time metrics in Prometheus  
✅ Beautiful Grafana dashboards  
✅ Distributed tracing in Jaeger  
✅ Meta-learning API endpoints  
✅ CLI for quick operations  

---

## What to Try Next

### 1. Generate Some Data

```bash
# Hit the API a few times
for i in {1..20}; do
  curl http://localhost:8000/health
  sleep 0.5
done
```

### 2. Watch Metrics Flow

- Open Grafana: http://localhost:3000
- Go to "System Overview" dashboard
- Watch the HTTP requests panel update in real-time

### 3. Try Meta-Learning Endpoints

```bash
# System insights
curl http://localhost:8000/api/v1/meta-learning/system-insights

# Leaderboard (will be empty until you have agents)
curl http://localhost:8000/api/v1/meta-learning/leaderboard
```

### 4. Explore with CLI

```bash
cd cli

# Check status
./omnipath.py status

# List agents (empty for now)
./omnipath.py agent list

# See all commands
./omnipath.py --help
```

---

## Troubleshooting

**Backend not responding?**

```bash
# Check logs
docker logs omnipath-backend

# Restart if needed
docker-compose -f docker-compose.v3.yml restart backend
```

**Grafana showing "No data"?**

- Generate some traffic (see "Generate Some Data" above)
- Wait 5-10 seconds for metrics to flow
- Refresh the dashboard

**CLI can't connect?**

```bash
# Configure the API URL
./omnipath.py config

# Enter: http://localhost:8000
```

---

## Next Steps

1. Read `V5_README.md` for complete documentation
2. Check `grafana/README.md` for dashboard customization
3. Explore the API at http://localhost:8000/docs
4. Create agents and run missions to see meta-learning in action

---

**Need Help?**

- Check logs: `docker logs omnipath-backend`
- View all services: `docker-compose -f docker-compose.v3.yml ps`
- Read full docs: `V5_README.md`

---

**Welcome to Omnipath v5.0! 🚀**
