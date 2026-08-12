# Holomoc Agent Base

Template base untuk semua Holomoc AI Agent. Fork repo ini untuk membuat agent baru.

## Agent yang Tersedia

| Agent | Nama | Port | Subdomain | Status |
|-------|------|------|-----------|--------|
| Admin | Ola  | 8080 | ola.holomoc.com | ✅ Running |
| Finance | Eva | 8081 | finance.holomoc.com | 🔜 Planned |
| Customer Support | Ona | 8082 | cs.holomoc.com | 🔜 Planned |
| Marketing | Ray | 8083 | marketing.holomoc.com | 🔜 Planned |
| Legal | Rea | 8084 | legal.holomoc.com | 🔜 Planned |

## Cara Membuat Agent Baru

### 1. Clone/fork repo ini
```bash
git clone https://github.com/AFEDLA/holomoc-agent-base.git nama-agent
cd nama-agent
```

### 2. Edit config.json
```json
{
  "agent_id": "eva",
  "agent_name": "Eva",
  "agent_tagline": "Holomoc AI Finance Assistant",
  "agent_gender": "female",
  "port": 8081,
  "subdomain": "finance.holomoc.com",
  "theme_color": "#2ECC71",
  "greeting_message": "Halo! Saya Eva, siap membantu urusan keuangan Anda!"
}
```

### 3. Kustomisasi agent/core.py
File yang WAJIB diubah:
- `INTENT_SYSTEM` — intent + contoh sesuai domain
- `_build_system_prompt()` — sudah otomatis baca dari config.json
- `_execute_intent()` — logic CRUD storage sesuai domain
- `_route_skill_from_intent()` — mapping intent ke skill

### 4. Tambahkan skills
```
skills/
└── nama-skill/
    ├── SKILL.md       ← instruksi perilaku untuk LLM
    └── scripts/       ← Python scripts (opsional)
```

### 5. Deploy ke VPS
```bash
# Edit AGENT_NAME dan PORT di deploy/deploy.sh
sudo bash deploy/deploy.sh
```

### Update rutin (setelah push ke GitHub)
```bash
cd /var/www/AGENT_NAME/holomoc-bot
git fetch
git reset --hard FETCH_HEAD
systemctl restart AGENT_NAME
```

## Struktur Folder

```
holomoc-agent-base/
├── agent/
│   ├── core.py           ← WAJIB dikustomisasi per agent
│   ├── hermes_client.py  ← shared, tidak perlu diubah
│   ├── gemini_client.py  ← shared, tidak perlu diubah
│   ├── groq_client.py    ← shared, tidak perlu diubah
│   ├── session.py        ← shared, tidak perlu diubah
│   └── skill_loader.py   ← shared, tidak perlu diubah
├── api/
│   ├── main.py           ← shared, tidak perlu diubah
│   └── tts.py            ← shared, tidak perlu diubah
├── skills/
│   ├── common/           ← konvensi skill (shared)
│   └── [skill-domain]/   ← skill spesifik agent ini
├── storage/
│   ├── manager.py        ← shared, tidak perlu diubah
│   └── generator.py      ← shared, bisa dikustomisasi template
├── web/
│   ├── index.html        ← WAJIB dikustomisasi (nama, warna, avatar)
│   ├── avatar_3d.html    ← shared
│   └── avatar_chat.html  ← shared
├── deploy/
│   ├── deploy.sh         ← edit AGENT_NAME + PORT
│   ├── systemd/agent.service ← template, di-generate deploy.sh
│   └── nginx/agent       ← template, di-generate deploy.sh
├── config.json           ← WAJIB diisi per agent
├── .env.production       ← template, copy ke .env dan isi
└── requirements.txt      ← shared
```
