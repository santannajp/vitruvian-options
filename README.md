# Vitruvian Options

Painel pessoal de simulação de posições Aave e consulta de opções de BTC.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Acesse `http://127.0.0.1:8000`. O banco local é `vitruvian.db`, ou o caminho definido por `VITRUVIAN_DB`.

Para executar os testes offline:

```bash
.venv/bin/python -m unittest discover -s tests -v
```
