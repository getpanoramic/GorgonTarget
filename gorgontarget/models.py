from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

class SonarrAddSeries(BaseModel):
    title: str
    tvdbId: int
    profileId: int
    rootFolderPath: str
    monitored: bool = True
    addOptions: Optional[Dict[str, Any]] = None

class SonarrCommand(BaseModel):
    name: str
    seriesId: Optional[int] = None
    episodeIds: Optional[List[int]] = None

class SonarrSeries(BaseModel):
    id: int
    title: str
    tvdbId: int
    imdbId: str = ""
    tmdbId: int = 0
    sortTitle: str = ""
    status: str = "continuing"
    overview: str = ""
    year: int = 0
    images: List[Dict] = []
    remotePoster: Optional[str] = None
    alternateTitles: List[Dict] = []
    genres: List[str] = []
    seriesType: str = "standard"
    path: str
    profileId: int = 1
    languageProfileId: int = 1
    monitored: bool = True
    useSceneNumbering: bool = False
    added: str = "2026-01-01T00:00:00Z"
    seasons: List[Dict] = []
    statistics: Dict[str, Any] = Field(default_factory=lambda: {
        "episodeFileCount": 0,
        "episodeCount": 0,
        "totalEpisodeCount": 0,
        "sizeOnDisk": 0,
        "percentOfEpisodes": 100
    })

class SonarrEpisode(BaseModel):
    id: int
    seriesId: int
    episodeFileId: int = 0
    seasonNumber: int
    episodeNumber: int
    title: str = ""
    overview: str = ""
    monitored: bool = True
    hasFile: bool = False
    episodeFile: Optional[Dict] = None

class SonarrSystemStatus(BaseModel):
    version: str
    buildTime: str = "2026-01-01T00:00:00Z"
    isDebug: bool = False
    isProduction: bool = True
    isAdmin: bool = True
    isUserInteractive: bool = False
    startupPath: str
    appData: str
    osName: str
    osVersion: str
    isNetCore: bool = True
    appName: str = "Sonarr"
