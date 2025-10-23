# 📘 Freelancer Admin App — README

A lightweight **Flask-based web application** to help freelancers or small studios manage clients, roles, and projects (“jobs”), track invoices, and optionally sync jobs with **Google Calendar**.

---

## 🚀 1. Installation

### Requirements
- Python 3.9 or higher  
- SQLite (included by default)  
- Flask and SQLAlchemy (already in `requirements.txt`)

### Basic local Installation

```bash
cd freelancer-admin-app
pip install -r requirements.txt
python app.py
```

The app will start locally at:

```
http://localhost:5000
```

### Running on a Synology NAS (Container Manager – recommended)

1. **Install “Container Manager”** from Package Center.  
2. **Copy the app folder** (this repository) into your NAS at: `/docker/freelancer-admin-app`  
   > You should have `/docker/freelancer-admin-app/docker-compose.yml`, `app.py`, `templates/`, etc.
3. In **Container Manager**, create a **Project** and set the **Source** to `/docker/freelancer-admin-app`.  
4. Use the existing **`docker-compose.yml`** in that folder to create the project (stack).  
5. **Expose port 8080** and create a **Reverse Proxy** (Control Panel → Login Portal → Advanced → Reverse Proxy):  
   - **Source**: your domain/subdomain, **port 443** (HTTPS)  
   - **Destination**: NAS **IP**, **port 8080** (the container’s published port)  
   - Optionally enable automatic certificate (Let’s Encrypt) on the source host for HTTPS.

> After deployment, your app will be available at:  
> - Local: `http://<nas-ip>:8080` (or the port you mapped)  
> - Internet: `https://your.domain.tld` (through the reverse proxy)


---

## 🧭 2. First Use — Configuration

After launching the app, open it in your browser and go to **Settings**.

You should configure the following parameters:

### 🛡️ Security and Access
- **Enable Login** → activate admin login  
- **Set a Password** → define your admin password (saved securely in your SQLite database)

### 🌙 Working Hours
- Define **Night Start Hour** and **Night End Hour** (used to highlight jobs that overlap night hours)

### 💱 Currency
- Choose your default **currency code** (e.g., `EUR`, `USD`, `SEK`)  
  → affects all pricing display labels (“per hour”, “per week”, etc.)

### 💰 Gross-to-Net Ratio
- Enter your actual **Net Rate Percent** (e.g., `70` if you typically keep 70% after taxes and charges).  
  Used in the monthly summary to estimate net income.

### 📅 Public Holidays
- Add your **holidays** (Settings → Holidays section)  
  → jobs scheduled on those dates will show a “holiday” warning automatically.

When finished, click **Save Settings**.

---

## 👥 3. Clients and Roles

Go to **Clients** in the top navigation.

1. Click **Add Client** and enter:
   - Client name  
   - Default VAT percentage  
   - (Optional) Logo URL  

2. For each client, add one or several **Roles**:
   - Role name (e.g., “Video Editor”, “Sound Engineer”)  
   - Billing mode → hourly / daily / weekly / per production  
   - Rate (per unit)  
   - VAT percentage  
   - Active toggle (if you stop offering that role)

These roles will be available when creating new jobs.

---

## 🗓️ 4. Adding Jobs

Go to the **Jobs** page.

- Click **New Job**.  
- Select the **Client** → the **Role** list will automatically update.  
- Choose **Start** and **End** dates/times.  
- Optionally add a description or notes.

The app automatically:
- Detects jobs overlapping **night hours**.
- Warns if a **holiday** occurs in the range.
- Calculates cost based on the chosen role’s mode (hour/day/week/production).

Jobs are grouped into **Upcoming** and **Past** sections.

---

## 📆 5. Monthly Summary Page

Click **Monthly Summary** in the menu.

This view shows all jobs for the selected month, grouped by client.

### You can:
- **See totals**:  
  - HT (before VAT)  
  - Gross (HT + VAT)  
  - Net (based on your `Net Rate %`)
- **Toggle status checkboxes** for each client/month:
  - ✅ *Sent* — invoice sent  
  - 💰 *Paid* — invoice paid  
- **Enter the invoice number** directly for easier tracking.  
- Navigate between months using the arrows.

Totals and statuses are saved automatically.

---

## 📅 6. Google Calendar Integration

The app can automatically **create events** in your Google Calendar when a job is added.

### Step 1. Create a Google Cloud Project
1. Visit [Google Cloud Console](https://console.cloud.google.com/).  
2. Create a **new project** (or use an existing one).  
3. Enable the **Google Calendar API** under *APIs & Services → Library*.  
4. Go to *APIs & Services → Credentials → Create Credentials → OAuth client ID*:
   - Application type: **Web application**
   - Add `http://localhost:5000` (or your NAS IP) as an **Authorized redirect URI**
5. Download the **credentials.json** file.  
   - Place it in the app folder `config/credentials.json`.

### Step 2. Obtain `token.json`
You can generate it using Google’s OAuth flow:
1. Run the app once and click **“Test Calendar Connection”** in Settings → Google Calendar.
2. If it reports “No valid token”, visit any [Google OAuth Playground](https://developers.google.com/oauthplayground/).
3. Authorize the `https://www.googleapis.com/auth/calendar` scope.
4. Download the generated **token.json** and place it in:
   ```
   data/token.json
   ```
   (the app will find it automatically).

### Step 3. Configure in the App
In **Settings → Google Calendar**:
- **Target Calendar ID** — usually your Gmail address or a shared calendar ID  
- **Embed URL** — paste the URL from “Integrate calendar” in Google Calendar  
- **Auto-create events** — set to *Enabled*

Click **Save Connection** and test with **“Test Calendar Connection”**.  
A small test event will appear in your Google Calendar if everything is working.

---

## 🧰 Technical Notes

- All data is stored locally in `freelancer.sqlite3`.  
- Uploaded or generated files (credentials, token, etc.) live in:
  ```
  /config/
  /data/
  ```
- You can back up these two folders to preserve your configuration and tokens.

---

## 🪪 License

This project is private-use software.  
You are free to modify or deploy it for your personal freelance management needs.
