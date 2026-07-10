from typing import Dict, Any
from .models import SonarrSeries, SonarrEpisode, SonarrSystemStatus

class MedusaTranslator:
    @staticmethod
    def extract_clean_integer_id(show_node: Dict[str, Any]) -> int:
        raw_id = show_node.get("id")
        if isinstance(raw_id, dict):
            raw_id = raw_id.get("medusa") or raw_id.get("tvdb") or raw_id.get("tmdb")
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

    @classmethod
    def to_sonarr_series(cls, medusa_show: Dict[str, Any]) -> SonarrSeries:
        ids = medusa_show.get("ids", {})
        medusa_id = cls.extract_clean_integer_id(medusa_show)
        title = medusa_show.get("title", f"Series {medusa_id}")
        
        raw_path = medusa_show.get("path", "")
        if not raw_path or raw_path == "/tv":
            safe_folder = title.replace("/", "_").replace("\\", "_")
            path = f"/tv/{safe_folder}"
        else:
            path = str(raw_path)

        return SonarrSeries(
            id=medusa_id,
            title=title,
            tvdbId=int(ids.get("tvdb") or 0),
            tmdbId=int(ids.get("tmdb") or 0),
            imdbId=ids.get("imdb") or "",
            sortTitle=title.lower(),
            status="continuing" if medusa_show.get("status") == "continuing" else "ended",
            overview=medusa_show.get("overview", ""),
            year=cls.extract_clean_year(medusa_show),
            path=path,
            monitored=not medusa_show.get("paused", False)
        )

    @classmethod
    def to_sonarr_episode(cls, medusa_ep: Dict[str, Any], series_id: int) -> SonarrEpisode:
        status = str(medusa_ep.get("status", "")).lower()
        has_file = status in ["downloaded", "snatched"]
        ep_id = int(medusa_ep.get("id", 0))

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
