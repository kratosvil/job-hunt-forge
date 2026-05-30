from src.scrapers.linkedin_scraper import LinkedInScraper


class EasyApplyScraper(LinkedInScraper):
    """
    Scrapes LinkedIn Easy Apply jobs by adding f_LF=f_AL to the search URL.
    Inherits all extraction and anti-bot logic from LinkedInScraper.
    Output dicts include source='linkedin_easy_apply' for DB distinction.
    """

    _SEARCH_URL: str = (
        "https://www.linkedin.com/jobs/search/"
        "?keywords={query}&location={location}&f_WT=2&f_TPR=r172800&f_LF=f_AL"
    )

    async def scrape(self):
        async for job in super().scrape():
            job["source"] = "linkedin_easy_apply"
            yield job
