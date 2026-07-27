from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

class CalendarEpisodeFile(BaseModel):
    id: int
    seriesId: int
    seasonNumber: int
    relativePath: Optional[str] = None
    path: Optional[str] = None
    size: int
    dateAdded: str
    quality: Dict[str, Any]
    customFormats: Optional[List[Dict[str, Any]]] = None
    customFormatScore: int
    releaseType: str
    mediaInfo: Optional[Dict[str, Any]] = None
    qualityCutoffNotMet: bool

class CalendarSeries(BaseModel):
    id: int
    title: Optional[str] = None
    status: str
    ended: bool = False
    overview: Optional[str] = None
    network: Optional[str] = None
    airTime: Optional[str] = None
    images: Optional[List[Dict[str, Any]]] = None
    year: int
    path: Optional[str] = None
    qualityProfileId: Optional[int] = None
    monitored: bool
    runtime: Optional[int] = None
    tvdbId: Optional[int] = None
    firstAired: Optional[str] = None
    seriesType: Optional[str] = None
    genres: Optional[List[str]] = None
    tags: Optional[List[int]] = None
    added: Optional[str] = None

class CalendarEpisode(BaseModel):
    id: int
    seriesId: int
    tvdbId: Optional[int] = None
    episodeFileId: Optional[int] = None
    seasonNumber: int
    episodeNumber: int
    title: Optional[str] = None
    airDate: Optional[str] = None
    airDateUtc: Optional[str] = None
    lastSearchTime: Optional[str] = None
    runtime: Optional[int] = None
    overview: Optional[str] = None
    episodeFile: Optional[CalendarEpisodeFile] = None
    hasFile: bool
    monitored: bool
    series: Optional[CalendarSeries] = None
    images: Optional[List[Dict[str, Any]]] = None
