"""Answers of `members_api`: who may open a project, and whom its members can add (P3)."""

from __future__ import annotations

from modeler_api.views.common import View


class MemberView(View):
    subject: str
    name: str
    added_by: str
    added_at: str


class PersonView(View):
    subject: str
    name: str


class MembersPage(View):
    """The project's members, and the people who signed in to this workspace and are not members yet. `managed` is
    false where the principal's access comes from the deployment rather than memberships (the DEV sign-in's `*`)."""

    members: list[MemberView]
    people: list[PersonView]
    managed: bool
