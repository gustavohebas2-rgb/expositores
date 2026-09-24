# Radar Comercial · Freedom Grupo

Dashboard estático gerado a partir dos exports do sistema. Roda inteiro no navegador,
sem servidor e sem banco de dados: os dados ficam embutidos no próprio `index.html`.

## Como atualizar

1. Exporte do sistema os dois CSVs e coloque-os em `dados/`:
   - `Clientes.csv` — cadastro completo de clientes
   - `ped_fatures.csv` — **todas** as linhas de pedido do período completo, não só o mês corrente

2. Gere o dashboard:

   ```bash
   python3 gerar_dashboard.py \
     --clientes dados/Clientes.csv \
     --pedidos  dados/ped_fatures.csv \
     --publico
   ```

3. Publique:

   ```bash
   git add index.html
   git commit -m "Dados de $(date +%d/%m/%Y)"
   git push
   ```

O GitHub Pages atualiza sozinho em um ou dois minutos.

## Substituição total

Cada execução reconstrói o dashboard do zero. Nada da versão anterior é aproveitado:
o que não estiver nos CSVs daquela rodada deixa de existir na página.

Por isso o script confere a cobertura do export antes de gravar e aborta se o período
for curto demais, se mais da metade do cadastro ficar sem nenhuma compra, ou se houver
menos de três meses de histórico. Se o aviso aparecer e ainda assim você quiser gravar,
responda `SIM` na pergunta (ou use `--sim` em automação).

## O `--publico` é obrigatório aqui

O GitHub Pages é **público**: mesmo com o repositório privado, a página publicada fica
acessível a qualquer pessoa com o link, no plano gratuito. A flag `--publico` remove
telefone e e-mail dos clientes antes de gravar o arquivo.

Nome de cliente, cidade, rede, vendedor e faturamento por cliente **continuam no arquivo**.
Se isso também não puder ser público, não use o Pages: deixe o repositório privado e
distribua o `index.html` pelo próprio GitHub, sem publicar.

Os CSVs estão no `.gitignore` e não devem ser commitados em nenhuma hipótese.

## Opções do gerador

| Flag | Para que serve |
|---|---|
| `--clientes` | CSV do cadastro de clientes (obrigatório) |
| `--pedidos` | Um ou mais CSVs de pedidos; duplicatas são removidas |
| `--publico` | Remove telefone e e-mail |
| `--saida` | Arquivo de saída (padrão `index.html`) |
| `--ref` | Data de referência `DD/MM/AAAA` (padrão: última data dos pedidos) |
| `--backup` | Guarda a versão anterior antes de sobrescrever |
| `--sim` | Não pergunta nada |
| `--minimo-dias` | Período mínimo esperado no export (padrão 180) |

## Estrutura

```
index.html            página publicada (gerada, ~2 a 5 MB)
template.html         layout e código, sem dados (~170 KB)
gerar_dashboard.py    gerador, só Python 3, sem dependências
dados/                CSVs locais, fora do Git
.nojekyll             impede o Jekyll de processar a pasta
```

## Como o comodato é identificado

A regra oficial é o agrupamento `DESCRICAO_AGRUP = 'DISPLAYS'`. Como nem todo export do
sistema traz essa coluna, o gerador trabalha em dois modos:

- **Export com `DESCRICAO_AGRUP`**: vale o agrupamento, e os códigos de produto
  encontrados são gravados em `comodato_produtos.json`. A lista se mantém sozinha.
- **Export sem a coluna**: o gerador usa os códigos já gravados nesse arquivo.

A lista atual tem 33 produtos e foi conferida contra um export que trazia o agrupamento:
bateu 324 de 324 linhas, sem nenhum falso positivo.

Se um display novo entrar no catálogo e o export do mês não tiver a coluna de
agrupamento, ele passa despercebido. Para evitar isso, de vez em quando exporte com
`DESCRICAO_AGRUP` — o gerador avisa quantos produtos novos aprendeu.
