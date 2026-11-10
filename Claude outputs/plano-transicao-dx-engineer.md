---
title: Plano de transição SDET → Developer Experience Engineer
created: 2026-11-09
tags: [carreira, dx-engineer, qa, plano]
status: em-andamento
duração: 9 meses
---

# Plano de transição: SDET → Developer Experience (DX) Engineer

## Contexto

- **Situação:** Senior QA / SDET. Gosto da parte de qualidade, mas falta crescimento e o dia a dia está cansativo.
- **O que quero:** escrever código, resolver problemas e ensinar.
- **Abertura:** posso mudar de empresa.
- **Opção escolhida:** Developer Experience Engineer (alternativas consideradas: AI Engineer com foco em evals, DevRel/Solutions Engineer).

## O que um DX Engineer faz (na prática)

Faz o time de engenharia entregar mais rápido e com menos dor: pipelines de CI/CD, testes lentos ou instáveis, ferramentas internas, templates de projeto, documentação e métricas de produtividade. O cliente é o desenvolvedor.

## Gap: o que já tenho vs. o que falta

**Já tenho**
- Python, Playwright, testes automatizados
- CI básico, métricas DORA
- Mentoria, escrita técnica, comunidade (He4rt, AWS Community Builder)

**Preciso reforçar**
- [ ] CI/CD avançado (GitHub Actions: reusable workflows, cache, matrix, paralelização, sharding de testes)
- [ ] Docker
- [ ] Terraform / IaC
- [ ] Observabilidade básica
- [ ] Segunda linguagem para ferramentas (TypeScript ou Go)

---

## Plano de 9 meses

### Meses 1-2: Fundação
- [ ] Aprofundar GitHub Actions (reusable workflows, cache, test sharding, runners)
- [ ] Docker + Terraform: conseguir provisionar um ambiente de CI na AWS
- [ ] Ler 5 vagas de DX / Developer Productivity e anotar palavras que se repetem

### Meses 3-5: Portfólio (parte mais importante)

**Projeto 1: evoluir o PR Test Selector**
- [ ] Integrar com GitHub Actions rodando só os testes relevantes ao PR
- [ ] Medir **antes/depois**: tempo de CI, custo por pipeline, % de testes pulados sem perder bugs
- [ ] Publicar artigo: "Reduzi o CI em X% com um agente de IA" (número concreto chama atenção)

**Projeto 2: detector de testes flaky**
- [ ] Ler resultados do CI e calcular taxa de falha intermitente por teste
- [ ] Abrir issue automática para os testes mais instáveis
- [ ] README com métricas e exemplo de uso

Núcleo da ideia:

```python
from collections import defaultdict

def flaky_score(runs):
    """runs: lista de (test_name, commit_sha, passed)"""
    by_test = defaultdict(lambda: defaultdict(set))
    for name, sha, passed in runs:
        by_test[name][sha].add(passed)
    scores = {}
    for name, commits in by_test.items():
        # flaky = mesmo commit com resultados diferentes
        flaky = sum(1 for r in commits.values() if len(r) > 1)
        scores[name] = flaky / len(commits)
    return dict(sorted(scores.items(), key=lambda x: -x[1]))
```

### Meses 6-7: Posicionamento
- [ ] Atualizar LinkedIn e portfólio: "SDET → Developer Experience", com os 2 projetos em destaque
- [ ] Dar uma palestra ou live (He4rt, Twitch) sobre "como reduzir tempo de CI"
- [ ] Pedir referências a quem já trabalha como DX / Platform

### Meses 8-9: Candidaturas
- [ ] Aplicar em vagas de *Developer Experience*, *Developer Productivity*, *Platform Engineer* e *SDET sênior com foco em plataforma*
- [ ] Em paralelo, conversar com o time atual para assumir tarefas de DX (CI, tooling), que já contam como experiência no currículo

---

## Narrativa de posicionamento

> "SDET que automatiza qualidade com IA e melhora a produtividade de quem desenvolve."

## Primeira semana

1. [ ] Escolher **uma dor real de CI** no trabalho atual (teste lento, flaky, build demorado) e medir o estado atual
2. [ ] Criar o repositório / branch de métricas antes/depois no PR Test Selector
3. [ ] Salvar 5 vagas-alvo numa lista

## Vagas-alvo

| Empresa | Vaga | Link | Palavras-chave | Status |
|---|---|---|---|---|
|  |  |  |  |  |
|  |  |  |  |  |
|  |  |  |  |  |
|  |  |  |  |  |
|  |  |  |  |  |

## Métricas do projeto (antes/depois)

| Métrica | Antes | Depois |
|---|---|---|
| Tempo médio de CI |  |  |
| Custo por pipeline |  |  |
| % de testes pulados |  |  |
| Bugs perdidos |  |  |

## Notas

-
