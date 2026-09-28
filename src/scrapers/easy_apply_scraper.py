from src.scrapers.linkedin_scraper import LinkedInScraper


class EasyApplyScraper(LinkedInScraper):
    """
    Scrapes LinkedIn Easy Apply jobs by adding f_LF=f_AL to the search URL.
    Accepts optional locations list to restrict search to a specific region.
    work_type: "2"=Remote, "3"=Hybrid, "1"=On-site, "2,3"=Remote+Hybrid
    Output dicts include source='linkedin_easy_apply' for DB distinction.
    """

    def __init__(
        self,
        locations: list[str] | None = None,
        roles: list[str] | None = None,
        work_type: str = "2",
    ) -> None:
        super().__init__(locations=locations, roles=roles)
        self._SEARCH_URL = (
            "https://www.linkedin.com/jobs/search/"
            f"?keywords={{query}}&location={{location}}&f_WT={work_type}&f_TPR=r172800&f_LF=f_AL"
        )

    async def scrape(self):
        async for job in super().scrape():
            job["source"] = "linkedin_easy_apply"
            yield job
