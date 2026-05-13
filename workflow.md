# Workflow de Orquestração — downdetector-collector

> Sequência de execução do projeto do zero até produção. Cada task tem **exatamente um agent owner**. Outros agents só aparecem como gate (validação) ou escalation (quando o owner trava), nunca trabalhando em paralelo na mesma task.

**Spec:** `/home/cristiano/docs/superpowers/specs/2026-05-12-dashboard-downdetector-design.md`
**Plano:** `/home/cristiano/docs/superpowers/plans/2026-05-12-dashboard-downdetector.md`
**Working dir:** `/home/cristiano/downdetector-collector/`

---

## Princípios de orquestração

1. **Um owner por task.** O owner é o único agent que **escreve código** naquela task. Outros podem ler/validar/sugerir, nunca editar concorrentemente.
2. **Escalation, não substituição.** Se o owner travar (ex: `python-dev` bate em Cloudflare durante Task 7), ele **encerra** sua intervenção, escala para o especialista, e só volta quando o especialista entregar a parte específica.
3. **Gates obrigatórios entre fases.** `test-runner` valida ao final de cada cluster de tasks com código testável; `code-reviewer` aprova antes de commits em tasks sensíveis (scraper, sink, scheduler, entry point).
4. **Nada de "while I'm here".** Owner toca apenas os arquivos listados na sua task. Refactor não-pedido é desvio.
5. **Commits dentro do escopo do owner.** Quem é owner da task faz o commit; ninguém commita por outro.

---

## Mapa de responsabilidades

| Agent | Owner em fases | Pode ler tudo? | Edita? |
|---|---|---|---|
| `downdetector-python-dev` | 0, 2, 3, 5, 6, 7, 8, 9 (parte) | Sim | Sim — apenas seus arquivos |
| `downdetector-playwright-specialist` | 1, 4 | Sim | Sim — `scraper.py`, `stealth.py`, `snapshot.py`, fixtures |
| `downdetector-test-runner` | 14 (smoke test) | Sim | **Não** — só Bash/Read |
| `downdetector-zabbix-grafana` | 10, 11, 12, 13 | Sim | Sim — `zabbix/`, `grafana/`, `systemd/`, `INSTALL.md` |
| `downdetector-code-reviewer` | nenhuma (gate) | Sim | **Não** — só Read/Grep/Bash |

---

## Fluxo de alto nível

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            CICLO POR TASK                                    │
│                                                                              │
│  ① owner implementa → ② test-runner valida → ③ code-reviewer aprova         │
│                       (se task tem testes)   (em tasks sensíveis)            │
│                                                                              │
│  Apenas após ③ o owner faz `git commit`. Próxima task começa.                │
└──────────────────────────────────────────────────────────────────────────────┘
```

```
Fase 0  Setup        → python-dev
  │
Fase 1  Fixtures     → playwright-specialist
  │
Fase 2  Parser TDD   → python-dev ──┐
  │                                  ├─→ test-runner (gate) → code-reviewer (gate)
Fase 3  Config TDD   → python-dev ──┘
  │
Fase 4  Scraper      → playwright-specialist → test-runner → code-reviewer
  │
Fase 5  Sink TDD     → python-dev ──┐
  │                                  ├─→ test-runner → code-reviewer
Fase 6  Scheduler    → python-dev ──┤
  │                                  │
Fase 7  Health TDD   → python-dev ──┘
  │
Fase 8  Entry point  → python-dev → test-runner → code-reviewer (rigor extra)
  │
Fase 9  Discovery    → python-dev (escala p/ playwright-specialist se 403)
  │
Fase 10 LLD external → zabbix-grafana
Fase 11 Tmpl Zabbix  → zabbix-grafana ─── code-reviewer (sintaxe + UUIDs)
Fase 12 Dash Grafana → zabbix-grafana
Fase 13 Provision    → zabbix-grafana
Fase 14 Systemd      → zabbix-grafana → code-reviewer (hardening)
  │
Fase 15 INSTALL.md   → zabbix-grafana
  │
Fase 16 Smoke test   → test-runner → escalation conforme falha:
                       ├─ erro código → python-dev
                       ├─ Cloudflare  → playwright-specialist
                       └─ Zabbix/Graf → zabbix-grafana
  │
Fase 17 Push remoto  → python-dev (apenas se usuário aprovar)
```

---

## Execução detalhada por fase

### Fase 0 — Setup do projeto

**Plan ref:** Task 1
**Owner:** `downdetector-python-dev`
**Arquivos tocados:** `.gitignore`, `pyproject.toml`, `README.md`, `collector/__init__.py`, `tests/__init__.py`
**Gate de saída:** nenhum (sem código testável ainda)
**Dispatch sugerido:**

> @downdetector-python-dev — Execute a Task 1 do plano (Phase 0). Crie o repo git, pyproject.toml com as deps listadas, README placeholder, e instale o virtualenv com Playwright Chromium. Termine com o commit `chore: initial project skeleton with deps`.

**Critério de conclusão:** `git log --oneline | wc -l` = 1; `.venv/bin/playwright --version` retorna versão.

---

### Fase 1 — Captura de fixtures HTML

**Plan ref:** Task 2
**Owner:** `downdetector-playwright-specialist`
**Por que ele e não python-dev:** essa task envolve browser real contra Cloudflare. Se o curl `/snapshot.py` der HTTP 403, é decisão técnica que cabe ao especialista (Xvfb? Firefox? FlareSolverr?), não ao python-dev.
**Arquivos tocados:** `bin/snapshot.py`, `tests/fixtures/downdetector_*.html`
**Gate de saída:** nenhum agente — mas o **owner** deve confirmar que pelo menos `downdetector_ok.html` foi capturado com HTTP 200 e contém marcador de status. Se não, **pare e reporte ao usuário** antes de avançar (a spec inteira depende disso).
**Dispatch sugerido:**

> @downdetector-playwright-specialist — Task 2 do plano. Crie `bin/snapshot.py` exatamente como descrito e capture as 4 fixtures (ok, warning, danger, blocked). Se capturar `ok` der 403, aplique seu playbook de bypass antes de tentar novamente; reporte qual técnica funcionou.

**Critério de conclusão:** `ls tests/fixtures/*.html | wc -l` ≥ 3 (ok+warning+blocked obrigatórios; danger ok se vazio).

---

### Fase 2 — Parser (TDD com fixtures reais)

**Plan ref:** Tasks 3, 4, 5
**Owner:** `downdetector-python-dev`
**Arquivos tocados:** `collector/parser.py`, `tests/test_parser.py`
**Gate de saída:**
1. `downdetector-test-runner` roda `pytest tests/test_parser.py -v` — deve PASS (skips legítimos OK)
2. `downdetector-code-reviewer` revisa diff: validar que regex não tem ReDoS, parser não lança exception não-tratada, ParseResult é `frozen`

**Dispatch sugerido em sequência (uma de cada vez):**

> @downdetector-python-dev — Task 3 do plano. TDD estrito conforme steps.
>
> (após PASS) → @downdetector-python-dev — Task 4 do plano.
>
> (após PASS) → @downdetector-python-dev — Task 5 do plano.
>
> (após Task 5) → @downdetector-test-runner — Roda toda a suite de test_parser e me dá um relatório.
>
> (após relatório verde) → @downdetector-code-reviewer — Revisa o diff das Tasks 3-5 (parser.py e test_parser.py).

**Critério de conclusão:** 5+ testes verdes em `test_parser.py`, code-reviewer com veredicto ✅.

---

### Fase 3 — Config (YAML loader TDD)

**Plan ref:** Task 6
**Owner:** `downdetector-python-dev`
**Arquivos tocados:** `collector/config.py`, `tests/test_config.py`, `config/services.example.yaml`
**Gate de saída:** `test-runner` valida (5 testes esperados PASS). Code-reviewer **opcional** (módulo simples).
**Dispatch:**

> @downdetector-python-dev — Task 6 do plano.
>
> @downdetector-test-runner — Valida test_config.

---

### Fase 4 — Scraper Playwright

**Plan ref:** Task 7
**Owner:** `downdetector-playwright-specialist`
**Por que ele:** wrapper Playwright + stealth + persistent context. Mesmo motivo da Fase 1: decisões técnicas de browser são suas.
**Arquivos tocados:** `collector/scraper.py`, `collector/stealth.py`
**Gate de saída:**
1. **Smoke manual** do Step 3 (script inline com Playwright real) — deve retornar `ScrapeResult` válido
2. `downdetector-code-reviewer` revisa: try/finally fechando browser, sem secrets em log, recycling correto

**Dispatch:**

> @downdetector-playwright-specialist — Task 7 do plano. Implemente scraper.py e stealth.py. Execute o smoke test do Step 3 e me mostre o output do ScrapeResult antes do commit.
>
> @downdetector-code-reviewer — Revisa diff da Task 7 com atenção especial a: finally em new_page/close, vazamento de cf_clearance em log, recycling condition.

**Critério de conclusão:** smoke retornou `status != UNKNOWN`, review ✅.

---

### Fase 5 — Zabbix sink (TDD com subprocess mock)

**Plan ref:** Task 8
**Owner:** `downdetector-python-dev`
**Arquivos tocados:** `collector/zabbix_sink.py`, `tests/test_zabbix_sink.py`
**Gate de saída:**
1. `test-runner` confirma 3 testes PASS
2. `code-reviewer` valida: `cmd` é lista (não string), escape de aspas correto, sem injection

**Dispatch:**

> @downdetector-python-dev — Task 8 do plano.
>
> @downdetector-test-runner — Valida test_zabbix_sink.
>
> @downdetector-code-reviewer — Revisa: subprocess injection, quoting.

---

### Fase 6 — Scheduler async

**Plan ref:** Task 9
**Owner:** `downdetector-python-dev`
**Arquivos tocados:** `collector/scheduler.py`, `tests/test_scheduler.py`
**Gate de saída:**
1. `test-runner` confirma — **atenção a flaky timing tests**. Se algum flakar, test-runner reporta para python-dev ajustar margens.
2. `code-reviewer` valida: dataclass(order=True) com `compare=False` correto, sem deadlock no `stop_event`, backoff exponential bem limitado

**Dispatch:**

> @downdetector-python-dev — Task 9 do plano.
>
> @downdetector-test-runner — Valida test_scheduler. Se algum timing test flaky, me reporta antes de eu invocar code-reviewer.
>
> @downdetector-code-reviewer — Revisa scheduler.

---

### Fase 7 — Health metrics (TDD)

**Plan ref:** Task 10
**Owner:** `downdetector-python-dev`
**Arquivos tocados:** `collector/health.py`, `tests/test_health.py`
**Gate de saída:** `test-runner` confirma 4 testes PASS. Code-reviewer opcional.
**Dispatch:**

> @downdetector-python-dev — Task 10.
>
> @downdetector-test-runner — Valida test_health.

---

### Fase 8 — Entry point (`__main__.py`)

**Plan ref:** Task 11
**Owner:** `downdetector-python-dev`
**Arquivos tocados:** `collector/__main__.py`
**Gate de saída:**
1. Smoke manual do Step 2 (rodar daemon contra services.yaml mínimo, ver logs JSON) — **owner valida**
2. `code-reviewer` revisa com rigor extra: SIGHUP handler correto, async tasks com `try/finally`, sem race conditions no `_stop_event`

**Dispatch:**

> @downdetector-python-dev — Task 11. Rode o smoke do Step 2 por 60s e me mostre logs do ciclo. Não commita ainda.
>
> @downdetector-code-reviewer — Revisa `__main__.py` com atenção a: signal handlers, asyncio tasks cleanup, race no stop_event, vazamento de browser em erro.
>
> (após ✅) @downdetector-python-dev — Faça o commit.

---

### Fase 9 — Discovery script

**Plan ref:** Task 12
**Owner:** `downdetector-python-dev` (script CLI Python simples reusando Scraper)
**Escalation:** se rodar e der CF block, **encerre seu trabalho** e dispatch `@downdetector-playwright-specialist` para resolver bypass — depois volta para você terminar.
**Arquivos tocados:** `bin/discover.py`
**Gate de saída:** smoke manual com slug conhecido (`cloudflare`) deve retornar entrada YAML válida.
**Dispatch:**

> @downdetector-python-dev — Task 12 do plano. Execute o Step 2 contra slug cloudflare e me mostre a saída YAML antes do commit. Se aparecer cloudflare_blocked, pare e me avise para chamar o playwright-specialist.

---

### Fase 10 — External script LLD do Zabbix

**Plan ref:** Task 13
**Owner:** `downdetector-zabbix-grafana`
**Por que ele:** script é Python mas o **conhecimento crítico** é o formato JSON do Zabbix LLD e onde ele roda (zabbix-server permissions). Owner não-Zabbix produziria algo tecnicamente correto mas operacionalmente errado.
**Arquivos tocados:** `zabbix/externalscripts/downdetector_discovery.py`
**Gate de saída:** owner executa Step 2 e valida que o JSON tem o formato `{"data": [...]}` exato esperado pelo Zabbix.
**Dispatch:**

> @downdetector-zabbix-grafana — Task 13 do plano.

---

### Fase 11 — Template Zabbix YAML

**Plan ref:** Task 14
**Owner:** `downdetector-zabbix-grafana`
**Arquivos tocados:** `zabbix/tmpl_downdetector.yaml`, `zabbix/valuemap_downdetector.yaml`, `zabbix/host_downdetector.yaml`
**Gate de saída:**
1. Owner executa Step 4 (validação `yaml.safe_load`) — 3× OK
2. `code-reviewer` valida: UUIDs únicos entre arquivos, severities em UPPERCASE, macros LLD em formato `{#NAME}`, sem credentials hardcoded

**Dispatch:**

> @downdetector-zabbix-grafana — Task 14 do plano.
>
> @downdetector-code-reviewer — Revisa os 3 YAMLs em `zabbix/`: foque em UUIDs únicos, sintaxe Zabbix 6.0, e ausência de credentials.

---

### Fase 12 — Dashboard JSON do Grafana

**Plan ref:** Task 15
**Owner:** `downdetector-zabbix-grafana`
**Arquivos tocados:** `grafana/dashboard_downdetector.json`
**Gate de saída:** owner valida JSON com `python -m json.tool`. Code-reviewer opcional.
**Dispatch:**

> @downdetector-zabbix-grafana — Task 15.

---

### Fase 13 — Provisionamento Grafana

**Plan ref:** Task 16
**Owner:** `downdetector-zabbix-grafana`
**Arquivos tocados:** `grafana/provisioning/datasources/zabbix.yaml`, `grafana/provisioning/dashboards/downdetector.yaml`, `grafana/logos/README.md`
**Gate de saída:** nenhum — configs declarativas simples.
**Dispatch:**

> @downdetector-zabbix-grafana — Task 16.

---

### Fase 14 — Systemd + logrotate

**Plan ref:** Task 17
**Owner:** `downdetector-zabbix-grafana`
**Arquivos tocados:** `systemd/downdetector-collector.service`, `systemd/downdetector-collector.logrotate`
**Gate de saída:** `code-reviewer` valida hardening: `User=`, `ReadWritePaths=` mínimo, `ExecStart` com path absoluto, `MemoryMax=` definido.
**Dispatch:**

> @downdetector-zabbix-grafana — Task 17.
>
> @downdetector-code-reviewer — Revisa o systemd unit: hardening (User não-root, ProtectSystem, ReadWritePaths mínimo, NoNewPrivileges, MemoryMax).

---

### Fase 15 — INSTALL.md

**Plan ref:** Task 18
**Owner:** `downdetector-zabbix-grafana`
**Por que ele:** o INSTALL.md fala de Zabbix import, Grafana provisioning, systemd — conhecimento operacional dele.
**Arquivos tocados:** `INSTALL.md`
**Gate de saída:** nenhum.
**Dispatch:**

> @downdetector-zabbix-grafana — Task 18.

---

### Fase 16 — Smoke test ponta-a-ponta

**Plan ref:** Task 19 (todas as steps)
**Owner:** `downdetector-test-runner`
**Por que ele:** task é exclusivamente **rodar comandos e interpretar saída**, sem modificar código. test-runner é read-only e otimizado para diagnóstico (haiku, rápido).
**Escalations (test-runner detecta, encerra sua passada, dispatch o especialista):**

| Sintoma | Escalar para |
|---|---|
| Daemon não inicia / erro Python | `downdetector-python-dev` |
| HTTP 403, CF blocks > 5 sustentado | `downdetector-playwright-specialist` |
| Items não aparecem no Zabbix UI | `downdetector-zabbix-grafana` |
| Dashboard vazio no Grafana | `downdetector-zabbix-grafana` |
| Trigger "Stale" não dispara | `downdetector-zabbix-grafana` |

**IMPORTANTE:** o test-runner **não tenta corrigir**. Reporta o sintoma com evidência e encaminha. Após o especialista entregar, test-runner re-roda a validação.

**Dispatch inicial:**

> @downdetector-test-runner — Execute a Task 19 completa do plano: smoke test ponta-a-ponta no servidor real (requer deploy via INSTALL.md ter sido feito). Reporte cada step e escalation conforme tabela do workflow.

**Critério de conclusão:** Step 8 do plano (24h estabilidade) ok — < 10 errors no journalctl, mediana CF blocks_5m < 2, RAM < 1.5 GB.

---

### Fase 17 — Push remoto (opcional)

**Plan ref:** Task 20
**Owner:** `downdetector-python-dev`
**Condição:** SÓ executa após confirmação explícita do usuário sobre nome do repo e visibilidade (private/public).
**Arquivos tocados:** `.git/config` (remote add); push.
**Dispatch:**

> (usuário confirmou) @downdetector-python-dev — Task 20 com nome `<repo>` e visibilidade `<private/public>`.

---

## Tabela mestre — quem faz o quê (sem sobreposição)

| Fase | Plan task | Owner único | Validador (gate) | Reviewer (gate) |
|---:|---:|---|---|---|
| 0 | 1 | python-dev | — | — |
| 1 | 2 | playwright-specialist | — (owner se valida) | — |
| 2 | 3, 4, 5 | python-dev | test-runner | code-reviewer |
| 3 | 6 | python-dev | test-runner | opcional |
| 4 | 7 | playwright-specialist | — (owner smoke) | code-reviewer |
| 5 | 8 | python-dev | test-runner | code-reviewer |
| 6 | 9 | python-dev | test-runner | code-reviewer |
| 7 | 10 | python-dev | test-runner | opcional |
| 8 | 11 | python-dev | — (owner smoke) | code-reviewer (rigor) |
| 9 | 12 | python-dev | — (owner smoke) | — |
| 10 | 13 | zabbix-grafana | — | — |
| 11 | 14 | zabbix-grafana | — | code-reviewer |
| 12 | 15 | zabbix-grafana | — | — |
| 13 | 16 | zabbix-grafana | — | — |
| 14 | 17 | zabbix-grafana | — | code-reviewer |
| 15 | 18 | zabbix-grafana | — | — |
| 16 | 19 | test-runner | — | — |
| 17 | 20 | python-dev | — | — |

**Verificação anti-sobreposição:**
- Cada linha tem **1 owner único**. ✓
- Validador e reviewer nunca editam — só rodam comandos / fazem assertions. ✓
- Owner nunca é também validador ou reviewer da mesma task. ✓
- `code-reviewer` aparece exclusivamente como gate (nunca como owner). ✓
- `test-runner` aparece como owner apenas na Fase 16 (smoke), onde NÃO há código sendo escrito por ninguém em paralelo. ✓

---

## Regras de escalation (quando o owner trava)

```
┌──────────────────────────────────────────────────────────────────┐
│ Owner enfrentou:                          Escalar para:           │
├──────────────────────────────────────────────────────────────────┤
│ python-dev — HTTP 403 / Cloudflare block  playwright-specialist  │
│ python-dev — pytest flaky inesperado      test-runner (diag)     │
│ python-dev — YAML/JSON Zabbix             zabbix-grafana         │
│ playwright-spec — bug em Python puro      python-dev             │
│ zabbix-grafana — código Python falha      python-dev             │
│ qualquer — incerteza de segurança         code-reviewer          │
└──────────────────────────────────────────────────────────────────┘
```

Quando o owner escala:
1. Encerra sua tentativa atual (sem commit parcial)
2. Resume em 2-3 frases o que tentou e o que falhou
3. Dispatch ao especialista
4. **Espera** o especialista entregar a parte específica
5. Retoma sua task original com a base já corrigida

Nunca dois agents editam o mesmo arquivo na mesma janela de tempo.

---

## Sinais de "fase concluída" vs "projeto concluído"

**Fase concluída:** owner fez commit, gates pertinentes passaram (`✅` no veredicto), próxima fase pode começar.

**Projeto concluído:**
- ✅ Todas as 17 fases acima com seus gates passados
- ✅ Fase 16 step 8: 24h de smoke test estável no servidor
- ✅ Dashboard Grafana "DASHBOARD DOWNDETECTOR" renderizando para os 15 serviços BR core
- ✅ Painel "Saúde do scraper" com cycle_seconds estável, blocks_5m média < 2
- ✅ INSTALL.md atualizado refletindo o que de fato foi feito

A partir daí, expansão para 48 serviços é trabalho de operação contínua, não da implementação inicial.

---

## Como usar este workflow

1. **Sempre dispatcha um agent por vez.** O orquestrador (você, o usuário; ou Claude principal sem subagent) é quem mantém o estado de "qual fase, qual task".
2. **Use as frases "Dispatch sugerido"** literalmente. Foram escritas para minimizar ambiguidade e ativar o subagent certo via `description` field.
3. **Não pule gates.** Mesmo um teste verde tem custo de gate baixíssimo (test-runner roda em ~10s); um bug em produção custa horas.
4. **Quando em dúvida sobre owner**, releia a tabela mestre acima. Se ainda em dúvida, é sinal de que a task está mal-definida no plano — abra uma discussão antes de avançar.

---

## Próxima ação para começar

Em uma nova sessão Claude Code no diretório do projeto:

```bash
cd /home/cristiano/downdetector-collector
claude
```

Cole o primeiro dispatch:

> @downdetector-python-dev — Execute a Task 1 do plano (Phase 0). Crie o repo git, pyproject.toml com as deps listadas, README placeholder, e instale o virtualenv com Playwright Chromium. Termine com o commit `chore: initial project skeleton with deps`.

E siga o workflow daí.
