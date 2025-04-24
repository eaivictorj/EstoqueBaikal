from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import io
from io import BytesIO
import pandas as pd
from xhtml2pdf import pisa
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
import openpyxl
from functools import wraps
from sqlalchemy import func, desc

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///almoxarifado.db'
app.config['SECRET_KEY'] = 'secreta'
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- Models ---

class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha = db.Column(db.String(100), nullable=False)
    perfil = db.Column(db.String(50), nullable=False)

class Produto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    codigo_barras = db.Column(db.String(100), unique=True, nullable=False)
    quantidade = db.Column(db.Integer, default=0)
    local = db.Column(db.String(100), nullable=False)
    data_cadastro = db.Column(db.DateTime, default=datetime.utcnow)
    familia = db.Column(db.String(100))
    fator = db.Column(db.String(50))
    rua = db.Column(db.String(50))
    prateleira = db.Column(db.String(50))
    nivel = db.Column(db.String(50))
    coluna = db.Column(db.String(50))

class HistoricoMovimentacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    data = db.Column(db.DateTime, default=datetime.utcnow)
    responsavel = db.Column(db.String(100), nullable=False)
    local = db.Column(db.String(100))
    observacoes = db.Column(db.Text)
    produto = db.relationship('Produto')

# --- Autenticação ---
@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.perfil != 'admin':
            flash("Apenas administradores podem acessar esta página.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated_function

# --- Lógica de saldo ---
def calcular_saldos(produto_id):
    entradas = db.session.query(db.func.sum(HistoricoMovimentacao.quantidade))\
        .filter_by(produto_id=produto_id, tipo='entrada').scalar() or 0
    saidas = db.session.query(db.func.sum(HistoricoMovimentacao.quantidade))\
        .filter_by(produto_id=produto_id, tipo='saida').scalar() or 0
    cadastro = HistoricoMovimentacao.query.filter_by(produto_id=produto_id, tipo='Cadastro').first()
    quantidade_inicial = cadastro.quantidade if cadastro else 0
    saldo = quantidade_inicial + entradas - saidas
    return {
        'inicial': quantidade_inicial,
        'entradas': entradas,
        'saidas': saidas,
        'saldo': saldo
    }

# --- Rotas ---
@app.route('/')
def index():
    return redirect(url_for('inventario')) if current_user.is_authenticated else redirect(url_for('login'))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get('email')
        senha = request.form.get('senha')
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario and check_password_hash(usuario.senha, senha):
            login_user(usuario)
            return redirect(url_for('inventario'))
        flash("Email ou senha inválidos", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route("/consulta")
@login_required
def consulta():
    produtos = Produto.query.all()
    return render_template("consulta.html", produtos=produtos)

@app.route("/inventario")
@login_required
def inventario():
    busca = request.args.get("busca", "")
    data_inicio_str = request.args.get("data_inicio", "")
    data_fim_str = request.args.get("data_fim", "")

    data_inicio = datetime.strptime(data_inicio_str, "%Y-%m-%d") if data_inicio_str else None
    data_fim = datetime.strptime(data_fim_str, "%Y-%m-%d") if data_fim_str else None

    if data_fim:
        # Adiciona 1 dia para incluir movimentações no final do dia selecionado
        data_fim = datetime.combine(data_fim, datetime.max.time())

    if busca:
        produtos = Produto.query.filter(
            (Produto.nome.ilike(f"%{busca}%")) | (Produto.codigo_barras.ilike(f"%{busca}%"))
        ).all()
    else:
        produtos = Produto.query.all()

    saldos = {p.id: calcular_saldos(p.id) for p in produtos}
    movimentacoes = {}

    for p in produtos:
        query = HistoricoMovimentacao.query.filter_by(produto_id=p.id)
        if data_inicio:
            query = query.filter(HistoricoMovimentacao.data >= data_inicio)
        if data_fim:
            query = query.filter(HistoricoMovimentacao.data <= data_fim)
        movimentacoes[p.id] = query.order_by(HistoricoMovimentacao.data.desc()).all()

    return render_template("inventario.html", produtos=produtos, saldos=saldos, movimentacoes=movimentacoes,
                           busca=busca, data_inicio=data_inicio_str, data_fim=data_fim_str)








@app.route('/cadastro_produto', methods=['GET', 'POST'])
@login_required
def cadastro_produto():
    if request.method == 'POST':
        nome = request.form['nome']
        codigo_barras = request.form['codigo_barras']
        quantidade = int(request.form['quantidade'])
        local = request.form['local']
        familia = request.form['familia']
        fator = request.form['fator']
        rua = request.form['rua']
        prateleira = request.form['prateleira']
        nivel = request.form['nivel']
        coluna = request.form['coluna']

        produto = Produto(
            nome=nome,
            codigo_barras=codigo_barras,
            local=local,
            familia=familia,
            fator=fator,
            rua=rua,
            prateleira=prateleira,
            nivel=nivel,
            coluna=coluna,
            data_cadastro=datetime.now()
        )
        db.session.add(produto)
        db.session.commit()

        # Cadastra também a entrada como movimentação
        movimentacao = HistoricoMovimentacao(
    produto_id=produto.id,
    tipo='Cadastro',
    quantidade=quantidade,
    data=datetime.now(),
    responsavel=current_user.nome,
    local=local,
    observacoes="Cadastro inicial do produto"
)

        db.session.add(movimentacao)
        db.session.commit()

        flash('Produto cadastrado com sucesso!', 'success')
        return redirect(url_for('cadastro_produto'))

    return render_template('cadastro_produto.html')


@app.route("/entrada_saida", methods=["GET", "POST"])
@login_required
def entrada_saida():
    if request.method == "POST":
        codigo = request.form.get("codigo")
        tipo = request.form.get("tipo")
        destino = request.form.get("destino")
        observacoes = request.form.get("observacoes")
        try:
            quantidade = int(request.form.get("quantidade"))
        except (ValueError, TypeError):
            flash("Quantidade inválida.", "danger")
            return redirect(url_for("entrada_saida"))

        if quantidade <= 0:
            flash("Quantidade deve ser maior que zero.", "danger")
            return redirect(url_for("entrada_saida"))

        produto = Produto.query.filter_by(codigo_barras=codigo).first()
        if not produto:
            flash("Produto não encontrado!", "danger")
            return redirect(url_for("entrada_saida"))

        saldos = calcular_saldos(produto.id)
        if tipo == "saida" and saldos['saldo'] < quantidade:
            flash("Estoque insuficiente para saída!", "danger")
            return redirect(url_for("entrada_saida"))

        # Registrar a movimentação
        movimentacao = HistoricoMovimentacao(
            produto_id=produto.id,
            tipo=tipo,
            quantidade=quantidade,
            responsavel=current_user.nome,
            local=destino,
            observacoes=observacoes,
            data=datetime.now()
        )
        db.session.add(movimentacao)
        db.session.commit()

        flash(f"Movimentação de {tipo} registrada com sucesso!", "success")
        
        # Redirecionar para a página do inventário
        return redirect(url_for('inventario'))  # Redireciona para o inventário após a movimentação ser registrada

    return render_template("entrada_saida.html")


@app.route("/criar_conta", methods=["GET", "POST"])
@login_required
@admin_required
def criar_usuario():
    if request.method == "POST":
        nome = request.form.get("nome")
        email = request.form.get("email")
        senha = request.form.get("senha")
        perfil = request.form.get("perfil")

        if Usuario.query.filter_by(email=email).first():
            flash("Email já cadastrado!", "danger")
        else:
            novo_usuario = Usuario(nome=nome, email=email, senha=generate_password_hash(senha), perfil=perfil)
            db.session.add(novo_usuario)
            db.session.commit()
            flash("Usuário criado com sucesso!", "success")
            return redirect(url_for("login"))

    return render_template("criar_usuario.html")

@app.route('/editar_produto/<int:produto_id>', methods=['GET', 'POST'])
@login_required
def editar_produto(produto_id):
    produto = Produto.query.get_or_404(produto_id)

    if request.method == 'POST':
        produto.nome = request.form['nome']
        produto.codigo_barras = request.form['codigo_barras']
        produto.quantidade = int(request.form['quantidade'])
        produto.local = request.form['local']
        produto.familia = request.form['familia']
        produto.fator = request.form['fator']
        produto.rua = request.form['rua']
        produto.prateleira = request.form['prateleira']
        produto.nivel = request.form['nivel']
        produto.coluna = request.form['coluna']
        
        db.session.commit()
        flash('Produto atualizado com sucesso!')
        return redirect(url_for('inventario'))

    return render_template('editar_produto.html', produto=produto)

@app.route('/excluir_produto/<int:produto_id>', methods=['POST', 'GET'])
@login_required
def excluir_produto(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    db.session.delete(produto)
    db.session.commit()
    flash('Produto excluído com sucesso!')
    return redirect(url_for('inventario'))

@app.route("/relatorio/pdf")
@login_required
def relatorio_pdf():
    produtos = Produto.query.all()
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=landscape(A4))
    width, height = landscape(A4)

    headers = [
        "Nome", "Código de Barras", "Qtd", "Local", "Família",
        "Fator", "Rua", "Prateleira", "Nível", "Coluna"
    ]
    col_widths = [100, 90, 40, 60, 70, 45, 45, 65, 45, 45]

    x_start = 30
    y = height - 40

    p.setFont("Helvetica-Bold", 10)
    x = x_start
    for i, header in enumerate(headers):
        p.drawString(x, y, header)
        x += col_widths[i]
    y -= 20

    p.setFont("Helvetica", 9)
    for produto in produtos:
        if y < 40:
            p.showPage()
            y = height - 40
            p.setFont("Helvetica-Bold", 10)
            x = x_start
            for i, header in enumerate(headers):
                p.drawString(x, y, header)
                x += col_widths[i]
            y -= 20
            p.setFont("Helvetica", 9)

        x = x_start
        valores = [
            produto.nome, produto.codigo_barras, str(produto.quantidade),
            produto.local, produto.familia, produto.fator,
            produto.rua, produto.prateleira, produto.nivel, produto.coluna
        ]

        for i, valor in enumerate(valores):
            p.drawString(x, y, str(valor))
            x += col_widths[i]
        y -= 18

    p.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="relatorio.pdf", mimetype="application/pdf")

@app.route('/relatorio/excel')
@login_required
def relatorio_excel():
    produtos = Produto.query.all()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inventário"
    headers = [
        "Nome", "Código de Barras", "Quantidade", "Local", "Família",
        "Fator", "Rua", "Prateleira", "Nível", "Coluna"
    ]
    ws.append(headers)
    for produto in produtos:
        ws.append([
            produto.nome,
            produto.codigo_barras,
            produto.quantidade,
            produto.local,
            produto.familia,
            produto.fator,
            produto.rua,
            produto.prateleira,
            produto.nivel,
            produto.coluna
        ])
    excel_io = BytesIO()
    wb.save(excel_io)
    excel_io.seek(0)
    return send_file(
        excel_io,
        as_attachment=True,
        download_name="relatorio.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route('/api/produto/<codigo>')
@login_required
def api_obter_produto(codigo):
    produto = Produto.query.filter_by(codigo_barras=codigo).first()
    if not produto:
        return jsonify({'erro': 'Produto não encontrado.'})

    saldo_info = calcular_saldos(produto.id)
    return jsonify({
        'nome': produto.nome,
        'saldo': saldo_info['saldo']
    })
@app.route('/movimentacoes', methods=['GET'])
@login_required
def movimentacoes():
    filtro = request.args.get('filtro', '')
    if filtro:
        movimentacoes = HistoricoMovimentacao.query.join(Produto).filter(
            (Produto.nome.ilike(f"%{filtro}%")) | 
            (Produto.codigo_barras.ilike(f"%{filtro}%"))
        ).order_by(HistoricoMovimentacao.data.desc()).all()
    else:
        movimentacoes = HistoricoMovimentacao.query.order_by(HistoricoMovimentacao.data.desc()).all()

    return render_template('movimentacoes.html', movimentacoes=movimentacoes)


@app.route("/relatorio", methods=["GET", "POST"])
@login_required
def relatorio_movimentacoes():
    filtro_codigo = request.args.get("filtro_codigo", "").strip()
    movimentacoes = []
    produto = None

    if filtro_codigo:
        produto = Produto.query.filter(Produto.codigo_barras.ilike(f"%{filtro_codigo}%")).first()
        if produto:
            movimentacoes = HistoricoMovimentacao.query.filter_by(produto_id=produto.id).order_by(HistoricoMovimentacao.data.desc()).all()
            if not movimentacoes:
                flash("Nenhuma movimentação encontrada para este código.", "warning")
        else:
            flash("Produto não encontrado!", "danger")

    return render_template("relatorio_movimentacoes.html", movimentacoes=movimentacoes, filtro_codigo=filtro_codigo, produto=produto)
@app.route('/exportar_movimentacoes_excel')
@login_required
def exportar_movimentacoes_excel():
    filtro = request.args.get('filtro', '')
    if filtro:
        movimentacoes = HistoricoMovimentacao.query.join(Produto).filter(
            (Produto.nome.ilike(f"%{filtro}%")) | 
            (Produto.codigo_barras.ilike(f"%{filtro}%"))
        ).order_by(HistoricoMovimentacao.data.desc()).all()
    else:
        movimentacoes = HistoricoMovimentacao.query.order_by(HistoricoMovimentacao.data.desc()).all()

    output = BytesIO()

    data = [{
        'Data': m.data.strftime('%d/%m/%Y %H:%M'),
        'Produto': m.produto.nome,
        'Código': m.produto.codigo_barras,
        'Tipo': m.tipo,
        'Quantidade': m.quantidade,
        'Responsável': m.responsavel
    } for m in movimentacoes]

    df = pd.DataFrame(data)
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)

    nome_arquivo = f"movimentacoes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(output, as_attachment=True,
                     download_name=nome_arquivo,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


from flask import render_template
from sqlalchemy import func, desc
# ... outros imports

@app.route('/dashboard')
def dashboard():
    # Top 5 produtos mais movimentados
    top_movimentados = db.session.query(
        Produto.nome,
        func.sum(HistoricoMovimentacao.quantidade).label('total_movimentado')
    ).join(HistoricoMovimentacao).group_by(Produto.id).order_by(desc('total_movimentado')).limit(5).all()

    # Gráfico de movimentações ao longo do tempo
    movimentacoes_por_data = db.session.query(
        func.date(HistoricoMovimentacao.data).label('data'),
        func.sum(HistoricoMovimentacao.quantidade).label('quantidade')
    ).group_by(func.date(HistoricoMovimentacao.data)).order_by('data').all()

    # ⚠️ Produtos com estoque baixo (ex: abaixo de 10 unidades)
    LIMIAR_ESTOQUE_BAIXO = 10
    produtos_baixo_estoque = Produto.query.filter(Produto.quantidade <= LIMIAR_ESTOQUE_BAIXO).all()

    # Indicadores rápidos
    total_produtos = Produto.query.count()
    total_estoque = db.session.query(func.sum(Produto.quantidade)).scalar() or 0

    return render_template('dashboard.html',
                           top_produtos=top_movimentados,
                           movimentacoes_por_data=movimentacoes_por_data,
                           produtos_estoque_baixo=produtos_baixo_estoque,
                           total_produtos=total_produtos,
                           total_estoque=total_estoque)





# --- Execução ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='172.7.10.20')
