from typing import Dict, Any
import sys
from .models import SonarrSeries, SonarrEpisode, SonarrSystemStatus
from .settings import settings

class MedusaTranslator:
    @staticmethod
    def extract_clean_integer_id(show_node: Dict[str, Any]) -> int:
        # Prioritize explicit unique identifiers from Medusa
        # Medusa episodes often have a 'tvdb' ID or a unique 'id'
        priority_keys = ['tvdb', 'id', 'indexerId']
        
        # If the input is a dictionary, check for these keys
        if isinstance(show_node, dict):
            for key in priority_keys:
                if key in show_node:
                    try:
                        val = show_node[key]
                        if isinstance(val, dict):
                             # Sometimes the ID is nested in a dict
                             return int(val.get('id') or val.get('value') or 0)
                        return int(val)
                    except (ValueError, TypeError):
                        continue
        
        # Fallback to generic parsing for non-standard structures
        try:
            return int(show_node) if not isinstance(show_node, dict) else 0
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def extract_clean_year(show_node: Dict[str, Any]) -> int:
        raw_year = show_node.get("year") or show_node.get("startYear")
        if isinstance(raw_year, dict):
            raw_year = raw_year.get("year") or raw_year.get("value") or list(raw_year.values())[0]
        try:
            if raw_year is not None:
                return int(raw_year)
        except (ValueError, TypeError):
            pass
        return 0

    @staticmethod
    def parse_size_to_bytes(size_str: str) -> int:
        try:
            if not size_str: return 0
            # Handle possible string representation of numbers or formatted strings
            if isinstance(size_str, (int, float)): return int(size_str)
            if " " in size_str:
                val, unit = size_str.split()
                val = float(val)
                multipliers = {"GB": 10**9, "TB": 10**12, "MB": 10**6, "KB": 10**3}
                return int(val * multipliers.get(unit.upper(), 1))
            return int(size_str)
        except (ValueError, AttributeError):
            return 0

    @classmethod
    def to_sonarr_series(cls, medusa_show: Dict[str, Any], api_key: str = "") -> SonarrSeries:
        ids = medusa_show.get("ids", {})
        medusa_id = cls.extract_clean_integer_id(medusa_show)
        title = medusa_show.get("title", f"Series {medusa_id}")

        # Aggregate statistics
        seasons_data = medusa_show.get("seasons", [])
        total_episodes = sum(int(s.get("episodes", 0)) for s in seasons_data)
        downloaded_episodes = sum(int(s.get("episodes", 0)) for s in seasons_data)
        percent_downloaded = (downloaded_episodes / total_episodes * 100) if total_episodes > 0 else 100

        seasons = []
        for s in seasons_data:
            ep_count = int(s.get("episodes", 0))
            season_size = cls.parse_size_to_bytes(s.get("size", "0 B"))
            
            seasons.append({
                "seasonNumber": int(s.get("season", 0)),
                "monitored": True,
                "statistics": {
                    "episodeFileCount": ep_count,
                    "episodeCount": ep_count,
                    "totalEpisodeCount": ep_count,
                    "sizeOnDisk": season_size,
                    "percentOfEpisodes": 100.0
                }
            })

        total_size_on_disk = sum(cls.parse_size_to_bytes(s.get("size", "0 B")) for s in seasons_data)
        key_param = f"?api_key={api_key}" if api_key else ""

        # Robust imdbId extraction
        imdb_val = ids.get("imdb") or medusa_show.get("externals", {}).get("imdb") or medusa_show.get("imdbInfo", {}).get("imdbId") or ""
        if isinstance(imdb_val, int):
            imdb_val = f"tt{imdb_val:07d}"
        
        return SonarrSeries(
            id=medusa_id,
            title=title,
            tvdbId=int(ids.get("tvdb") or medusa_show.get("externals", {}).get("tvdb") or 0),
            tmdbId=int(ids.get("tmdb") or medusa_show.get("externals", {}).get("tmdb") or 0),
            imdbId=str(imdb_val),
            sortTitle=title.lower(),
            status="continuing" if medusa_show.get("status", "").lower() == "continuing" else "ended",
            overview=medusa_show.get("plot", medusa_show.get("overview", "")),
            year=cls.extract_clean_year(medusa_show),
            path=medusa_show.get("config", {}).get("location", f"/tv/{title}"),
            monitored=not medusa_show.get("paused", False),
            images=[
                {"coverType": "poster", "url": f"/api/v3/mediacover/{medusa_id}/poster-500.jpg{key_param}", "remoteUrl": f"/api/v3/mediacover/{medusa_id}/poster-500.jpg{key_param}"},
                {"coverType": "banner", "url": f"/api/v3/mediacover/{medusa_id}/banner-500.jpg{key_param}", "remoteUrl": f"/api/v3/mediacover/{medusa_id}/banner-500.jpg{key_param}"},
                {"coverType": "fanart", "url": f"/api/v3/mediacover/{medusa_id}/fanart-500.jpg{key_param}", "remoteUrl": f"/api/v3/mediacover/{medusa_id}/fanart-500.jpg{key_param}"}
            ],
            remotePoster=f"/api/v3/mediacover/{medusa_id}/poster-500.jpg{key_param}",
            seasons=seasons,
            statistics={
                "episodeFileCount": total_episodes,
                "episodeCount": total_episodes,
                "totalEpisodeCount": total_episodes,
                "sizeOnDisk": total_size_on_disk,
                "percentOfEpisodes": percent_downloaded
            },
            network=medusa_show.get("network", "Unknown"),
            genres=medusa_show.get("genres", []),
            ratings={"votes": 0, "value": float(medusa_show.get("rating") if isinstance(medusa_show.get("rating"), (int, float, str)) else 0.0)},
            certification=medusa_show.get("certification", None),
            tags=[]
        )

    @classmethod
    def to_sonarr_episode(cls, medusa_ep: Dict[str, Any], series_id: int) -> SonarrEpisode:
        status = str(medusa_ep.get("status", "")).lower()
        has_file = status in ["downloaded", "snatched"]
        # Use the robust extraction method to handle nested dictionaries
        ep_id = cls.extract_clean_integer_id(medusa_ep)

        episode = SonarrEpisode(
            id=ep_id,
            seriesId=series_id,
            episodeFileId=ep_id if has_file else 0,
            seasonNumber=int(medusa_ep.get("season", 0)),
            episodeNumber=int(medusa_ep.get("episode", medusa_ep.get("number", 0))),
            title=medusa_ep.get("title", ""),
            overview=medusa_ep.get("overview", ""),
            monitored=True,
            hasFile=has_file
        )
        if has_file:
            location = medusa_ep.get("location", "")
            episode.episodeFile = {
                "id": ep_id, 
                "seriesId": series_id, 
                "size": cls.parse_size_to_bytes(medusa_ep.get("size", "0 B")),
                "path": location,
                "relativePath": location,
                "dateAdded": medusa_ep.get("date", "2026-01-01T00:00:00Z")
            }
        return episode
