from django.test import TestCase
from django.urls import reverse

from .registry import TOOLS


class ToolPagesTests(TestCase):
	def test_hub_lists_every_registered_tool(self):
		resp = self.client.get(reverse("tools:index"))
		self.assertEqual(resp.status_code, 200)
		for tool in TOOLS:
			self.assertContains(resp, tool["title"])
			self.assertContains(resp, reverse(tool["url_name"]))

	def test_tool_pages_are_public(self):
		for tool in TOOLS:
			self.assertEqual(self.client.get(reverse(tool["url_name"])).status_code, 200)

	def test_nav_has_tool_link(self):
		resp = self.client.get(reverse("tools:index"))
		self.assertContains(resp, f'href="{reverse("tools:index")}"')

	def test_home_quick_nav_has_tool_link(self):
		resp = self.client.get(reverse("main:home"))
		self.assertContains(resp, f'href="{reverse("tools:index")}"')
