from pupa.scrape import Jurisdiction

# from .events import TorontoEventScraper
from .people import SummersidePersonScraper
# from .votes import TorontoVoteScraper
from utils import lxmlize

import re

class Summerside(Jurisdiction):
  jurisdiction_id = 'ca-pe-summerside'

  def get_metadata(self):
    return {
      'name': 'Summerside',
      'legislature_name': 'Summerside City Council',
      'legislature_url': 'http://city.summerside.pe.ca/mayor-and-council/pages/2012/2/councillors/',
      'terms': [{
        'name': '2010-2014',
        'sessions': ['2010-2014'],
        'start_year': 2010,
        'end_year': 2014,
      }],
      'provides': ['people'],
      'parties': [],
      'session_details': {
        '2010-2014': {
          '_scraped_name': '2010-2014',
        }
      },
      'feature_flags': [],
      # '_ignored_scraped_sessions': ['2006-2010'],
    }

  def get_scraper(self, term, session, scraper_type):
    # if scraper_type == 'events':
    #     return TorontoEventScraper
    if scraper_type == 'people':
        return SummersidePersonScraper
    # if scraper_type == 'votes':
    #     return TorontoVoteScraper

  def scrape_session_list(self):
    return ['2010-2014']
    