import requests
import json
import os
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

# -------------------------------
# إعدادات CinemaBox API
# -------------------------------
BASE_URL = "https://cinema.albox.co/api/v4/"
BACKUP_URL = "https://pucinema.albox.co/api/v4/"
APP_VERSION = "4.6.0"
TIMEOUT = 15

# -------------------------------
# نماذج البيانات (Pydantic)
# -------------------------------
class StreamVideo(BaseModel):
    quality: str
    url: str

class SubtitleTrack(BaseModel):
    language: str
    vtt_url: str
    srt_url: str

class MediaResult(BaseModel):
    episode_id: int
    show_title: str
    show_type: str
    show_id: int
    episode_number: int
    season_number: int
    season_id: int
    image_url: str
    length_ms: int
    videos: List[StreamVideo]
    subtitles: List[SubtitleTrack]
    intro_start: int
    intro_end: int
    outro_start: int
    outro_end: int

class ShowResult(BaseModel):
    id: int
    title: str
    type: str
    image_url: str
    year: int

class SearchResponse(BaseModel):
    results: List[ShowResult]

class ResolveRequest(BaseModel):
    title: str
    original_title: Optional[str] = None
    year: int
    media_type: str = "movie"

class ResolveResponse(BaseModel):
    episode_id: int
    show_id: int
    quality: str
    stream_url: str
    media: MediaResult

class EpisodeRequest(BaseModel):
    title: str
    original_title: Optional[str] = None
    year: int
    season_number: int
    episode_number: int

# -------------------------------
# إدارة التوكن
# -------------------------------
class CinemaBoxClient:
    def init(self):
        self.jwt = None
        self.active_url = BASE_URL
        self.last_login = 0
    
    def ensure_login(self):
        if self.jwt and (time.time() - self.last_login) < 3600:
            return
        payload = {
            "username_or_email": os.environ.get("CINEMABOX_EMAIL", "bkrmshtaq79@gmail.com"),
            "password": os.environ.get("CINEMABOX_PASSWORD", "07744080333@@")
        }
        try:
            resp = self._request("auth/login", method="POST", json=payload, use_auth=False)
            if "jwt" in resp:
                self.jwt = resp["jwt"]
                self.last_login = time.time()
            else:
                raise Exception("No JWT in response")
        except Exception as e:
            raise Exception(f"Login failed: {str(e)}")
    
    def _request(self, endpoint: str, method="GET", json=None, use_auth=True):
        url = self.active_url + endpoint
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "App-Version": APP_VERSION,
            "Accept-Language": "ar",
            "Device-Id": "vercel_server",
            "Device-Model": "Server",
            "Device-OS-Version": "3",
            "Device-Store": "google"
        }
        if use_auth and self.jwt:
            headers["Authorization"] = self.jwt
        
        try:
            if method.upper() == "GET":
                r = requests.get(url, headers=headers, timeout=TIMEOUT)
            else:
                r = requests.post(url, headers=headers, json=json, timeout=TIMEOUT)
            
            if r.status_code == 503 and self.active_url == BASE_URL:
                self.active_url = BACKUP_URL
                return self._request(endpoint, method, json, use_auth)
            
            if r.status_code == 401:
                self.jwt = None
                self.ensure_login()
                headers["Authorization"] = self.jwt
                r = requests.get(url, headers=headers, timeout=TIMEOUT) if method=="GET" else requests.post(url, headers=headers, json=json, timeout=TIMEOUT)
[14/05/2026 05:14 م] Satoru: if r.status_code >= 400:
                raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
            
            return r.json()
        except Exception as e:
            raise Exception(f"Request error: {str(e)}")
    
    def search(self, query: str) -> List[ShowResult]:
        self.ensure_login()
        encoded = requests.utils.quote(query)
        resp = self._request(f"search?q={encoded}")
        results = []
        for item in resp.get("results", []):
            img = item.get("style", {}).get("image", "") if "style" in item else ""
            results.append(ShowResult(
                id=item["id"],
                title=item["title"],
                type=item["type"],
                image_url=img,
                year=item.get("year", 0)
            ))
        return results
    
    def get_stream(self, episode_id: int) -> MediaResult:
        self.ensure_login()
        data = self._request(f"shows/episodes/player/{episode_id}")
        videos = []
        for v in data.get("videos", []):
            videos.append(StreamVideo(quality=v.get("quality", "auto"), url=v.get("url", "")))
        subtitles = []
        for s in data.get("subtitles", []):
            subtitles.append(SubtitleTrack(
                language=s.get("language", ""),
                vtt_url=s.get("vtt", ""),
                srt_url=s.get("srt", "")
            ))
        pa = data.get("parental_access", {})
        intro = pa.get("intro", {})
        outro = pa.get("outro", {})
        return MediaResult(
            episode_id=data.get("id", episode_id),
            show_title=data.get("show_title", ""),
            show_type=data.get("show_type", ""),
            show_id=data.get("show_id", 0),
            episode_number=data.get("episode_number", 0),
            season_number=data.get("season_number", 0),
            season_id=data.get("season_id", 0),
            image_url=data.get("image", ""),
            length_ms=data.get("length", 0),
            videos=videos,
            subtitles=subtitles,
            intro_start=intro.get("start", 0),
            intro_end=intro.get("end", 0),
            outro_start=outro.get("start", 0),
            outro_end=outro.get("end", 0)
        )
    
    def get_sections(self, show_id: int):
        self.ensure_login()
        return self._request(f"shows/shows/dynamic/{show_id}")
    
    def find_episode_id_by_index(self, show_id: int, season_number: int, episode_number: int) -> int:
        sections = self.get_sections(show_id)
        season_counter = 0
        for section in sections.get("sections", []):
            data = section.get("data", [])
            if not data:
                continue
            season_counter += 1
            if season_counter != season_number:
                continue
            idx = episode_number - 1
            if 0 <= idx < len(data):
                return data[idx].get("id", -1)
        return -1

# -------------------------------
# تطبيق FastAPI (لـ Vercel)
# -------------------------------
app = FastAPI(title="CinemaBox Proxy API")

# إضافة CORS للسماح لأي تطبيق بالاتصال
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = CinemaBoxClient()

# محاولة تسجيل الدخول عند بدء التشغيل (اختياري)
@app.on_event("startup")
async def startup():
    try:
        client.ensure_login()
        print("✅ CinemaBox login successful")
    except Exception as e:
        print(f"⚠️ Initial login failed: {e}")

# -------------------------------
# نقاط النهاية (Endpoints)
# -------------------------------
@app.get("/search", response_model=SearchResponse)
async def search(query: str):
    results = client.search(query)
    return SearchResponse(results=results)

@app.get("/stream/{episode_id}", response_model=MediaResult)
async def get_stream(episode_id: int):
    return client.get_stream(episode_id)
[14/05/2026 05:14 م] Satoru: @app.post("/resolve_movie", response_model=ResolveResponse)
async def resolve_movie(req: ResolveRequest):
    query = req.original_title if req.original_title else req.title
    results = client.search(query)
    best_show = None
    best_score = -1
    for r in results:
        if r.type != "MOVIE":
            continue
        score = 0
        if r.title.lower() == req.title.lower():
            score += 100
        elif req.title.lower() in r.title.lower() or r.title.lower() in req.title.lower():
            score += 50
        if r.year == req.year:
            score += 30
        elif abs(r.year - req.year) <= 2:
            score += 10
        if score > best_score:
            best_score = score
            best_show = r
    if not best_show:
        raise HTTPException(status_code=404, detail=f"No movie found for '{req.title}'")
    
    sections = client.get_sections(best_show.id)
    episode_id = -1
    for sec in sections.get("sections", []):
        for item in sec.get("data", []):
            if item.get("type") == "episode":
                episode_id = item.get("id")
                break
        if episode_id != -1:
            break
    if episode_id == -1:
        raise HTTPException(status_code=404, detail="No episode found for this movie")
    
    media = client.get_stream(episode_id)
    if not media.videos:
        raise HTTPException(status_code=404, detail="No video streams available")
    
    best_quality = media.videos[0]
    for v in media.videos:
        if "1080" in v.quality:
            best_quality = v
            break
        elif "720" in v.quality and best_quality.quality != "1080p":
            best_quality = v
    return ResolveResponse(
        episode_id=episode_id,
        show_id=best_show.id,
        quality=best_quality.quality,
        stream_url=best_quality.url,
        media=media
    )

@app.post("/resolve_tv", response_model=ResolveResponse)
async def resolve_tv(req: EpisodeRequest):
    query = req.original_title if req.original_title else req.title
    results = client.search(query)
    best_show = None
    best_score = -1
    for r in results:
        if r.type != "SERIES":
            continue
        score = 0
        if r.title.lower() == req.title.lower():
            score += 100
        elif req.title.lower() in r.title.lower() or r.title.lower() in req.title.lower():
            score += 50
        if r.year == req.year:
            score += 30
        elif abs(r.year - req.year) <= 2:
            score += 10
        if score > best_score:
            best_score = score
            best_show = r
    if not best_show:
        raise HTTPException(status_code=404, detail=f"No series found for '{req.title}'")
    
    episode_id = client.find_episode_id_by_index(best_show.id, req.season_number, req.episode_number)
    if episode_id == -1:
        raise HTTPException(status_code=404, detail=f"Episode S{req.season_number}E{req.episode_number} not found")
    
    media = client.get_stream(episode_id)
    if not media.videos:
        raise HTTPException(status_code=404, detail="No video streams available")
    
    best_quality = media.videos[0]
    for v in media.videos:
        if "1080" in v.quality:
            best_quality = v
            break
        elif "720" in v.quality and best_quality.quality != "1080p":
            best_quality = v
    return ResolveResponse(
        episode_id=episode_id,
        show_id=best_show.id,
        quality=best_quality.quality,
        stream_url=best_quality.url,
        media=media
    )

@app.get("/health")
async def health():
    return {"status": "ok", "logged_in": client.jwt is not None}
