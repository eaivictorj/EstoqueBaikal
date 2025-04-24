from app import app, db, Usuario
from werkzeug.security import generate_password_hash

with app.app_context():
    novo_usuario = Usuario(
        nome="Admin",
        email="admin@gmail.com",
        senha=generate_password_hash("123"),
        perfil="admin"
    )

    db.session.add(novo_usuario)
    db.session.commit()

    print("Usuário admin criado com sucesso!")
