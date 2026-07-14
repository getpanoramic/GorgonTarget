from typing import Dict, Any
import sys
from .models import SonarrSeries, SonarrEpisode, SonarrSystemStatus

class MedusaTranslator:
    @staticmethod
    def extract_clean_integer_id(show_node: Dict[str, Any]) -> int:
        raw_id = show_node.get("id")
        
        # If it's a dict, try extracting a numeric ID dynamically
        if isinstance(raw_id, dict):
            # Try to find the first numeric value in the dict
            for key, val in raw_id.items():
                if key != 'slug': # 'slug' is not a numeric id
                    try:
                        return int(val)
                    except (ValueError, TypeError):
                        continue
            
            # If no numeric ID found, hash the slug to create a deterministic integer ID
            slug = raw_id.get("slug")
            if slug:
                return hash(slug) % 1000000 # Use a safe modulo to keep it manageable
            return 0
            
        try:
            return int(raw_id)
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
            val, unit = size_str.split()
            val = float(val)
            multipliers = {"GB": 10**9, "TB": 10**12, "MB": 10**6}
            return int(val * multipliers.get(unit.upper(), 1))
        except (ValueError, AttributeError):
            return 0

    @classmethod
    def to_sonarr_series(cls, medusa_show: Dict[str, Any]) -> SonarrSeries:
        ids = medusa_show.get("ids", {})
        medusa_id = cls.extract_clean_integer_id(medusa_show)
        title = medusa_show.get("title", f"Series {medusa_id}")

        # Aggregate statistics
        seasons_data = medusa_show.get("seasons", [])
        total_episodes = sum(int(s.get("episodes", 0)) for s in seasons_data)
        # Assuming all episodes are 'wanted' or 'snatched' or 'downloaded' for percentage calculation 
        # as a proxy since Medusa doesn't provide fine-grained per-season status easily
        downloaded_episodes = sum(int(s.get("episodes", 0)) for s in seasons_data) # Placeholder logic for 'downloaded'
        percent_downloaded = (downloaded_episodes / total_episodes * 100) if total_episodes > 0 else 100

        seasons = []
        for s in seasons_data:
            ep_count = int(s.get("episodes", 0))
            seasons.append({
                "seasonNumber": int(s.get("season", 0)),
                "monitored": True,
                "statistics": {
                    "episodeFileCount": ep_count,
                    "episodeCount": ep_count,
                    "totalEpisodeCount": ep_count,
                    "sizeOnDisk": 0,
                    "percentOfEpisodes": 100.0
                }
            })


        return SonarrSeries(
            id=medusa_id,
            title=title,
            tvdbId=int(ids.get("tvdb") or 0),
            tmdbId=int(ids.get("tmdb") or 0),
            imdbId=ids.get("imdb") or "",
            sortTitle=title.lower(),
            status="continuing" if medusa_show.get("status", "").lower() == "continuing" else "ended",
            overview=medusa_show.get("plot", medusa_show.get("overview", "")),
            year=cls.extract_clean_year(medusa_show),
            path=medusa_show.get("config", {}).get("location", f"/tv/{title}"),
            monitored=not medusa_show.get("paused", False),
            images=[
                {"coverType": "poster", "url": f"/v3/mediacover/{medusa_id}/poster.jpg"},
                {"coverType": "banner", "url": f"/v3/mediacover/{medusa_id}/banner.jpg"},
                {"coverType": "fanart", "url": f"/v3/mediacover/{medusa_id}/fanart.jpg"}
            ],
            seasons=seasons,
            statistics={
                "episodeFileCount": total_episodes,
                "episodeCount": total_episodes,
                "totalEpisodeCount": total_episodes,
                "sizeOnDisk": 0,
                "percentOfEpisodes": percent_downloaded
            }
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
            episode.episodeFile = {"id": ep_id, "seriesId": series_id, "size": 0}
        return episode
