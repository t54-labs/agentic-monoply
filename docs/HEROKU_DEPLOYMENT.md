# 🚀 Heroku Deployment Guide

## 📋 Pre-Deployment Checklist

### 1. Required Environment Variables

```bash
# OpenAI config (required)
heroku config:set OPENAI_API_KEY=your_openai_api_key_here

# TPay/TLedger config (payment system)
heroku config:set TLEDGER_API_KEY=your_tledger_api_key
heroku config:set TLEDGER_API_SECRET=your_tledger_api_secret  
heroku config:set TLEDGER_PROJECT_ID=your_tledger_project_id
heroku config:set TLEDGER_BASE_URL=https://api.tpay.com

# Admin config
heroku config:set ADMIN_SECRET_KEY=your_admin_secret_key

# Database config (Heroku automatically provides DATABASE_URL)
# If you’re using a custom DB, set these:
heroku config:set DB_USER=your_db_user
heroku config:set DB_PASSWORD=your_db_password
heroku config:set DB_HOST=your_db_host
heroku config:set DB_PORT=5432
heroku config:set DB_NAME=monopoly

# Runtime config
heroku config:set RUN_CONTEXT=production
```

### 2. Add a PostgreSQL Database

```bash
heroku addons:create heroku-postgresql:essential-0
```

## 🔧 Deployment Files

The project already includes all the necessary deployment files:

* ✅ `Procfile` – Defines how to start the web server
* ✅ `requirements.txt` – Python dependencies (includes the local TPay SDK)
* ✅ `runtime.txt` – Python version (3.11.0)

## 🚀 Deployment Steps

### 1. Log In to the Heroku CLI

```bash
heroku login
```

### 2. Create a Heroku App

```bash
heroku create your-app-name
```

### 3. Push Your Code

```bash
git add .
git commit -m "Ready for Heroku deployment"
git push heroku main
```

### 4. Scale the Web Process

```bash
heroku ps:scale web=1
```

### 5. View Logs

```bash
heroku logs --tail
```

## 🏗️ App Architecture

* **Web Server**: FastAPI + Uvicorn
* **Database**: PostgreSQL (Heroku Postgres)
* **AI Engine**: OpenAI GPT
* **Payment System**: TPay SDK (local package)
* **Real-Time Comms**: WebSocket

## 🌐 Accessing the App

Once deployed, visit:

* **Game Lobby**: `https://your-app-name.herokuapp.com/`
* **API Docs**: `https://your-app-name.herokuapp.com/docs`
* **Admin Panel**: `https://your-app-name.herokuapp.com/api/admin/`

## 🔍 Troubleshooting

### Common Issues

1. **App Won’t Start**

   ```bash
   heroku logs --tail
   ```

   Check for missing required env vars.

2. **Database Connection Error**

   ```bash
   heroku config:get DATABASE_URL
   ```

   Make sure the database was added correctly.

3. **OpenAI API Errors**

   ```bash
   heroku config:get OPENAI_API_KEY
   ```

   Verify that the API key is correct.

4. **Local TPay Package Fails to Install**

   * Ensure `dist/tpay-0.1.1.tar.gz` is committed to git.
   * Double-check the path in `requirements.txt`.

### Performance Tips

```bash
# Monitor app performance
heroku logs --tail --app your-app-name

# View metrics  
heroku addons:create newrelic:wayne

# Increase dyno size (if needed)
heroku ps:resize web=standard-2x
```

## 📊 Monitoring & Maintenance

### Health-Check Endpoints

* `GET /api/admin/games/status` – Game status
* `GET /api/admin/agents/status` – AI agent status
* `GET /api/admin/config` – Config info

### Routine Maintenance

```bash
# Restart the app
heroku restart

# Database maintenance
heroku pg:reset DATABASE_URL --confirm your-app-name
heroku run python database.py
```

## 🔐 Security Configuration

1. **Enable HTTPS**: Provided automatically by Heroku
2. **Environment Variables**: Never hard-code secrets in code
3. **Admin Key**: Use a strong password for `ADMIN_SECRET_KEY`
4. **Database**: Rely on Heroku Postgres’ built-in security features

## 📈 Extended Deployment

### Automatic Deployment

```bash
# Link to GitHub (optional)
heroku git:remote -a your-app-name
heroku buildpacks:add heroku/python

# Set up auto-deploy
# Connect your GitHub repo in the Heroku Dashboard
```

### CI/CD Integration

The project includes a GitHub Actions workflow that can:

* Automatically run tests
* Check code quality
* Deploy to Heroku once tests pass

---

🎮 **Once deployment is complete, your Monopoly game server will be up and running on Heroku!**
