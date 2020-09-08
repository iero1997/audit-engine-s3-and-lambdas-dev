import datetime
import glob
import os

from dominate import document
from dominate.tags import a, div, h1, h3, h4, h5, h6, link, p, script, b, img

from models.Style import Style

from utilities import utils
from utilities.config_d import config_dict


class StyleSummary(Style):

    @staticmethod
    def get_style_images(code: str) -> list:
        """Returns a list of images file paths related to the Style.
        :param code: Code of the Style instance.
        """
        return [os.path.realpath(image_path) for image_path
                in glob.glob(f"{config_dict['RESOUCES_PATH']}{config_dict['STYLES_PATHFRAG']}{code}(*).png")]

    @staticmethod
    def get_ballot_images_path(ballot_id: str, code: str) -> list:
        """Returns a list of ballot images from which Style was built.
        :param ballot_id: 'Ballot' instance id.
        :param code: Style code.
        """
        return [os.path.realpath(image_path) for image_path
                in glob.glob(f"{config_dict['RESOUCES_PATH']}{config_dict['STYLES_PATHFRAG']}{code}/{ballot_id}-*.jpg")]

    @staticmethod
    def get_details_row(title: str, text) -> div:
        """Returns 'div' element with row class, containing 'b' tag
        as title and 'p' tag as the text.
        :param title: Text that will display in 'b' tag on the left side.
        :param text: Text that will display in 'p' tag on the right side.
        """
        return div(
            b(f'{title.title()}:', cls='mx-1'),
            p(text, cls='mb-0'),
            cls='row'
        )

    @staticmethod
    def get_option_details(option) -> div:
        """Return 'div' element with info about 'option' instance.
        :param option: Option instance from which 'div' tag should
            be build.
        """
        coordinates = f'{option.coordinates[0]}px, {option.coordinates[1]}px'
        option_attributes = [
            ('name from OCR', option.name),
            ('name from fuzzy matching', option.fuzzy_name),
            ('Position (left, top)', coordinates),
        ]
        title = option.fuzzy_name or option.name
        option_container = div(id=title, cls='ml-1 mb-2')
        option_container.add(h6(title, cls='ml-2 mb-0'))
        option_div = div(cls='col pl-4')
        for option_key, option_value in option_attributes:
            option_div.add(StyleSummary.get_details_row(option_key, str(option_value)))
        option_container.add(option_div)

        return option_container

    @staticmethod
    def get_contest_details(contest) -> div:
        """Return 'div' element with info about 'contest' instance
        and it's options.
        :param contest: Contest instance from which 'div' tag should
            be build.
        """
        contest_attributes = [
            ('name from OCR', contest.name),
            ('name from fuzzy matching', contest.fuzzy_name),
            ('name from alias', contest.alias_name),
            ('referendum header', contest.additional_text),
            ('question', contest.question),
            ('Yes/No contest', contest.bipolar),
            ('on page', contest.page + 1),
            ('vote for', contest.vote_for),
        ]
        title = contest.alias_name or contest.fuzzy_name or contest.name
        contest_container = div(id=title, cls='py-1')
        contest_container.add(h4(title, cls='mt-2'))
        contest_div = div(cls='col pl-4')
        for contest_key, contest_value in contest_attributes:
            contest_div.add(StyleSummary.get_details_row(contest_key, str(contest_value)))
        options_div = div()
        contest_div.add(h5('Options', cls='mt-2'))
        for option in reversed(contest.options):
            options_div.add(StyleSummary.get_option_details(option))
        contest_div.add(options_div)
        contest_container.add(contest_div)

        return contest_container

    @staticmethod
    def get_ballot_images_div(ballot_id: str, images: list) -> div:
        """Return 'div' element with ballot id text and links to the
        ballot images.
        :param ballot_id: 'Ballot' instance id.
        :param images: List of images of single ballot from which style
            was built.
        """
        images_container = div(cls='row mx-1')
        images_container.add(div(f'{ballot_id}('))
        for index, image in enumerate(images):
            if index == len(images) - 1:
                images_container.add(a(index + 1, href=image))
            else:
                images_container.add(a(f'{index + 1},', href=image, cls="mr-1"))
        images_container.add(div(')'))

        return images_container

    @staticmethod
    def get_html_string(style: Style) -> document:
        """Creates a HTML string for generating the summary file."""
        utc_time = datetime.datetime.utcfromtimestamp(style.timestamp)
        style_attributes = [
            ('code', style.code),
            ('number', style.number),
            ('precinct', style.precinct),
            ('built at', f'{utc_time.strftime("%Y-%m-%d %H:%M:%S")}'),
            ('built from number of ballots', style.build_from_count),
        ]

        script_abs_path = os.path.abspath('assets/copy_to_clipboard.js')
        version = utils.show_version()
        doc = document(title='Audit Engine version: ' + version)
        with doc.head:
            link(
                rel='stylesheet',
                href='https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/css/bootstrap.min.css',
                integrity="sha384-ggOyR0iXCbMQv3Xipma34MD+dH/1fQ784/j6cY/iJTQUOhcWr7x9JvoRxT2MZw1T",
                crossorigin="anonymous",
            )
            script(type='text/javascript', src=script_abs_path)

        with doc:
            with div(cls='container'):
                with div(cls='jumbotron'):
                    h1('Audit Engine: {version} - style summary'.format(version=version))
                    build_time = datetime.datetime.now(datetime.timezone.utc)
                    p(f'Summary built at: {build_time.strftime("%Y-%m-%d %H:%M:%S")}', cls='lead')
                with div(cls='col pl-3 mt-1') as style_details_column:
                    for style_key, style_value in style_attributes:
                        style_details_column.add(StyleSummary.get_details_row(style_key,
                                                                              str(style_value)))
                h3('Contests', cls='mb-0 mt-1')
                with div(cls='col pl-3') as contest_details_column:
                    for style_contest in style.contests:
                        contest_details_column.add(StyleSummary.get_contest_details(style_contest))
                h3('Built from ballots', cls='mb-3 mt-1')
                with div(cls='col pl-3'):
                    with div(cls='row flex-wrap') as images_column:
                        for ballot_id in style.build_from_ballots:
                            images = StyleSummary.get_ballot_images_path(ballot_id, style.code)
                            images_column.add(StyleSummary.get_ballot_images_div(ballot_id, images))
                h3('Style weighted images', cls='mb-3 mt-1')
                with div():
                    for image in StyleSummary.get_style_images(style.code):
                        a(img(src=os.path.basename(image), cls='img-thumbnail',
                              alt='File not found'), href=image)
        return doc

    @staticmethod
    def get_html_doc_string(style: Style):
        """Returns an HTML file with the summary of the 'Style'.
        :param style: Style instance from which summary should be build.
        """

        return StyleSummary.get_html_string(style)
