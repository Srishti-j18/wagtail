import json
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils.html import escape
from django.utils.http import urlencode

from wagtail.admin.views.chooser import can_choose_page
from wagtail.models import Locale, Page
from wagtail.test.testapp.models import (
    EventIndex,
    EventPage,
    SimplePage,
    SingleEventPage,
)
from wagtail.test.utils import WagtailTestUtils


class TestChooserBrowse(WagtailTestUtils, TestCase):
    def setUp(self):
        self.root_page = Page.objects.get(id=2)

        # Add child page
        self.child_page = SimplePage(title="foobarbaz", content="hello")
        self.root_page.add_child(instance=self.child_page)

        self.login()

    def get(self, params={}):
        return self.client.get(reverse("wagtailadmin_choose_page"), params)

    def test_simple(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/browse.html")

    def test_construct_queryset_hook(self):
        page = SimplePage(title="Test shown", content="hello")
        Page.get_first_root_node().add_child(instance=page)

        page_not_shown = SimplePage(title="Test not shown", content="hello")
        Page.get_first_root_node().add_child(instance=page_not_shown)

        def filter_pages(pages, request):
            return pages.filter(id=page.id)

        with self.register_hook("construct_page_chooser_queryset", filter_pages):
            response = self.get()
        # 'results' in the template context consists of the parent page followed by the queryset
        self.assertEqual(len(response.context["table"].data), 2)
        self.assertEqual(response.context["table"].data[1].specific, page)

    @override_settings(USE_THOUSAND_SEPARATOR=True)
    def test_multiple_chooser_view(self):
        self.page = Page.objects.get(id=1)

        self.child_page = SimplePage(
            title="test_child_page", content="test content", pk=10022
        )
        self.page.add_child(instance=self.child_page)

        response = self.get({"multiple": "1"})

        checkbox_value = str(self.child_page.id)
        decoded_content = response.content.decode()
        response_json = json.loads(decoded_content)
        self.assertEqual(response_json["step"], "browse")
        response_html = response_json["html"]

        self.assertIn(f'value="{checkbox_value}"', response_html)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/browse.html")

        soup = self.get_soup(response_html)
        search_url = soup.find("form", role="search")["action"]
        search_query_params = parse_qs(urlsplit(search_url).query)
        self.assertEqual(search_query_params["multiple"], ["1"])

    @override_settings(USE_THOUSAND_SEPARATOR=False)
    def test_multiple_chooser_view_without_thousand_separator(self):
        self.page = Page.objects.get(id=1)

        self.child_page = SimplePage(
            title="test_child_page", content="test content", pk=10050
        )
        self.page.add_child(instance=self.child_page)

        response = self.get({"multiple": "1"})

        checkbox_value = str(self.child_page.id)
        decoded_content = response.content.decode()

        self.assertIn(f'value=\\"{checkbox_value}\\"', decoded_content)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/browse.html")


class TestCanChooseRootFlag(WagtailTestUtils, TestCase):
    def setUp(self):
        self.login()

    def get(self, params={}):
        return self.client.get(reverse("wagtailadmin_choose_page"), params)

    def test_cannot_choose_root_by_default(self):
        response = self.get()
        self.assertNotContains(response, "/admin/pages/1/edit/")

    def test_can_choose_root(self):
        response = self.get({"can_choose_root": "true"})
        self.assertContains(response, "/admin/pages/1/edit/")


class TestChooserBrowseChild(WagtailTestUtils, TestCase):
    def setUp(self):
        self.root_page = Page.objects.get(id=2)

        # Add child page
        self.child_page = SimplePage(title="foobarbaz", content="hello")
        self.root_page.add_child(instance=self.child_page)

        self.login()

    def get(self, params={}):
        return self.client.get(
            reverse("wagtailadmin_choose_page_child", args=(self.root_page.id,)), params
        )

    def get_invalid(self, params={}):
        return self.client.get(
            reverse("wagtailadmin_choose_page_child", args=(9999999,)), params
        )

    def test_simple(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/browse.html")

    def test_get_invalid(self):
        self.assertEqual(self.get_invalid().status_code, 404)

    def test_with_page_type(self):
        # Add a page that is not a SimplePage
        event_page = EventPage(
            title="event",
            location="the moon",
            audience="public",
            cost="free",
            date_from="2001-01-01",
        )
        self.root_page.add_child(instance=event_page)

        # Add a page with a child page
        event_index_page = EventIndex(
            title="events",
        )
        self.root_page.add_child(instance=event_index_page)
        event_index_page.add_child(
            instance=EventPage(
                title="other event",
                location="the moon",
                audience="public",
                cost="free",
                date_from="2001-01-01",
            )
        )

        # Send request
        response = self.get({"page_type": "tests.simplepage"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/browse.html")
        self.assertEqual(response.context["page_type_string"], "tests.simplepage")

        pages = {page.id: page for page in response.context["table"].data}

        # Child page is a simple page directly underneath root
        # so should appear in the list
        self.assertIn(self.child_page.id, pages)
        self.assertTrue(pages[self.child_page.id].can_choose)
        self.assertFalse(pages[self.child_page.id].can_descend)

        # Event page is not a simple page and is not descendable either
        # so should not appear in the list
        self.assertNotIn(event_page.id, pages)

        # Event index page is not a simple page but has a child and is therefore descendable
        # so should appear in the list
        self.assertIn(event_index_page.id, pages)
        self.assertFalse(pages[event_index_page.id].can_choose)
        self.assertTrue(pages[event_index_page.id].can_descend)

    def test_with_url_extended_page_type(self):
        # Add a page that overrides the url path
        single_event_page = SingleEventPage(
            title="foo",
            location="the moon",
            audience="public",
            cost="free",
            date_from="2001-01-01",
        )
        self.root_page.add_child(instance=single_event_page)

        # Send request
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/browse.html")

        page_urls = [page.url for page in response.context["table"].data]

        self.assertIn("/foo/pointless-suffix/", page_urls)

    def test_with_blank_page_type(self):
        # a blank page_type parameter should be equivalent to an absent parameter
        # (or an explicit page_type of wagtailcore.page)
        response = self.get({"page_type": ""})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/browse.html")

    def test_with_multiple_page_types(self):
        # Add a page that is not a SimplePage
        event_page = EventPage(
            title="event",
            location="the moon",
            audience="public",
            cost="free",
            date_from="2001-01-01",
        )
        self.root_page.add_child(instance=event_page)

        # Send request
        response = self.get({"page_type": "tests.simplepage,tests.eventpage"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/browse.html")
        self.assertEqual(
            response.context["page_type_string"], "tests.simplepage,tests.eventpage"
        )

        pages = {page.id: page for page in response.context["table"].data}

        # Simple page in results, as before
        self.assertIn(self.child_page.id, pages)
        self.assertTrue(pages[self.child_page.id].can_choose)

        # Event page should now also be choosable
        self.assertIn(event_page.id, pages)
        self.assertTrue(pages[self.child_page.id].can_choose)

    def test_with_multiple_specific_page_types_display_warning(self):
        # Add a page that is not a SimplePage
        event_page = EventPage(
            title="event",
            location="the moon",
            audience="public",
            cost="free",
            date_from="2001-01-01",
        )
        self.root_page.add_child(instance=event_page)

        # Send request
        response = self.get({"page_type": "tests.simplepage,tests.eventpage"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["page_type_names"], ["Simple page", "Event page"]
        )

        html = response.json().get("html")
        expected = """
            <p class="help-block help-warning">
                <svg class="icon icon-warning icon" aria-hidden="true"><use href="#icon-warning"></use></svg>
                Only the following page types may be chosen for this field: Simple page, Event page. Search results will exclude pages of other types.
            </p>
        """

        self.assertTagInHTML(expected, html)

    def test_with_unknown_page_type(self):
        response = self.get({"page_type": "foo.bar"})
        self.assertEqual(response.status_code, 404)

    def test_with_bad_page_type(self):
        response = self.get({"page_type": "wagtailcore.site"})
        self.assertEqual(response.status_code, 404)

    def test_with_invalid_page_type(self):
        response = self.get({"page_type": "foo"})
        self.assertEqual(response.status_code, 404)

    def test_with_admin_display_title(self):
        # Check the display of the child page title when it's a child
        response = self.get({"page_type": "wagtailcore.Page"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/browse.html")

        html = response.json().get("html")
        self.assertInHTML("foobarbaz (simple page)", html)

        # The data-title attribute should not use the custom admin display title,
        # because JS code that uses that attribute (e.g. the rich text editor)
        # should use the real page title.
        self.assertIn('data-title="foobarbaz"', html)

    def test_parent_with_admin_display_title(self):
        # Add another child under child_page so it renders a chooser list
        leaf_page = SimplePage(title="quux", content="goodbye")
        self.child_page.add_child(instance=leaf_page)

        # Use the child page as the chooser parent
        response = self.client.get(
            reverse("wagtailadmin_choose_page_child", args=(self.child_page.id,)),
            params={"page_type": "wagtailcore.Page"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/browse.html")

        self.assertInHTML("foobarbaz (simple page)", response.json().get("html"))
        self.assertInHTML("quux (simple page)", response.json().get("html"))

    def test_admin_display_title_breadcrumb(self):
        # Add another child under child_page so we get breadcrumbs
        leaf_page = SimplePage(title="quux", content="goodbye")
        self.child_page.add_child(instance=leaf_page)

        # Use the leaf page as the chooser parent, so child is in the breadcrumbs
        response = self.client.get(
            reverse("wagtailadmin_choose_page_child", args=(leaf_page.id,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/browse.html")

        # Look for a link element in the breadcrumbs with the admin title
        expected = """
            <li class="w-h-full w-flex w-items-center w-overflow-hidden w-transition w-duration-300 w-whitespace-nowrap w-flex-shrink-0 w-font-bold " data-w-breadcrumbs-target="content">
                <a class="w-flex w-items-center w-text-text-label w-pr-0.5 w-text-14 w-no-underline w-outline-offset-inside w-border-b w-border-b-2 w-border-transparent w-box-content hover:w-border-current hover:w-text-text-label" href="/admin/choose-page/{page_id}/?">
                    {page_title}
                </a>
                <svg class="icon icon-arrow-right w-w-4 w-h-4 w-ml-3" aria-hidden="true">
                   <use href="#icon-arrow-right"></use>
                </svg>
            </li>
        """.format(
            page_id=self.child_page.id,
            page_title="foobarbaz (simple page)",
        )
        self.assertTagInHTML(expected, response.json().get("html"))

    def setup_pagination_test_data(self):
        # Create lots of pages
        for i in range(100):
            new_page = SimplePage(
                title="foobarbaz",
                slug="foobarbaz-%d" % i,
                content="hello",
            )
            self.root_page.add_child(instance=new_page)

    def test_pagination_basic(self):
        self.setup_pagination_test_data()

        response = self.get()
        self.assertEqual(response.context["pagination_page"].paginator.num_pages, 5)
        self.assertEqual(response.context["pagination_page"].number, 1)

    def test_pagination_another_page(self):
        self.setup_pagination_test_data()

        response = self.get({"p": 2})
        self.assertEqual(response.context["pagination_page"].number, 2)

    def test_pagination_invalid_page(self):
        self.setup_pagination_test_data()

        response = self.get({"p": "foo"})
        self.assertEqual(response.status_code, 404)

    def test_pagination_out_of_range_page(self):
        self.setup_pagination_test_data()

        response = self.get({"p": 100})
        self.assertEqual(response.status_code, 404)


class TestChooserSearch(WagtailTestUtils, TransactionTestCase):
    fixtures = ["test_empty.json"]

    def setUp(self):
        self.root_page = Page.objects.get(id=2)

        # Add child page
        self.child_page = SimplePage(title="foobarbaz", content="hello")
        self.root_page.add_child(instance=self.child_page)

        self.login()

    def get(self, params=None):
        return self.client.get(reverse("wagtailadmin_choose_page_search"), params or {})

    def test_simple(self):
        response = self.get({"q": "foobarbaz", "allow_external_link": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/_search_results.html")
        self.assertContains(response, "There is 1 match")
        self.assertContains(response, "foobarbaz")

        # parent page link should preserve the allow_external_link parameter
        expected_url = (
            reverse("wagtailadmin_choose_page_child", args=[self.root_page.id])
            + "?allow_external_link=true"
        )
        self.assertContains(
            response,
            f'<a href="{expected_url}" class="navigate-parent">{self.root_page.title}</a>',
        )

    def test_partial_match(self):
        response = self.get({"q": "fooba"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/_search_results.html")
        self.assertContains(response, "There is 1 match")
        self.assertContains(response, "foobarbaz")

    def test_result_uses_custom_admin_display_title(self):
        single_event_page = SingleEventPage(
            title="Lunar event",
            location="the moon",
            audience="public",
            cost="free",
            date_from="2001-01-01",
        )
        self.root_page.add_child(instance=single_event_page)

        response = self.get({"q": "lunar"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/_search_results.html")
        self.assertContains(response, "Lunar event (single event)")

    def test_search_no_results(self):
        response = self.get({"q": "quux"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "There are 0 matches")

    def test_with_page_type(self):
        # Add a page that is not a SimplePage
        event_page = EventPage(
            title="foobarbaz again",
            location="the moon",
            audience="public",
            cost="free",
            date_from="2001-01-01",
        )
        self.root_page.add_child(instance=event_page)

        # Send request
        response = self.get({"q": "foobarbaz", "page_type": "tests.simplepage"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/_search_results.html")
        self.assertEqual(response.context["page_type_string"], "tests.simplepage")

        pages = {page.id: page for page in response.context["pages"]}

        self.assertIn(self.child_page.id, pages)

        # Not a simple page
        self.assertNotIn(event_page.id, pages)

    def test_with_blank_page_type(self):
        # a blank page_type parameter should be equivalent to an absent parameter
        # (or an explicit page_type of wagtailcore.page)
        response = self.get({"q": "foobarbaz", "page_type": ""})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/_search_results.html")
        self.assertContains(response, "There is 1 match")
        self.assertContains(response, "foobarbaz")

    def test_with_multiple_page_types(self):
        # Add a page that is not a SimplePage
        event_page = EventPage(
            title="foobarbaz again",
            location="the moon",
            audience="public",
            cost="free",
            date_from="2001-01-01",
        )
        self.root_page.add_child(instance=event_page)

        # Send request
        response = self.get(
            {"q": "foobarbaz", "page_type": "tests.simplepage,tests.eventpage"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/_search_results.html")
        self.assertEqual(
            response.context["page_type_string"], "tests.simplepage,tests.eventpage"
        )

        pages = {page.id: page for page in response.context["pages"]}

        # Simple page in results, as before
        self.assertIn(self.child_page.id, pages)

        # Event page should now also be choosable
        self.assertIn(event_page.id, pages)

    def test_with_unknown_page_type(self):
        response = self.get({"page_type": "foo.bar"})
        self.assertEqual(response.status_code, 404)

    def test_with_bad_page_type(self):
        response = self.get({"page_type": "wagtailcore.site"})
        self.assertEqual(response.status_code, 404)

    def test_with_invalid_page_type(self):
        response = self.get({"page_type": "foo"})
        self.assertEqual(response.status_code, 404)

    def test_construct_queryset_hook(self):
        page = SimplePage(title="Test shown", content="hello")
        self.root_page.add_child(instance=page)

        page_not_shown = SimplePage(title="Test not shown", content="hello")
        self.root_page.add_child(instance=page_not_shown)

        def filter_pages(pages, request):
            return pages.filter(id=page.id)

        with self.register_hook("construct_page_chooser_queryset", filter_pages):
            response = self.get({"q": "Test"})
        self.assertEqual(len(response.context["pages"]), 1)
        self.assertEqual(response.context["pages"][0].specific, page)


class TestAutomaticRootPageDetection(WagtailTestUtils, TestCase):
    def setUp(self):
        self.tree_root = Page.objects.get(id=1)
        self.home_page = Page.objects.get(id=2)

        self.about_page = self.home_page.add_child(
            instance=SimplePage(title="About", content="About Foo")
        )
        self.contact_page = self.about_page.add_child(
            instance=SimplePage(title="Contact", content="Content Foo")
        )
        self.people_page = self.about_page.add_child(
            instance=SimplePage(title="People", content="The people of Foo")
        )

        self.event_index = self.make_event_section("Events")

        self.login()

    def make_event_section(self, name):
        event_index = self.home_page.add_child(instance=EventIndex(title=name))
        event_index.add_child(
            instance=EventPage(
                title="First Event",
                location="Bar",
                audience="public",
                cost="free",
                date_from="2001-01-01",
            )
        )
        event_index.add_child(
            instance=EventPage(
                title="Second Event",
                location="Baz",
                audience="public",
                cost="free",
                date_from="2001-01-01",
            )
        )
        return event_index

    def get_best_root(self, params={}):
        response = self.client.get(reverse("wagtailadmin_choose_page"), params)
        return response.context["parent_page"].specific

    def test_no_type_filter(self):
        self.assertEqual(self.get_best_root(), self.tree_root)

    def test_type_page(self):
        self.assertEqual(
            self.get_best_root({"page_type": "wagtailcore.Page"}), self.tree_root
        )

    def test_type_eventpage(self):
        """
        The chooser should start at the EventIndex that holds all the
        EventPages.
        """
        self.assertEqual(
            self.get_best_root({"page_type": "tests.EventPage"}), self.event_index
        )

    def test_type_eventpage_two_indexes(self):
        """
        The chooser should start at the home page, as there are two
        EventIndexes with EventPages.
        """
        self.make_event_section("Other events")
        self.assertEqual(
            self.get_best_root({"page_type": "tests.EventPage"}), self.home_page
        )

    def test_type_simple_page(self):
        """
        The chooser should start at the home page, as all SimplePages are
        directly under it
        """
        self.assertEqual(
            self.get_best_root({"page_type": "tests.BusinessIndex"}), self.tree_root
        )

    def test_type_missing(self):
        """
        The chooser should start at the root, as there are no BusinessIndexes
        """
        self.assertEqual(
            self.get_best_root({"page_type": "tests.BusinessIndex"}), self.tree_root
        )


class TestChooserExternalLink(WagtailTestUtils, TestCase):
    def setUp(self):
        self.login()
        self.internal_page = SimplePage(title="About", content="About Foo")
        Page.objects.get(pk=2).add_child(instance=self.internal_page)

    def get(self, params={}):
        return self.client.get(
            reverse("wagtailadmin_choose_page_external_link"), params
        )

    def post(self, post_data={}, url_params={}):
        url = reverse("wagtailadmin_choose_page_external_link")
        if url_params:
            url += "?" + urlencode(url_params)
        return self.client.post(url, post_data)

    def test_simple(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/external_link.html")

    def test_prepopulated_form(self):
        response = self.get(
            {"link_text": "Torchbox", "link_url": "https://torchbox.com/"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Torchbox")
        self.assertContains(response, "https://torchbox.com/")

    def test_create_link(self):
        response = self.post(
            {
                "external-link-chooser-url": "http://www.example.com/",
                "external-link-chooser-link_text": "example",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        self.assertEqual(response_json["step"], "external_link_chosen")
        self.assertEqual(response_json["result"]["url"], "http://www.example.com/")
        self.assertEqual(
            response_json["result"]["title"], "example"
        )  # When link text is given, it is used
        self.assertIs(response_json["result"]["prefer_this_title_as_link_text"], True)

    def test_create_link_without_text(self):
        response = self.post({"external-link-chooser-url": "http://www.example.com/"})
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        self.assertEqual(response_json["step"], "external_link_chosen")
        self.assertEqual(response_json["result"]["url"], "http://www.example.com/")
        self.assertEqual(
            response_json["result"]["title"], "http://www.example.com/"
        )  # When no text is given, it uses the url
        self.assertIs(response_json["result"]["prefer_this_title_as_link_text"], False)

    def test_notice_changes_to_link_text(self):
        response = self.post(
            {
                "external-link-chooser-url": "http://www.example.com/",
                "external-link-chooser-link_text": "example",
            },  # POST data
            {
                "link_url": "http://old.example.com/",
                "link_text": "example",
            },  # GET params - initial data
        )
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "http://www.example.com/")
        self.assertEqual(result["title"], "example")
        # no change to link text, so prefer the existing link/selection content where available
        self.assertIs(result["prefer_this_title_as_link_text"], False)

        response = self.post(
            {
                "external-link-chooser-url": "http://www.example.com/",
                "external-link-chooser-link_text": "new example",
            },  # POST data
            {
                "link_url": "http://old.example.com/",
                "link_text": "example",
            },  # GET params - initial data
        )
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "http://www.example.com/")
        self.assertEqual(result["title"], "new example")
        # link text has changed, so tell the caller to use it
        self.assertIs(result["prefer_this_title_as_link_text"], True)

    def test_invalid_url(self):
        response = self.post(
            {
                "external-link-chooser-url": "ntp://www.example.com",
                "external-link-chooser-link_text": "example",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        self.assertEqual(
            response_json["step"], "external_link"
        )  # indicates failure / show error message
        self.assertContains(response, "Enter a valid URL.")

    def test_allow_local_url(self):
        response = self.post(
            {
                "external-link-chooser-url": "/admin/",
                "external-link-chooser-link_text": "admin",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        self.assertEqual(
            response_json["step"], "external_link_chosen"
        )  # indicates success / post back to calling page
        self.assertEqual(response_json["result"]["url"], "/admin/")
        self.assertEqual(response_json["result"]["title"], "admin")

    def test_convert_external_to_internal_link(self):
        response = self.post(
            {
                "external-link-chooser-url": "http://localhost/about/",
                "external-link-chooser-link_text": "about",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        self.assertEqual(response_json["step"], "external_link_chosen")
        self.assertEqual(response_json["result"]["url"], "/about/")
        self.assertEqual(response_json["result"]["id"], self.internal_page.pk)

    def test_convert_external_link_with_query_parameters_to_internal_link(self):
        response = self.post(
            {
                "external-link-chooser-url": "http://localhost/about?test=1",
                "external-link-chooser-link_text": "about",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())

        # Query parameters will get stripped, so the user should get asked to confirm the conversion
        self.assertEqual(response_json["step"], "confirm_external_to_internal")

        self.assertEqual(
            response_json["external"]["url"], "http://localhost/about?test=1"
        )
        self.assertEqual(response_json["internal"]["url"], "/about/")
        self.assertEqual(response_json["internal"]["id"], self.internal_page.pk)

    def test_convert_relative_external_link_to_internal_link(self):
        response = self.post(
            {
                "external-link-chooser-url": "/about/",
                "external-link-chooser-link_text": "about",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        self.assertEqual(response_json["step"], "external_link_chosen")
        self.assertEqual(response_json["result"]["url"], "/about/")
        self.assertEqual(response_json["result"]["id"], self.internal_page.pk)

    @override_settings(WAGTAILADMIN_EXTERNAL_LINK_CONVERSION="")
    def test_no_conversion_external_to_internal_link_when_disabled(self):
        url = "http://localhost/about/"
        title = "about"
        response = self.post(
            {"external-link-chooser-url": url, "external-link-chooser-link_text": title}
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        self.assertEqual(response_json["step"], "external_link_chosen")

        self.assertEqual(response_json["result"]["url"], url)
        self.assertEqual(response_json["result"]["title"], title)
        self.assertNotIn("id", response_json["result"])

    @override_settings(WAGTAILADMIN_EXTERNAL_LINK_CONVERSION="exact")
    def test_no_confirm_external_to_internal_link_when_exact(self):
        url = "http://localhost/about?test=1"
        title = "about"
        response = self.post(
            {"external-link-chooser-url": url, "external-link-chooser-link_text": title}
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        # Query parameters will get stripped, so this link should be left as an external url with the 'exact' setting
        self.assertEqual(response_json["step"], "external_link_chosen")

        self.assertEqual(response_json["result"]["url"], url)
        self.assertEqual(response_json["result"]["title"], title)
        self.assertNotIn("id", response_json["result"])

    @override_settings(WAGTAILADMIN_EXTERNAL_LINK_CONVERSION="confirm")
    def test_convert_external_link_to_internal_link_with_confirm_setting(self):
        url = "http://localhost/about/"
        response = self.post(
            {
                "external-link-chooser-url": url,
                "external-link-chooser-link_text": "about",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())

        # The url is identical, but the conversion setting is set to 'confirm'
        # so the user should get asked to confirm the conversion
        self.assertEqual(response_json["step"], "confirm_external_to_internal")

        self.assertEqual(response_json["external"]["url"], url)
        self.assertEqual(response_json["internal"]["url"], "/about/")
        self.assertEqual(response_json["internal"]["id"], self.internal_page.pk)


@override_settings(ROOT_URLCONF="wagtail.test.headless_urls")
class TestChooserExternalLinkWithNoServePath(TestChooserExternalLink):
    def test_convert_external_to_internal_link(self):
        # Normally this should be converted without any confirmation, but since
        # the serve path is not registered, the page route will resolve to None,
        # so the user should be asked to confirm the conversion.
        # As a result, this test is now identical to
        # test_convert_external_link_to_internal_link_with_confirm_setting
        response = self.post(
            {
                "external-link-chooser-url": "http://localhost/about/",
                "external-link-chooser-link_text": "about",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        self.assertEqual(response_json["step"], "confirm_external_to_internal")
        self.assertEqual(response_json["external"]["url"], "http://localhost/about/")
        self.assertIsNone(response_json["internal"]["url"])
        self.assertEqual(response_json["internal"]["id"], self.internal_page.pk)

    def test_convert_external_link_with_query_parameters_to_internal_link(self):
        response = self.post(
            {
                "external-link-chooser-url": "http://localhost/about?test=1",
                "external-link-chooser-link_text": "about",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())

        # Query parameters will get stripped, so the user should get asked to confirm the conversion
        self.assertEqual(response_json["step"], "confirm_external_to_internal")

        self.assertEqual(
            response_json["external"]["url"], "http://localhost/about?test=1"
        )
        # The serve path is not registered, so the page route will resolve to None
        self.assertIsNone(response_json["internal"]["url"])
        self.assertEqual(response_json["internal"]["id"], self.internal_page.pk)

    def test_convert_relative_external_link_to_internal_link(self):
        response = self.post(
            {
                "external-link-chooser-url": "/about/",
                "external-link-chooser-link_text": "about",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        # As with test_convert_external_to_internal_link, normally this doesn't
        # require confirmation, but since the serve path is not registered, the
        # full URL of the page is None, thus triggering the confirmation
        self.assertEqual(response_json["step"], "confirm_external_to_internal")
        self.assertEqual(response_json["external"]["url"], "/about/")
        # The serve path is not registered, so the page route will resolve to None
        self.assertIsNone(response_json["internal"]["url"])
        self.assertEqual(response_json["internal"]["id"], self.internal_page.pk)

    @override_settings(WAGTAILADMIN_EXTERNAL_LINK_CONVERSION="confirm")
    def test_convert_external_link_to_internal_link_with_confirm_setting(self):
        url = "http://localhost/about/"
        response = self.post(
            {
                "external-link-chooser-url": url,
                "external-link-chooser-link_text": "about",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())

        # The serve path is not registered so the URL can never be identical,
        # which means the setting doesn't matter in this case, but we keep the
        # test case anyway to ensure that the confirmation step is triggered
        self.assertEqual(response_json["step"], "confirm_external_to_internal")

        self.assertEqual(response_json["external"]["url"], url)
        self.assertIsNone(response_json["internal"]["url"])
        self.assertEqual(response_json["internal"]["id"], self.internal_page.pk)


@override_settings(ROOT_URLCONF="wagtail.test.non_root_urls")
class TestChooserExternalLinkWithNonRootServePath(TestChooserExternalLink):
    prefix = "site/"

    def test_convert_external_to_internal_link(self):
        # Legacy behaviour: when using a non-root serve path, entering a full
        # URL without the serve path will trigger the conversion.
        # Normally this should be converted without any confirmation, but since
        # the actual URL will include the serve path (thus different from the
        # input URL), the user should be asked to confirm.
        response = self.post(
            {
                "external-link-chooser-url": "http://localhost/about/",
                "external-link-chooser-link_text": "about",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        self.assertEqual(response_json["step"], "confirm_external_to_internal")
        self.assertEqual(response_json["external"]["url"], "http://localhost/about/")
        self.assertEqual(response_json["internal"]["url"], f"/{self.prefix}about/")
        self.assertEqual(response_json["internal"]["id"], self.internal_page.pk)

    def test_convert_external_to_internal_link_with_serve_path(self):
        # https://github.com/wagtail/wagtail/issues/11996
        # New behaviour: when using a non-root serve path, entering a full
        # URL with the serve path will trigger the conversion. Previously, this
        # would have been considered an external link since the logic does not
        # take the serve path into account, but now it should be correctly
        # converted to an internal link (without needing confirmation as the
        # input URL will be an exact match to the page's full URL).

        # Warm up the cache
        response = self.post(
            {
                "external-link-chooser-url": f"http://localhost/{self.prefix}about/",
                "external-link-chooser-link_text": "about",
            }
        )
        with self.assertNumQueries(10):
            response = self.post(
                {
                    "external-link-chooser-url": f"http://localhost/{self.prefix}about/",
                    "external-link-chooser-link_text": "about",
                }
            )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        self.assertEqual(response_json["step"], "external_link_chosen")
        self.assertEqual(response_json["result"]["url"], f"/{self.prefix}about/")
        self.assertEqual(response_json["result"]["id"], self.internal_page.pk)

    def test_convert_external_link_with_query_parameters_to_internal_link(self):
        # Legacy behaviour: when using a non-root serve path, entering a full
        # URL without the serve path will trigger the conversion. The user
        # should be asked to confirm the conversion as the input URL will be
        # different from the page's full URL (as the serve path is added and
        # the query parameters are removed).
        response = self.post(
            {
                "external-link-chooser-url": "http://localhost/about?test=1",
                "external-link-chooser-link_text": "about",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())

        # Query parameters will get stripped, so the user should get asked to confirm the conversion
        self.assertEqual(response_json["step"], "confirm_external_to_internal")

        self.assertEqual(
            response_json["external"]["url"], "http://localhost/about?test=1"
        )
        self.assertEqual(response_json["internal"]["url"], f"/{self.prefix}about/")
        self.assertEqual(response_json["internal"]["id"], self.internal_page.pk)

    def test_convert_external_link_with_query_parameters_to_internal_link_with_serve_path(
        self,
    ):
        # https://github.com/wagtail/wagtail/issues/11996
        # New behaviour: when using a non-root serve path, entering a full
        # URL with the serve path will trigger the conversion. Previously, this
        # would have been considered an external link since the logic does not
        # take the serve path into account, but now it should be correctly
        # converted to an internal link. It still needs a confirmation as the
        # input URL includes query parameters that will be stripped when matching
        # it with the page's full URL.
        response = self.post(
            {
                "external-link-chooser-url": f"http://localhost/{self.prefix}about?test=1",
                "external-link-chooser-link_text": "about",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())

        # Query parameters will get stripped, so the user should get asked to confirm the conversion
        self.assertEqual(response_json["step"], "confirm_external_to_internal")

        self.assertEqual(
            response_json["external"]["url"],
            f"http://localhost/{self.prefix}about?test=1",
        )
        self.assertEqual(response_json["internal"]["url"], f"/{self.prefix}about/")
        self.assertEqual(response_json["internal"]["id"], self.internal_page.pk)

    def test_convert_relative_external_link_to_internal_link(self):
        # Legacy behaviour: when using a non-root serve path, entering a relative
        # URL without the serve path will trigger the conversion.
        # Normally this should be converted without any confirmation, but since
        # the actual URL will include the serve path (thus different from the
        # input URL), the user should be asked to confirm.
        response = self.post(
            {
                "external-link-chooser-url": "/about/",
                "external-link-chooser-link_text": "about",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        self.assertEqual(response_json["step"], "confirm_external_to_internal")
        self.assertEqual(response_json["external"]["url"], "/about/")
        self.assertEqual(response_json["internal"]["url"], f"/{self.prefix}about/")
        self.assertEqual(response_json["internal"]["id"], self.internal_page.pk)

    def test_convert_relative_external_link_to_internal_link_with_serve_path(self):
        # https://github.com/wagtail/wagtail/issues/11996
        # New behaviour: when using a non-root serve path, entering a relative
        # URL with the serve path will trigger the conversion. Previously, this
        # would have been considered an external link since the logic does not
        # take the serve path into account, but now it should be correctly
        # converted to an internal link (without needing confirmation as the
        # input URL will be an exact match to the page's relative URL).
        response = self.post(
            {
                "external-link-chooser-url": f"/{self.prefix}about/",
                "external-link-chooser-link_text": "about",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        self.assertEqual(response_json["step"], "external_link_chosen")
        self.assertEqual(response_json["result"]["url"], f"/{self.prefix}about/")
        self.assertEqual(response_json["result"]["id"], self.internal_page.pk)

    @override_settings(WAGTAILADMIN_EXTERNAL_LINK_CONVERSION="")
    def test_no_conversion_external_to_internal_link_when_disabled_with_serve_path(
        self,
    ):
        url = f"http://localhost/{self.prefix}about/"
        title = "about"
        response = self.post(
            {"external-link-chooser-url": url, "external-link-chooser-link_text": title}
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        self.assertEqual(response_json["step"], "external_link_chosen")

        self.assertEqual(response_json["result"]["url"], url)
        self.assertEqual(response_json["result"]["title"], title)
        self.assertNotIn("id", response_json["result"])

    @override_settings(WAGTAILADMIN_EXTERNAL_LINK_CONVERSION="exact")
    def test_no_confirm_external_to_internal_link_when_exact_with_serve_path(self):
        url = f"http://localhost/{self.prefix}about?test=1"
        title = "about"
        response = self.post(
            {"external-link-chooser-url": url, "external-link-chooser-link_text": title}
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())
        # Query parameters will get stripped, so this link should be left as an external url with the 'exact' setting
        self.assertEqual(response_json["step"], "external_link_chosen")

        self.assertEqual(response_json["result"]["url"], url)
        self.assertEqual(response_json["result"]["title"], title)
        self.assertNotIn("id", response_json["result"])

    @override_settings(WAGTAILADMIN_EXTERNAL_LINK_CONVERSION="confirm")
    def test_convert_external_link_to_internal_link_with_confirm_setting(self):
        url = f"http://localhost/{self.prefix}about/"
        response = self.post(
            {
                "external-link-chooser-url": url,
                "external-link-chooser-link_text": "about",
            }
        )
        self.assertEqual(response.status_code, 200)
        response_json = json.loads(response.content.decode())

        # The url is identical, but the conversion setting is set to 'confirm'
        # so the user should get asked to confirm the conversion
        self.assertEqual(response_json["step"], "confirm_external_to_internal")

        self.assertEqual(response_json["external"]["url"], url)
        self.assertEqual(response_json["internal"]["url"], f"/{self.prefix}about/")
        self.assertEqual(response_json["internal"]["id"], self.internal_page.pk)


@override_settings(
    WAGTAIL_I18N_ENABLED=True,
    ROOT_URLCONF="wagtail.test.urls_multilang",
)
class TestChooserExternalLinkWithI18n(TestChooserExternalLinkWithNonRootServePath):
    prefix = "en/"


@override_settings(
    WAGTAIL_I18N_ENABLED=True,
    ROOT_URLCONF="wagtail.test.urls_multilang_non_root",
)
class TestChooserExternalLinkWithI18nNonRoot(
    TestChooserExternalLinkWithNonRootServePath
):
    prefix = "en/site/"


class TestChooserAnchorLink(WagtailTestUtils, TestCase):
    def setUp(self):
        self.login()

    def get(self, params={}):
        return self.client.get(reverse("wagtailadmin_choose_page_anchor_link"), params)

    def post(self, post_data={}, url_params={}):
        url = reverse("wagtailadmin_choose_page_anchor_link")
        if url_params:
            url += "?" + urlencode(url_params)
        return self.client.post(url, post_data)

    def test_simple(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/anchor_link.html")

    def test_prepopulated_form(self):
        response = self.get(
            {"link_text": "Example Anchor Text", "link_url": "exampleanchor"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Example Anchor Text")
        self.assertContains(response, "exampleanchor")

    def test_create_link(self):
        response = self.post(
            {
                "anchor-link-chooser-url": "exampleanchor",
                "anchor-link-chooser-link_text": "Example Anchor Text",
            }
        )
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "#exampleanchor")
        self.assertEqual(
            result["title"], "Example Anchor Text"
        )  # When link text is given, it is used
        self.assertIs(result["prefer_this_title_as_link_text"], True)

    def test_create_link_without_text(self):
        response = self.post({"anchor-link-chooser-url": "exampleanchor"})
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "#exampleanchor")
        self.assertEqual(
            result["title"], "exampleanchor"
        )  # When no link text is given, it uses anchor
        self.assertIs(result["prefer_this_title_as_link_text"], False)

    def test_notice_changes_to_link_text(self):
        response = self.post(
            {
                "anchor-link-chooser-url": "exampleanchor2",
                "email-link-chooser-link_text": "Example Text",
            },  # POST data
            {
                "link_url": "exampleanchor2",
                "link_text": "Example Text",
            },  # GET params - initial data
        )
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "#exampleanchor2")
        self.assertEqual(result["title"], "exampleanchor2")
        # no change to link text, so prefer the existing link/selection content where available
        self.assertIs(result["prefer_this_title_as_link_text"], True)

        response = self.post(
            {
                "anchor-link-chooser-url": "exampleanchor2",
                "anchor-link-chooser-link_text": "Example Anchor Test 2.1",
            },  # POST data
            {
                "link_url": "exampleanchor",
                "link_text": "Example Anchor Text",
            },  # GET params - initial data
        )
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "#exampleanchor2")
        self.assertEqual(result["title"], "Example Anchor Test 2.1")
        # link text has changed, so tell the caller to use it
        self.assertIs(result["prefer_this_title_as_link_text"], True)


class TestChooserEmailLink(WagtailTestUtils, TestCase):
    def setUp(self):
        self.login()

    def get(self, params={}):
        return self.client.get(reverse("wagtailadmin_choose_page_email_link"), params)

    def post(self, post_data={}, url_params={}):
        url = reverse("wagtailadmin_choose_page_email_link")
        if url_params:
            url += "?" + urlencode(url_params)
        return self.client.post(url, post_data)

    def test_simple(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/email_link.html")

    def test_prepopulated_form(self):
        response = self.get({"link_text": "Example", "link_url": "example@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Example")
        self.assertContains(response, "example@example.com")

    def test_create_link(self):
        response = self.post(
            {
                "email-link-chooser-email_address": "example@example.com",
                "email-link-chooser-link_text": "contact",
            }
        )
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "mailto:example@example.com")
        self.assertEqual(
            result["title"], "contact"
        )  # When link text is given, it is used
        self.assertIs(result["prefer_this_title_as_link_text"], True)

    def test_create_link_with_subject_and_body(self):
        response = self.post(
            {
                "email-link-chooser-email_address": "example@example.com",
                "email-link-chooser-link_text": "contact",
                "email-link-chooser-subject": "Awesome Subject",
                "email-link-chooser-body": "An example body",
            }
        )
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content.decode())["result"]
        url = result["url"]
        self.assertEqual(
            url,
            "mailto:example@example.com?subject=Awesome%20Subject&body=An%20example%20body",
        )
        self.assertEqual(
            result["title"], "contact"
        )  # When link text is given, it is used
        self.assertIs(result["prefer_this_title_as_link_text"], True)

        mail_parts = urlsplit(url)
        query = parse_qs(mail_parts.query)
        self.assertEqual(mail_parts.path, "example@example.com")
        self.assertEqual(query["subject"][0], "Awesome Subject")
        self.assertEqual(query["body"][0], "An example body")

    def test_create_link_with_subject_only(self):
        response = self.post(
            {
                "email-link-chooser-email_address": "example@example.com",
                "email-link-chooser-link_text": "contact",
                "email-link-chooser-subject": "Awesome Subject",
            }
        )
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content.decode())["result"]
        url = result["url"]
        self.assertEqual(url, "mailto:example@example.com?subject=Awesome%20Subject")
        self.assertEqual(
            result["title"], "contact"
        )  # When link text is given, it is used
        self.assertIs(result["prefer_this_title_as_link_text"], True)

        mail_parts = urlsplit(url)
        query = parse_qs(mail_parts.query)
        self.assertEqual(mail_parts.path, "example@example.com")
        self.assertEqual(query["subject"][0], "Awesome Subject")
        self.assertTrue("body" not in query)

    def test_create_link_with_body_only(self):
        response = self.post(
            {
                "email-link-chooser-email_address": "example@example.com",
                "email-link-chooser-link_text": "contact",
                "email-link-chooser-body": "An example body",
            }
        )
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content.decode())["result"]
        url = result["url"]
        self.assertEqual(url, "mailto:example@example.com?body=An%20example%20body")
        self.assertEqual(
            result["title"], "contact"
        )  # When link text is given, it is used
        self.assertIs(result["prefer_this_title_as_link_text"], True)

        mail_parts = urlsplit(url)
        query = parse_qs(mail_parts.query)
        self.assertEqual(mail_parts.path, "example@example.com")
        self.assertEqual(query["body"][0], "An example body")
        self.assertTrue("subject" not in query)

    def test_create_link_without_text(self):
        response = self.post(
            {"email-link-chooser-email_address": "example@example.com"}
        )
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "mailto:example@example.com")
        self.assertEqual(
            result["title"], "example@example.com"
        )  # When no link text is given, it uses the email
        self.assertIs(result["prefer_this_title_as_link_text"], False)

    def test_notice_changes_to_link_text(self):
        response = self.post(
            {
                "email-link-chooser-email_address": "example2@example.com",
                "email-link-chooser-link_text": "example",
            },  # POST data
            {
                "link_url": "example@example.com",
                "link_text": "example",
            },  # GET params - initial data
        )
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "mailto:example2@example.com")
        self.assertEqual(result["title"], "example")
        # no change to link text, so prefer the existing link/selection content where available
        self.assertIs(result["prefer_this_title_as_link_text"], False)

        response = self.post(
            {
                "email-link-chooser-email_address": "example2@example.com",
                "email-link-chooser-link_text": "new example",
            },  # POST data
            {
                "link_url": "example@example.com",
                "link_text": "example",
            },  # GET params - initial data
        )
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "mailto:example2@example.com")
        self.assertEqual(result["title"], "new example")
        # link text has changed, so tell the caller to use it
        self.assertIs(result["prefer_this_title_as_link_text"], True)


class TestChooserPhoneLink(WagtailTestUtils, TestCase):
    def setUp(self):
        self.login()

    def get(self, params={}):
        return self.client.get(reverse("wagtailadmin_choose_page_phone_link"), params)

    def post(self, post_data={}, url_params={}):
        url = reverse("wagtailadmin_choose_page_phone_link")
        if url_params:
            url += "?" + urlencode(url_params)
        return self.client.post(url, post_data)

    def test_simple(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/chooser/phone_link.html")

    def test_prepopulated_form(self):
        response = self.get({"link_text": "Example", "link_url": "+123456789"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Example")
        self.assertContains(response, "+123456789")

    def test_create_link(self):
        response = self.post(
            {
                "phone-link-chooser-phone_number": "+123456789",
                "phone-link-chooser-link_text": "call",
            }
        )
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "tel:+123456789")
        self.assertEqual(result["title"], "call")
        self.assertIs(result["prefer_this_title_as_link_text"], True)

    def test_create_link_without_text(self):
        response = self.post({"phone-link-chooser-phone_number": "+123456789"})
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "tel:+123456789")
        self.assertEqual(
            result["title"], "+123456789"
        )  # When no link text is given, it uses the phone number
        self.assertIs(result["prefer_this_title_as_link_text"], False)

    def test_notice_changes_to_link_text(self):
        response = self.post(
            {
                "phone-link-chooser-phone_number": "+222222222",
                "phone-link-chooser-link_text": "example",
            },  # POST data
            {
                "link_url": "+111111111",
                "link_text": "example",
            },  # GET params - initial data
        )
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "tel:+222222222")
        self.assertEqual(result["title"], "example")
        # no change to link text, so prefer the existing link/selection content where available
        self.assertIs(result["prefer_this_title_as_link_text"], False)

        response = self.post(
            {
                "phone-link-chooser-phone_number": "+222222222",
                "phone-link-chooser-link_text": "new example",
            },  # POST data
            {
                "link_url": "+111111111",
                "link_text": "example",
            },  # GET params - initial data
        )
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "tel:+222222222")
        self.assertEqual(result["title"], "new example")
        # link text has changed, so tell the caller to use it
        self.assertIs(result["prefer_this_title_as_link_text"], True)

    def test_phone_number_has_spaces(self):
        response = self.post(
            {
                "phone-link-chooser-phone_number": "+1 234 567 890",
                "phone-link-chooser-link_text": "call",
            }
        )
        result = json.loads(response.content.decode())["result"]
        self.assertEqual(result["url"], "tel:+1234567890")
        self.assertEqual(result["title"], "call")
        self.assertIs(result["prefer_this_title_as_link_text"], True)


class TestCanChoosePage(WagtailTestUtils, TestCase):
    fixtures = ["test.json"]

    def setUp(self):
        self.user = self.login()
        self.desired_classes = (Page,)

    def test_can_choose_page(self):
        homepage = Page.objects.get(url_path="/home/")
        result = can_choose_page(homepage, self.user, self.desired_classes)
        self.assertTrue(result)

    def test_with_user_no_permission(self):
        homepage = Page.objects.get(url_path="/home/")
        # event editor does not have permissions on homepage
        event_editor = get_user_model().objects.get(email="eventeditor@example.com")
        result = can_choose_page(
            homepage, event_editor, self.desired_classes, user_perm="copy_to"
        )
        self.assertFalse(result)

    def test_with_can_choose_root(self):
        root = Page.objects.get(url_path="/")
        result = can_choose_page(
            root, self.user, self.desired_classes, can_choose_root=True
        )
        self.assertTrue(result)

    def test_with_can_not_choose_root(self):
        root = Page.objects.get(url_path="/")
        result = can_choose_page(
            root, self.user, self.desired_classes, can_choose_root=False
        )
        self.assertFalse(result)

    def test_move_to_same_page(self):
        homepage = Page.objects.get(url_path="/home/")
        result = can_choose_page(
            homepage,
            self.user,
            self.desired_classes,
            user_perm="move_to",
            target_pages=[homepage],
        )
        self.assertFalse(result)

    def test_move_to_root(self):
        homepage = Page.objects.get(url_path="/home/")
        root = Page.objects.get(url_path="/")
        result = can_choose_page(
            root,
            self.user,
            self.desired_classes,
            user_perm="move_to",
            target_pages=[homepage],
        )
        self.assertTrue(result)

    def test_move_to_page_with_wrong_parent_types(self):
        board_meetings = Page.objects.get(
            url_path="/home/events/businessy-events/board-meetings/"
        )
        homepage = Page.objects.get(url_path="/home/")
        result = can_choose_page(
            homepage,
            self.user,
            self.desired_classes,
            user_perm="move_to",
            target_pages=[board_meetings],
        )
        self.assertFalse(result)

    def test_move_to_same_page_bulk(self):
        homepage = Page.objects.get(url_path="/home/")
        secret_plans = Page.objects.get(url_path="/home/secret-plans/")
        result = can_choose_page(
            homepage,
            self.user,
            self.desired_classes,
            user_perm="bulk_move_to",
            target_pages=[homepage, secret_plans],
        )
        self.assertFalse(result)

    def test_move_to_root_bulk(self):
        homepage = Page.objects.get(url_path="/home/")
        secret_plans = Page.objects.get(url_path="/home/secret-plans/")
        root = Page.objects.get(url_path="/")
        result = can_choose_page(
            root,
            self.user,
            self.desired_classes,
            user_perm="bulk_move_to",
            target_pages=[homepage, secret_plans],
        )
        self.assertTrue(result)

    def test_move_to_page_with_wrong_parent_types_bulk(self):
        board_meetings = Page.objects.get(
            url_path="/home/events/businessy-events/board-meetings/"
        )
        steal_underpants = Page.objects.get(
            url_path="/home/secret-plans/steal-underpants/"
        )
        homepage = Page.objects.get(url_path="/home/")
        result = can_choose_page(
            homepage,
            self.user,
            self.desired_classes,
            user_perm="bulk_move_to",
            target_pages=[board_meetings, steal_underpants],
        )
        self.assertTrue(result)


@override_settings(WAGTAIL_I18N_ENABLED=True)
class TestPageChooserLocaleSelector(WagtailTestUtils, TestCase):
    fixtures = ["test.json"]

    LOCALE_SELECTOR_HTML = r"data-locale-selector[^<]+<button[^<]+<svg[^<]+<use[^<]+<\/use[^<]+<\/svg[^<]+English"

    def setUp(self):
        self.root_page = Page.objects.get(id=2)

        # Add child page
        self.child_page = SimplePage(title="foobarbaz", content="hello")
        self.root_page.add_child(instance=self.child_page)

        self.fr_locale = Locale.objects.create(language_code="fr")
        self.root_page_fr = self.root_page.copy_for_translation(self.fr_locale)
        self.root_page_fr.title = "Bienvenue"
        self.root_page_fr.save()
        self.child_page_fr = self.child_page.copy_for_translation(self.fr_locale)
        self.child_page_fr.save()

        switch_to_french_url = self.get_choose_page_url(
            parent_page_id=self.child_page_fr.pk
        )
        self.LOCALE_SELECTOR_HTML_FR = (
            f'<a href="{switch_to_french_url}" data-locale-selector-link>'
        )

        self.login()

    def get(self, parent_page_id):
        return self.client.get(
            reverse("wagtailadmin_choose_page_child", args=[parent_page_id])
        )

    def get_choose_page_url(self, parent_page_id=None, params=""):
        if parent_page_id is not None:
            url = reverse("wagtailadmin_choose_page_child", args=[parent_page_id])
        else:
            url = reverse("wagtailadmin_choose_page")
        return f"{url}?{params}"

    def test_locale_selector_present_in_root_view(self):
        response = self.client.get(reverse("wagtailadmin_choose_page"))
        html = response.json().get("html")

        self.assertRegex(html, self.LOCALE_SELECTOR_HTML)

        switch_to_french_url = self.get_choose_page_url(params="locale=fr")
        fr_selector = f'<a href="{switch_to_french_url}" data-locale-selector-link>'
        self.assertIn(fr_selector, html)

    def test_locale_selector(self):
        response = self.get(self.child_page.pk)

        html = response.json().get("html")
        self.assertRegex(html, self.LOCALE_SELECTOR_HTML)
        self.assertIn(self.LOCALE_SELECTOR_HTML_FR, html)

    def test_locale_selector_without_translation(self):
        self.child_page_fr.delete()

        response = self.get(self.child_page.pk)
        html = response.json().get("html")
        self.assertNotIn("data-locale-selector", html)

    def test_locale_selector_with_active_locale(self):
        switch_to_french_url = self.get_choose_page_url(params="locale=fr")
        response = self.client.get(switch_to_french_url)
        html = response.json().get("html")

        self.assertNotIn(self.LOCALE_SELECTOR_HTML_FR, html)
        self.assertNotIn(f'data-title="{self.root_page.title}"', html)
        self.assertIn(self.root_page_fr.title, html)
        self.assertRegex(
            html,
            r"data-locale-selector[^<]+<button[^<]+<svg[^<]+<use[^<]+<\/use[^<]+<\/svg[^<]+French",
        )
        switch_to_english_url = self.get_choose_page_url(params="locale=en")
        self.assertIn(
            f'<a href="{switch_to_english_url}" data-locale-selector-link>',
            html,
        )

    @override_settings(WAGTAIL_I18N_ENABLED=False)
    def test_locale_selector_not_present_when_i18n_disabled(self):
        response = self.get(self.child_page.pk)
        html = response.json().get("html")
        self.assertNotIn("data-locale-selector", html)

    def test_query_params_preserved(self):
        choose_url = reverse(
            "wagtailadmin_choose_page_child", args=[self.child_page.pk]
        )
        params = "can_choose_root=false&user_perms=copy_to&match_subclass=true"
        response = self.client.get(f"{choose_url}?{params}&p=1")
        html = response.json().get("html")
        self.assertIn("data-locale-selector", html)

        switch_to_french_url = self.get_choose_page_url(
            parent_page_id=self.child_page_fr.pk, params=params
        )
        self.assertIn(escape(switch_to_french_url), html)

    def test_query_params_preserved_in_root_view(self):
        choose_url = reverse("wagtailadmin_choose_page")
        params = "can_choose_root=false&user_perms=copy_to&match_subclass=true"
        response = self.client.get(f"{choose_url}?{params}&p=1")
        html = response.json().get("html")
        self.assertIn("data-locale-selector", html)

        switch_to_french_url = self.get_choose_page_url(params=params + "&locale=fr")
        self.assertIn(escape(switch_to_french_url), html)
