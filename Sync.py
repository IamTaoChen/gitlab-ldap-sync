#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
from MyGitlab import *
from MyLDAP import *


@dataclass
class MyConfig:

    def from_dict(self, value: dict[str, Any]) -> None:
        self_dict = self.__dict__
        for key in self_dict:
            if key in value:
                self_dict[key] = value[key]

    def asdict(self) -> dict[str, Any]:
        return deepcopy(asdict(self))


@dataclass
class LDAP_Config(MyConfig):
    host: str = ""
    admin: str = ''
    password: str = ''
    base_user: str = ''
    base_group: str = ''
    group_class: list[str] = field(default_factory=lambda: ["groupOfUniqueNames", "posixGroup"])
    group_like = '*'


@dataclass
class Gitlab_Config(MyConfig):
    url: str = ''
    access: str = ''
    check_attr: str = 'extern_uid'
    ssl_verify: bool = True
    create_user: bool = False
    new_group_visibility: str = 'private'
    ldap_provider: str = 'ldapmain'


@dataclass
class Sync_Config:
    gitlab: Gitlab_Config = field(default_factory=Gitlab_Config)
    LDAP: LDAP_Config = field(default_factory=LDAP_Config)

    @property
    def user_con(self) -> UserSearchCon:
        return UserSearchCon(base=self.LDAP.base_user)

    @property
    def group_con(self) -> UserSearchCon:
        condition = GroupSearchCon(base=self.LDAP.base_group,
                                   name_like=self.LDAP.group_like,
                                   classname=self.LDAP.group_class)
        return condition

    def read_from_json(self, filename='./config.json') -> None:
        with open(filename) as f:
            config = json.load(f)
        self.gitlab.from_dict(value=config['gitlab'])
        self.gitlab.from_dict(value=config['LDAP'])

    def weite_to_json(self, filename='./config.json') -> None:
        with open(filename, 'w') as f:
            json.dump(asdict(self), f, indent=4)

    def config_to(self) -> tuple[myLDAP, MyGitlab]:
        ldap_config = self.LDAP
        gitlab_config = self.gitlab
        mygitlab = MyGitlab(url=gitlab_config.url, access_token=gitlab_config.access, ssl_verify=gitlab_config.ssl_verify)
        mygitlab.connect()

        ldap = LDAP(host=ldap_config.host,
                    admin=ldap_config.admin,
                    password=ldap_config.password)
        myldap = myLDAP(ldap=ldap)
        return myldap, mygitlab


class Sync:
    def __init__(self, config: str) -> None:
        self.__config: Sync_Config = Sync_Config()
        self.__myldap: myLDAP = None
        self.__mygitlab: MyGitlab = None
        try:
            self.init(config=config)
        except:
            pass

    @property
    def config(self) -> Sync_Config:
        return self.__config

    @property
    def myldap(self) -> myLDAP:
        return self.__myldap

    @property
    def mygitlab(self) -> MyGitlab:
        return self.__mygitlab

    def init(self, config: str) -> None:
        self.__config.read_from_json(config)
        self.__myldap, self.__mygitlab = self.__config.config_to()

    def ldap_user_to_gitlab(self, ldap_user_attr: dict[int, Any], dn: str) -> MyUser:
        user = MyUser(id=-1,
                      username=ldap_user_attr['uid'],
                      name=ldap_user_attr['cn'],
                      email=ldap_user_attr['mail']
                      )
        user.ext_ID.uid = dn
        user.ext_ID.provider = self.config.gitlab.ldap_provider
        return user

    def create_group_in_gitlab_by_ldap(self, ldap_group: SimpleGroup) -> int:
        group_info = GitlabGroup(name=ldap_group.name, visibility=self.config.gitlab.new_group_visibility)
        if ldap_group.description is not None and ldap_group.description == '':
            group_info.description = ldap_group.description
        group_id = self.mygitlab.group_create(group_info)
        return group_id

    def check_group_member_in_gitlab(self, ldap_group: SimpleGroup) -> tuple[bool, MyGroup, list[str]]:
        absense_items = ldap_group.members
        gitlab_group_names = self.mygitlab.mygroup_all.names
        create = ldap_group.name not in gitlab_group_names
        if create:
            group_id = self.create_group_in_gitlab_by_ldap(self, ldap_group=ldap_group)
            gitlab_group = MyGroup(id=group_id, name=ldap_group.name)
        else:
            gitlab_group = self.mygitlab.mygroup_all.search(name=ldap_group.name)
            if gitlab_group is not None:
                absense_items = gitlab_group.check(red_list=ldap_group.member, attr=self.config.gitlab.check_attr)[0]
        return create, gitlab_group, absense_items

    def create_user_in_gitlab_by_ldap(self, dn: str) -> int:
        user_attr = self.myldap.user_info(dn=dn)
        user = self.ldap_user_to_gitlab(ldap_user_attr=user_attr, dn=dn)
        return self.mygitlab.user_create(info=user)

    def modify_group_user_into_gitlab_from_ldap(self, ldap_group: SimpleGroup) -> None:
        results = self.check_group_member_in_gitlab(ldap_group=ldap_group)
        create, gitlab_group, absense_items = results
        for item in absense_items:
            user = self.mygitlab.myuser_all.search_by_ext_uid(extern_uid=item)
            if user is None and self.config.gitlab.create_user:
                try:
                    user_id = self.create_user_in_gitlab_by_ldap(dn=item)
                except:
                    continue
            else:
                user_id = user.id
            if user_id is not None:
                self.mygitlab.group_add_member(group_info=gitlab_group, user_info=user, access_level=DEVELOPER_ACCESS)

    def sync(self) -> None:
        ldap_group_list = self.myldap.get_users(group_Con=self.config.group_con, user_Con=self.config.user_con)
        for ldap_group in ldap_group_list:
            try:
                self.modify_group_user_into_gitlab_from_ldap(ldap_group=ldap_group)
            except:
                pass


if __name__ == '__main__':
    # a = Sync_Config()
    # a.weite_to_json()
    sync=Sync(config='./config.json')
    sync.sync()
    
