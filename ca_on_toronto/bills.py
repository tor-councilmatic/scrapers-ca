from __future__ import unicode_literals

from collections import defaultdict
from pupa.scrape import Bill, VoteEvent
from utils import CanadianScraper

import datetime
import lxml.etree as etree
import traceback
import pytz
import re

# TODO: Create ticket to move lxmlize into pupa.scrape.Base

ACTION_CLASSIFICATION = {
    # Overall actions
    'Adopted': 'passage',
    'Adopted on Consent': 'passage',
    'Amended': 'amendment-amended',
    'Confirmed': 'passage',
    'Deferred': 'deferred',
    'Deferred Indefinitely': 'deferred',
    'Intro Failed': None,
    'No Action': None,
    'No Quorum': 'failure',
    'Not Adopted': None,
    'Noted/Filed': 'filing',
    'Received': None,
    'Referred': 'committee-referral',
    'Recinded': 'failure',
    'Withdrawn': 'withdrawal',
    'Without Recs': None,
    'Waive Referral': None,
    # Made this one up
    'Filed': 'filing',
    # Motion actions
    'Add New Business at Committee': 'introduction',
    'Adopt Item as Amended': 'passage',
    'Adopt Item': 'passage',
    'Adopt Minutes': 'passage',
    'Adopt Order Paper as Amended': 'passage',
    'Adopt Order Paper': 'passage',
    'Amend Item (Additional)': 'amendment-passage',
    'Amend Item': 'amendment-passage',
    'Amend Motion': None,
    'Amend the Order Paper': None,
    'Confirm Order': None,
    'Defer Item Indefinitely': 'deferred',
    'Defer Item': 'deferred',
    'End Debate': None,
    'Excuse Absentees': None,
    'Extend the Meeting': None,
    'Extend Speaking Time': None,
    'forward item Without Recommendations': None,
    'Introduce Motion without Notice': 'introduction',
    'Introduce Report': None,
    'Introduce and Pass Bills (Two-thirds)': None,
    'Introduce and Pass Confirmatory Bill': None,
    'Introduce and Pass General Bills': None,
    'Meet in Closed Session': None,
    'Re-open Item': None,
    'Receive Item': None,
    'Reconsider Item': None,
    'Reconsider Vote': None,
    'Reconvene in Public Session': None,
    'Refer Item': 'committee-referral',
    'Refer Motion': None,
    'Set Committee Rule': None,
    'Remove from Committee': None,
    'Waive Notice': None,
    'Waive Referral': None,
    'Withdraw a Motion': None,
    'Withdraw an Item': 'withdrawal',
}

VOTE_RESULT_MAP = {
    'Amended': 'pass',
    'Carried': 'pass',
    'Lost': 'fail',
    'Lost (tie)': 'fail',
    # No VoteEvents
    'Withdrawn': None,
    'Redundant': None,
    # See: http://app.toronto.ca/tmmis/viewAgendaItemHistory.do?item=2016.CD10.2#header1
    'Referred': None,
    # See: http://app.toronto.ca/tmmis/viewAgendaItemHistory.do?item=2016.SC13.20
    'Final': None,  # Lost quorum?
    'Out of Order': None,
}

MEETING_MAP_URL_TEMPLATE='http://app.toronto.ca/tmmis/getAddressList.do?function=getMeetingAddressList&meetingId={}'

agenda_item_re = re.compile(r'reference = "(?P<identifier>.+?)";')
address_re = re.compile(r'codeAddress\("\d", ".+?". "(?P<address>.+?)"')
motion_re = re.compile(r'(?:(?P<number>[0-9a-zA-Z]+) - )?Motion to (?P<action>.+?) (?:moved by (?:Councillor|(?:Deputy )?Mayor )?(?P<mover>.+?) )?\((?P<result>.{0,12})\)$')
agenda_item_title_re = re.compile('^(.+?)(?: - (?:by )?((?:Deputy )?Mayor|Councillor) (.+), seconded by ((?:Deputy )?Mayor|Councillor) (.+))?$')


class TorontoBillScraper(CanadianScraper):
    AGENDA_ITEM_SEARCH_URL = 'http://app.toronto.ca/tmmis/findAgendaItem.do?function=doSearch&itemsPerPage=1000&sortBy=reference&sortOrder=A'
    AGENDA_ITEM_URL_TEMPLATE = 'http://app.toronto.ca/tmmis/viewAgendaItemHistory.do?item={}'

    meeting_addresses_d = {}

    TIMEZONE = 'America/Toronto'
    date_format = '%B %d, %Y'

    start_date = datetime.datetime(2014, 12, 1)
    end_date = datetime.datetime.today() + datetime.timedelta(days=14)

    def scrape(self):
        for agenda_item in self.agendaItems(date_from=self.start_date, date_to=self.end_date):
            b = self.createBill(agenda_item)
            agenda_item_versions = self.agendaItemVersions(agenda_item)

            # Use most recent agenda item version for summary and fulltext
            recent_version = agenda_item_versions[-1]
            b.extras['full_text'] = recent_version['full_text']
            b.extras['wards'] = recent_version['wards']
            b.extras['type'] = recent_version['type'].lower()
            for title, content in recent_version['sections'].items():
                if 'Summary' in title:
                    date = self.toDate(recent_version['date'])
                    b.add_abstract(content, note='', date=date)

            for version in agenda_item_versions:
                # TODO: "Adopted by Consent" agenda items have no motions, so
                # will need to add these per-version
                action_date = self.toDate(version['date'])
                action_description = version['action']
                responsible_org = version['responsible_org']
                action_class = ACTION_CLASSIFICATION.get(version['action'])

                def is_recommendation(version):
                    return any('Recommendations' in s for s in version['sections'].keys())

                if responsible_org == 'City Council':
                    responsible_org = self.jurisdiction.name
                else:
                    if action_class == 'passage':
                        action_class = 'committee-passage'

                        if is_recommendation(version):
                            action_class = 'committee-passage-favorable'

                if version['action'] == 'Filed':
                    action_description = version['action']
                    action_class = ACTION_CLASSIFICATION.get(version['action'])
                    b.add_action(
                        action_description,
                        action_date,
                        organization={'name': responsible_org},
                        classification=action_class
                    )
                elif action_description and 'Motions' not in version['sections']:
                    # TODO: Why do some have no action_description?
                    # TODO: Do we fabricate a VoteEvent here?
                    # Use version-level action when no motions,
                    # ie. "Adopted by Consent"
                    b.add_action(
                        action_description,
                        action_date,
                        organization={'name': responsible_org},
                        classification=action_class
                    )


                for title, content in version['sections'].items():
                    if 'Motions' in title:
                        motions = content
                        for i, motion in enumerate(motions):
                            result = VOTE_RESULT_MAP[motion['result']]
                            if result:
                                v = self.createVoteEvent(motion, version)
                                count = i + 1
                                v.extras['order'] = count

                                # TODO: Add actions for failures
                                if result == 'pass':
                                    action_description = motion['action']
                                    action_class = ACTION_CLASSIFICATION[motion['action']]
                                    b.add_action(
                                        action_description,
                                        action_date,
                                        organization={'name': responsible_org},
                                        classification=action_class
                                    )

                                yield v

            yield b

    def createBill(self, agenda_item):
        title = agenda_item['Title'].replace('\n', ' ')
        title, primary_role, primary_sponsor, secondary_role, secondary_sponsor = re.match(agenda_item_title_re, title).groups()

        bill = {
            'identifier': agenda_item['Item No.'],
            'title': title,
            'legislative_session': agenda_item['session'],
            # TODO: Add agenda_item type to OCD
            'classification': 'bill',
            'from_organization': {'name': self.jurisdiction.name},
        }

        b = Bill(**bill)
        b.add_source(agenda_item['url'], note='web')

        meeting_id = self.recentMeetingId(b.identifier)
        addresses_d = self.addressesByMeetingId(meeting_id)

        if b.identifier in addresses_d:
            addresses = addresses_d[b.identifier]
            b.extras['locations'] = []
            for address in addresses:
                location = {'address': {'full_address': address}}
                b.extras['locations'].append(location)

        if primary_sponsor and secondary_sponsor:
            b.add_sponsorship(primary_sponsor, 'mover', 'person', True)
            b.add_sponsorship(secondary_sponsor, 'seconder', 'person', False)

        return b

    def createVoteEvent(self, motion, agenda_item_version):
        version = agenda_item_version
        date = self.toDate(version['date'])
        v = VoteEvent(
            motion_text=motion['title_text'],
            result=VOTE_RESULT_MAP[motion['result']],
            classification=motion['action'],
            start_date=date,
            legislative_session=version['session'],
        )

        if motion['mover']:
            v.extras['mover'] = motion['mover']
        if motion['body_text']:
            v.extras['body'] = motion['body_text']

        v.set_bill(version['bill_identifier'])
        v.add_source(version['url'])

        return v

    def agendaItems(self, date_from=None, date_to=None):
        for agenda_item_summary in self.searchAgendaItems(date_from, date_to):
            yield agenda_item_summary

    def searchAgendaItems(self, date_from=None, date_to=None):
        """
        Submit a search query on the agenda item search page, and return a list
        of result pages.
        """
        for session in self.jurisdiction.sessions():
            search_qs = '&termId={}'.format(session['termId'])

            if date_from and date_to:
                search_qs += '&fromDate={}&toDate={}'.format(date_from.strftime('%Y-%m-%d'), date_to.strftime('%Y-%m-%d'))

            page = self.lxmlize(self.AGENDA_ITEM_SEARCH_URL + search_qs)
            for agenda_item_summary in self.parseSearchResults(page):
                agenda_item_summary['session'] = session['term_name']
                yield agenda_item_summary

    def parseSearchResults(self, page):
        """Take a page of search results and return a sequence of data
        of tuples about the agenda_item, of the form

        TODO: Fix column names
        ('Document ID', 'Document URL', 'Type', 'Status', 'Introduction Date'
        'Passed Date', 'Main Sponsor', 'Title')
        """
        for agenda_item, headers, _ in self.parseDataTable(page):
            id_key = headers[1]

            agenda_item_id = agenda_item[id_key]['label']
            agenda_item[id_key] = agenda_item_id

            agenda_item_url = self.AGENDA_ITEM_URL_TEMPLATE.format(agenda_item_id)
            agenda_item['url'] = agenda_item_url

            yield agenda_item

    def agendaItemVersions(self, agenda_item):
        page = self.lxmlize(agenda_item['url'])
        versions = []
        for version in self.parseAgendaItemVersions(page):
            version['bill_identifier'] = agenda_item['Item No.']
            version['session'] = agenda_item['session']
            versions.append(version)

        return versions

    def parseAgendaItemVersions(self, page):
        script_text = page.xpath('//head/script[not(@src)]/text()')[0]
        index_qs = re.findall(r'if\(index == (\d)\){', script_text)
        function_qs = re.findall(r'var f = "(.*)";', script_text)
        agenda_item_id_qs = re.findall(r'agendaItemId:"(.*)"', script_text)
        url_template = 'http://app.toronto.ca/tmmis/viewAgendaItemDetails.do?function={}&agendaItemId={}'
        for i, func, id in sorted(zip(index_qs, function_qs, agenda_item_id_qs), key=lambda tup: tup[2]):
            # Decision document only rarely has motion breakdown.
            if func == 'getDecisionDocumentItemPreview':
                func = 'getMinutesItemPreview'

            agenda_item_version_url = url_template.format(func, id)
            version = self.agendaItemVersion(agenda_item_version_url)

            xpr = '//div[@id="header{}"]'.format(i)
            header = page.xpath(xpr)[0].text_content()
            header_re = re.compile('^(.+) consideration on (.+)$')
            org, date = re.match(header_re, header).groups()
            version.update({
                'responsible_org': org,
                'date': date,
                'url': agenda_item_version_url,
            })

            if 'Origin' in version['sections']:
                origin_text = version['sections']['Origin']
                filing_date_re = re.compile('\((.+?)\) .+')
                filing_date = re.match(filing_date_re, origin_text).group(1)
                filing_version = {}
                filing_version.update({
                    'date': filing_date,
                    'action': 'Filed',
                    'sections': {},
                    'responsible_org': org,
                })
                yield filing_version

            yield version

    def recentMeetingId(self, bill_identifier):
        url_template = 'http://app.toronto.ca/tmmis/viewAgendaItemHistory.do?item={}'
        url = url_template.format(bill_identifier)
        page = self.lxmlize(url)
        button = page.find(".//button[@id='btHome']")
        func_re = re.compile(r'goToProfile\((?P<meetingId>\d+)\);')
        meeting_id = re.match(func_re, button.attrib['onclick']).group('meetingId')

        return meeting_id

    def parseDataTable(self, table):
        """
        Legistar uses the same kind of data table in a number of
        places. This will return a list of dictionaries using the
        table headers as keys.
        """
        headers = table.xpath(".//th")
        rows = table.xpath(".//tr[@class='hoverOver']")

        keys = []
        for header in headers:
            text_content = header.text_content().replace('&nbsp;', ' ').strip()
            if text_content:
                keys.append(text_content)
            else:
                keys.append(header.xpath('.//input')[0].value)

        for row in rows:
            try:
                data = defaultdict(lambda: None)

                for key, field in zip(keys, row.xpath("./td")):
                    text_content = self._stringify(field)

                    if field.find('.//a') is not None:
                        address = self._get_link_address(field.find('.//a'))
                        if address:
                            value = {'label': text_content,
                                     'url': address}
                        else:
                            value = text_content
                    else:
                        value = text_content

                    data[key] = value

                yield data, keys, row

            except Exception as e:
                print('Problem parsing row:')
                print(etree.tostring(row))
                print(traceback.format_exc())
                raise e

    def _get_link_address(self, link):
        url = None
        if 'onclick' in link.attrib:
            onclick = link.attrib['onclick']
            if (onclick is not None and
                    onclick.startswith(("radopen('",
                                        "window.open",
                                        "OpenTelerikWindow"))):
                url = self.BASE_URL + onclick.split("'")[1]
        elif 'href' in link.attrib:
            url = link.attrib['href']

        return url

    def _stringify(self, field):
        for br in field.xpath("*//br"):
            br.tail = "\n" + br.tail if br.tail else "\n"
        for em in field.xpath("*//em"):
            if em.text:
                em.text = "--em--" + em.text + "--em--"
        return field.text_content().replace('&nbsp;', ' ').strip()

    def agendaItemVersion(self, agenda_item_version_url):
        """
        Details:
            * type
            * ward(s)

        Possible sections:
            * [ Board | Community Council | Committee ] Decision Advice and Other Information
            * Origin
            * [ Board | Community Council | Committee ] Recommendations
            * Summary
            * Financial Impact
            * Background Information [ (Board | Community Council | Committee | City Council) ] (parsed)
            * Speakers
            * Communications [ (Board | Community Council | Committee | City Council) ] (parsed)
            * Declared Interests [ (Board | Community Council | Committee | City Council) ]
            * Subsections? (recursive)
            * Motions (parsed)
                * Votes (optional)
            * Rulings (parsed) Ex: http://app.toronto.ca/tmmis/viewAgendaItemHistory.do?item=2016.EY12.29
                * Votes (optional on challenge)

        TODO: Investigate "Bills and By-law" [BL] code for bill context
        """
        page = self.lxmlize(agenda_item_version_url)

        version = {}
        version.update({
            'type': page.xpath("//table[@class='border'][1]//td[2]")[0].text_content().strip().lower(),
            'action': page.xpath("//table[@class='border'][1]//td[3]")[0].text_content().strip(),
        })

        wards = page.xpath("//table[@class='border'][1]//td[5]")[0].text_content().strip().lower()
        wards_re = re.compile('ward:(.*)')
        matches = re.match(wards_re, wards)
        if matches and matches.group(1) != 'all':
            wards = wards.split(', ')
        else:
            wards = []

        version.update({'wards': wards})

        header_elem = page.xpath("//table[@class='border']")[0]
        page.remove(header_elem)
        version['full_text'] = etree.tostring(page, pretty_print=True).decode()

        section_nodes = page.xpath("//table[@width=620 and .//font[@face='Arial' and @size=3] and .//tr[3]]")
        sections = {}
        for node in section_nodes:
            section_title = node.find('.//tr[1]/td//font/b').text_content().strip()
            section_content = node.find('.//tr[2]/td')
            sections[section_title] = section_content

        for title, content in sections.items():
            if 'Motions' in title:
                sections[title] = self.parseAgendaItemVersionMotions(sections[title])
            else:
                sections[title] = content.text_content()

        version.update({'sections': sections})

        return version

    def parseAgendaItemVersionMotions(self, content_etree):
        motions = []
        motion_titles = content_etree.xpath('.//i')
        # TODO: Body not always present, so figure out how to collect it
        motion_bodies = content_etree.xpath('.//div[@class="wep"]')  # NOQA
        for title in motion_titles:
            title_text = title.text_content().replace(u'\xa0', ' ').strip()
            if 'Motion to' not in title_text:
                # Outputting non-motion actions for inspection
                print(title_text)
                continue
            motion = re.match(motion_re, title_text).groupdict()
            motion['title_text'] = title_text
            motion['body_text'] = ''
            motions.append(motion)

        return motions

    def toTime(self, text):
        time = datetime.datetime.strptime(text, self.date_format)
        time = pytz.timezone(self.TIMEZONE).localize(time)
        return time

    def toDate(self, text):
        return self.toTime(text).date().isoformat()

    # TODO: Figure out how to get addresses back into bills
    def addressesByMeetingId(self, meeting_id):
        if self.meeting_addresses_d.get(meeting_id):
            return self.meeting_addresses_d[meeting_id]

        meeting_map_url = MEETING_MAP_URL_TEMPLATE.format(meeting_id)
        page = self.lxmlize(meeting_map_url)
        script_text = page.xpath('//script[not(@src)]')[0].text_content()

        agenda_item_ids = re.findall(agenda_item_re, script_text)
        addresses = re.findall(address_re, script_text)

        item_addresses = {}
        for id, address in zip(agenda_item_ids, addresses):
            if not item_addresses.get(id):
                item_addresses[id] = [address]
            else:
                item_addresses[id].append(address)

        self.meeting_addresses_d[meeting_id] = item_addresses

        return item_addresses
