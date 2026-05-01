from fastapi import FastAPI, APIRouter, HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, date, timedelta
import jwt
import bcrypt
from bson import ObjectId
import asyncio
import resend

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Resend configuration
resend.api_key = os.environ.get('RESEND_API_KEY', '')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'onboarding@resend.dev')

# JWT Configuration
SECRET_KEY = os.environ.get('JWT_SECRET', 'gamerswipe-secret-key-2024')
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 7  # 7 days

# Banned words filter (French + English profanity)
BANNED_WORDS = [
    # French profanity
    "putain", "merde", "connard", "connasse", "salope", "salaud", "enculé", "nique", 
    "niquer", "batard", "bâtard", "fdp", "ntm", "pd", "pédé", "tapette", "gouine",
    "enfoiré", "pute", "bordel", "couille", "bite", "chier", "encule", "cul",
    # English profanity
    "fuck", "shit", "bitch", "ass", "asshole", "dick", "pussy", "cock", "cunt",
    "nigger", "nigga", "fag", "faggot", "retard", "whore", "slut", "bastard",
    # Insults and threats
    "suicide", "kill yourself", "die", "crève", "mort", "tuer", "rape", "viol"
]

def contains_banned_words(text: str) -> bool:
    """Check if text contains any banned words"""
    if not text:
        return False
    text_lower = text.lower()
    for word in BANNED_WORDS:
        if word in text_lower:
            return True
    return False

async def increment_violation_count(user_id: str) -> int:
    """Increment violation count and return new count"""
    result = await db.users.find_one_and_update(
        {"_id": ObjectId(user_id)},
        {"$inc": {"violation_count": 1}},
        return_document=True
    )
    return result.get("violation_count", 1) if result else 1

# Create the main app
app = FastAPI(title="GamerSwipe API")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Security - auto_error=False to return 401 instead of 403 when no token provided
security = HTTPBearer(auto_error=False)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===================== MODELS =====================

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    nickname: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    email: EmailStr
    reset_code: str
    new_password: str

class UserProfile(BaseModel):
    nickname: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None  # homme, femme, autre
    country: Optional[str] = None
    console: Optional[str] = None  # xbox, ps5, pc
    games: Optional[List[str]] = []
    interests: Optional[List[str]] = []
    looking_for: Optional[str] = None  # ami_occasionnel, ami_team, ami_regulier
    photo: Optional[str] = None  # base64
    bio: Optional[str] = None
    languages: Optional[List[str]] = []  # français, anglais, espagnol, italien, mandarin, arabe
    availability_periods: Optional[List[str]] = []  # matin, midi, soir
    availability_start: Optional[str] = None  # heure de début ex: "18:00"
    availability_end: Optional[str] = None  # heure de fin ex: "23:00"
    timezone: Optional[str] = None  # ex: "Europe/Paris", "America/New_York"
    status: Optional[str] = None  # online, in_game, busy, offline
    gaming_accounts: Optional[dict] = None  # {"steam": "tag", "xbox": "tag", "psn": "tag", "nintendo": "tag", "activision": "tag"}

class UserResponse(BaseModel):
    id: str
    email: str
    nickname: str
    nickname_hidden: str  # masked version
    age: Optional[int] = None
    gender: Optional[str] = None
    country: Optional[str] = None
    console: Optional[str] = None
    games: List[str] = []
    interests: List[str] = []
    looking_for: Optional[str] = None
    photo: Optional[str] = None
    bio: Optional[str] = None
    languages: List[str] = []
    availability_periods: List[str] = []  # matin, midi, soir
    availability_start: Optional[str] = None
    availability_end: Optional[str] = None
    timezone: Optional[str] = None
    status: Optional[str] = None
    created_at: datetime
    profile_complete: bool = False

# Team Models
class TeamCreate(BaseModel):
    name: str
    description: Optional[str] = None
    game: str  # jeu principal de la team
    looking_for_count: int = 1  # nombre de joueurs recherchés
    country: Optional[str] = None
    console: Optional[str] = None
    play_days: Optional[List[str]] = None  # lundi, mardi, etc.
    play_time: Optional[str] = None  # matin, apres-midi, soir

class TeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    game: Optional[str] = None
    looking_for_count: Optional[int] = None
    country: Optional[str] = None
    console: Optional[str] = None
    play_days: Optional[List[str]] = None
    play_time: Optional[str] = None

class TeamInvite(BaseModel):
    user_id: str

# Game Night Models
class GameNightCreate(BaseModel):
    match_id: str
    game: str
    scheduled_date: str  # YYYY-MM-DD
    scheduled_time: str  # HH:MM
    note: Optional[str] = None

class GameNightRespond(BaseModel):
    status: str  # "accepted" or "declined"

class TeamResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    game: str
    owner_id: str
    members: List[dict]
    looking_for_count: int
    created_at: datetime

class SwipeCreate(BaseModel):
    swiped_user_id: str
    action: str  # like, dislike

class MessageCreate(BaseModel):
    content: str
    message_type: str = "text"  # "text" or "audio"

class MatchResponse(BaseModel):
    id: str
    user: dict
    matched_at: datetime
    nickname_revealed: bool = True

class MessageResponse(BaseModel):
    id: str
    match_id: str
    sender_id: str
    content: str
    message_type: str = "text"
    timestamp: datetime

class BlockUserRequest(BaseModel):
    user_id: str

class SubscriptionResponse(BaseModel):
    type: str  # free, premium
    swipes_remaining: int
    is_premium: bool
    coins: int

# ===================== HELPERS =====================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_access_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def mask_nickname(nickname: str) -> str:
    """Mask nickname like: 'GamerPro123' -> 'Gam****23'"""
    if len(nickname) <= 4:
        return "*" * len(nickname)
    return nickname[:3] + "*" * (len(nickname) - 5) + nickname[-2:]

def blur_gamertag(tag: str) -> str:
    """Blur a gamertag: 'ProGamer99' -> 'Pr*****99'"""
    if not tag or len(tag) <= 3:
        return "***"
    return tag[:2] + "*" * (len(tag) - 4) + tag[-2:]

def blur_gaming_accounts(accounts: dict) -> dict:
    """Return gaming accounts with blurred gamertags"""
    if not accounts:
        return {}
    return {platform: blur_gamertag(tag) for platform, tag in accounts.items() if tag}

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Token manquant")
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")

def is_profile_complete(user: dict) -> bool:
    required = ['age', 'gender', 'country', 'console', 'photo']
    return all(user.get(field) for field in required)

# ===================== HEALTH CHECK =====================

@api_router.get("/health")
async def health_check():
    """Health check endpoint for monitoring services like UptimeRobot"""
    return {"status": "healthy", "service": "gamly-backend", "timestamp": datetime.utcnow().isoformat()}

# ===================== ACCOUNT DELETION PAGE =====================

@api_router.get("/delete-account", response_class=HTMLResponse)
async def delete_account_page():
    """Web page for account deletion - required by Google Play"""
    html_content = """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Supprimer mon compte - GAMLY</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #0A0A0F 0%, #1a1a2e 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
                color: white;
            }
            .container {
                background: rgba(255,255,255,0.05);
                border-radius: 20px;
                padding: 40px;
                max-width: 500px;
                width: 100%;
                text-align: center;
                border: 1px solid rgba(255,255,255,0.1);
            }
            .logo {
                font-size: 48px;
                margin-bottom: 20px;
            }
            h1 {
                font-size: 24px;
                margin-bottom: 20px;
                background: linear-gradient(90deg, #FF1493, #00BFFF);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            p {
                color: #a0a0a0;
                margin-bottom: 20px;
                line-height: 1.6;
            }
            .warning {
                background: rgba(255,0,0,0.1);
                border: 1px solid rgba(255,0,0,0.3);
                border-radius: 10px;
                padding: 15px;
                margin-bottom: 20px;
            }
            .warning-text {
                color: #ff6b6b;
                font-weight: 500;
            }
            .form-group {
                margin-bottom: 15px;
                text-align: left;
            }
            label {
                display: block;
                margin-bottom: 5px;
                color: #ccc;
                font-size: 14px;
            }
            input {
                width: 100%;
                padding: 12px;
                border-radius: 10px;
                border: 1px solid rgba(255,255,255,0.2);
                background: rgba(255,255,255,0.05);
                color: white;
                font-size: 16px;
            }
            input:focus {
                outline: none;
                border-color: #FF1493;
            }
            .btn {
                width: 100%;
                padding: 15px;
                border: none;
                border-radius: 10px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                margin-top: 10px;
            }
            .btn-danger {
                background: linear-gradient(90deg, #ff4444, #cc0000);
                color: white;
            }
            .btn-danger:hover {
                opacity: 0.9;
            }
            .success {
                background: rgba(0,255,0,0.1);
                border: 1px solid rgba(0,255,0,0.3);
                border-radius: 10px;
                padding: 20px;
                color: #4ade80;
                display: none;
            }
            .error {
                background: rgba(255,0,0,0.1);
                border: 1px solid rgba(255,0,0,0.3);
                border-radius: 10px;
                padding: 15px;
                color: #ff6b6b;
                margin-top: 15px;
                display: none;
            }
            .steps {
                text-align: left;
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid rgba(255,255,255,0.1);
            }
            .steps h3 {
                margin-bottom: 15px;
                color: #ccc;
            }
            .steps ol {
                padding-left: 20px;
                color: #a0a0a0;
            }
            .steps li {
                margin-bottom: 10px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">🎮</div>
            <h1>Supprimer mon compte GAMLY</h1>
            
            <div id="form-container">
                <p>Pour supprimer votre compte, veuillez vous connecter avec vos identifiants.</p>
                
                <div class="warning">
                    <p class="warning-text">⚠️ Attention : Cette action est irréversible. Toutes vos données, matchs et messages seront définitivement supprimés.</p>
                </div>
                
                <form id="delete-form">
                    <div class="form-group">
                        <label for="email">Email</label>
                        <input type="email" id="email" name="email" required placeholder="votre@email.com">
                    </div>
                    <div class="form-group">
                        <label for="password">Mot de passe</label>
                        <input type="password" id="password" name="password" required placeholder="Votre mot de passe">
                    </div>
                    <button type="submit" class="btn btn-danger">Supprimer mon compte</button>
                </form>
                
                <div id="error-message" class="error"></div>
            </div>
            
            <div id="success-message" class="success">
                <h2>✅ Compte supprimé</h2>
                <p>Votre compte a été supprimé avec succès. Toutes vos données ont été effacées.</p>
            </div>
            
            <div class="steps">
                <h3>Vous pouvez également supprimer votre compte depuis l'app :</h3>
                <ol>
                    <li>Ouvrez l'application GAMLY</li>
                    <li>Allez dans l'onglet "Mon Profil"</li>
                    <li>Faites défiler vers le bas</li>
                    <li>Cliquez sur "Supprimer mon compte"</li>
                </ol>
            </div>
        </div>
        
        <script>
            document.getElementById('delete-form').addEventListener('submit', async (e) => {
                e.preventDefault();
                const email = document.getElementById('email').value;
                const password = document.getElementById('password').value;
                const errorDiv = document.getElementById('error-message');
                const successDiv = document.getElementById('success-message');
                const formContainer = document.getElementById('form-container');
                
                errorDiv.style.display = 'none';
                
                try {
                    // First login to get token
                    const loginResponse = await fetch('/api/auth/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email, password })
                    });
                    
                    if (!loginResponse.ok) {
                        throw new Error('Email ou mot de passe incorrect');
                    }
                    
                    const loginData = await loginResponse.json();
                    
                    // Delete account
                    const deleteResponse = await fetch('/api/auth/delete-account', {
                        method: 'DELETE',
                        headers: { 
                            'Authorization': `Bearer ${loginData.token}`,
                            'Content-Type': 'application/json'
                        }
                    });
                    
                    if (!deleteResponse.ok) {
                        throw new Error('Erreur lors de la suppression');
                    }
                    
                    // Show success
                    formContainer.style.display = 'none';
                    successDiv.style.display = 'block';
                    
                } catch (error) {
                    errorDiv.textContent = error.message;
                    errorDiv.style.display = 'block';
                }
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ===================== PRIVACY POLICY =====================

@api_router.get("/privacy-policy", response_class=HTMLResponse)
async def privacy_policy():
    html_content = """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Politique de Confidentialité - GAMLY</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 100%);
                min-height: 100vh;
                color: #e0e0e0;
                line-height: 1.6;
                padding: 20px;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                background: rgba(30, 30, 50, 0.9);
                border-radius: 20px;
                padding: 40px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.5);
            }
            .logo { text-align: center; margin-bottom: 30px; }
            .logo h1 {
                font-size: 2.5em;
                background: linear-gradient(90deg, #ff006e, #8338ec, #3a86ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            h2 { color: #ff006e; margin: 25px 0 15px; font-size: 1.3em; }
            p, li { margin-bottom: 10px; color: #b0b0b0; }
            ul { padding-left: 20px; }
            .date { text-align: center; color: #666; margin-top: 30px; font-size: 0.9em; }
            a { color: #3a86ff; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">
                <h1>GAMLY</h1>
                <p>Politique de Confidentialité</p>
            </div>
            
            <h2>1. Introduction</h2>
            <p>Bienvenue sur GAMLY, l'application de rencontres pour gamers. Nous accordons une grande importance à la protection de vos données personnelles. Cette politique explique comment nous collectons, utilisons et protégeons vos informations.</p>
            
            <h2>2. Données collectées</h2>
            <p>Nous collectons les données suivantes :</p>
            <ul>
                <li><strong>Informations de profil :</strong> pseudo, âge, pays, photo de profil (ou avatar), bio, jeux favoris, centres d'intérêt</li>
                <li><strong>Informations de connexion :</strong> email et mot de passe (crypté)</li>
                <li><strong>Préférences de jeu :</strong> plateforme (PC, PlayStation, Xbox, Nintendo, Mobile), disponibilités</li>
                <li><strong>Communications :</strong> messages échangés avec d'autres utilisateurs</li>
            </ul>
            
            <h2>3. Utilisation des données</h2>
            <p>Vos données sont utilisées pour :</p>
            <ul>
                <li>Créer et gérer votre compte</li>
                <li>Vous proposer des profils compatibles</li>
                <li>Permettre la messagerie entre utilisateurs matchés</li>
                <li>Améliorer nos services</li>
            </ul>
            
            <h2>4. Partage des données</h2>
            <p>Nous ne vendons jamais vos données personnelles. Vos informations ne sont partagées qu'avec :</p>
            <ul>
                <li>Les autres utilisateurs (uniquement les informations de votre profil public)</li>
                <li>Nos prestataires techniques (hébergement, base de données) sous contrat de confidentialité</li>
            </ul>
            
            <h2>5. Sécurité</h2>
            <p>Nous mettons en œuvre des mesures de sécurité pour protéger vos données :</p>
            <ul>
                <li>Mots de passe cryptés (bcrypt)</li>
                <li>Connexions sécurisées (HTTPS)</li>
                <li>Accès restreint aux données</li>
            </ul>
            
            <h2>6. Vos droits</h2>
            <p>Conformément au RGPD, vous avez le droit de :</p>
            <ul>
                <li>Accéder à vos données personnelles</li>
                <li>Rectifier vos informations</li>
                <li>Supprimer votre compte et toutes vos données</li>
                <li>Exporter vos données</li>
            </ul>
            
            <h2>7. Suppression du compte</h2>
            <p>Vous pouvez supprimer votre compte à tout moment depuis l'application (Profil > Supprimer mon compte). Toutes vos données seront définitivement effacées.</p>
            
            <h2>8. Contact</h2>
            <p>Pour toute question concernant cette politique, contactez-nous à : <a href="mailto:contact@gamly.app">contact@gamly.app</a></p>
            
            <p class="date">Dernière mise à jour : Février 2026</p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ===================== AUTH ENDPOINTS =====================

@api_router.post("/auth/register")
async def register(user_data: UserCreate):
    # Check if email exists
    existing = await db.users.find_one({"email": user_data.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email déjà utilisé")
    
    # Check if nickname exists
    existing_nick = await db.users.find_one({"nickname": user_data.nickname})
    if existing_nick:
        raise HTTPException(status_code=400, detail="Nickname déjà utilisé")
    
    # Create user
    user_doc = {
        "email": user_data.email,
        "password_hash": hash_password(user_data.password),
        "nickname": user_data.nickname,
        "age": None,
        "gender": None,
        "country": None,
        "console": None,
        "games": [],
        "interests": [],
        "languages": [],
        "looking_for": None,
        "photo": None,
        "bio": None,
        "created_at": datetime.utcnow(),
        "swipes_remaining": 10,  # 10 free swipes at account creation
        "swipes_today": 0,
        "last_swipe_reset": date.today().isoformat(),
        "is_premium": False,
        "coins": 0,  # purchased swipe coins
    }
    
    result = await db.users.insert_one(user_doc)
    user_id = str(result.inserted_id)
    token = create_access_token(user_id)
    
    return {
        "token": token,
        "user": {
            "id": user_id,
            "email": user_data.email,
            "nickname": user_data.nickname,
            "profile_complete": False
        }
    }

@api_router.post("/auth/login")
async def login(user_data: UserLogin):
    # Clean input - mobile keyboards often add spaces or uppercase
    clean_email = user_data.email.strip().lower()
    clean_password = user_data.password.strip()
    
    user = await db.users.find_one({"email": clean_email})
    if not user:
        logger.warning(f"Login failed - email not found: '{clean_email}'")
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    
    if not verify_password(clean_password, user["password_hash"]):
        logger.warning(f"Login failed - wrong password for: '{clean_email}'")
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    
    user_id = str(user["_id"])
    token = create_access_token(user_id)
    
    return {
        "token": token,
        "user": {
            "id": user_id,
            "email": user["email"],
            "nickname": user["nickname"],
            "gender": user.get("gender"),
            "profile_complete": is_profile_complete(user)
        }
    }

# ===================== PASSWORD RESET ENDPOINTS =====================

# Store reset codes in memory (in production, use Redis or database)
reset_codes = {}

@api_router.post("/auth/forgot-password")
async def forgot_password(data: PasswordResetRequest):
    """Request password reset - generates a code and sends it via email"""
    user = await db.users.find_one({"email": data.email})
    if not user:
        return {"message": "Si cet email existe, un code de réinitialisation a été envoyé."}
    
    import random
    code = str(random.randint(100000, 999999))
    
    # Send email via Resend
    html_content = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;background:#0A0A0F;color:#E0E0E0;padding:30px;border-radius:12px;">
        <h1 style="color:#FF1493;text-align:center;margin-bottom:20px;">GAMLY</h1>
        <p style="font-size:16px;margin-bottom:15px;">Bonjour,</p>
        <p style="font-size:16px;margin-bottom:20px;">Voici votre code de réinitialisation de mot de passe :</p>
        <div style="background:#1a1a2e;border:2px solid #FF1493;border-radius:10px;padding:20px;text-align:center;margin-bottom:20px;">
            <span style="font-size:32px;font-weight:bold;letter-spacing:8px;color:#FF1493;">{code}</span>
        </div>
        <p style="font-size:14px;color:#888;">Ce code expire dans <strong>10 minutes</strong>.</p>
        <p style="font-size:14px;color:#888;">Si vous n'avez pas demandé cette réinitialisation, ignorez cet email.</p>
        <hr style="border:1px solid #333;margin:20px 0;">
        <p style="font-size:12px;color:#666;text-align:center;">GAMLY - L'app de rencontres pour gamers</p>
    </div>
    """
    
    try:
        params = {
            "from": SENDER_EMAIL,
            "to": [data.email],
            "subject": "GAMLY - Code de réinitialisation",
            "html": html_content
        }
        await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Password reset email sent to {data.email}")
    except Exception as e:
        logger.error(f"Failed to send reset email to {data.email}: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'envoi de l'email. Réessayez plus tard.")
    
    # Only store code after successful email send
    reset_codes[data.email] = {
        "code": code,
        "expires": datetime.utcnow() + timedelta(minutes=10)
    }
    
    return {"message": "Si cet email existe, un code de réinitialisation a été envoyé."}

@api_router.post("/auth/reset-password")
async def reset_password(data: PasswordResetConfirm):
    """Reset password with code"""
    # Check if code exists and is valid
    reset_data = reset_codes.get(data.email)
    if not reset_data:
        raise HTTPException(status_code=400, detail="Aucun code de réinitialisation trouvé")
    
    if datetime.utcnow() > reset_data["expires"]:
        del reset_codes[data.email]
        raise HTTPException(status_code=400, detail="Code expiré")
    
    if reset_data["code"] != data.reset_code:
        raise HTTPException(status_code=400, detail="Code incorrect")
    
    # Validate new password
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Le mot de passe doit contenir au moins 6 caractères")
    
    # Update password
    user = await db.users.find_one({"email": data.email})
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"password_hash": hash_password(data.new_password)}}
    )
    
    # Remove used code
    del reset_codes[data.email]
    
    return {"message": "Mot de passe mis à jour avec succès!"}

@api_router.delete("/auth/delete-account")
async def delete_account(current_user: dict = Depends(get_current_user)):
    """Delete user account and all associated data"""
    user_id = current_user["_id"]
    
    # Delete all matches involving this user
    await db.matches.delete_many({
        "$or": [{"user1_id": str(user_id)}, {"user2_id": str(user_id)}]
    })
    
    # Delete all messages involving this user
    await db.messages.delete_many({
        "$or": [{"sender_id": str(user_id)}, {"receiver_id": str(user_id)}]
    })
    
    # Delete all swipes by this user
    await db.swipes.delete_many({"swiper_id": str(user_id)})
    
    # Delete all swipes on this user
    await db.swipes.delete_many({"swiped_id": str(user_id)})
    
    # Delete the user account
    await db.users.delete_one({"_id": user_id})
    
    logger.info(f"User account deleted: {user_id}")
    
    return {"message": "Compte supprimé avec succès"}

@api_router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": str(current_user["_id"]),
        "email": current_user["email"],
        "nickname": current_user["nickname"],
        "nickname_hidden": mask_nickname(current_user["nickname"]),
        "age": current_user.get("age"),
        "gender": current_user.get("gender"),
        "country": current_user.get("country"),
        "console": current_user.get("console"),
        "games": current_user.get("games", []),
        "interests": current_user.get("interests", []),
        "languages": current_user.get("languages", []),
        "looking_for": current_user.get("looking_for"),
        "photo": current_user.get("photo"),
        "bio": current_user.get("bio"),
        "profile_complete": is_profile_complete(current_user),
        "is_premium": current_user.get("is_premium", False),
        "status": current_user.get("status", "offline"),
        "gaming_accounts": current_user.get("gaming_accounts", {}),
        "created_at": current_user.get("created_at")
    }

# ===================== PROFILE ENDPOINTS =====================

@api_router.put("/profile")
async def update_profile(profile: UserProfile, current_user: dict = Depends(get_current_user)):
    update_data = {}
    
    if profile.nickname is not None:
        # Check if nickname is taken by another user
        existing = await db.users.find_one({
            "nickname": profile.nickname, 
            "_id": {"$ne": current_user["_id"]}
        })
        if existing:
            raise HTTPException(status_code=400, detail="Nickname déjà utilisé")
        update_data["nickname"] = profile.nickname
    
    if profile.age is not None:
        update_data["age"] = profile.age
    if profile.gender is not None:
        update_data["gender"] = profile.gender
    if profile.country is not None:
        update_data["country"] = profile.country
    if profile.console is not None:
        update_data["console"] = profile.console
    if profile.games is not None:
        update_data["games"] = profile.games
    if profile.interests is not None:
        update_data["interests"] = profile.interests
    if profile.languages is not None:
        update_data["languages"] = profile.languages
    if profile.looking_for is not None:
        update_data["looking_for"] = profile.looking_for
    if profile.photo is not None:
        update_data["photo"] = profile.photo
    if profile.bio is not None:
        update_data["bio"] = profile.bio
    if profile.availability_periods is not None:
        update_data["availability_periods"] = profile.availability_periods
    if profile.availability_start is not None:
        update_data["availability_start"] = profile.availability_start
    if profile.availability_end is not None:
        update_data["availability_end"] = profile.availability_end
    if profile.timezone is not None:
        update_data["timezone"] = profile.timezone
    if profile.status is not None:
        update_data["status"] = profile.status
    if profile.gaming_accounts is not None:
        update_data["gaming_accounts"] = profile.gaming_accounts
    
    if update_data:
        await db.users.update_one(
            {"_id": current_user["_id"]},
            {"$set": update_data}
        )
    
    # Return updated user
    updated_user = await db.users.find_one({"_id": current_user["_id"]})
    return {
        "id": str(updated_user["_id"]),
        "email": updated_user["email"],
        "nickname": updated_user["nickname"],
        "nickname_hidden": mask_nickname(updated_user["nickname"]),
        "age": updated_user.get("age"),
        "gender": updated_user.get("gender"),
        "country": updated_user.get("country"),
        "console": updated_user.get("console"),
        "games": updated_user.get("games", []),
        "interests": updated_user.get("interests", []),
        "languages": updated_user.get("languages", []),
        "looking_for": updated_user.get("looking_for"),
        "photo": updated_user.get("photo"),
        "bio": updated_user.get("bio"),
        "availability_periods": updated_user.get("availability_periods", []),
        "availability_start": updated_user.get("availability_start"),
        "availability_end": updated_user.get("availability_end"),
        "timezone": updated_user.get("timezone"),
        "status": updated_user.get("status"),
        "gaming_accounts": updated_user.get("gaming_accounts", {}),
        "profile_complete": is_profile_complete(updated_user)
    }

# ===================== STATUS ENDPOINT =====================

@api_router.put("/profile/status")
async def update_status(status: str, current_user: dict = Depends(get_current_user)):
    """Update user status (online, in_game, busy, offline)"""
    valid_statuses = ["online", "in_game", "busy", "offline"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Statut invalide. Utilisez: {valid_statuses}")
    
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"status": status, "last_active": datetime.utcnow()}}
    )
    
    return {"status": status}

# ===================== DISCOVER / SWIPE ENDPOINTS =====================

@api_router.get("/discover")
async def discover_profiles(
    current_user: dict = Depends(get_current_user),
    gender: Optional[str] = None,
    country: Optional[str] = None,
    language: Optional[str] = None,
    game: Optional[str] = None,
    availability: Optional[List[str]] = None
):
    """Get profiles to swipe on with optional filters"""
    user_id = current_user["_id"]
    
    # Get users already swiped
    swiped_ids = await db.swipes.distinct("swiped_user_id", {"swiper_id": str(user_id)})
    swiped_object_ids = [ObjectId(sid) for sid in swiped_ids if ObjectId.is_valid(sid)]
    
    # Get blocked users (both directions)
    blocked_by_me = await db.blocks.distinct("blocked_id", {"blocker_id": str(user_id)})
    blocked_me = await db.blocks.distinct("blocker_id", {"blocked_id": str(user_id)})
    blocked_ids = set(blocked_by_me + blocked_me)
    blocked_object_ids = [ObjectId(bid) for bid in blocked_ids if ObjectId.is_valid(bid)]
    
    # Exclude current user, swiped users, and blocked users
    exclude_ids = [user_id] + swiped_object_ids + blocked_object_ids
    
    # Build query with filters
    query = {
        "_id": {"$nin": exclude_ids},
        "photo": {"$ne": None},
        "age": {"$ne": None},
        "console": {"$ne": None}
    }
    
    # Apply optional filters
    if gender:
        query["gender"] = gender
    if country:
        query["country"] = country
    if language:
        query["languages"] = language  # MongoDB will match if language is in the array
    if game:
        query["games"] = game  # MongoDB will match if game is in the array
    
    # Filter by availability periods (matin, midi, soir)
    if availability and len(availability) > 0:
        query["availability_periods"] = {"$in": availability}
    
    # Find profiles
    profiles = await db.users.find(query).limit(20).to_list(20)
    
    # Format profiles with common interests
    user_games = set(current_user.get("games", []))
    user_interests = set(current_user.get("interests", []))
    
    result = []
    for profile in profiles:
        profile_games = set(profile.get("games", []))
        profile_interests = set(profile.get("interests", []))
        
        common_games = list(user_games & profile_games)
        common_interests = list(user_interests & profile_interests)
        
        result.append({
            "id": str(profile["_id"]),
            "nickname_hidden": mask_nickname(profile["nickname"]),
            "age": profile.get("age"),
            "gender": profile.get("gender"),
            "country": profile.get("country"),
            "console": profile.get("console"),
            "games": profile.get("games", []),
            "interests": profile.get("interests", []),
            "languages": profile.get("languages", []),
            "looking_for": profile.get("looking_for"),
            "photo": profile.get("photo"),
            "bio": profile.get("bio"),
            "availability_periods": profile.get("availability_periods", []),
            "availability_start": profile.get("availability_start"),
            "availability_end": profile.get("availability_end"),
            "status": profile.get("status"),
            "gaming_accounts_blurred": blur_gaming_accounts(profile.get("gaming_accounts", {})),
            "common_games": common_games,
            "common_interests": common_interests,
            "common_count": len(common_games) + len(common_interests)
        })
    
    return result

@api_router.post("/swipe")
async def swipe(swipe_data: SwipeCreate, current_user: dict = Depends(get_current_user)):
    """Process a swipe action"""
    user_id = str(current_user["_id"])
    today = date.today().isoformat()
    
    # Check and reset daily swipe count
    if current_user.get("last_swipe_reset") != today:
        await db.users.update_one(
            {"_id": current_user["_id"]},
            {"$set": {"swipes_today": 0, "last_swipe_reset": today}}
        )
        current_user["swipes_today"] = 0
    
    # Check swipe limit (10 free swipes total, then need coins or premium)
    if not current_user.get("is_premium", False):
        swipes_remaining = current_user.get("swipes_remaining", 0)
        coins = current_user.get("coins", 0)
        if swipes_remaining <= 0 and coins <= 0:
            raise HTTPException(
                status_code=403, 
                detail="Plus de swipes disponibles. Achetez des swipes ou passez Premium!"
            )
    
    # Check if already swiped
    existing = await db.swipes.find_one({
        "swiper_id": user_id,
        "swiped_user_id": swipe_data.swiped_user_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="Déjà swipé sur ce profil")
    
    # Record swipe
    swipe_doc = {
        "swiper_id": user_id,
        "swiped_user_id": swipe_data.swiped_user_id,
        "action": swipe_data.action,
        "timestamp": datetime.utcnow()
    }
    await db.swipes.insert_one(swipe_doc)
    
    # Decrement swipe count (use free swipes first, then coins)
    if not current_user.get("is_premium", False):
        swipes_remaining = current_user.get("swipes_remaining", 0)
        if swipes_remaining > 0:
            await db.users.update_one(
                {"_id": current_user["_id"]},
                {"$inc": {"swipes_remaining": -1, "swipes_today": 1}}
            )
        else:
            await db.users.update_one(
                {"_id": current_user["_id"]},
                {"$inc": {"coins": -1, "swipes_today": 1}}
            )
    else:
        await db.users.update_one(
            {"_id": current_user["_id"]},
            {"$inc": {"swipes_today": 1}}
        )
    
    # Check for match (if liked)
    is_match = False
    match_data = None
    
    if swipe_data.action == "like":
        # Check if other user also liked us
        other_swipe = await db.swipes.find_one({
            "swiper_id": swipe_data.swiped_user_id,
            "swiped_user_id": user_id,
            "action": "like"
        })
        
        # AUTO-MATCH FOR DEMO: If the swiped user is a demo profile, auto-like back
        demo_emails = ["sarah.gamer@example.com", "alex.pro@example.com", "luna.pcmaster@example.com"]
        swiped_user = await db.users.find_one({"_id": ObjectId(swipe_data.swiped_user_id)})
        
        if swiped_user and swiped_user.get("email") in demo_emails and not other_swipe:
            # Create automatic like from demo profile
            auto_swipe_doc = {
                "swiper_id": swipe_data.swiped_user_id,
                "swiped_user_id": user_id,
                "action": "like",
                "timestamp": datetime.utcnow()
            }
            await db.swipes.insert_one(auto_swipe_doc)
            other_swipe = auto_swipe_doc  # Now there's a match!
        
        if other_swipe:
            is_match = True
            # Create match
            match_doc = {
                "user1_id": user_id,
                "user2_id": swipe_data.swiped_user_id,
                "matched_at": datetime.utcnow()
            }
            match_result = await db.matches.insert_one(match_doc)
            
            # Get matched user details
            matched_user = await db.users.find_one({"_id": ObjectId(swipe_data.swiped_user_id)})
            if matched_user:
                match_data = {
                    "match_id": str(match_result.inserted_id),
                    "user": {
                        "id": str(matched_user["_id"]),
                        "nickname": matched_user["nickname"],  # Revealed!
                        "photo": matched_user.get("photo"),
                        "console": matched_user.get("console")
                    },
                    "your_nickname": current_user["nickname"]  # Your nickname for the other
                }
    
    # Get remaining swipes
    updated_user = await db.users.find_one({"_id": current_user["_id"]})
    if updated_user.get("is_premium"):
        swipes_remaining = -1
    else:
        swipes_remaining = updated_user.get("swipes_remaining", 0) + updated_user.get("coins", 0)
    
    return {
        "success": True,
        "is_match": is_match,
        "match_data": match_data,
        "swipes_remaining": swipes_remaining,
        "is_premium": updated_user.get("is_premium", False)
    }

# ===================== MATCHES ENDPOINTS =====================

@api_router.get("/matches")
async def get_matches(current_user: dict = Depends(get_current_user)):
    """Get all matches for current user"""
    user_id = str(current_user["_id"])
    
    # Find matches where user is either user1 or user2
    matches = await db.matches.find({
        "$or": [
            {"user1_id": user_id},
            {"user2_id": user_id}
        ]
    }).sort("matched_at", -1).to_list(100)
    
    result = []
    for match in matches:
        # Get the other user
        other_user_id = match["user2_id"] if match["user1_id"] == user_id else match["user1_id"]
        other_user = await db.users.find_one({"_id": ObjectId(other_user_id)})
        
        if other_user:
            # Check if blocked
            is_blocked = await db.blocks.find_one({
                "$or": [
                    {"blocker_id": user_id, "blocked_id": other_user_id},
                    {"blocker_id": other_user_id, "blocked_id": user_id}
                ]
            })
            
            if not is_blocked:
                # Get last message
                last_message = await db.messages.find_one(
                    {"match_id": str(match["_id"])},
                    sort=[("timestamp", -1)]
                )
                
                result.append({
                    "id": str(match["_id"]),
                    "user": {
                        "id": str(other_user["_id"]),
                        "nickname": other_user["nickname"],  # Revealed after match
                        "photo": other_user.get("photo"),
                        "console": other_user.get("console"),
                        "country": other_user.get("country"),
                        "gender": other_user.get("gender"),
                        "gaming_accounts": other_user.get("gaming_accounts", {})
                    },
                    "matched_at": match["matched_at"],
                    "last_message": {
                        "content": last_message["content"] if last_message else None,
                        "message_type": last_message.get("message_type", "text") if last_message else "text",
                        "timestamp": last_message["timestamp"] if last_message else None,
                        "is_mine": last_message["sender_id"] == user_id if last_message else False
                    } if last_message else None
                })
    
    return result

# ===================== MESSAGES ENDPOINTS =====================

@api_router.get("/messages/{match_id}")
async def get_messages(match_id: str, current_user: dict = Depends(get_current_user)):
    """Get messages for a match"""
    user_id = str(current_user["_id"])
    
    # Verify user is part of this match
    match = await db.matches.find_one({"_id": ObjectId(match_id)})
    if not match:
        raise HTTPException(status_code=404, detail="Match non trouvé")
    
    if user_id not in [match["user1_id"], match["user2_id"]]:
        raise HTTPException(status_code=403, detail="Accès non autorisé")
    
    # Get messages
    messages = await db.messages.find({"match_id": match_id}).sort("timestamp", 1).to_list(500)
    
    return [{
        "id": str(msg["_id"]),
        "match_id": msg["match_id"],
        "sender_id": msg["sender_id"],
        "content": msg["content"],
        "message_type": msg.get("message_type", "text"),
        "timestamp": msg["timestamp"],
        "is_mine": msg["sender_id"] == user_id
    } for msg in messages]

@api_router.post("/messages/{match_id}")
async def send_message(match_id: str, message: MessageCreate, current_user: dict = Depends(get_current_user)):
    """Send a message in a match"""
    user_id = str(current_user["_id"])
    
    # Check for banned words (only for text messages)
    if message.message_type == "text" and contains_banned_words(message.content):
        # Increment violation count
        violation_count = await increment_violation_count(user_id)
        
        # Log the violation
        await db.violations.insert_one({
            "user_id": user_id,
            "type": "banned_words",
            "content": message.content,
            "timestamp": datetime.utcnow()
        })
        
        # If 3+ violations, ban the account
        if violation_count >= 3:
            await db.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"is_banned": True, "banned_at": datetime.utcnow()}}
            )
            raise HTTPException(
                status_code=403, 
                detail="Votre compte a été suspendu pour comportement inapproprié répété. Contactez le support pour plus d'informations."
            )
        
        raise HTTPException(
            status_code=400, 
            detail=f"Message bloqué: contenu inapproprié détecté. Attention: {3 - violation_count} avertissement(s) restant(s) avant suspension du compte."
        )
    
    # Verify user is part of this match
    match = await db.matches.find_one({"_id": ObjectId(match_id)})
    if not match:
        raise HTTPException(status_code=404, detail="Match non trouvé")
    
    if user_id not in [match["user1_id"], match["user2_id"]]:
        raise HTTPException(status_code=403, detail="Accès non autorisé")
    
    # Check if blocked
    other_user_id = match["user2_id"] if match["user1_id"] == user_id else match["user1_id"]
    is_blocked = await db.blocks.find_one({
        "$or": [
            {"blocker_id": user_id, "blocked_id": other_user_id},
            {"blocker_id": other_user_id, "blocked_id": user_id}
        ]
    })
    if is_blocked:
        raise HTTPException(status_code=403, detail="Impossible d'envoyer un message à cet utilisateur")
    
    # Create message
    message_doc = {
        "match_id": match_id,
        "sender_id": user_id,
        "content": message.content,
        "message_type": message.message_type,
        "timestamp": datetime.utcnow()
    }
    result = await db.messages.insert_one(message_doc)
    
    return {
        "id": str(result.inserted_id),
        "match_id": match_id,
        "sender_id": user_id,
        "content": message.content,
        "message_type": message.message_type,
        "timestamp": message_doc["timestamp"],
        "is_mine": True
    }

# ===================== BLOCK ENDPOINTS =====================

@api_router.post("/block")
async def block_user(block_data: BlockUserRequest, current_user: dict = Depends(get_current_user)):
    """Block a user"""
    user_id = str(current_user["_id"])
    
    if user_id == block_data.user_id:
        raise HTTPException(status_code=400, detail="Impossible de se bloquer soi-même")
    
    # Check if already blocked
    existing = await db.blocks.find_one({
        "blocker_id": user_id,
        "blocked_id": block_data.user_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="Utilisateur déjà bloqué")
    
    # Create block
    block_doc = {
        "blocker_id": user_id,
        "blocked_id": block_data.user_id,
        "timestamp": datetime.utcnow()
    }
    await db.blocks.insert_one(block_doc)
    
    return {"success": True, "message": "Utilisateur bloqué"}

@api_router.delete("/block/{user_id}")
async def unblock_user(user_id: str, current_user: dict = Depends(get_current_user)):
    """Unblock a user"""
    current_id = str(current_user["_id"])
    
    result = await db.blocks.delete_one({
        "blocker_id": current_id,
        "blocked_id": user_id
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Blocage non trouvé")
    
    return {"success": True, "message": "Utilisateur débloqué"}

# ===================== SUBSCRIPTION ENDPOINTS =====================

@api_router.get("/subscription")
async def get_subscription(current_user: dict = Depends(get_current_user)):
    """Get subscription status"""
    is_premium = current_user.get("is_premium", False)
    swipes_remaining = current_user.get("swipes_remaining", 0)
    coins = current_user.get("coins", 0)
    
    return {
        "type": "premium" if is_premium else "free",
        "swipes_remaining": -1 if is_premium else swipes_remaining + coins,
        "free_swipes": swipes_remaining,
        "coins": coins,
        "is_premium": is_premium,
        "pricing": {
            "subscription_monthly": 17.99,
            "pack_50": 5.99,
            "pack_200": 9.99,
            "currency": "USD"
        }
    }

try:
      from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionResponse, CheckoutStatusResponse, CheckoutSessionRequest
      STRIPE_AVAILABLE = True
except ImportError:
      STRIPE_AVAILABLE = False

# ===================== STRIPE PAYMENT ENDPOINTS =====================

PAYMENT_PACKAGES = {
    "premium": {"amount": 17.99, "description": "GAMLY Premium - Swipes illimites", "type": "subscription", "google_product_id": "gamly_premium_monthly"},
    "pack_50": {"amount": 5.99, "description": "50 Swipes", "coins": 50, "type": "pack", "google_product_id": "gamly_swipes_50"},
    "pack_200": {"amount": 9.99, "description": "200 Swipes", "coins": 200, "type": "pack", "google_product_id": "gamly_swipes_200"},
}

class CheckoutRequest(BaseModel):
    package_id: str
    origin_url: str

@api_router.post("/payments/create-checkout")
async def create_checkout(data: CheckoutRequest, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    package = PAYMENT_PACKAGES.get(data.package_id)
    if not package:
        raise HTTPException(status_code=400, detail="Package invalide")
    
    stripe_key = os.environ.get("STRIPE_API_KEY")
    if not stripe_key:
        raise HTTPException(status_code=500, detail="Stripe non configure")
    
    success_url = f"{data.origin_url}/payment-success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{data.origin_url}/subscription"
    
    webhook_url = f"{str(data.origin_url)}/api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=stripe_key, webhook_url=webhook_url)
    
    checkout_request = CheckoutSessionRequest(
        amount=float(package["amount"]),
        currency="usd",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "user_id": user_id,
            "package_id": data.package_id,
            "package_type": package["type"],
        }
    )
    
    session: CheckoutSessionResponse = await stripe_checkout.create_checkout_session(checkout_request)
    
    # Create payment transaction record
    await db.payment_transactions.insert_one({
        "session_id": session.session_id,
        "user_id": user_id,
        "package_id": data.package_id,
        "amount": package["amount"],
        "currency": "usd",
        "payment_status": "pending",
        "metadata": {"package_type": package["type"]},
        "created_at": datetime.utcnow()
    })
    
    return {"url": session.url, "session_id": session.session_id}

@api_router.get("/payments/status/{session_id}")
async def check_payment_status(session_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    
    transaction = await db.payment_transactions.find_one({"session_id": session_id, "user_id": user_id})
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction non trouvee")
    
    # If already processed, return cached status
    if transaction.get("payment_status") == "paid":
        return {"status": "complete", "payment_status": "paid", "already_processed": True}
    
    stripe_key = os.environ.get("STRIPE_API_KEY")
    webhook_url = "https://placeholder.com/api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=stripe_key, webhook_url=webhook_url)
    
    status: CheckoutStatusResponse = await stripe_checkout.get_checkout_status(session_id)
    
    if status.payment_status == "paid" and transaction.get("payment_status") != "paid":
        # Update transaction
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"payment_status": "paid", "paid_at": datetime.utcnow()}}
        )
        
        package = PAYMENT_PACKAGES.get(transaction["package_id"])
        if package:
            if package["type"] == "subscription":
                await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"is_premium": True}})
            elif package["type"] == "pack":
                await db.users.update_one({"_id": ObjectId(user_id)}, {"$inc": {"swipes_remaining": package["coins"]}})
    elif status.payment_status != "paid":
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"payment_status": status.payment_status}}
        )
    
    return {"status": status.status, "payment_status": status.payment_status}

@api_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    
    stripe_key = os.environ.get("STRIPE_API_KEY")
    webhook_url = str(request.url)
    stripe_checkout = StripeCheckout(api_key=stripe_key, webhook_url=webhook_url)
    
    try:
        event = await stripe_checkout.handle_webhook(body, signature)
        if event.payment_status == "paid":
            transaction = await db.payment_transactions.find_one({"session_id": event.session_id})
            if transaction and transaction.get("payment_status") != "paid":
                await db.payment_transactions.update_one(
                    {"session_id": event.session_id},
                    {"$set": {"payment_status": "paid", "paid_at": datetime.utcnow()}}
                )
                package = PAYMENT_PACKAGES.get(transaction["package_id"])
                user_id = transaction["user_id"]
                if package:
                    if package["type"] == "subscription":
                        await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"is_premium": True}})
                    elif package["type"] == "pack":
                        await db.users.update_one({"_id": ObjectId(user_id)}, {"$inc": {"swipes_remaining": package["coins"]}})
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

# ===================== GOOGLE PLAY BILLING ENDPOINTS =====================

class GooglePlayPurchase(BaseModel):
    product_id: str
    purchase_token: str
    order_id: str

@api_router.post("/payments/verify-google")
async def verify_google_purchase(data: GooglePlayPurchase, current_user: dict = Depends(get_current_user)):
    """Verify and process a Google Play purchase"""
    user_id = str(current_user["_id"])
    
    # Check if this purchase was already processed
    existing = await db.payment_transactions.find_one({"order_id": data.order_id, "payment_status": "paid"})
    if existing:
        return {"status": "already_processed", "message": "Achat déjà traité"}
    
    # Find matching package by Google product ID
    package = None
    package_id = None
    for pid, pkg in PAYMENT_PACKAGES.items():
        if pkg.get("google_product_id") == data.product_id:
            package = pkg
            package_id = pid
            break
    
    if not package:
        raise HTTPException(status_code=400, detail="Produit inconnu")
    
    # Store transaction
    await db.payment_transactions.insert_one({
        "user_id": user_id,
        "package_id": package_id,
        "product_id": data.product_id,
        "purchase_token": data.purchase_token,
        "order_id": data.order_id,
        "amount": package["amount"],
        "currency": "usd",
        "payment_status": "paid",
        "payment_method": "google_play",
        "paid_at": datetime.utcnow(),
        "created_at": datetime.utcnow()
    })
    
    # Apply purchase
    if package["type"] == "subscription":
        await db.users.update_one(
            {"_id": current_user["_id"]},
            {"$set": {"is_premium": True, "premium_source": "google_play", "premium_order_id": data.order_id}}
        )
        logger.info(f"User {user_id} upgraded to Premium via Google Play")
        return {"status": "success", "message": "Premium activé!", "is_premium": True}
    elif package["type"] == "pack":
        coins = package["coins"]
        await db.users.update_one(
            {"_id": current_user["_id"]},
            {"$inc": {"swipes_remaining": coins}}
        )
        updated = await db.users.find_one({"_id": current_user["_id"]})
        total = updated.get("swipes_remaining", 0) + updated.get("coins", 0)
        logger.info(f"User {user_id} purchased {coins} swipes via Google Play")
        return {"status": "success", "message": f"+{coins} swipes!", "swipes_added": coins, "total_swipes": total}

@api_router.get("/payments/products")
async def get_products():
    """Return available product IDs for Google Play"""
    return {
        "products": [
            {"id": "gamly_premium_monthly", "type": "subscription", "price": "$17.99/mois", "description": "GAMLY Premium - Swipes illimités"},
            {"id": "gamly_swipes_50", "type": "consumable", "price": "$5.99", "description": "50 Swipes"},
            {"id": "gamly_swipes_200", "type": "consumable", "price": "$9.99", "description": "200 Swipes"},
        ]
    }

# Keep legacy endpoints for backward compatibility
@api_router.post("/subscription/upgrade")
async def upgrade_subscription(current_user: dict = Depends(get_current_user)):
    """Upgrade to premium $17.99/month (mock - no real payment)"""
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"is_premium": True}}
    )
    
    return {
        "success": True,
        "message": "Félicitations! Vous êtes maintenant Premium!",
        "is_premium": True
    }

class PurchaseSwipes(BaseModel):
    pack: str  # "pack_50" or "pack_200"

@api_router.post("/subscription/buy-swipes")
async def buy_swipes(purchase: PurchaseSwipes, current_user: dict = Depends(get_current_user)):
    """Buy swipe packs (mock - no real payment)"""
    packs = {
        "pack_50": {"coins": 50, "price": 3.99},
        "pack_200": {"coins": 200, "price": 9.99},
    }
    
    pack_info = packs.get(purchase.pack)
    if not pack_info:
        raise HTTPException(status_code=400, detail="Pack invalide")
    
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$inc": {"coins": pack_info["coins"]}}
    )
    
    new_coins = current_user.get("coins", 0) + pack_info["coins"]
    
    return {
        "success": True,
        "message": f"+{pack_info['coins']} swipes ajoutés!",
        "coins_added": pack_info["coins"],
        "total_coins": new_coins,
        "price": pack_info["price"]
    }

@api_router.post("/subscription/cancel")
async def cancel_subscription(current_user: dict = Depends(get_current_user)):
    """Cancel premium subscription (mock)"""
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"is_premium": False}}
    )
    
    return {
        "success": True,
        "message": "Abonnement annulé",
        "is_premium": False
    }

# ===================== DELETE MATCH =====================

@api_router.delete("/matches/{match_id}")
async def delete_match(match_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a match and all associated messages"""
    user_id = str(current_user["_id"])
    
    # Verify user is part of this match
    match = await db.matches.find_one({"_id": ObjectId(match_id)})
    if not match:
        raise HTTPException(status_code=404, detail="Match non trouvé")
    
    if user_id not in [match["user1_id"], match["user2_id"]]:
        raise HTTPException(status_code=403, detail="Accès non autorisé")
    
    # Delete all messages
    await db.messages.delete_many({"match_id": match_id})
    
    # Delete match
    await db.matches.delete_one({"_id": ObjectId(match_id)})
    
    return {"success": True, "message": "Match supprimé"}

# ===================== TEAMS ENDPOINTS =====================

@api_router.post("/teams")
async def create_team(team_data: TeamCreate, current_user: dict = Depends(get_current_user)):
    """Create a new team (Premium only)"""
    if not current_user.get("is_premium", False):
        raise HTTPException(status_code=403, detail="Seuls les utilisateurs Premium peuvent créer une team")
    
    # Check if user is already in a team
    existing_team = await db.teams.find_one({
        "$or": [
            {"owner_id": str(current_user["_id"])},
            {"member_ids": str(current_user["_id"])}
        ]
    })
    if existing_team:
        raise HTTPException(status_code=400, detail="Vous êtes déjà dans une team")
    
    team_doc = {
        "name": team_data.name,
        "description": team_data.description,
        "game": team_data.game,
        "owner_id": str(current_user["_id"]),
        "member_ids": [str(current_user["_id"])],  # Owner is first member
        "looking_for_count": min(team_data.looking_for_count, 3),  # Max 3 more (total 4)
        "country": team_data.country,
        "console": team_data.console,
        "play_days": team_data.play_days or [],
        "play_time": team_data.play_time,
        "created_at": datetime.utcnow()
    }
    
    result = await db.teams.insert_one(team_doc)
    team_doc["_id"] = result.inserted_id
    
    return await format_team_response(team_doc)

@api_router.get("/teams")
async def get_teams(
    current_user: dict = Depends(get_current_user),
    game: Optional[str] = None
):
    """Get teams looking for members"""
    query = {"looking_for_count": {"$gt": 0}}
    
    if game:
        query["game"] = game
    
    teams = await db.teams.find(query).sort("created_at", -1).to_list(50)
    
    result = []
    for team in teams:
        formatted = await format_team_response(team)
        result.append(formatted)
    
    return result

@api_router.get("/teams/my")
async def get_my_team(current_user: dict = Depends(get_current_user)):
    """Get the team the user is in"""
    user_id = str(current_user["_id"])
    
    team = await db.teams.find_one({
        "$or": [
            {"owner_id": user_id},
            {"member_ids": user_id}
        ]
    })
    
    if not team:
        return None
    
    return await format_team_response(team)

@api_router.post("/teams/{team_id}/join")
async def join_team(team_id: str, current_user: dict = Depends(get_current_user)):
    """Request to join a team"""
    user_id = str(current_user["_id"])
    
    # Check if already in a team
    existing = await db.teams.find_one({
        "$or": [
            {"owner_id": user_id},
            {"member_ids": user_id}
        ]
    })
    if existing:
        raise HTTPException(status_code=400, detail="Vous êtes déjà dans une team")
    
    team = await db.teams.find_one({"_id": ObjectId(team_id)})
    if not team:
        raise HTTPException(status_code=404, detail="Team non trouvée")
    
    if len(team.get("member_ids", [])) >= 4:
        raise HTTPException(status_code=400, detail="La team est complète")
    
    if team.get("looking_for_count", 0) <= 0:
        raise HTTPException(status_code=400, detail="La team ne recherche plus de membres")
    
    # Add user to team
    await db.teams.update_one(
        {"_id": ObjectId(team_id)},
        {
            "$push": {"member_ids": user_id},
            "$inc": {"looking_for_count": -1}
        }
    )
    
    return {"success": True, "message": "Vous avez rejoint la team!"}

@api_router.post("/teams/{team_id}/leave")
async def leave_team(team_id: str, current_user: dict = Depends(get_current_user)):
    """Leave a team"""
    user_id = str(current_user["_id"])
    
    team = await db.teams.find_one({"_id": ObjectId(team_id)})
    if not team:
        raise HTTPException(status_code=404, detail="Team non trouvée")
    
    if user_id not in team.get("member_ids", []):
        raise HTTPException(status_code=400, detail="Vous n'êtes pas dans cette team")
    
    # If owner leaves, delete the team
    if team["owner_id"] == user_id:
        await db.teams.delete_one({"_id": ObjectId(team_id)})
        return {"success": True, "message": "Team supprimée"}
    
    # Otherwise just remove the member
    await db.teams.update_one(
        {"_id": ObjectId(team_id)},
        {
            "$pull": {"member_ids": user_id},
            "$inc": {"looking_for_count": 1}
        }
    )
    
    return {"success": True, "message": "Vous avez quitté la team"}

@api_router.put("/teams/{team_id}")
async def update_team(team_id: str, team_data: TeamUpdate, current_user: dict = Depends(get_current_user)):
    """Update team (owner only)"""
    user_id = str(current_user["_id"])
    
    team = await db.teams.find_one({"_id": ObjectId(team_id)})
    if not team:
        raise HTTPException(status_code=404, detail="Team non trouvée")
    
    if team["owner_id"] != user_id:
        raise HTTPException(status_code=403, detail="Seul le propriétaire peut modifier la team")
    
    update_data = {}
    if team_data.name:
        update_data["name"] = team_data.name
    if team_data.description is not None:
        update_data["description"] = team_data.description
    if team_data.game:
        update_data["game"] = team_data.game
    if team_data.looking_for_count is not None:
        max_looking = 4 - len(team.get("member_ids", []))
        update_data["looking_for_count"] = min(team_data.looking_for_count, max_looking)
    if team_data.country is not None:
        update_data["country"] = team_data.country
    if team_data.console is not None:
        update_data["console"] = team_data.console
    if team_data.play_days is not None:
        update_data["play_days"] = team_data.play_days
    if team_data.play_time is not None:
        update_data["play_time"] = team_data.play_time
    
    if update_data:
        await db.teams.update_one(
            {"_id": ObjectId(team_id)},
            {"$set": update_data}
        )
    
    updated_team = await db.teams.find_one({"_id": ObjectId(team_id)})
    return await format_team_response(updated_team)

@api_router.delete("/teams/{team_id}")
async def delete_team(team_id: str, current_user: dict = Depends(get_current_user)):
    """Delete team (owner only)"""
    user_id = str(current_user["_id"])
    
    team = await db.teams.find_one({"_id": ObjectId(team_id)})
    if not team:
        raise HTTPException(status_code=404, detail="Team non trouvée")
    
    if team["owner_id"] != user_id:
        raise HTTPException(status_code=403, detail="Seul le propriétaire peut supprimer la team")
    
    await db.teams.delete_one({"_id": ObjectId(team_id)})
    
    return {"success": True, "message": "Team supprimée"}

async def format_team_response(team: dict) -> dict:
    """Helper to format team response with member details"""
    members = []
    for member_id in team.get("member_ids", []):
        user = await db.users.find_one({"_id": ObjectId(member_id)})
        if user:
            members.append({
                "id": str(user["_id"]),
                "nickname": user["nickname"],
                "photo": user.get("photo"),
                "console": user.get("console"),
                "status": user.get("status", "offline")
            })
    
    return {
        "id": str(team["_id"]),
        "name": team["name"],
        "description": team.get("description"),
        "game": team["game"],
        "owner_id": team["owner_id"],
        "members": members,
        "looking_for_count": team.get("looking_for_count", 0),
        "country": team.get("country"),
        "console": team.get("console"),
        "play_days": team.get("play_days", []),
        "play_time": team.get("play_time"),
        "created_at": team.get("created_at")
    }

# ===================== GAME NIGHT ENDPOINTS =====================

@api_router.post("/game-nights")
async def create_game_night(data: GameNightCreate, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    match = await db.matches.find_one({"_id": ObjectId(data.match_id)})
    if not match:
        raise HTTPException(status_code=404, detail="Match non trouve")
    if user_id not in [match["user1_id"], match["user2_id"]]:
        raise HTTPException(status_code=403, detail="Acces non autorise")
    
    other_user_id = match["user2_id"] if match["user1_id"] == user_id else match["user1_id"]
    
    game_night_doc = {
        "match_id": data.match_id,
        "creator_id": user_id,
        "invited_id": other_user_id,
        "game": data.game,
        "scheduled_date": data.scheduled_date,
        "scheduled_time": data.scheduled_time,
        "note": data.note or "",
        "status": "pending",
        "created_at": datetime.utcnow()
    }
    result = await db.game_nights.insert_one(game_night_doc)
    
    system_msg = {
        "match_id": data.match_id,
        "sender_id": user_id,
        "content": f"Game Night propose ! {data.game} le {data.scheduled_date} a {data.scheduled_time}",
        "message_type": "game_night",
        "timestamp": datetime.utcnow()
    }
    await db.messages.insert_one(system_msg)
    
    return {
        "id": str(result.inserted_id),
        "match_id": data.match_id,
        "creator_id": user_id,
        "invited_id": other_user_id,
        "game": data.game,
        "scheduled_date": data.scheduled_date,
        "scheduled_time": data.scheduled_time,
        "note": data.note or "",
        "status": "pending",
        "created_at": game_night_doc["created_at"]
    }

@api_router.get("/game-nights/{match_id}")
async def get_game_nights(match_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    match = await db.matches.find_one({"_id": ObjectId(match_id)})
    if not match:
        raise HTTPException(status_code=404, detail="Match non trouve")
    if user_id not in [match["user1_id"], match["user2_id"]]:
        raise HTTPException(status_code=403, detail="Acces non autorise")
    
    game_nights = await db.game_nights.find({"match_id": match_id}).sort("created_at", -1).to_list(50)
    return [{
        "id": str(gn["_id"]),
        "match_id": gn["match_id"],
        "creator_id": gn["creator_id"],
        "invited_id": gn["invited_id"],
        "game": gn["game"],
        "scheduled_date": gn["scheduled_date"],
        "scheduled_time": gn["scheduled_time"],
        "note": gn.get("note", ""),
        "status": gn["status"],
        "created_at": gn["created_at"]
    } for gn in game_nights]

@api_router.put("/game-nights/{game_night_id}/respond")
async def respond_game_night(game_night_id: str, data: GameNightRespond, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    gn = await db.game_nights.find_one({"_id": ObjectId(game_night_id)})
    if not gn:
        raise HTTPException(status_code=404, detail="Game Night non trouve")
    if gn["invited_id"] != user_id:
        raise HTTPException(status_code=403, detail="Seul l'invite peut repondre")
    if data.status not in ["accepted", "declined"]:
        raise HTTPException(status_code=400, detail="Statut invalide")
    
    await db.game_nights.update_one({"_id": ObjectId(game_night_id)}, {"$set": {"status": data.status}})
    
    status_text = "accepte" if data.status == "accepted" else "decline"
    system_msg = {
        "match_id": gn["match_id"],
        "sender_id": user_id,
        "content": f"Game Night {status_text} ! {gn['game']} le {gn['scheduled_date']} a {gn['scheduled_time']}",
        "message_type": "game_night",
        "timestamp": datetime.utcnow()
    }
    await db.messages.insert_one(system_msg)
    return {"message": f"Game Night {status_text}", "status": data.status}

@api_router.delete("/game-nights/{game_night_id}")
async def cancel_game_night(game_night_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    gn = await db.game_nights.find_one({"_id": ObjectId(game_night_id)})
    if not gn:
        raise HTTPException(status_code=404, detail="Game Night non trouve")
    if gn["creator_id"] != user_id:
        raise HTTPException(status_code=403, detail="Seul le createur peut annuler")
    await db.game_nights.delete_one({"_id": ObjectId(game_night_id)})
    return {"message": "Game Night annule"}

# ===================== HEALTH CHECK =====================

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow()}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================== LEGAL PAGES (served at root, not /api) =====================

PRIVACY_POLICY_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GAMLY - Politique de Confidentialite</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0A0A0F;color:#E0E0E0;line-height:1.7;padding:20px;max-width:800px;margin:0 auto}
h1{color:#FF1493;font-size:28px;margin:30px 0 10px;border-bottom:2px solid #FF1493;padding-bottom:10px}
h2{color:#FF1493;font-size:20px;margin:25px 0 10px}
h3{color:#bb8fce;font-size:16px;margin:15px 0 8px}
p,li{font-size:15px;margin-bottom:8px;color:#ccc}
ul{padding-left:20px}
.header{text-align:center;padding:20px 0}
.header h1{border:none;font-size:32px}
.date{color:#888;font-size:13px;text-align:center}
a{color:#FF1493}
</style>
</head>
<body>
<div class="header"><h1>GAMLY</h1><p>Politique de Confidentialite</p></div>
<p class="date">Derniere mise a jour : 1er mars 2026</p>

<h2>1. Introduction</h2>
<p>GAMLY ("nous", "notre", "l'application") est une application de rencontre pour gamers. Nous nous engageons a proteger la vie privee de nos utilisateurs. Cette politique explique comment nous collectons, utilisons et protegeons vos donnees personnelles.</p>

<h2>2. Donnees collectees</h2>
<h3>2.1 Donnees fournies par vous</h3>
<ul>
<li><strong>Informations de compte</strong> : adresse email, mot de passe (chiffre)</li>
<li><strong>Profil</strong> : pseudo, age, genre, pays, console de jeu, bio, photo/avatar</li>
<li><strong>Preferences de jeu</strong> : jeux preferes, centres d'interet, langues, disponibilites</li>
<li><strong>Comptes gaming</strong> : gamertags Steam, Xbox, PlayStation, Nintendo, Activision (fournis volontairement)</li>
<li><strong>Messages</strong> : messages texte et vocaux envoyes dans l'application</li>
</ul>
<h3>2.2 Donnees collectees automatiquement</h3>
<ul>
<li>Date de creation du compte</li>
<li>Historique des swipes et matchs</li>
</ul>

<h2>3. Utilisation des donnees</h2>
<p>Vos donnees sont utilisees pour :</p>
<ul>
<li>Creer et gerer votre compte</li>
<li>Vous proposer des profils compatibles</li>
<li>Permettre la communication entre matchs</li>
<li>Ameliorer l'experience utilisateur</li>
<li>Assurer la securite et prevenir les abus</li>
</ul>

<h2>4. Partage des donnees</h2>
<p>Nous ne vendons <strong>jamais</strong> vos donnees personnelles. Vos informations ne sont partagees qu'avec :</p>
<ul>
<li><strong>Vos matchs</strong> : votre pseudo, photo, bio, jeux, et gamertags sont reveles uniquement apres un match mutuel</li>
<li><strong>Avant le match</strong> : vos gamertags sont affiches de maniere floutee (ex: "St****42")</li>
</ul>

<h2>5. Securite des donnees</h2>
<ul>
<li>Les mots de passe sont chiffres avec bcrypt</li>
<li>Les communications sont protegees par HTTPS</li>
<li>L'acces aux donnees est restreint par authentification JWT</li>
</ul>

<h2>6. Conservation des donnees</h2>
<p>Vos donnees sont conservees tant que votre compte est actif. En cas de suppression du compte, toutes vos donnees personnelles, messages et matchs sont definitivement supprimes.</p>

<h2>7. Vos droits</h2>
<p>Vous avez le droit de :</p>
<ul>
<li><strong>Acceder</strong> a vos donnees personnelles (via votre profil)</li>
<li><strong>Modifier</strong> vos informations a tout moment</li>
<li><strong>Supprimer</strong> votre compte et toutes vos donnees (Profil &gt; Supprimer le compte)</li>
<li><strong>Supprimer</strong> des matchs, conversations ou equipes individuellement</li>
</ul>

<h2>8. Mineurs</h2>
<p>GAMLY est destinee aux personnes agees de <strong>18 ans et plus</strong>. Nous ne collectons pas sciemment de donnees de mineurs.</p>

<h2>9. Modifications</h2>
<p>Nous nous reservons le droit de modifier cette politique. Les utilisateurs seront informes des changements importants.</p>

<h2>10. Contact</h2>
<p>Pour toute question concernant vos donnees : <a href="mailto:contact@gamly.app">contact@gamly.app</a></p>
</body>
</html>"""

TERMS_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GAMLY - Conditions d'Utilisation</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0A0A0F;color:#E0E0E0;line-height:1.7;padding:20px;max-width:800px;margin:0 auto}
h1{color:#FF1493;font-size:28px;margin:30px 0 10px;border-bottom:2px solid #FF1493;padding-bottom:10px}
h2{color:#FF1493;font-size:20px;margin:25px 0 10px}
p,li{font-size:15px;margin-bottom:8px;color:#ccc}
ul{padding-left:20px}
.header{text-align:center;padding:20px 0}
.header h1{border:none;font-size:32px}
.date{color:#888;font-size:13px;text-align:center}
a{color:#FF1493}
</style>
</head>
<body>
<div class="header"><h1>GAMLY</h1><p>Conditions d'Utilisation</p></div>
<p class="date">Derniere mise a jour : 1er mars 2026</p>

<h2>1. Acceptation des conditions</h2>
<p>En utilisant GAMLY, vous acceptez les presentes conditions d'utilisation. Si vous n'acceptez pas ces conditions, veuillez ne pas utiliser l'application.</p>

<h2>2. Description du service</h2>
<p>GAMLY est une application de rencontre destinee aux gamers, permettant de decouvrir des profils, matcher, discuter et planifier des sessions de jeu ensemble.</p>

<h2>3. Inscription</h2>
<ul>
<li>Vous devez avoir au moins <strong>18 ans</strong> pour utiliser GAMLY</li>
<li>Vous devez fournir des informations exactes lors de l'inscription</li>
<li>Vous etes responsable de la securite de votre compte</li>
</ul>

<h2>4. Comportement des utilisateurs</h2>
<p>Les comportements suivants sont <strong>strictement interdits</strong> :</p>
<ul>
<li>Harcelement, intimidation ou menaces</li>
<li>Contenu sexuellement explicite, violent ou haineux</li>
<li>Spam, arnaques ou tentatives de fraude</li>
<li>Usurpation d'identite</li>
<li>Utilisation de langage inapproprie (detecte automatiquement)</li>
</ul>
<p>Apres <strong>3 avertissements</strong>, votre compte sera suspendu.</p>

<h2>5. Abonnements et achats</h2>
<ul>
<li><strong>Swipes gratuits</strong> : 10 swipes offerts a l'inscription</li>
<li><strong>Abonnement Premium</strong> : 17,99 EUR/mois pour des swipes illimites</li>
<li><strong>Packs de swipes</strong> : 50 swipes (3,99 EUR), 200 swipes (9,99 EUR)</li>
</ul>

<h2>6. Propriete intellectuelle</h2>
<p>GAMLY et son contenu (design, logo, code) sont proteges par le droit d'auteur. Toute reproduction non autorisee est interdite.</p>

<h2>7. Limitation de responsabilite</h2>
<p>GAMLY ne peut etre tenue responsable des interactions entre utilisateurs en dehors de l'application, ni des contenus publies par les utilisateurs.</p>

<h2>8. Suppression de compte</h2>
<p>Vous pouvez supprimer votre compte a tout moment depuis les parametres de votre profil. La suppression est definitive et irreversible.</p>

<h2>9. Modifications</h2>
<p>Nous nous reservons le droit de modifier ces conditions. L'utilisation continue de l'application apres modification vaut acceptation.</p>

<h2>10. Contact</h2>
<p>Pour toute question : <a href="mailto:contact@gamly.app">contact@gamly.app</a></p>
</body>
</html>"""

@app.get("/privacy-policy", response_class=HTMLResponse)
async def privacy_policy():
    return PRIVACY_POLICY_HTML

@app.get("/terms", response_class=HTMLResponse)
async def terms_of_service():
    return TERMS_HTML

@api_router.get("/privacy-policy", response_class=HTMLResponse)
async def api_privacy_policy():
    return PRIVACY_POLICY_HTML

@api_router.get("/terms", response_class=HTMLResponse)
async def api_terms_of_service():
    return TERMS_HTML

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
