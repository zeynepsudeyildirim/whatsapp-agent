# wa-agent

Restoranlar için çok dilli, sesli WhatsApp agent'ı. İki kanal var: tedarikçi ↔ işletme ve işletme ↔ müşteri.
Mimari ve kararlar için tasarım dokümanına bak: https://claude.ai/artifact/GhCRYGE48y4cbJiTVZizCg

## Durum: Faz 0

| Hazır | Sırada (Faz 1) |
| --- | --- |
| İmza doğrulamalı webhook (`X-Hub-Signature-256`) | Ses indirme + STT |
| Meta doğrulama el sıkışması (GET /webhook) | Yapılandırılmış çıkarım + çeviri + rakam doğrulama |
| `wamid` ile idempotent kayıt (çift teslimat tek kez işlenir) | Onay kartı ve `pending_action` akışı |
| 24 saat penceresinin takibi (`last_inbound_at`) | Giden mesaj servisi (şablon / serbest mesaj seçimi) |
| Kuyruk soyutlaması (in-memory, Cloud Tasks) | LangGraph tedarikçi alt grafı |
| Role göre kanal yönlendirme (tanınmayan numara = müşteri) | Terraform (Cloud Run, Cloud SQL, Cloud Tasks) |
| Veri modeli: tenant, contact, conversation, message, pending_action, audit_log | Alembic migrasyonları + Postgres RLS |
| WhatsApp istemcisi: metin, butonlar, şablon, medya indirme | |

## Yerelde çalıştırma

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                       # testler SQLite in-memory ile çalışır, Postgres gerekmez

cp .env.example .env         # değerleri doldur
uvicorn waagent.main:create_app --factory --reload --port 8080
```

Meta webhook'unu yerelde denemek için bir tünel (ör. `cloudflared tunnel --url http://localhost:8080`) aç ve
Meta uygulamasında callback URL'yi `https://<tünel>/webhook` olarak gir.

## Yapı

```
waagent/
  main.py              HTTP uç noktaları (webhook, worker, healthz)
  ingest.py            hızlı yol: kaydet, tekilleştir, kuyruğa at
  routing.py           gönderenin rolüne göre kanal seçimi
  queue.py             InMemoryQueue, CloudTasksQueue
  config.py            ortam değişkenleri (WA_ önekli)
  db/models.py         veri modeli
  whatsapp/
    signature.py       HMAC-SHA256 doğrulama
    payloads.py        webhook payload modelleri
    client.py          Cloud API istemcisi + 24 saat penceresi
tests/
```
