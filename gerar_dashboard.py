#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera o dashboard Radar Comercial Freedom a partir dos CSVs exportados do sistema.

Uso:
    python3 gerar_dashboard.py --clientes dados/Clientes.csv --pedidos dados/pedidos.csv --publico

SUBSTITUICAO TOTAL: cada execucao reconstroi o dashboard inteiro a partir dos CSVs
informados. Nada da versao anterior e aproveitado. O que nao estiver nos arquivos
desta rodada deixa de existir no dashboard.

Por isso o script confere a cobertura do export antes de gravar. Se o periodo for
curto demais para sustentar os indicadores de recencia (padrao: menos de 180 dias),
ele avisa e pede confirmacao. Use --sim para pular a pergunta em automacao.

COMO O COMODATO E IDENTIFICADO
    1. Se o export trouxer a coluna DESCRICAO_AGRUP, vale o agrupamento DISPLAYS.
       Os codigos de produto encontrados assim sao gravados em comodato_produtos.json.
    2. Se a coluna nao vier no export, o script usa a lista de codigos desse arquivo.
    Um export com o agrupamento mantem a lista em dia; um export sem ele ainda
    funciona, usando o que ja foi aprendido antes.

Os arquivos de pedidos podem ser varios: o script junta todos e remove linhas
repetidas (mesmo pedido + produto + data + quantidade + valor).
"""
import argparse, csv, io, json, os, sys, datetime, collections

CSV_ENC = ['latin-1', 'cp1252', 'utf-8-sig']
COMODATO_AGRUP = 'DISPLAYS'
LISTA_PRODUTOS = 'comodato_produtos.json'
DIM_KEYS = ['CODIGO_AGRUP', 'DESCRICAO_AGRUP', 'CPAGTO', 'PORTADOR', 'VENDEDOR', 'REDE',
            'PRODUTO', 'CIDADE', 'TRANSPORTADORA', 'COMPRADOR', 'UN', 'FRETE',
            'TIPO_COTACAO', 'SITUACAO', 'PADRAO_PEDIDO']
NUM_COLS = ['QTDE', 'PRECO', 'PRECO_S_DESC', 'VALORVENDA', 'VALORTABELA', 'PESOBRUTO',
            'PESOLIQUIDO', 'VALOR_COTACAO', 'VALUNIT_COTACAO', 'VALTOTAL_COTACAO']
NA = 'Não informado'


def abrir(caminho):
    """Devolve um DictReader lendo o arquivo em streaming, mais o handle aberto."""
    amostra_bytes = open(caminho, 'rb').read(200000)
    enc = 'latin-1'
    for e in CSV_ENC:
        try:
            amostra_bytes.decode(e)
            enc = e
            break
        except UnicodeDecodeError:
            continue
    amostra = amostra_bytes.decode(enc, 'replace')[:4000]
    sep = ';' if amostra.count(';') >= amostra.count(',') else ','
    f = io.open(caminho, encoding=enc, errors='replace', newline='')
    return csv.DictReader(f, delimiter=sep), f


def num(v):
    if not v:
        return 0.0
    v = str(v).strip().replace('R$', '').replace(' ', '')
    if not v:
        return 0.0
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


def carregar_lista(pasta):
    caminho = os.path.join(pasta, LISTA_PRODUTOS)
    if os.path.exists(caminho):
        try:
            return json.load(io.open(caminho, encoding='utf-8')).get('produtos', {})
        except Exception as e:
            print('Aviso: não consegui ler %s (%s).' % (LISTA_PRODUTOS, e))
    return {}


def salvar_lista(pasta, produtos):
    io.open(os.path.join(pasta, LISTA_PRODUTOS), 'w', encoding='utf-8').write(json.dumps(
        {'agrupamento': COMODATO_AGRUP, 'produtos': dict(sorted(produtos.items()))},
        ensure_ascii=False, indent=1))


def montar(clientes_csv, pedidos_csvs, ref_txt, conhecidos):
    rd, fh = abrir(clientes_csv)
    cli = list(rd)
    fh.close()
    cadastro = {}
    for r in cli:
        cod = (r.get('CODCLIENTE') or '').strip()
        if cod:
            cadastro[cod] = r

    C = collections.defaultdict(lambda: {
        'orders': set(), 'value': 0.0, 'first': None, 'last': None,
        'network': None, 'seller': None, 'city': None, 'name': None,
        'prod': collections.Counter()})
    meses = collections.defaultdict(lambda: {'orders': set(), 'value': 0.0})
    redes = collections.defaultdict(lambda: {'clients': set(), 'orders': set(), 'value': 0.0})
    vends = collections.defaultdict(lambda: {'clients': set(), 'orders': set(), 'value': 0.0})
    prods = collections.defaultdict(lambda: {'qty': 0.0, 'orders': set(), 'value': 0.0})
    sits = collections.Counter()
    dims = collections.defaultdict(lambda: collections.defaultdict(
        lambda: {'rows': 0, 'orders': set(), 'clients': set(), 'value': 0.0, 'qty': 0.0}))
    cov = {c: {'sum': 0.0, 'nonzero': 0, 'min': None, 'max': None} for c in NUM_COLS}
    K = collections.defaultdict(lambda: {
        'orders': set(), 'qty': 0.0, 'value': 0.0, 'first': None, 'last': None,
        'items': collections.defaultdict(float), 'det': collections.OrderedDict()})

    vistos, colunas, dim_cols = set(), [], None
    linhas = com_linhas = 0
    dmin = dmax = None
    aprendidos = dict(conhecidos)
    tinha_agrup = False

    for caminho in pedidos_csvs:
        rd, fh = abrir(caminho)
        campos = rd.fieldnames or []
        if not colunas:
            colunas = list(campos)
        if dim_cols is None:
            dim_cols = [k for k in DIM_KEYS if k in campos]
        tem_agrup = 'DESCRICAO_AGRUP' in campos
        tinha_agrup = tinha_agrup or tem_agrup
        n0 = linhas

        for r in rd:
            chave = (r.get('NROPEDIDO', ''), r.get('CODPRODUTO', ''), r.get('DATA', ''),
                     r.get('QTDE', ''), r.get('VALORVENDA', ''), r.get('CODCLIENTE', ''))
            if chave in vistos:
                continue
            vistos.add(chave)
            linhas += 1

            cod = (r.get('CODCLIENTE') or '').strip()
            nro = (r.get('NROPEDIDO') or '').strip()
            cprod = (r.get('CODPRODUTO') or '').strip()
            dt = data(r.get('DATA'))
            qt = num(r.get('QTDE'))
            vl = num(r.get('VALORVENDA'))
            rede = txt(r.get('REDE'), 'SEM REDE')
            vend = txt(r.get('VENDEDOR'), NA)
            prod = txt(r.get('PRODUTO'), NA)

            for c in NUM_COLS:
                if c not in r:
                    continue
                v = num(r.get(c))
                st = cov[c]
                st['sum'] += v
                if v:
                    st['nonzero'] += 1
                st['min'] = v if st['min'] is None else min(st['min'], v)
                st['max'] = v if st['max'] is None else max(st['max'], v)

            x = C[cod]
            x['orders'].add(nro)
            x['value'] += vl
            if not x['name']:
                x['name'] = txt(r.get('CLIENTE'), '')
            if not x['network']:
                x['network'] = rede
            if not x['seller']:
                x['seller'] = vend
            if not x['city']:
                x['city'] = txt(r.get('CIDADE'), '')
            x['prod'][prod] += qt
            if dt:
                x['first'] = dt if x['first'] is None else min(x['first'], dt)
                x['last'] = dt if x['last'] is None else max(x['last'], dt)
                dmin = dt if dmin is None else min(dmin, dt)
                dmax = dt if dmax is None else max(dmax, dt)
                m = meses[dt.strftime('%Y-%m')]
                m['orders'].add(nro)
                m['value'] += vl

            redes[rede]['clients'].add(cod); redes[rede]['orders'].add(nro); redes[rede]['value'] += vl
            vends[vend]['clients'].add(cod); vends[vend]['orders'].add(nro); vends[vend]['value'] += vl
            prods[prod]['qty'] += qt; prods[prod]['orders'].add(nro); prods[prod]['value'] += vl
            sits[txt(r.get('SITUACAO'), NA)] += 1

            for k in dim_cols:
                d = dims[k][txt(r.get(k), NA)]
                d['rows'] += 1
                d['orders'].add(nro)
                d['clients'].add(cod)
                d['value'] += vl
                d['qty'] += qt

            if tem_agrup:
                ehcom = (r.get('DESCRICAO_AGRUP') or '').strip().upper() == COMODATO_AGRUP
                if ehcom and cprod:
                    aprendidos[cprod] = prod
            else:
                ehcom = cprod in aprendidos

            if ehcom:
                com_linhas += 1
                k = K[cod]
                k['orders'].add(nro)
                k['qty'] += qt
                k['value'] += vl
                k['items'][prod] += qt
                if dt:
                    k['first'] = dt if k['first'] is None else min(k['first'], dt)
                    k['last'] = dt if k['last'] is None else max(k['last'], dt)
                o = k['det'].setdefault(nro, {'order': nro, 'date': dt.isoformat() if dt else '',
                                              'value': 0.0, 'items': []})
                o['value'] += vl
                o['items'].append({'code': cprod, 'name': prod, 'qty': qt,
                                   'unit': txt(r.get('UN'), ''), 'value': vl})
        fh.close()
        print('  %-40s %9s linhas%s' % (os.path.basename(caminho)[:40],
              f'{linhas - n0:,}'.replace(',', '.'),
              '' if tem_agrup else '   (sem DESCRICAO_AGRUP)'))

    if dmin is None:
        raise SystemExit('Nenhuma data válida encontrada na coluna DATA dos pedidos.')
    ref = data(ref_txt) or dmax

    customers = []
    for cod in set(list(cadastro) + list(C)):
        m = cadastro.get(cod, {})
        v = C.get(cod)
        if v and v['name']:
            nome = v['name']
        else:
            base = txt(m.get('NOME') or m.get('FANTASIA'), '')
            nome = '%s - %s' % (cod, base) if base else cod
        np_ = len(v['orders']) if v else 0
        valor = round(v['value'], 2) if v else 0
        ult = v['last'] if v else None
        dias = (ref - ult).days if ult else None
        customers.append({
            'code': cod, 'name': nome,
            'city': txt(m.get('CIDADE') or (v['city'] if v else ''), '—'),
            'network': (v['network'] if v else '—'),
            'seller': txt(m.get('VENDEDOR') or (v['seller'] if v else ''), '—'),
            'last': ult.isoformat() if ult else '',
            'first': v['first'].isoformat() if v and v['first'] else '',
            'days': dias, 'bucket': bucket(dias), 'orders': np_, 'value': valor,
            'avg_ticket': round(valor / np_, 2) if np_ else 0,
            'top_product': v['prod'].most_common(1)[0][0] if v and v['prod'] else '',
            'phone': txt(m.get('CELULAR') or m.get('FONE1'), ''),
            'email': txt(m.get('EMAIL') or m.get('EMAIL_NFE'), ''),
            'master_status': txt(m.get('SITUACAO'), ''),
            'master_last': txt(m.get('ULTCOMPRA'), ''),
        })

    fl = lambda d: {'clients': len(d['clients']), 'orders': len(d['orders']), 'value': round(d['value'], 2)}
    dim_out = {k: sorted([{'name': n, 'rows': d['rows'], 'orders': len(d['orders']),
                           'clients': len(d['clients']), 'value': round(d['value'], 2),
                           'qty': round(d['qty'], 2)} for n, d in dims[k].items()],
                         key=lambda x: -x['value'])[:400] for k in dims}

    DATA = {
        'summary': {
            'reference_date': ref.isoformat(), 'order_lines': linhas,
            'unique_orders': len(set(k[0] for k in vistos)),
            'active_customers_with_orders': len([c for c in customers if c['orders'] > 0]),
            'master_customers': len(cadastro),
            'never_buyers': len([c for c in customers if c['orders'] == 0]),
            'total_value': round(sum(c['value'] for c in customers), 2),
            'buckets': dict(collections.Counter(c['bucket'] for c in customers)),
        },
        'customers': sorted(customers, key=lambda c: c['name']),
        'monthly': [{'month': m, 'orders': len(v['orders']), 'value': round(v['value'], 2)}
                    for m, v in sorted(meses.items())],
        'networks': sorted([dict(name=n, **fl(d)) for n, d in redes.items()], key=lambda x: -x['value']),
        'sellers': sorted([dict(name=n, **fl(d)) for n, d in vends.items()], key=lambda x: -x['value']),
        'products': sorted([{'name': n, 'qty': round(d['qty'], 2), 'orders': len(d['orders']),
                             'value': round(d['value'], 2)} for n, d in prods.items()],
                           key=lambda x: -x['qty'])[:400],
        'statuses': [{'name': n, 'count': c} for n, c in sits.most_common()],
        'meta': {'client_rows_read': len(cli), 'order_lines_read': linhas},
        'dimensions': dim_out,
        'coverage': {
            'order_columns': colunas, 'order_column_count': len(colunas),
            'client_columns': list(cli[0].keys()) if cli else [],
            'client_column_count': len(cli[0]) if cli else 0,
            **{c: {'sum': round(s['sum'], 2), 'nonzero': s['nonzero'],
                   'min': s['min'] or 0, 'max': s['max'] or 0} for c, s in cov.items()},
        },
    }

    com = []
    for cod, k in K.items():
        m = cadastro.get(cod, {})
        v = C.get(cod)
        nome = v['name'] if v and v['name'] else '%s - %s' % (cod, txt(m.get('NOME'), ''))
        com.append({
            'code': cod, 'name': nome,
            'city': txt(m.get('CIDADE') or (v['city'] if v else ''), ''),
            'seller': txt(m.get('VENDEDOR') or (v['seller'] if v else ''), NA),
            'network': (v['network'] if v else 'SEM REDE'),
            'comodato_orders': len(k['orders']),
            'items': [{'name': n, 'qty': round(q, 2)} for n, q in
                      sorted(k['items'].items(), key=lambda x: -x[1])],
            'qty': round(k['qty'], 2), 'value': round(k['value'], 2),
            'first': k['first'].isoformat() if k['first'] else '',
            'last': k['last'].isoformat() if k['last'] else '',
            'order_details': sorted(k['det'].values(), key=lambda o: o['date'], reverse=True),
        })
    com.sort(key=lambda x: x['name'])

    D = {'clients': com, 'summary': {
        'order_lines_read': linhas, 'comodato_lines': com_linhas,
        'clients_with_comodato': len(com),
        'comodato_orders': sum(c['comodato_orders'] for c in com),
        'comodato_value': round(sum(c['value'] for c in com), 2)}}

    return DATA, D, ref, dmin, dmax, aprendidos, tinha_agrup


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--clientes', required=True)
    ap.add_argument('--pedidos', required=True, nargs='+')
    ap.add_argument('--template', default='template.html')
    ap.add_argument('--saida', default='index.html')
    ap.add_argument('--ref', help='data de referência DD/MM/AAAA (padrão: última data dos pedidos)')
    ap.add_argument('--sim', action='store_true', help='não perguntar nada, sobrescrever direto')
    ap.add_argument('--publico', action='store_true',
                    help='remove telefone e e-mail dos clientes (use ao publicar no GitHub Pages)')
    ap.add_argument('--backup', action='store_true', help='renomear a saída anterior antes de gravar')
    ap.add_argument('--minimo-dias', type=int, default=180,
                    help='período mínimo esperado no export de pedidos (padrão 180)')
    a = ap.parse_args()

    pasta = os.path.dirname(os.path.abspath(a.template)) or '.'
    conhecidos = carregar_lista(pasta)
    print('Lendo arquivos...')
    if conhecidos:
        print('  lista de comodato: %d produtos conhecidos' % len(conhecidos))
    DATA, D, ref, ini, fim, aprendidos, tinha_agrup = montar(a.clientes, a.pedidos, a.ref, conhecidos)

    novos = len(aprendidos) - len(conhecidos)
    if tinha_agrup and novos > 0:
        salvar_lista(pasta, aprendidos)
        print('  %d produto(s) novo(s) de comodato salvos em %s' % (novos, LISTA_PRODUTOS))
    if not tinha_agrup and not conhecidos:
        raise SystemExit('Os pedidos não trazem DESCRICAO_AGRUP e não existe %s para consultar.\n'
                         'Exporte uma vez com a coluna de agrupamento para montar a lista.' % LISTA_PRODUTOS)

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
    if D['summary']['clients_with_comodato'] == 0:
        avisos.append('Nenhum comodato identificado. Confira a lista de produtos.')

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

    if a.publico:
        limpos = sum(1 for c in DATA['customers'] if c['phone'] or c['email'])
        for c in DATA['customers']:
            c['phone'] = c['email'] = ''
        print('Modo público: telefone e e-mail removidos de %d clientes.' % limpos)

    if a.backup and os.path.exists(a.saida):
        base, ext = os.path.splitext(a.saida)
        anterior = '%s_anterior_%s%s' % (base, datetime.datetime.now().strftime('%Y%m%d_%H%M'), ext)
        os.replace(a.saida, anterior)
        print('Versão anterior guardada em %s' % anterior)

    tpl = io.open(a.template, encoding='utf-8').read()
    for marca in ('__DATA_JSON__', '__D_JSON__'):
        if marca not in tpl:
            raise SystemExit('O template não contém a marca %s.' % marca)
    mes0 = DATA['monthly'][0]['month'].split('-')
    io.open(a.saida, 'w', encoding='utf-8').write(
        tpl.replace('__DATA_JSON__', json.dumps(DATA, ensure_ascii=False))
           .replace('__D_JSON__', json.dumps(D, ensure_ascii=False))
           .replace('__REF_DATE__', ref.strftime('%d/%m/%Y'))
           .replace('__PERIODO_INICIO__', '%s/%s' % (mes0[1], mes0[0])))

    s, ds = DATA['summary'], D['summary']
    br = lambda v: f'{v:,}'.replace(',', '.')
    print('\nReferência ............. %s' % ref.strftime('%d/%m/%Y'))
    print('Cobertura .............. %s a %s (%d dias, %d meses)'
          % (ini.strftime('%d/%m/%Y'), fim.strftime('%d/%m/%Y'), cobertura, len(DATA['monthly'])))
    print('Linhas de pedido ....... %s' % br(s['order_lines']))
    print('Pedidos únicos ......... %s' % br(s['unique_orders']))
    print('Clientes no cadastro ... %s' % br(s['master_customers']))
    print('Clientes com compra .... %s' % br(s['active_customers_with_orders']))
    print('Valor total ............ R$ %s'
          % f"{s['total_value']:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
    print('Comodato ............... %s clientes · %s linhas · %s itens'
          % (br(ds['clients_with_comodato']), br(ds['comodato_lines']),
             br(int(sum(c['qty'] for c in D['clients'])))))
    print('Recência ............... ' + ' · '.join('%s: %s' % (k, br(v)) for k, v in s['buckets'].items()))
    print('Modo ................... %s' % ('PÚBLICO (sem contatos)' if a.publico else 'interno (com contatos)'))
    print('\nArquivo gerado: %s (%.1f MB)' % (a.saida, os.path.getsize(a.saida) / 1048576))
    if not a.publico:
        print('Este arquivo contém telefone e e-mail de clientes. Não publique sem --publico.')


if __name__ == '__main__':
    main()
