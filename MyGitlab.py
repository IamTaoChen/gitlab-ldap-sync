#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from dataclasses import asdict, dataclass, field
from typing import Any, Union

from gitlab import Gitlab, exceptions
from gitlab.const import *
from gitlab.v4.objects.groups import Group
from gitlab.v4.objects.users import User

_debug_ = True


@dataclass
class GitlabGroup:
    name: str
    path: str = None
    visibility: str = 'private'
    description: str = 'Create by LDAP'

    def __post_init__(self) -> None:
        if self.path is None:
            self.path = self.name

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class extID:
    provider: str = None
    uid: str = None

    def is_uid(self, uid: str) -> bool:
        return uid == self.uid


@dataclass
class MyUser:
    id: int
    username: str
    name: str
    email: str
    ext_ID: extID = field(default_factory=extID)

    def asdict_for_create(self) -> dict[str, Any]:
        tmp = asdict(self)
        tmp.pop('id')
        tmp.pop('ext_ID')
        tmp['provider'] = self.ext_ID.provider
        tmp['extern_uid'] = self.ext_ID.uid
        tmp['password'] = 'pouetpouet'
        return tmp

    def is_ext_uid(self, extern_uid: str) -> bool:
        return self.ext_ID.is_uid(uid=extern_uid)

    def is_id(self, id: int) -> bool:
        return self.id == id

    def is_usename(self, username: str) -> bool:
        return self.username == username

    def is_name(self, name: str) -> bool:
        return self.name == name

    def is_email(self, email: str) -> bool:
        return self.email == email

    def check(self, attr: str, value: Union[int, str]) -> bool:
        return self.get_value_by_attr(attr=attr) == value

    def get_value_by_attr(self, attr: str) -> Union[int, str]:
        return self.asdict_for_create()[attr]


@dataclass
class MyUserList:
    users: list[MyUser] = field(default_factory=list[MyUser])

    def __len__(self) -> int:
        len(self.users)

    def __getitem__(self, index) -> MyUser:
        return self.users[index]

    def append(self, group: MyUser) -> None:
        self.users.append(group)

    def search_by_name(self, name: str) -> MyUser:
        for group in self.users:
            if group.name == name:
                return group
        return None

    def search_by_attr(self, attr: str, value: Union[int, str]) -> MyUser:
        for user in self.users:
            if user.get_value_by_attr(attr=attr) == value:
                return user
        return None

    def search_by_ext_uid(self, extern_uid: str) -> MyUser:
        return self.search_by_attr(attr='extern_uid', value=extern_uid)

    @property
    def names(self) -> list[str]:
        return [i.name for i in self.users]


@dataclass
class MyGroup:
    id: int
    name: str
    member: MyUserList = field(default_factory=MyUserList)

    def check(self, ref_list: list[Union[int, str]], attr: str) -> tuple[list[Union[int, str], MyUserList]]:
        """
        @description   :    check the user if exist in ref_list by the attr
        ---------
        @Arguments     :
        -------
        @Returns       :    tuple[absence,exist]
        -------
        """
        exists_item = MyUserList()
        absense_item: list[Union[int, str]] = []
        memeber_attr_list = [i.get_value_by_attr(attr=attr) for i in self.member]
        for ref in ref_list:
            try:
                index = memeber_attr_list.index(ref)
                exists_item.append(self.member[index])
            except ValueError:
                absense_item.append(ref)
        return absense_item, exists_item


@dataclass
class MyGroupList:
    groups: list[MyGroup] = field(default_factory=list[MyGroup])

    def __len__(self) -> int:
        len(self.groups)

    def __getitem__(self, index) -> MyGroup:
        return self.groups[index]

    def append(self, group: MyGroup) -> None:
        self.groups.append(group)

    def search(self, name: str) -> MyGroup:
        for group in self.groups:
            if group.name == name:
                return group
        return None

    @property
    def names(self) -> list[str]:
        return [i.name for i in self.groups]


class MyGitlab:
    def __init__(self, url: str = 'http://localhost', access_token: str = None, ssl_verify: bool = False) -> None:
        self.url: str = url
        self.access_token: str = access_token
        self.ssl_verify: bool = ssl_verify
        self.gitlab: Gitlab = None
        self.connect_status = False
        self.__my_user_all: MyUserList = None
        self.__my_group_all: MyUserList = None

    @property
    def myuser_all(self) -> MyUserList:
        if not self.connect_status:
            return None
        if self.__my_user_all is None:
            self.__my_user_all = self.get_user_all()
        return self.__my_user_all

    @property
    def mygroup_all(self) -> MyGroupList:
        if not self.connect_status:
            return None
        if self.__my_group_all is None:
            self.__my_group_all = self.get_group_member_all()
        return self.__my_group_all

    def refresh(self) -> None:
        if not self.connect_status:
            self.connect()
        if not self.connect_status:
            return None
        self.__my_user_all = self.get_user_all()
        self.__my_group_all = self.get_group_member_all()

    def connect(self) -> bool:
        self.connect_status = False
        try:
            self.gitlab = Gitlab(url=self.url,
                                 private_token=self.access_token,
                                 ssl_verify=self.ssl_verify
                                 )
            self.connect_status = True
        except:
            return False

    def get_group_by_id(self, id=int) -> Group:
        return self.gitlab.groups.get(id=id)

    def get_groups(self) -> list[Group]:
        if not self.connect_status:
            return []
        return self.gitlab.groups.list(all=True)

    def get_groups_all_names(self) -> list[str]:
        return [i.full_name for i in self.get_groups()]

    def get_users_in_group(self, group: Union[int, Group]) -> list[User]:
        if isinstance(group, int):
            group = self.get_group_by_id(id=group)
        return group.members.list(all=True)

    def get_user_by_id(self, id: int) -> User:
        return self.gitlab.users.get(id=id)

    def get_user_all_info(self, id: int) -> dict[str, Any]:
        if not self.connect_status:
            return []
        return self.get_user_by_id(id).attributes

    def trans_user_info_2_myuser(self, info, ext_provider='ldapmain') -> MyUser:
        user = MyUser(id=info['id'],
                      username=info['username'],
                      name=info['name'],
                      email=info['email']
                      )
        for identity in info['identities']:
            if identity['provider'] == ext_provider:
                user.ext_ID.provider = ext_provider
                user.ext_ID.uid = identity['extern_uid']
                break
        return user

    def get_user_simple(self, id: int, ext_provider='ldapmain') -> MyUser:
        if not self.connect_status:
            return []
        info = self.get_user_all_info(id=id)
        return self.trans_user_info_2_myuser(info=info, ext_provider=ext_provider)

    def get_user_all(self) -> MyUserList:
        gitlab_all_user = self.gitlab.users.list(all=True)
        user_list = MyGroupList()
        for gitlab_user in gitlab_all_user:
            info = self.get_user_all_info(id=gitlab_user.get_id())
            myuser = self.trans_user_info_2_myuser(info=info)
            user_list.append(myuser)
        return user_list

    def get_group_member_all(self, ext_provider='ldapmain') -> MyGroupList:
        if not self.connect_status:
            return []
        group_list = self.get_groups()
        data: MyGroupList = MyGroupList()
        # print(group_list)
        for group in group_list:
            tmp_group = MyGroup(id=group.get_id(), name=group.full_name)
            members = group.members.list(all=True)
            # print(members)
            for member in members:
                tmp_user = self.get_user_simple(id=member.get_id(), ext_provider=ext_provider)
                tmp_group.member.append(tmp_user)
            data.append(tmp_group)
        return data

    def group_create(self, info: GitlabGroup) -> int:
        if _debug_:
            print('Create group with \t:\t', info.asdict())
            return
        g = self.gitlab.groups.create(info.asdict())
        g.save()
        return g.get_id()

    def user_create(self, info: MyUser) -> int:
        if _debug_:
            print('Create user with \t:\t', info.asdict_for_create())
            return
        info_dict = info.asdict_for_create()
        try:
            u = self.gitlab.users.create(info_dict)
        except exceptions as e:
            if e.response_code == '409':
                info_dict['email'] = info.email.replace('@', '+gl-%s@' % info.username)
                u: User = self.gitlab.users.create(info_dict)
        info.id = u.get_id()
        return info.id

    def group_add_member(self, group_info: MyGroup, user_info: Union[MyUser, int], access_level: str = DEVELOPER_ACCESS) -> None:
        if _debug_:
            print('add {user} into {group}'.format(
                User=user_info.asdict_for_create(),
                group=group_info.name
            ))
            return
        group = self.get_group_by_id(group_info.id)
        if isinstance(user_info, MyUser):
            user_info = user_info.id
        group.members.create({'user_id': user_info, 'access_level': access_level})
        group.save()
