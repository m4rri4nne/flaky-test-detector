# flaky-test-detector

Detecta testes instáveis (flaky) a partir do histórico de execuções do CI e abre issues automaticamente para os piores casos.

> Um teste é **flaky** quando, no **mesmo commit**, ele passa em uma execução e falha em outra, sem nenhuma mudança de código.

## Por que isso importa

Testes flaky custam tempo e confiança do time:

- Pipelines são re-executados "só para ver se passa".
- Falhas reais passam a ser ignoradas ("deve ser o teste de novo").
- O tempo de CI e o custo por pipeline aumentam.

Este projeto transforma esse problema em um número mensurável: a **taxa de flakiness por teste**.

## Como funciona

```
Resultados do CI  →  Parser  →  Cálculo de flakiness  →  Relatório  →  Issue no GitHub
(JUnit XML / API)               (por teste e commit)     (tabela)      (para os piores)
```

1. **Coleta** os resultados dos testes de várias execuções do CI (JUnit XML ou GitHub Actions API).
2. **Agrupa** os resultados por teste e por commit.
3. **Calcula** a taxa de flakiness: em quantos commits o mesmo teste teve resultados diferentes.
4. **Gera** um ranking dos testes mais instáveis.
5. **Abre uma issue** (opcional) para os testes acima de um limite definido.

### O cálculo

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

**Exemplo:** um teste rodou em 10 commits e, em 3 deles, passou e falhou no mesmo commit → score de `0.30` (30%).

## Instalação

```bash
git clone https://github.com/<seu-usuario>/flaky-test-detector.git
cd flaky-test-detector
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Requisitos: Python 3.10+.

## Uso

### Analisar arquivos JUnit XML locais

```bash
python -m flaky_detector analyze ./results/*.xml --threshold 0.1
```

### Analisar execuções do GitHub Actions

```bash
export GITHUB_TOKEN=<seu-token>
python -m flaky_detector analyze --repo owner/repo --last-runs 50
```

### Abrir issues para os testes flaky

```bash
python -m flaky_detector analyze --repo owner/repo --last-runs 50 \
  --threshold 0.1 --create-issues
```

### Exemplo de saída

```
Teste                                   Commits   Flaky   Score
--------------------------------------  -------  ------  ------
tests/checkout/test_payment.py::test_3       20       7    35.0%
tests/login/test_session.py::test_expiry     20       4    20.0%
tests/api/test_orders.py::test_create        20       2    10.0%
```

## Opções

| Opção | Descrição | Padrão |
|---|---|---|
| `--threshold` | Score mínimo para considerar um teste flaky | `0.1` |
| `--last-runs` | Quantidade de execuções do CI a analisar | `30` |
| `--min-commits` | Mínimo de commits com dados para entrar no ranking | `5` |
| `--create-issues` | Abre uma issue por teste acima do threshold | desligado |
| `--format` | Formato do relatório: `table`, `json` ou `markdown` | `table` |

## Uso no GitHub Actions

```yaml
name: Flaky Test Report

on:
  schedule:
    - cron: "0 6 * * 1"   # toda segunda, 06:00 UTC
  workflow_dispatch:

jobs:
  detect:
    runs-on: ubuntu-latest
    permissions:
      actions: read
      issues: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: |
          python -m flaky_detector analyze \
            --repo ${{ github.repository }} \
            --last-runs 50 --threshold 0.1 --create-issues
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Estrutura do projeto

```
flaky-test-detector/
├── flaky_detector/
│   ├── __init__.py
│   ├── __main__.py        # CLI
│   ├── parsers.py         # JUnit XML e GitHub Actions API
│   ├── scoring.py         # cálculo de flakiness
│   ├── report.py          # tabela, JSON e markdown
│   └── issues.py          # criação de issues no GitHub
├── tests/
├── requirements.txt
└── README.md
```

## Roadmap

- [ ] Parser de JUnit XML
- [ ] Cálculo de flakiness por teste e commit
- [ ] Relatório em tabela, JSON e markdown
- [ ] Integração com GitHub Actions API
- [ ] Criação automática de issues (sem duplicar issues já abertas)
- [ ] Workflow de exemplo agendado
- [ ] Quarentena sugerida: marcar testes flaky para não bloquear o merge
- [ ] Histórico da taxa de flakiness ao longo do tempo
- [ ] Suporte a outros CIs (GitLab CI, CircleCI)

## Limitações

- Só detecta flakiness quando há **mais de uma execução no mesmo commit** (re-runs). Sem re-runs, o teste não tem como ser classificado.
- Falhas causadas por infraestrutura (timeout de runner, queda de rede) podem aparecer como flakiness e devem ser revisadas manualmente.

## Contribuindo

Contribuições são bem-vindas. Abra uma issue descrevendo a ideia antes de enviar um pull request.

## Licença

MIT
