👉 https://github.com/Moka2310/gamly-backend/blob/main/server.py

Étape 2 : Cliquez sur ✏️ (crayon)
Étape 3 : SUPPRIMEZ TOUT (Ctrl+A puis Suppr)
Étape 4 : Collez ce code complet :
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
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Supprimer mon compte - GAMLY</title>
    <style>body{font-family:sans-serif;background:#1a1a2e;color:white;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}.container{background:rgba(255,255,255,0.1);padding:40px;border-radius:20px;max-width:500px;text-align:center}h1{color:#FF1493}p{color:#aaa;line-height:1.6}.warning{background:rgba(255,0,0,0.2);padding:15px;border-radius:10px;color:#ff6b6b;margin:20px 0}ol{text-align:left;color:#ccc;line-height:2}</style>
    </head>
    <body><div class="container">
    <h1>Supprimer mon compte GAMLY</h1>
    <div class="warning">Cette action est irreversible. Toutes vos donnees seront supprimees.</div>
    <h3>Pour supprimer votre compte :</h3>
    <ol><li>Ouvrez l'application GAMLY</li><li>Allez dans "Mon Profil"</li><li>Faites defiler vers le bas</li><li>Cliquez sur "Supprimer mon compte"</li><li>Confirmez la suppression</li></ol>
    <p>Contact: support@gamly.app</p>
    </div></body></html>
    """
    return HTMLResponse(content=html)
