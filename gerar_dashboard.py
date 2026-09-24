#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera o dashboard Radar Comercial Freedom a partir dos CSVs exportados do sistema.

Uso:
    python3 gerar_dashboard.py --clientes Clientes.csv --pedidos ped_fatures.csv
    python3 gerar_dashboard.py --clientes Clientes.csv --pedidos hist.csv set.csv --saida index.html

SUBSTITUICAO TOTAL: cada execucao reconstroi o dashboard inteiro a partir dos CSVs
informados. Nada da versao anterior e aproveitado. O que nao estiver nos arquivos
desta rodada deixa de existir no dashboard.

Por isso o script confere a cobertura do export antes de gravar. Se o periodo for
curto demais para sustentar os indicadores de recencia (padrao: menos de 180 dias),
ele avisa e pede confirmacao. Use --sim para pular a pergunta em automacao.

Os arquivos de pedidos podem ser varios: o script junta todos e remove linhas
repetidas (mesmo pedido + produto + data + quantidade + valor).
"""
import argparse, csv, io, json, os, sys, datetime, collections

CSV_ENC = ['latin-1', 'cp1252', 'utf-8-sig']
COMODATO_AGRUP = 'DISPLAYS'          # agrupamento que identifica display/expositor
DIM_KEYS = ['CODIGO_AGRUP', 'DESCRICAO_AGRUP', 'CPAGTO', 'PORTADOR', 'VENDEDOR', 'REDE',
            'PRODUTO', 'CIDADE', 'TRANSPORTADORA', 'COMPRADOR', 'UN', 'FRETE',
            'TIPO_COTACAO', 'SITUACAO', 'PADRAO_PEDIDO']
NUM_COLS = ['QTDE', 'PRECO', 'PRECO_S_DESC', 'VALORVENDA', 'VALORTABELA', 'PESOBRUTO',
            'PESOLIQUIDO', 'VALOR_COTACAO', 'VALUNIT_COTACAO', 'VALTOTAL_COTACAO']
NA = 'Não informado'


# ------------------------------------------------------------------ leitura
def ler_csv(caminho):
    dados = open(caminho, 'rb').read()
    for enc in CSV_ENC:
        try:
            texto = dados.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit('Não consegui ler %s (codificação desconhecida).' % caminho)
    amostra = texto[:4000]
    sep = ';' if amostra.count(';') >= amostra.count(',') else ','
    return list(csv.DictReader(io.StringIO(texto), delimiter=sep))


def num(v):
    if v is None:
        return 0.0
    v = str(v).strip()
    if not v:
        return 0.0
    v = v.replace('R$', '').replace(' ', '')
    if ',' in v:
        v = v.replace('.', '').replace(',', '.')
    try:
        return float(v)
    except ValueError:
        return 0.0


def data(v):
    v = (v or '').strip()[:10]
    for f in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
        try:
            return datetime.datetime.strptime(v, f).date()
        except ValueError:
            continue
    return None


def txt(v, padrao=NA):
    v = (v or '').strip()
    return v if v else padrao


def bucket(dias):
    if dias is None:
        return 'Nunca comprou'
    if dias <= 30:
        return 'Ativo até 30d'
    if dias <= 60:
        return 'Atenção 31–60d'
    if dias <= 90:
        return 'Risco 61–90d'
    return 'Reativar 90d+'


# ------------------------------------------------------------------ dados
def montar(clientes_csv, pedidos_csvs, ref_txt=None):
    cli = ler_csv(clientes_csv)
    ped, vistos = [], set()
    for caminho in pedidos_csvs:
        linhas = ler_csv(caminho)
        for r in linhas:
            chave = (r.get('NROPEDIDO', ''), r.get('CODPRODUTO', ''), r.get('DATA', ''),
                     r.get('QTDE', ''), r.get('VALORVENDA', ''), r.get('CODCLIENTE', ''))
            if chave in vistos:
                continue
            vistos.add(chave)
            ped.append(r)
        print('  %-42s %7d linhas' % (os.path.basename(caminho), len(linhas)))

    datas = [d for d in (data(r.get('DATA')) for r in ped) if d]
    if not datas:
        raise SystemExit('Nenhuma data válida encontrada na coluna DATA dos pedidos.')
    ref = data(ref_txt) if ref_txt else max(datas)

    # ---- agregacoes por cliente
    C = collections.defaultdict(lambda: {
        'orders': set(), 'value': 0.0, 'first': None, 'last': None,
        'network': None, 'seller': None, 'city': None, 'name': None,
        'prod': collections.Counter()})
    meses = collections.defaultdict(lambda: {'orders': set(), 'value': 0.0})
    redes = collections.defaultdict(lambda: {'clients': set(), 'orders': set(), 'value': 0.0})
    vends = collections.defaultdict(lambda: {'clients': set(), 'orders': set(), 'value': 0.0})
    prods = collections.defaultdict(lambda: {'qty': 0.0, 'orders': set(), 'value': 0.0})
    sits = collections.Counter()
    dims = {k: collections.defaultdict(lambda: {'rows': 0, 'orders': set(), 'clients': set(),
                                                'value': 0.0, 'qty': 0.0}) for k in DIM_KEYS}
    cov = {c: {'sum': 0.0, 'nonzero': 0, 'min': None, 'max': None} for c in NUM_COLS}

    # ---- comodato
    K = collections.defaultdict(lambda: {
        'orders': set(), 'qty': 0.0, 'value': 0.0, 'first': None, 'last': None,
        'items': collections.defaultdict(float), 'det': collections.OrderedDict()})
    com_linhas = 0

    for r in ped:
        cod = (r.get('CODCLIENTE') or '').strip()
        nro = (r.get('NROPEDIDO') or '').strip()
        dt = data(r.get('DATA'))
        qt = num(r.get('QTDE'))
        vl = num(r.get('VALORVENDA'))
        rede = txt(r.get('REDE'), 'SEM REDE')
        vend = txt(r.get('VENDEDOR'), NA)
        prod = txt(r.get('PRODUTO'), NA)

        for c in NUM_COLS:
            v = num(r.get(c))
            s = cov[c]
            s['sum'] += v
            if v:
                s['nonzero'] += 1
            s['min'] = v if s['min'] is None else min(s['min'], v)
            s['max'] = v if s['max'] is None else max(s['max'], v)

        x = C[cod]
        x['orders'].add(nro)
        x['value'] += vl
        x['name'] = x['name'] or txt(r.get('CLIENTE'), '')
        x['network'] = x['network'] or rede
        x['seller'] = x['seller'] or vend
        x['city'] = x['city'] or txt(r.get('CIDADE'), '')
        x['prod'][prod] += qt
        if dt:
            x['first'] = dt if x['first'] is None else min(x['first'], dt)
            x['last'] = dt if x['last'] is None else max(x['last'], dt)
            m = meses[dt.strftime('%Y-%m')]
            m['orders'].add(nro)
            m['value'] += vl

        redes[rede]['clients'].add(cod); redes[rede]['orders'].add(nro); redes[rede]['value'] += vl
        vends[vend]['clients'].add(cod); vends[vend]['orders'].add(nro); vends[vend]['value'] += vl
        prods[prod]['qty'] += qt; prods[prod]['orders'].add(nro); prods[prod]['value'] += vl
        sits[txt(r.get('SITUACAO'), NA)] += 1

        for k in DIM_KEYS:
            d = dims[k][txt(r.get(k), NA)]
            d['rows'] += 1
            d['orders'].add(nro)
            d['clients'].add(cod)
            d['value'] += vl
            d['qty'] += qt

        if (r.get('DESCRICAO_AGRUP') or '').strip().upper() == COMODATO_AGRUP:
            com_linhas += 1
            k = K[cod]
            k['orders'].add(nro)
            k['qty'] += qt
            k['value'] += vl
            k['items'][prod] += qt
            if dt:
                k['first'] = dt if k['first'] is None else min(k['first'], dt)
                k['last'] = dt if k['last'] is None else max(k['last'], dt)
            o = k['det'].setdefault(nro, {'order': nro,
                                          'date': dt.isoformat() if dt else '',
                                          'value': 0.0, 'items': []})
            o['value'] += vl
            o['items'].append({'code': txt(r.get('CODPRODUTO'), ''), 'name': prod,
                               'qty': qt, 'unit': txt(r.get('UN'), ''), 'value': vl})

    # ---- carteira (cadastro + quem comprou)
    cadastro, customers = {}, []
    for r in cli:
        cod = (r.get('CODCLIENTE') or '').strip()
        if cod:
            cadastro[cod] = r

    for cod in sorted(set(list(cadastro) + list(C)), key=lambda c: (len(c), c)):
        m = cadastro.get(cod, {})
        v = C.get(cod)
        nome = txt(m.get('NOME') or m.get('FANTASIA'), '') or (v['name'] if v else '')
        if v and v['name']:
            nome = v['name']
        elif nome:
            nome = '%s - %s' % (cod, nome)
        pedidos = len(v['orders']) if v else 0
        valor = round(v['value'], 2) if v else 0
        ult = v['last'] if v else None
        dias = (ref - ult).days if ult else None
        customers.append({
            'code': cod,
            'name': nome,
            'city': txt(m.get('CIDADE') or (v['city'] if v else ''), '—'),
            'network': (v['network'] if v else '—'),
            'seller': txt(m.get('VENDEDOR') or (v['seller'] if v else ''), '—'),
            'last': ult.isoformat() if ult else '',
            'first': v['first'].isoformat() if v and v['first'] else '',
            'days': dias,
            'bucket': bucket(dias),
            'orders': pedidos,
            'value': valor,
            'avg_ticket': round(valor / pedidos, 2) if pedidos else 0,
            'top_product': v['prod'].most_common(1)[0][0] if v and v['prod'] else '',
            'phone': txt(m.get('CELULAR') or m.get('FONE1'), ''),
            'email': txt(m.get('EMAIL') or m.get('EMAIL_NFE'), ''),
            'master_status': txt(m.get('SITUACAO'), ''),
            'master_last': txt(m.get('ULTCOMPRA'), ''),
        })

    fl = lambda d: {'clients': len(d['clients']), 'orders': len(d['orders']), 'value': round(d['value'], 2)}
    dim_out = {}
    for k in DIM_KEYS:
        dim_out[k] = sorted(
            [{'name': n, 'rows': d['rows'], 'orders': len(d['orders']), 'clients': len(d['clients']),
              'value': round(d['value'], 2), 'qty': round(d['qty'], 2)} for n, d in dims[k].items()],
            key=lambda x: -x['value'])[:400]

    buckets = collections.Counter(c['bucket'] for c in customers)
    DATA = {
        'summary': {
            'reference_date': ref.isoformat(),
            'order_lines': len(ped),
            'unique_orders': len(set((r.get('NROPEDIDO') or '').strip() for r in ped)),
            'active_customers_with_orders': len([c for c in customers if c['orders'] > 0]),
            'master_customers': len(cadastro),
            'never_buyers': len([c for c in customers if c['orders'] == 0]),
            'total_value': round(sum(c['value'] for c in customers), 2),
            'buckets': dict(buckets),
        },
        'customers': sorted(customers, key=lambda c: c['name']),
        'monthly': [{'month': m, 'orders': len(v['orders']), 'value': round(v['value'], 2)}
                    for m, v in sorted(meses.items())],
        'networks': sorted([dict(name=n, **fl(d)) for n, d in redes.items()],
                           key=lambda x: -x['value']),
        'sellers': sorted([dict(name=n, **fl(d)) for n, d in vends.items()],
                          key=lambda x: -x['value']),
        'products': sorted([{'name': n, 'qty': round(d['qty'], 2), 'orders': len(d['orders']),
                             'value': round(d['value'], 2)} for n, d in prods.items()],
                           key=lambda x: -x['qty'])[:400],
        'statuses': [{'name': n, 'count': c} for n, c in sits.most_common()],
        'meta': {'client_rows_read': len(cli), 'order_lines_read': len(ped)},
        'dimensions': dim_out,
        'coverage': {
            'order_columns': list(ped[0].keys()) if ped else [],
            'order_column_count': len(ped[0]) if ped else 0,
            'client_columns': list(cli[0].keys()) if cli else [],
            'client_column_count': len(cli[0]) if cli else 0,
            **{c: {'sum': round(s['sum'], 2), 'nonzero': s['nonzero'],
                   'min': s['min'] or 0, 'max': s['max'] or 0} for c, s in cov.items()},
        },
    }

    com_clients = []
    for cod, k in K.items():
        m = cadastro.get(cod, {})
        v = C.get(cod)
        nome = (v['name'] if v and v['name'] else '%s - %s' % (cod, txt(m.get('NOME'), '')))
        com_clients.append({
            'code': cod,
            'name': nome,
            'city': txt(m.get('CIDADE') or (v['city'] if v else ''), ''),
            'seller': txt(m.get('VENDEDOR') or (v['seller'] if v else ''), NA),
            'network': (v['network'] if v else 'SEM REDE'),
            'comodato_orders': len(k['orders']),
            'items': [{'name': n, 'qty': round(q, 2)} for n, q in
                      sorted(k['items'].items(), key=lambda x: -x[1])],
            'qty': round(k['qty'], 2),
            'value': round(k['value'], 2),
            'first': k['first'].isoformat() if k['first'] else '',
            'last': k['last'].isoformat() if k['last'] else '',
            'order_details': sorted(k['det'].values(), key=lambda o: o['date'], reverse=True),
        })
    com_clients.sort(key=lambda x: x['name'])

    D = {
        'clients': com_clients,
        'summary': {
            'order_lines_read': len(ped),
            'comodato_lines': com_linhas,
            'clients_with_comodato': len(com_clients),
            'comodato_orders': sum(c['comodato_orders'] for c in com_clients),
            'comodato_value': round(sum(c['value'] for c in com_clients), 2),
        },
    }
    return DATA, D, ref, min(datas), max(datas)


# ------------------------------------------------------------------ saida
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--clientes', required=True)
    ap.add_argument('--pedidos', required=True, nargs='+')
    ap.add_argument('--template', default='template.html')
    ap.add_argument('--saida', default='index.html')
    ap.add_argument('--ref', help='data de referência DD/MM/AAAA (padrão: última data dos pedidos)')
    ap.add_argument('--sim', action='store_true', help='não perguntar nada, sobrescrever direto')
    ap.add_argument('--backup', action='store_true', help='renomear a saída anterior antes de gravar')
    ap.add_argument('--minimo-dias', type=int, default=180,
                    help='período mínimo esperado no export de pedidos (padrão 180)')
    a = ap.parse_args()

    print('Lendo arquivos...')
    DATA, D, ref, ini, fim = montar(a.clientes, a.pedidos, a.ref)

    cobertura = (fim - ini).days + 1
    sem_compra = DATA['summary']['never_buyers']
    total_cad = DATA['summary']['master_customers'] or 1
    avisos = []
    if cobertura < a.minimo_dias:
        avisos.append('O export cobre apenas %d dias (%s a %s). Abaixo dos %d dias esperados.'
                      % (cobertura, ini.strftime('%d/%m/%Y'), fim.strftime('%d/%m/%Y'), a.minimo_dias))
    if sem_compra / total_cad > 0.5:
        avisos.append('%d de %d clientes do cadastro (%.0f%%) ficariam como "Nunca comprou".'
                      % (sem_compra, total_cad, 100 * sem_compra / total_cad))
    if len(DATA['monthly']) < 3:
        avisos.append('Só %d mês(es) de histórico: o gráfico de ritmo e a recência ficam sem base.'
                      % len(DATA['monthly']))

    if avisos:
        print('\n' + '!' * 68)
        print('ATENÇÃO — este arquivo SUBSTITUI toda a base do dashboard.')
        for m in avisos:
            print('  · ' + m)
        print('Um export parcial apaga o histórico e zera os indicadores de reativação')
        print('e de comodato parado. O ideal é exportar o período completo.')
        print('!' * 68)
        if not a.sim:
            if not sys.stdin.isatty():
                raise SystemExit('Abortado. Rode com --sim se quiser gravar mesmo assim.')
            if input('Gravar assim mesmo? (digite SIM) ').strip().upper() != 'SIM':
                raise SystemExit('Abortado. Nada foi gravado.')

    if a.backup and os.path.exists(a.saida):
        marca = datetime.datetime.now().strftime('%Y%m%d_%H%M')
        base, ext = os.path.splitext(a.saida)
        anterior = '%s_anterior_%s%s' % (base, marca, ext)
        os.replace(a.saida, anterior)
        print('Versão anterior guardada em %s' % anterior)

    tpl = io.open(a.template, encoding='utf-8').read()
    for marca in ('__DATA_JSON__', '__D_JSON__'):
        if marca not in tpl:
            raise SystemExit('O template não contém a marca %s.' % marca)
    saida = (tpl.replace('__DATA_JSON__', json.dumps(DATA, ensure_ascii=False))
                .replace('__D_JSON__', json.dumps(D, ensure_ascii=False))
                .replace('__REF_DATE__', ref.strftime('%d/%m/%Y'))
                .replace('__PERIODO_INICIO__', DATA['monthly'][0]['month'].split('-')[::-1][0] + '/' + DATA['monthly'][0]['month'].split('-')[0]))
    io.open(a.saida, 'w', encoding='utf-8').write(saida)

    s = DATA['summary']
    print('\nReferência ............. %s' % ref.strftime('%d/%m/%Y'))
    print('Cobertura .............. %s a %s (%d dias)' % (ini.strftime('%d/%m/%Y'), fim.strftime('%d/%m/%Y'), cobertura))
    print('Período ................ %s a %s' % (DATA['monthly'][0]['month'], DATA['monthly'][-1]['month']))
    print('Linhas de pedido ....... %s' % f"{s['order_lines']:,}".replace(',', '.'))
    print('Pedidos únicos ......... %s' % f"{s['unique_orders']:,}".replace(',', '.'))
    print('Clientes no cadastro ... %s' % f"{s['master_customers']:,}".replace(',', '.'))
    print('Clientes com compra .... %s' % f"{s['active_customers_with_orders']:,}".replace(',', '.'))
    print('Valor total ............ R$ %s' % f"{s['total_value']:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
    print('Clientes com comodato .. %s (%s itens)' % (D['summary']['clients_with_comodato'],
          f"{sum(c['qty'] for c in D['clients']):,.0f}".replace(',', '.')))
    print('\nArquivo gerado: %s (%.1f MB)' % (a.saida, os.path.getsize(a.saida) / 1048576))


if __name__ == '__main__':
    main()
