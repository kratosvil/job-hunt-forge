from src.scrapers.linkedin_scraper import LinkedInScraper


class EasyApplyScraper(LinkedInScraper):
    """
    Scrapes LinkedIn Easy Apply jobs by adding f_LF=f_AL to the search URL.
    Accepts optional locations list to restrict search to a specific region.
    Output dicts include source='linkedin_easy_apply' for DB distinction.
    """

    _SEARCH_URL: str = (
        "https://www.linkedin.com/jobs/search/"
        "?keywords={query}&location={location}&f_WT=2&f_TPR=r172800&f_LF=f_AL"
    )

    def __init__(self, locations: list[str] | None = None, roles: list[str] | None = None) -> None:
        super().__init__(locations=locations, roles=roles)

    async def scrape(self):
        async for job in super().scrape():
            job["source"] = "linkedin_easy_apply"
            yield job
