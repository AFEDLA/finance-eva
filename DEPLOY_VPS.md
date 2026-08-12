# Deploy EVA Finance Assistant ke VPS

Panduan ini untuk **Hajid** — langkah-langkah deploy EVA ke subdomain `finance.holomoc.com`.

---

## Info Teknis

| Item | Value |
|---|---|
| Subdomain | `finance.holomoc.com` |
| Port | `8081` |
| Deploy dir | `/var/www/eva-finance/` |
| Project dir | `/var/www/eva-finance/holomoc-bot/` |
| Service name | `eva-finance` |

---

## Langkah Deploy

### 1. Clone repo ke VPS

```bash
mkdir -p /var/www/eva-finance
cd /var/www/eva-finance
git clone https://github.com/AFEDLA/eva-finance.git holomoc-bot
cd holomoc-bot
```

### 2. Jalankan deploy script

```bash
sudo bash deploy/deploy.sh
```

Script ini otomatis akan:
- Install dependencies sistem (python3, nginx, ffmpeg)
- Buat folder `storage-data/` dengan subfolder yang dibutuhkan
- Setup virtualenv dan install Python packages
- Copy `.env.production` → `.env` (perlu diisi manual)
- Setup systemd service `eva-finance`
- Setup Nginx config untuk `finance.holomoc.com`

### 3. Isi file `.env`

```bash
nano /var/www/eva-finance/.env
```

Isi nilai berikut:
- `LLM_API_KEY` → API key Hermes
- `ELEVENLABS_API_KEY` → ElevenLabs key (minta ke Al)
- `ELEVENLABS_VOICE_ID` → Voice ID Eva (minta ke Al)
- `GROQ_API_KEY` → Groq key (untuk OCR struk, minta ke Al)

Setelah diisi, restart service:
```bash
systemctl restart eva-finance
```

### 4. Pasang SSL

```bash
certbot --nginx -d finance.holomoc.com
```

---

## Cek Status & Log

```bash
# Status service
systemctl status eva-finance

# Log real-time
journalctl -u eva-finance -f

# Test endpoint
curl http://127.0.0.1:8081/health
```

---

## Update Setelah Ada Perubahan Code

```bash
cd /var/www/eva-finance/holomoc-bot
git pull
systemctl restart eva-finance
```

---

## Catatan Penting

- File `.env` **TIDAK** ada di repo (di-gitignore). Harus dibuat manual dari `.env.production`.
- Folder `storage-data/` **TIDAK** ada di repo. Dibuat otomatis oleh `deploy.sh`.
- File avatar `.glb` **TIDAK** ada di repo (terlalu besar). Upload manual via SCP jika dibutuhkan.
- Port EVA adalah **8081** (beda dari Ola yang pakai 8080).
