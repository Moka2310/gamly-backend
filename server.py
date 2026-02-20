from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="GAMLY API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "GAMLY API is running"}

@app.get("/api/health")
async def health():
    return {"status": "healthy"}

@app.get("/api/delete-account", response_class=HTMLResponse)
async def delete_account_page():
    html = """<!DOCTYPE html>
<html><head><title>Supprimer mon compte - GAMLY</title>
<style>body{font-family:sans-serif;background:#1a1a2e;color:white;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}.container{background:rgba(255,255,255,0.1);padding:40px;border-radius:20px;max-width:500px;text-align:center}h1{color:#FF1493}.warning{background:rgba(255,0,0,0.2);padding:15px;border-radius:10px;color:#ff6b6b;margin:20px 0}ol{text-align:left;color:#ccc;line-height:2}</style>
</head><body><div class="container">
<h1>Supprimer mon compte GAMLY</h1>
<div class="warning">Cette action est irreversible.</div>
<h3>Pour supprimer votre compte:</h3>
<ol><li>Ouvrez application GAMLY</li><li>Allez dans Mon Profil</li><li>Cliquez sur Supprimer mon compte</li><li>Confirmez</li></ol>
</div></body></html>"""
    return HTMLResponse(content=html)

@app.get("/api/privacy", response_class=HTMLResponse)
async def privacy_policy():
    html = """<!DOCTYPE html>
<html><head><title>Politique de confidentialite - GAMLY</title>
<style>body{font-family:sans-serif;background:#1a1a2e;color:white;padding:40px;line-height:1.8}h1{color:#FF1493}h2{color:#00BFFF;margin-top:30px}p{color:#ccc}.container{max-width:800px;margin:0 auto}</style>
</head><body><div class="container">
<h1>Politique de Confidentialite GAMLY</h1>
<p>Derniere mise a jour: Fevrier 2026</p>

<h2>1. Donnees collectees</h2>
<p>GAMLY collecte les donnees suivantes pour le fonctionnement de l'application:</p>
<p>- Email (pour l'authentification)<br>- Pseudo, age, genre, pays<br>- Photo de profil<br>- Preferences de jeux et centres d'interet<br>- Messages echanges avec vos matchs</p>

<h2>2. Utilisation des donnees</h2>
<p>Vos donnees sont utilisees pour:</p>
<p>- Creer et gerer votre compte<br>- Vous proposer des profils compatibles<br>- Permettre la communication entre utilisateurs<br>- Ameliorer l'experience utilisateur</p>

<h2>3. Partage des donnees</h2>
<p>Vos informations de profil (pseudo, photo, age, pays, jeux) sont visibles par les autres utilisateurs de l'application. Nous ne vendons pas vos donnees a des tiers.</p>

<h2>4. Securite</h2>
<p>Vos donnees sont stockees de maniere securisee. Les mots de passe sont chiffres.</p>

<h2>5. Suppression des donnees</h2>
<p>Vous pouvez supprimer votre compte a tout moment depuis l'application (Mon Profil > Supprimer mon compte) ou via notre page de suppression.</p>

<h2>6. Contact</h2>
<p>Pour toute question: support@gamly.app</p>
</div></body></html>"""
    return HTMLResponse(content=html)
