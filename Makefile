.PHONY: dev prod down logs migrate shell test deploy

# ─── Development (local Docker) ──────────────────────────────────────────────

dev:
	docker compose -f docker-compose.dev.yml up --build

dev-d:
	docker compose -f docker-compose.dev.yml up --build -d

dev-down:
	docker compose -f docker-compose.dev.yml down

# ─── Production (Oracle Cloud) ───────────────────────────────────────────────

prod:
	docker compose -f docker-compose.prod.yml up --build -d

prod-down:
	docker compose -f docker-compose.prod.yml down

prod-logs:
	docker compose -f docker-compose.prod.yml logs -f

prod-restart:
	docker compose -f docker-compose.prod.yml restart web celery

# ─── Common ───────────────────────────────────────────────────────────────────

logs:
	docker compose -f docker-compose.dev.yml logs -f web

migrate:
	docker compose -f docker-compose.dev.yml exec web python manage.py makemigrations
	docker compose -f docker-compose.dev.yml exec web python manage.py migrate

shell:
	docker compose -f docker-compose.dev.yml exec web python manage.py shell

createsuperuser:
	docker compose -f docker-compose.dev.yml exec web python manage.py createsuperuser

test:
	docker compose -f docker-compose.dev.yml exec web python manage.py test

# ─── Oracle Cloud Deploy (manual) ────────────────────────────────────────────

deploy:
	ssh $(ORACLE_USER)@$(ORACLE_HOST) "cd /opt/manakrishi && git pull && docker compose -f docker-compose.prod.yml up --build -d && docker image prune -f"

# ─── SSL (Let's Encrypt on Oracle VM) ────────────────────────────────────────

ssl:
	ssh $(ORACLE_USER)@$(ORACLE_HOST) "sudo certbot certonly --standalone -d api.manakrishi.com && sudo cp /etc/letsencrypt/live/api.manakrishi.com/fullchain.pem /opt/manakrishi/docker/ssl/ && sudo cp /etc/letsencrypt/live/api.manakrishi.com/privkey.pem /opt/manakrishi/docker/ssl/ && cd /opt/manakrishi && docker compose -f docker-compose.prod.yml restart nginx"

# ─── Clean ────────────────────────────────────────────────────────────────────

clean:
	docker compose -f docker-compose.dev.yml down -v
	docker system prune -f
