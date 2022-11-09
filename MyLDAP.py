#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
# import ldap
# import ldap.asyncsearch
from ldap3 import Server, Connection, SAFE_SYNC, ALL, BASE, LEVEL, MODIFY_ADD, MODIFY_DELETE, MODIFY_REPLACE, ALL_ATTRIBUTES, SUBTREE

from dataclasses import dataclass, field
from abc import abstractmethod
from copy import deepcopy
from typing import Any


@dataclass
class Alias:
    name: str = "cn"
    member: str = "uniqueMember"
    description: str = "description"


@dataclass
class SimpleGroup:
    name: str
    member: list[str] = field(default_factory=list[str])
    description: str = ''

    @property
    def members(self) -> list[str]:
        return self.member


@dataclass
class SimpleGroupList:
    groups: list[SimpleGroup] = field(default_factory=list[SimpleGroup])

    def __len__(self) -> int:
        len(self.groups)

    def __getitem__(self, index) -> SimpleGroup:
        return self.groups[index]

    def append(self, group: SimpleGroup) -> None:
        self.groups.append(group)

    def search(self, name: str) -> SimpleGroup:
        for group in self.groups:
            if group.name == name:
                return group
        return None

    @property
    def name_list(self) -> list[str]:
        return [i.name for i in self.groups]


@dataclass
class myObject:
    name: str = None
    class_name: str = None
    dn: str = None


@dataclass
class Group(myObject, SimpleGroup):
    description: str = None
    class_name: str = 'Group'

    @abstractmethod
    def from_dict(self, result: dict[str, list[str]]) -> None:
        alias: Alias = Alias(member="member")
        self._from_dict(result=result, alias=alias)

    def _from_dict(self, result: dict[str, list[str]], alias: Alias = Alias()) -> None:
        # print(alias)
        self.dn = result["dn"]
        data = result["attributes"]
        self.class_name = data["objectClass"][0]
        self.name = data[alias.name][0]
        self.member = data[alias.member]
        if alias.description in data:
            self.description = data[alias.description][0]
        else:
            self.description = ""

    def get_member_rdn(self, user_Con: UserSearchCon, ldap: Connection) -> SimpleGroup:
        sg = SimpleGroup(name=self.name, member=self.member, description=self.description)
        return sg


class posixGroup(Group):
    gidNumber: int = 0
    class_name: str = 'posixGroup'

    def from_dict(self, result: dict[str, list[str]]) -> None:
        alias: Alias = Alias(member="memberUid")
        self._from_dict(result, alias)
        self.gidNumber = result["attributes"]["gidNumber"]

    def get_member_rdn(self,  user_Con: UserSearchCon, ldap: Connection) -> SimpleGroup:
        usc = deepcopy(user_Con)
        usc.name_at = 'uid'
        sg = SimpleGroup(name=self.name, description=self.description)
        for user_name in self.member:
            usc.name_like = user_name
            try:
                result = usc.search(ldap=ldap)[2][0]
                sg.member.append(result["dn"])
            except:
                return None
        return sg


@dataclass
class groupOfUniqueNames(Group):
    owner: str = None
    class_name: str = 'groupOfUniqueNames'

    def from_dict(self, result: dict[str, list[str]]) -> None:
        alias: Alias = Alias(member="uniqueMember")
        self._from_dict(result=result, alias=alias)
        self.owner = result["attributes"]["owner"][0]

    def get_member_rdn(self, user_Con: UserSearchCon, ldap: Connection) -> list[str]:
        base = user_Con.base
        l = len(base)
        member = [i for i in self.member if base == i[-l:]]
        sg = SimpleGroup(name=self.name, member=member, description=self.description)
        return sg


@dataclass
class SearchCon:
    base: str
    classname: list[str] = field(default_factory=lambda: ['posixGroup', 'groupOfUniqueNames'])
    name_like: str = None
    name_at: str = 'cn'
    attrlist: str = ALL_ATTRIBUTES

    def filterstr(self) -> str:
        base = ""
        if len(self.classname) > 1:
            for i in self.classname:
                base += "(objectClass={name})".format(name=i)
            base = "|"+base
        else:
            base = "objectClass="+self.classname[0]
        filterstr = "({base})".format(base=base)
        if self.name_like is not None:
            filterstr = "(&{base}({name}={pattern}))".format(
                pattern=self.name_like,
                base=filterstr,
                name=self.name_at
            )
        return filterstr

    def search(self, ldap: Connection, search_scope=SUBTREE) -> tuple[bool, dict[int, str, str, str, str, str], list[dict[str, str, str, str, str]], dict[str, int, int, int, int, bool, str, list[str], str, str]]:
        filterstr = self.filterstr()
        results = ldap.search(
            search_base=self.base,
            search_scope=search_scope,
            search_filter=filterstr,
            attributes=self.attrlist
        )
        return results


@dataclass
class GroupSearchCon(SearchCon):
    classname: list[str] = field(default_factory=lambda: ['posixGroup', 'groupOfUniqueNames'])
    name_at: str = 'cn'


@dataclass
class UserSearchCon(SearchCon):
    classname: list[str] = field(default_factory=lambda: ['posixAccount'])
    name_at: str = 'cn'


@dataclass
class LDAP:
    host: str
    admin: str
    password: str
    port: int = 389
    ssl: bool = False


class myLDAP:
    def __init__(self, ldap: LDAP) -> None:
        # self.ldap: ldap = ldap.initialize(uri=url)
        self.server: Server = Server(ldap.host, use_ssl=ldap.ssl, get_info=ALL)

        self.ldap: Connection = Connection(server=self.server,
                                           user=ldap.admin,
                                           password=ldap.password,
                                           client_strategy=SAFE_SYNC,
                                           auto_bind=True,
                                           read_only=True)
        # self.base_user: str = base_user
        # self.base_group: str = base_group

    def get_groups(self, condition: GroupSearchCon) -> list[Group]:
        results = condition.search(ldap=self.ldap)
        status, result, response, info = results
        if not status:
            return []
        group_list: list[Group] = []

        for row in response:
            objectClass = row['attributes']['objectClass'][0]
            if objectClass == 'posixGroup':
                group = posixGroup()
            elif objectClass == 'groupOfUniqueNames':
                group = groupOfUniqueNames()
            else:
                group = Group()
            group.from_dict(row)
            group_list.append(group)
        return group_list

    def get_users(self, group_Con: GroupSearchCon, user_Con: UserSearchCon) -> SimpleGroupList:
        group_list = self.get_groups(condition=group_Con)
        data = SimpleGroupList()
        for group in group_list:
            tmp = group.get_member_rdn(user_Con, ldap=self.ldap)
            if tmp is not None:
                data.append(tmp)
        return data

    def search_dn(self, dn: str) -> tuple[bool, dict, dict, dict]:
        results = self.ldap.search(search_base=dn,
                                   search_scope=BASE,
                                   search_filter='(objectClass=*)',
                                   attributes=ALL_ATTRIBUTES)
        return results

    def user_info(self, dn: str) -> dict:
        result = self.search_dn(dn=dn)[2][0]
        if 'attributes' in result:
            return result['attributes']
        return {}

    def __del__(self) -> None:
        self.ldap.unbind()
