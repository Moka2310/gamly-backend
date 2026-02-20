Le backend sur Emergent est complet. Le problème est que Render n'a pas ce code.

---

## 🔧 Solution : Mettre à jour Render avec le code complet

### Étape 1 : Je vais créer le fichier server.py complet pour Render

Allez sur GitHub : https://github.com/Moka2310/gamly-backend/edit/main/server.py

**Supprimez TOUT** et collez ce code complet (c'est long mais nécessaire) :
Action: $ cat /app/backend/server.py
Observation: from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
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

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

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

# Security
security = HTTPBearer()

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
    created_at: datetime
    profile_complete: bool = False

class SwipeCreate(BaseModel):
    swiped_user_id: str
    action: str  # like, dislike

class MessageCreate(BaseModel):
    content: str

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
    timestamp: datetime

class BlockUserRequest(BaseModel):
    user_id: str

class SubscriptionResponse(BaseModel):
    type: str  # free, premium
    swipes_today: int
    swipes_remaining: int
    max_daily_swipes: int
    is_premium: bool

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

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
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
        "swipes_today": 0,
        "last_swipe_reset": date.today().isoformat(),
        "is_premium": False,
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
    user = await db.users.find_one({"email": user_data.email})
    if not user:
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    
    if not verify_password(user_data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    
    user_id = str(user["_id"])
    token = create_access_token(user_id)
    
    return {
        "token": token,
        "user": {
            "id": user_id,
            "email": user["email"],
            "nickname": user["nickname"],
            "profile_complete": is_profile_complete(user)
        }
    }

# ===================== PASSWORD RESET ENDPOINTS =====================

# Store reset codes in memory (in production, use Redis or database)
reset_codes = {}

@api_router.post("/auth/forgot-password")
async def forgot_password(data: PasswordResetRequest):
    """Request password reset - generates a code"""
    user = await db.users.find_one({"email": data.email})
    if not user:
        # Don't reveal if email exists or not for security
        return {"message": "Si cet email existe, un code de réinitialisation a été généré."}
    
    # Generate 6-digit code
    import random
    code = str(random.randint(100000, 999999))
    
    # Store code with expiration (10 minutes)
    reset_codes[data.email] = {
        "code": code,
        "expires": datetime.utcnow() + timedelta(minutes=10)
    }
    
    # In production, send email here
    # For demo, we'll return the code (remove in production!)
    logger.info(f"Password reset code for {data.email}: {code}")
    
    return {
        "message": "Code de réinitialisation généré.",
        "demo_code": code  # Remove this in production!
    }

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
        "profile_complete": is_profile_complete(updated_user)
    }

# ===================== DISCOVER / SWIPE ENDPOINTS =====================

@api_router.get("/discover")
async def discover_profiles(
    current_user: dict = Depends(get_current_user),
    gender: Optional[str] = None,
    country: Optional[str] = None,
    language: Optional[str] = None
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
    
    # Find profiles with complete profiles
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
    
    # Check swipe limit (3 free swipes per day)
    if not current_user.get("is_premium", False):
        if current_user.get("swipes_today", 0) >= 5:
            raise HTTPException(
                status_code=403, 
                detail="Limite de swipes atteinte. Passez Premium pour des swipes illimités!"
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
    
    # Increment swipe count
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
    swipes_remaining = max(0, 3 - updated_user.get("swipes_today", 0)) if not updated_user.get("is_premium") else -1
    
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
                        "gender": other_user.get("gender")
                    },
                    "matched_at": match["matched_at"],
                    "last_message": {
                        "content": last_message["content"] if last_message else None,
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
        "timestamp": msg["timestamp"],
        "is_mine": msg["sender_id"] == user_id
    } for msg in messages]

@api_router.post("/messages/{match_id}")
async def send_message(match_id: str, message: MessageCreate, current_user: dict = Depends(get_current_user)):
    """Send a message in a match"""
    user_id = str(current_user["_id"])
    
    # Check for banned words
    if contains_banned_words(message.content):
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
        "timestamp": datetime.utcnow()
    }
    result = await db.messages.insert_one(message_doc)
    
    return {
        "id": str(result.inserted_id),
        "match_id": match_id,
        "sender_id": user_id,
        "content": message.content,
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
    await db.blocks
... [stdout truncated]
Exit code: 0
